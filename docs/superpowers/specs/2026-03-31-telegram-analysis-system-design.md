# Telegram 聊天分析系统 — 设计文档

**日期：** 2026-03-31
**状态：** 已审批（v2，根据 Codex review 修订）

---

## 1. 问题陈述

系统需要回答以下问题：
- 他们现在在聊什么
- 今天主要聊了哪些主题
- 历史上某段时间聊了什么
- 某个话题是怎么演变的
- 他们聊天里出现的黑话是什么意思

目标用户：单用户，观察多个 Telegram 群组，个人工具，不需要多租户权限模型。

---

## 2. 技术选型

| 层 | 技术 |
|---|---|
| Telegram 接入 | Telethon（MTProto API） |
| 后端 | Python 3.11 + FastAPI |
| 后台 Worker | asyncio tasks + PostgreSQL 轮询（pgqueuer），无额外队列依赖 |
| 结构化存储 | PostgreSQL |
| 向量存储 | Qdrant（本地 Docker），仅用于 `slices` collection |
| AI 处理 | Claude API（claude-sonnet-4-6） |
| Embedding | 任意 OpenAI 兼容接口，通过环境变量配置 |
| 前端 | React + shadcn/ui + Recharts + TanStack Query |

**terms 不使用 Qdrant**：术语查询用 PostgreSQL trigram/FTS 精确匹配即可，无需向量搜索。

---

## 3. 系统架构

```
Telegram MTProto
      ↓
Ingestion Layer        Telethon：实时监听 + 历史批量拉取
      ↓
Processing Pipeline    切片 → 聚类 → 摘要 → 黑话识别（Claude API）
      ↓
Storage Layer          PostgreSQL（结构化）+ Qdrant（slices 向量）
      ↓
API Layer              FastAPI REST + WebSocket（实时推送）
      ↓
Dashboard              React Web UI
```

### 数据流

**实时路径：**
Telethon event listener → 消息写入 PostgreSQL（`messages`）→ 消息放入 `pending_slice_messages` 暂存 → asyncio 定时 worker（每 5 分钟）扫描超过沉默阈值的暂存组 → 确认切片 → 聚类/摘要 → 更新 Qdrant → WebSocket 推送 Dashboard

**历史路径：**
用户触发（选择群 + 时间范围）→ `sync_jobs` 写库 → 批量拉取 worker 按批次拉取并写 `messages` → 切片/聚类/摘要 worker 消费 → 结果写库

两条路径共用同一套 processing pipeline，通过 `sync_jobs` 队列协调。

### 三边写入一致性

PostgreSQL、Qdrant、Claude API 三边写入无分布式事务，采用**补偿策略**：
- 每个 `slice` 记录 `pg_done`、`qdrant_done`、`llm_done` 三个状态位
- Worker 启动时扫描部分完成的 slice，补跑缺失步骤
- Qdrant 写入幂等（upsert by point_id = slice.id）
- LLM 处理幂等（结果有则跳过）

### 进程模型（单机）

```
backend 容器内：
  - FastAPI server（uvicorn）
  - Telethon listener（asyncio task）
  - processing worker（asyncio task，定时轮询 sync_jobs 和 pending_slice_messages）
```

三者共享一个 asyncio event loop，通过 PostgreSQL 协调状态，无竞争消费风险。

---

## 4. 数据库设计

### PostgreSQL 表结构

