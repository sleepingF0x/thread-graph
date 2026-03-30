# Telegram 聊天分析系统 — 设计文档

**日期：** 2026-03-31
**状态：** 已审批

---

## 1. 问题陈述

系统需要回答以下问题：
- 他们现在在聊什么
- 今天主要聊了哪些主题
- 历史上某段时间聊了什么
- 某个话题是怎么演变的
- 他们聊天里出现的黑话是什么意思

目标用户：多个 Telegram 群组的观察者/管理者，需要同时跟踪多个群的讨论动态。

---

## 2. 技术选型

| 层 | 技术 |
|---|---|
| Telegram 接入 | Telethon（MTProto API，用户提供 api_id） |
| 后端 | Python 3.11 + FastAPI |
| 结构化存储 | PostgreSQL |
| 向量存储 | Qdrant（本地 Docker） |
| AI 处理 | Claude API（claude-sonnet-4-6） |
| Embedding | 任意 OpenAI 兼容接口，通过环境变量配置 |
| 前端 | React + shadcn/ui + Recharts + TanStack Query |

---

## 3. 系统架构

```
Telegram MTProto
      ↓
Ingestion Layer        Telethon：实时监听 + 历史批量拉取
      ↓
Processing Pipeline    切片 → 聚类 → 摘要 → 黑话识别
      ↓
Storage Layer          PostgreSQL（结构化）+ Qdrant（向量）
      ↓
API Layer              FastAPI REST + WebSocket（实时推送）
      ↓
Dashboard              React Web UI
```

### 数据流

**实时路径：**
Telethon event listener → 消息写入 PostgreSQL → 后台 worker 触发增量切片/聚类/摘要 → 更新 Qdrant embedding → WebSocket 推送 Dashboard

**历史路径：**
用户触发（选择群 + 时间范围）→ sync_job 入队 → 批量拉取消息 → 全量处理 pipeline → 结果写库

两条路径共用同一套 processing pipeline。

---

## 4. 数据库设计

### PostgreSQL 表结构

```sql
-- 群组
groups (
  id          BIGINT PRIMARY KEY,   -- Telegram group_id
  name        TEXT,
  type        TEXT,                 -- group / channel / supergroup
  last_synced_at TIMESTAMPTZ,
  is_active   BOOLEAN DEFAULT true
)

-- 原始消息
messages (
  id          BIGINT,
  group_id    BIGINT REFERENCES groups,
  sender_id   BIGINT,
  text        TEXT,
  reply_to_id BIGINT,
  ts          TIMESTAMPTZ,
  PRIMARY KEY (id, group_id)
)
-- 索引：(group_id, ts)，(reply_to_id)，全文搜索 on text

-- 切片
slices (
  id          UUID PRIMARY KEY,
  group_id    BIGINT REFERENCES groups,
  message_ids BIGINT[],
  time_start  TIMESTAMPTZ,
  time_end    TIMESTAMPTZ,
  summary     TEXT,
  status      TEXT   -- pending / processed
)

-- 话题
topics (
  id          UUID PRIMARY KEY,
  group_id    BIGINT REFERENCES groups,
  name        TEXT,             -- Claude 生成的 3-5 字标签
  summary     TEXT,
  action_items TEXT[],
  time_start  TIMESTAMPTZ,
  time_end    TIMESTAMPTZ,
  is_active   BOOLEAN           -- 是否仍在活跃
)

-- 切片-话题关联
slice_topics (
  slice_id    UUID REFERENCES slices,
  topic_id    UUID REFERENCES topics,
  PRIMARY KEY (slice_id, topic_id)
)

-- 术语库
terms (
  id          UUID PRIMARY KEY,
  word        TEXT,
  variants    TEXT[],           -- 变体/同义词
  meanings    JSONB,            -- [{meaning, confidence}]
  examples    TEXT[],           -- 来自真实消息的例句
  status      TEXT,             -- auto / confirmed / rejected
  group_id    BIGINT REFERENCES groups,  -- NULL 表示跨群通用
  created_at  TIMESTAMPTZ,
  updated_at  TIMESTAMPTZ
)

-- 同步任务
sync_jobs (
  id          UUID PRIMARY KEY,
  group_id    BIGINT REFERENCES groups,
  from_ts     TIMESTAMPTZ,
  to_ts       TIMESTAMPTZ,
  status      TEXT,             -- pending / running / done / failed
  created_at  TIMESTAMPTZ
)

-- RAG 问答会话
qa_sessions (
  id          UUID PRIMARY KEY,
  question    TEXT,
  context_slice_ids UUID[],     -- 召回的切片
  answer      TEXT,
  group_id    BIGINT,           -- NULL 表示跨群查询
  created_at  TIMESTAMPTZ
)
```

### Qdrant Collections