```sql
-- 群组
groups (
  id             BIGINT PRIMARY KEY,   -- Telegram group_id
  name           TEXT,
  type           TEXT,                 -- group / channel / supergroup
  last_synced_at TIMESTAMPTZ,
  is_active      BOOLEAN DEFAULT true
)

-- 原始消息
messages (
  id             BIGINT,
  group_id       BIGINT REFERENCES groups,
  sender_id      BIGINT,
  text           TEXT,
  reply_to_id    BIGINT,              -- 注：同群内引用，非 FK（跨批次消息可能不存在）
  reply_to_group_id BIGINT,           -- 与 reply_to_id 配合构成完整引用
  message_type   TEXT DEFAULT 'text', -- text / media / sticker / service / forward / poll
  raw_json       JSONB,               -- 保留原始消息，edit/delete 时可 diff
  is_deleted     BOOLEAN DEFAULT false,
  edited_at      TIMESTAMPTZ,
  ts             TIMESTAMPTZ,
  PRIMARY KEY (id, group_id)
)
-- 索引：(group_id, ts)，(group_id, reply_to_id)，全文搜索 GIN on text

-- 实时暂存（等待切片确认）
pending_slice_messages (
  group_id       BIGINT REFERENCES groups,
  message_id     BIGINT,
  ts             TIMESTAMPTZ,
  PRIMARY KEY (group_id, message_id)
)

-- 切片
slices (
  id             UUID PRIMARY KEY,
  group_id       BIGINT REFERENCES groups,
  time_start     TIMESTAMPTZ,
  time_end       TIMESTAMPTZ,
  summary        TEXT,
  status         TEXT,   -- pending / processed / failed
  pg_done        BOOLEAN DEFAULT false,
  qdrant_done    BOOLEAN DEFAULT false,
  llm_done       BOOLEAN DEFAULT false,
  embedding_model TEXT,              -- 记录生成 embedding 时使用的模型版本
  created_at     TIMESTAMPTZ DEFAULT now()
)

-- 切片-消息关联（替代 BIGINT[] 数组）
slice_messages (
  slice_id       UUID REFERENCES slices,
  message_id     BIGINT,
  group_id       BIGINT,
  position       INT,               -- 消息在切片内的顺序
  PRIMARY KEY (slice_id, message_id, group_id)
)

-- 话题
topics (
  id             UUID PRIMARY KEY,
  group_id       BIGINT REFERENCES groups,
  name           TEXT,              -- Claude 生成的 3-5 字标签
  summary        TEXT,              -- 渐进式摘要，每次只更新增量
  summary_version INT DEFAULT 0,    -- 摘要版本号，便于审计
  llm_model      TEXT,              -- 生成摘要时使用的模型版本
  time_start     TIMESTAMPTZ,
  time_end       TIMESTAMPTZ,
  is_active      BOOLEAN,
  slice_count    INT DEFAULT 0      -- 冗余计数，避免频繁 COUNT
)

-- 切片-话题关联（一个切片属于一个主话题）
slice_topics (
  slice_id       UUID REFERENCES slices UNIQUE,  -- 每个 slice 只有一个主 topic
  topic_id       UUID REFERENCES topics,
  similarity     FLOAT,            -- 归入时的余弦相似度，便于审计
  PRIMARY KEY (slice_id, topic_id)
)

-- 术语库
terms (
  id             UUID PRIMARY KEY,
  word           TEXT NOT NULL,
  variants       TEXT[],           -- 变体/同义词
  meanings       JSONB,            -- [{meaning, confidence}]
  examples       TEXT[],           -- 来自真实消息的例句
  status         TEXT,             -- auto / confirmed / rejected
  needs_review   BOOLEAN DEFAULT false,
  group_id       BIGINT REFERENCES groups,  -- NULL 表示跨群通用
  llm_model      TEXT,             -- 识别时使用的模型版本
  created_at     TIMESTAMPTZ,
  updated_at     TIMESTAMPTZ
)
-- 索引：GIN on word（trigram），用于模糊匹配

-- 同步任务
sync_jobs (
  id                    UUID PRIMARY KEY,
  group_id              BIGINT REFERENCES groups,
  from_ts               TIMESTAMPTZ,
  to_ts                 TIMESTAMPTZ,
  status                TEXT,       -- pending / running / done / failed
  checkpoint_message_id BIGINT,     -- 断点续传：已同步到的 message_id
  checkpoint_ts         TIMESTAMPTZ,
  error_message         TEXT,
  created_at            TIMESTAMPTZ
)

-- RAG 问答会话
qa_sessions (
  id          UUID PRIMARY KEY,
  question    TEXT,
  answer      TEXT,
  group_id    BIGINT,              -- NULL 表示跨群查询
  llm_model   TEXT,
  created_at  TIMESTAMPTZ
)

-- RAG 召回上下文（替代 UUID[] 数组）
qa_context (
  qa_session_id  UUID REFERENCES qa_sessions,
  slice_id       UUID REFERENCES slices,
  similarity     FLOAT,            -- 检索时的相似度分数
  rank           INT,              -- 召回排名
  PRIMARY KEY (qa_session_id, slice_id)
)
```

### Qdrant Collections

**collection: `slices`**
- point_id: slice.id（UUID）
- vector: embedding（维度固定在系统初始化时写入配置 `EMBEDDING_DIM`；换模型需重建 collection）
- payload: `{group_id, time_start, time_end, topic_id, summary_preview}`

**terms 不建 Qdrant collection**，用 PostgreSQL trigram 索引做模糊匹配。

---

## 5. Processing Pipeline

### 5.1 切片（Slicing）

**实时路径（延迟确认机制）：**

消息到达时不立即切片，先写入 `pending_slice_messages`。asyncio worker 每 5 分钟扫描一次：

```
对每个 group_id：
  取出 pending 消息，按回复链聚合（BFS 遍历 reply_to_id）
  对每个连通分量：
    最新消息时间戳 + 30 分钟 > now() → 继续等待（话题可能还没结束）
    最新消息时间戳 + 30 分钟 ≤ now() → 确认为一个切片，从 pending 移出
    超过 2 小时的 pending 消息 → 强制按时间窗口切断
```

**关键约定：切片一旦确认就不修改**。后续消息如果通过 reply 指向已确认切片内的消息，新建一个"延伸切片"并通过 `slice_topics` 关联到同一 topic。

**历史路径（确定性切片）：**

消息已全量写入 `messages`，直接对时间范围内的消息做批量 BFS 切片，无需等待。

### 5.2 聚类（Clustering）

1. 对每个新切片的 summary 生成 embedding，写入 Qdrant（upsert）
2. 在 Qdrant 中按 `group_id` filter，查找余弦相似度 > 0.75 的已有切片
3. 相似切片归入同一 topic（写 `slice_topics`）；无相似则新建 topic
4. Claude 为新 topic 生成名称标签（3-5 字）
5. 相似度阈值 0.75 写入配置，可按群调整；未来可支持 topic merge/split（手动触发）

### 5.3 摘要（Summarization）

**渐进式摘要（解决 context 上限问题）：**

- **片段级**：每个切片 → 1-2 句摘要（Claude）
- **话题级（渐进式）**：
  - 新切片归入 topic 时，只把"当前 topic.summary + 新切片 summary"送给 Claude，生成新的 topic.summary
  - 不重新读取所有历史切片
  - `summary_version` 递增，旧版本不保留（可后续扩展为 append-only）
- **增量更新**：每次归入新切片触发一次 topic 摘要更新

### 5.4 黑话识别

- 每批消息处理完成后，Claude 扫描该批次
- Claude 返回结构化 JSON：`{word, meanings: [{meaning, confidence}], context_examples}`
- max(confidence) ≥ 0.8：写入 `terms`，`needs_review=false`，`status=auto`
- max(confidence) < 0.8：写入 `terms`，`needs_review=true`，`status=auto`
- `confirmed` 术语注入 Claude prompt 时**按群过滤**：只注入与当前处理群相关（`group_id` 匹配或 `group_id IS NULL`）的术语，避免跨群污染和 prompt 无限膨胀
- 术语数量超过 100 条时，只注入最近更新的 50 条 + 本次消息中出现过的词

---

## 6. RAG 查询

用户在 Dashboard 提问 → FastAPI 接收 →
1. 对问题生成 embedding
2. Qdrant 向量检索（按 `group_id` / 时间范围 filter）召回 top-k 切片（默认 k=5）
3. 将召回切片的 **原始消息文本**（而非仅 summary）截取后拼入 Claude prompt
4. Claude 基于上下文生成回答，要求引用具体切片 id 作为来源
5. 结果写入 `qa_sessions` + `qa_context`，返回前端（含来源引用）
6. 检索失败（k=0 或相似度均低于 0.5）时返回明确提示，不生成幻觉回答

---

## 7. 历史消息策略

- 默认拉取近 30 天；大群拉取前展示预估消息量，需用户确认
- Dashboard 支持选择群 + 时间范围，触发 `sync_job`
- `sync_job` 增量执行，断点续传通过 `checkpoint_message_id` + `checkpoint_ts` 记录
- 历史拉取与实时监听并行时通过 `messages` 主键（id, group_id）去重，幂等写入
- 大批量历史处理在后台运行，Dashboard 展示进度

---

## 8. API 设计（主要端点）