**collection: `slices`**
- point_id: slice.id
- vector: embedding（维度由所选模型决定，运行时从第一次调用结果推断并写入配置）
- payload: `{group_id, time_start, time_end, topic_id, summary_preview}`

**collection: `terms`**
- point_id: term.id
- vector: embedding of word + meanings
- payload: `{word, status, group_id}`

---

## 5. Processing Pipeline

### 5.1 切片（Slicing）

优先级规则（按序应用）：
1. **回复链**：reply_to_message_id 相同的消息归为同一片段
2. **时间窗口**：同一主题消息通常在 30 分钟内集中，超过则考虑切断
3. **沉默断点**：超过 2 小时无新消息，强制切片

每个切片产出：消息列表 + 时间范围 + 参与者列表

### 5.2 聚类（Clustering）

1. 对每个切片生成 embedding，写入 Qdrant
2. 新切片进来时，在 Qdrant 中查找余弦相似度 > 0.75 的已有切片
3. 相似切片归入同一 topic；无相似则新建 topic
4. Claude 为新 topic 生成 3-5 字标签

### 5.3 摘要（Summarization）

- **片段级**：每个切片 → 1-2 句摘要（Claude）
- **话题级**：topic 下所有切片合并 → 完整摘要 + 结论/待办识别（Claude）
- **增量更新**：新切片归入已有 topic 时，触发 topic 摘要 refresh

### 5.4 黑话识别

- 每批消息处理完成后，Claude 扫描该批次
- 识别候选术语，Claude 返回结构化 JSON：`{word, meanings, confidence: 0-1}`
- confidence ≥ 0.8 自动写入 terms 表（status: auto）
- confidence < 0.8 写入但标记为待确认（status: auto，needs_review: true）
- `confirmed` 术语注入后续所有 Claude prompt 的 system context

---

## 6. RAG 查询

用户在 Dashboard 提问 → FastAPI 接收 →
1. 对问题生成 embedding
2. Qdrant 向量检索（可按 group_id / 时间范围 filter）召回 top-k 切片
3. 将召回切片的 summary 拼入 Claude prompt
4. Claude 基于上下文生成回答
5. 结果写入 qa_sessions，返回前端

---

## 7. 历史消息策略

- 默认拉取近 30 天
- Dashboard 支持选择群 + 时间范围，触发 sync_job
- sync_job 增量执行，支持断点续传（记录已同步到的 message_id）
- 大批量历史处理在后台运行，Dashboard 展示进度

---

## 8. API 设计（主要端点）

```
GET  /groups                         列出所有监听的群组
POST /groups                         添加群组
GET  /groups/{id}/topics             获取话题列表（支持时间范围筛选）
GET  /groups/{id}/topics/{topic_id}  话题详情 + 原始切片
POST /groups/{id}/sync               触发历史同步
GET  /topics/active                  跨群活跃话题（首页用）

GET  /terms                          术语列表（支持 status filter）
POST /terms                          手动添加术语
PATCH /terms/{id}                    确认 / 修改 / 拒绝术语

POST /qa                             RAG 问答
GET  /qa/sessions                    历史问答记录

WS   /ws/realtime                    实时推送新话题 / 更新
```

---

## 9. Dashboard 页面

| 页面 | 功能 |
|---|---|
| Home（总览） | 跨群活跃话题卡片，实时更新；最近 2 小时活跃摘要 |
| Topics（话题时间线） | 按群/时间筛选；时间轴展示；点击查看摘要+原始消息；RAG 提问入口 |
| History（历史回顾） | 按天/周/月聚合；触发历史同步任务；进度展示 |
| Glossary（术语库） | 待确认术语列表；人工校准；手动添加 |
| Settings（设置） | 群组管理；Telegram 连接状态；同步任务监控 |

---

## 10. 部署结构

本地开发 / 单机部署：
```
docker-compose:
  - postgres:15
  - qdrant:latest
  - backend (FastAPI + Telethon worker)
  - frontend (React, nginx)
```

Telethon session 文件持久化挂载到宿主机，避免每次重启重新登录。

环境变量配置（`.env`）：
```
# Telegram
TELEGRAM_API_ID=
TELEGRAM_API_HASH=

# Claude
ANTHROPIC_API_KEY=

# Embedding（OpenAI 兼容接口）
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=text-embedding-3-small

# PostgreSQL
DATABASE_URL=postgresql://...

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333
```

---

## 11. 关键约束与风险

| 风险 | 缓解方案 |
|---|---|
| Telegram API 限速 | 历史拉取加 rate limiter，批次间 sleep |
| Claude API 成本 | 批量处理合并 prompt，避免逐条调用；片段级摘要可降级用更小模型 |
| 消息量过大（大群长历史） | sync_job 分批执行，Qdrant payload filter 避免全量扫描 |
| Telethon session 过期 | 持久化 session 文件 + 异常告警 |