```
# 认证 & 连接
GET  /auth/status                    Telegram 连接状态（已登录/未登录/session 过期）
POST /auth/login                     发起登录（返回 phone_code_hash）
POST /auth/verify                    提交验证码完成登录

# 群组
GET  /groups                         列出所有监听的群组
POST /groups                         添加群组（触发初始 30 天同步）
DELETE /groups/{id}                  停止监听

# 话题
GET  /groups/{id}/topics             话题列表（支持时间范围筛选）
GET  /groups/{id}/topics/{topic_id}  话题详情 + 原始切片 + 消息
GET  /topics/active                  跨群活跃话题（首页用）
POST /topics/{id}/reprocess          手动触发重新摘要

# 同步
POST /groups/{id}/sync               触发历史同步（含时间范围参数）
GET  /sync_jobs                      同步任务列表 + 状态
POST /sync_jobs/{id}/cancel          取消同步任务

# 术语库
GET  /terms                          术语列表（支持 status / needs_review / group_id filter）
POST /terms                          手动添加术语
PATCH /terms/{id}                    确认 / 修改 / 拒绝术语

# RAG 问答
POST /qa                             RAG 问答（含来源引用）
GET  /qa/sessions                    历史问答记录

# 实时推送
WS   /ws/realtime                    新话题 / 话题更新 / sync 进度推送
```

WebSocket 事件格式：`{event: "topic_updated" | "sync_progress" | "new_slice", payload: {...}, dedup_key: "<uuid>"}`，客户端用 `dedup_key` 去重。

---

## 9. Dashboard 页面

| 页面 | 功能 |
|---|---|
| Home（总览） | 跨群活跃话题卡片，实时更新；最近 2 小时活跃摘要 |
| Topics（话题时间线） | 按群/时间筛选；时间轴展示；点击查看摘要+原始消息；RAG 提问入口 |
| History（历史回顾） | 按天/周/月聚合；触发历史同步任务；进度展示 |
| Glossary（术语库） | 待确认术语列表（needs_review=true 优先）；人工校准；手动添加 |
| Settings（设置） | 群组管理；Telegram 连接状态；sync_job 监控；登录/重登入口 |

---

## 10. 部署结构

本地开发 / 单机部署：
```yaml
docker-compose:
  postgres:
    image: postgres:15
  qdrant:
    image: qdrant/qdrant:latest
  backend:
    # 包含：FastAPI server + Telethon listener + processing worker（同一 asyncio loop）
    volumes:
      - ./telegram_session:/app/session   # session 文件持久化
  frontend:
    image: nginx
```

**容器间通信**：Qdrant 通过 service name 访问（`QDRANT_HOST=qdrant`，非 localhost）。

**Telethon 登录流**：
- 首次启动时 `/auth/status` 返回未登录
- 用户在 Settings 页面输入手机号，后端调用 Telethon `send_code_request`
- 用户输入验证码，后端调用 `sign_in`，session 文件持久化到 `./telegram_session`
- 重启后自动加载 session，无需重新登录
- session 失效时 WebSocket 推送告警，Settings 页面提示重新登录

**Qdrant collection 初始化**：
- 系统启动时检查 `slices` collection 是否存在
- 不存在则从 `EMBEDDING_DIM` 环境变量读取维度并创建
- 换模型需要手动删除 collection 并重建（Settings 页面提供操作入口）

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
EMBEDDING_DIM=1536

# PostgreSQL
DATABASE_URL=postgresql://user:pass@postgres:5432/threadgraph

# Qdrant
QDRANT_HOST=qdrant
QDRANT_PORT=6333
```

---

## 11. 关键约束与风险

| 风险 | 缓解方案 |
|---|---|
| Telegram API 限速（FloodWait） | Telethon 自动处理 FloodWaitError，捕获后 sleep 精确等待时间，历史拉取批次间加 0.5s 间隔 |
| Claude API 成本 | 批量处理合并 prompt；topic 摘要用渐进式而非全量 refresh；术语抽取可配置跳过频率（每 N 条消息扫描一次） |
| 消息量过大（大群长历史） | 拉取前预估量级，用户确认；sync_job 分批执行，单批 500 条；Qdrant payload filter 避免全量扫描 |
| Telethon session 过期 | session 文件持久化 + WebSocket 实时告警 + Settings 页面重登入口 |
| Postgres/Qdrant 数据分叉 | 三状态位（pg_done/qdrant_done/llm_done）+ 启动时补偿扫描 |
| 消息编辑/删除 | `raw_json` 保留原始数据；编辑更新 `messages.edited_at`；删除标记 `is_deleted`；已生成的 slice/topic 摘要不自动回滚（标记为 stale，可手动 reprocess） |
| 多语言混聊（中英混合） | embedding 模型选择需支持多语言（如 multilingual-e5）；0.75 相似度阈值在混合语言场景下应降至 0.65，可按群配置 |
