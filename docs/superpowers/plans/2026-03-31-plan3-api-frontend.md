# Plan 3: API Layer + Frontend Dashboard

**Date:** 2026-03-31
**Status:** Active
**Depends on:** Plan 2 complete (processing pipeline, all 22 tests passing)

---

## Overview

Plan 3 adds the full API surface and React dashboard on top of the processing pipeline from Plans 1 & 2.

**Backend additions:**
- Topics API (list, detail, active, reprocess)
- Terms API (list, create, patch)
- QA/RAG API (ask question, session history)
- WebSocket real-time push

**Frontend:**
- Vite + React + TypeScript + Tailwind + shadcn/ui + TanStack Query + Recharts + React Router
- 5 pages: Home, Topics, History, Glossary, Settings
- Docker service (nginx) added to docker-compose

---

## Architecture Context

```
backend/
  app/
    api/
      auth.py      ← exists (Plan 1)
      groups.py    ← exists (Plan 1)
      topics.py    ← NEW (Task 1)
      terms.py     ← NEW (Task 2)
      qa.py        ← NEW (Task 3)
      ws.py        ← NEW (Task 4)
    main.py        ← update: add new routers + WS
    models/        ← all exist, no changes needed
    pipeline/      ← all exist, no changes needed
    worker/        ← all exist, no changes needed

frontend/          ← NEW (Tasks 5–9)
  src/
    api/           ← typed API client (axios/fetch)
    components/    ← shared UI (layout, cards)
    pages/         ← Home, Topics, History, Glossary, Settings
    hooks/         ← useWebSocket, useGroups, etc.
  Dockerfile
  nginx.conf

docker-compose.yml ← add frontend service (Task 9)
```

---

## Database Models Reference

All models already exist. Key fields for API responses:

**Topic:** `id(UUID), group_id, name, summary, summary_version, time_start, time_end, is_active, slice_count`
**SliceTopic:** `slice_id, topic_id, similarity`
**Slice:** `id(UUID), group_id, time_start, time_end, summary, status, pg_done, qdrant_done, llm_done`
**SliceMessage:** `slice_id, message_id, group_id, position`
**Message:** `id, group_id, sender_id, text, reply_to_id, ts`
**Term:** `id(UUID), word, variants[], meanings(JSONB), examples[], status, needs_review, group_id`
**QaSession:** `id(UUID), question, answer, group_id, llm_model, created_at`
**QaContext:** `qa_session_id, slice_id, similarity, rank`

---

## Task 1: Topics API

### File: `backend/app/api/topics.py` (new)

```python
router = APIRouter()

GET  /groups/{group_id}/topics
     query params: limit=50, offset=0, from_ts, to_ts (ISO8601 optional)
     → list of {id, name, summary, is_active, slice_count, time_start, time_end}
     order by time_end DESC

GET  /groups/{group_id}/topics/{topic_id}
     → full topic + slices list + messages per slice
     response: {
       id, name, summary, is_active, slice_count, time_start, time_end,
       slices: [{id, time_start, time_end, summary, messages: [{id, text, ts, sender_id}]}]
     }
     load slices via slice_topics join, load messages via slice_messages join
     order slices by time_start ASC, messages by position ASC

GET  /topics/active
     query params: limit=20
     → cross-group active topics (is_active=True)
     join with groups to include group name
     response: [{id, name, summary, group_id, group_name, slice_count, time_start, time_end}]
     order by time_end DESC

POST /topics/{topic_id}/reprocess
     → set all slices of this topic back to status='pending'
        and reset topic.summary='', summary_version=0
     → worker will pick them up and reprocess
     response: {topic_id, slices_reset: int}
```

### Tests: `backend/tests/test_topics_api.py`

- `test_list_topics_empty` — 200 empty list when no topics
- `test_list_topics_filtered` — from_ts/to_ts filter works
- `test_get_topic_detail` — includes slices and messages
- `test_get_active_topics` — only is_active=True, includes group_name
- `test_reprocess_topic` — resets slice status and topic summary

### Update `backend/app/main.py`
- `from app.api.topics import router as topics_router`
- `app.include_router(topics_router, prefix="/groups", tags=["topics"])` (for group-scoped routes)
- `app.include_router(topics_router, prefix="", tags=["topics"])` — note: use a single router with two prefixes or split into two routers

**Implementation note:** Use one router in topics.py. Register it twice in main.py:
```python
app.include_router(topics_router)  # covers /topics/active and /topics/{id}/reprocess
app.include_router(topics_router, prefix="/groups")  # covered by routes that start with /{group_id}/topics
```
Actually simpler: put all routes explicitly without prefix ambiguity. Use these exact paths in the router:
- `/groups/{group_id}/topics`
- `/groups/{group_id}/topics/{topic_id}`
- `/topics/active`
- `/topics/{topic_id}/reprocess`

Register without prefix: `app.include_router(topics_router, tags=["topics"])`

### Acceptance Criteria
- All 5 tests pass
- `GET /topics/active` returns correct cross-group data
- `POST /topics/{id}/reprocess` resets slices in DB

---

## Task 2: Terms API

### File: `backend/app/api/terms.py` (new)

```python
router = APIRouter()

GET  /terms
     query params: status (auto/confirmed/rejected/all, default=all),
                   needs_review (bool optional), group_id (optional),
                   limit=50, offset=0
     → list of term objects
     order: needs_review DESC, updated_at DESC

POST /terms
     body: {word, variants?, meanings?, examples?, group_id?}
     meanings defaults to [] if not provided
     status = "confirmed", needs_review = False
     → created term

PATCH /terms/{term_id}
     body (all optional): {word?, variants?, meanings?, examples?, status?, needs_review?}
     valid status values: auto, confirmed, rejected
     → updated term
     update updated_at to now()
```

### Tests: `backend/tests/test_terms_api.py`

- `test_list_terms_empty` — 200 empty list
- `test_list_terms_filter_needs_review` — needs_review=true filter
- `test_list_terms_filter_status` — status=confirmed filter
- `test_create_term` — creates with status=confirmed
- `test_patch_term_status` — confirm an auto term
- `test_patch_term_not_found` — 404

### Update `backend/app/main.py`
- `from app.api.terms import router as terms_router`
- `app.include_router(terms_router, prefix="/terms", tags=["terms"])`

### Acceptance Criteria
- All 6 tests pass
- Filter combinations work correctly

---

## Task 3: QA/RAG API

### File: `backend/app/api/qa.py` (new)

QA pipeline: embed question → Qdrant search → load raw messages → Claude answer

```python
router = APIRouter()

POST /qa
     body: {question: str, group_id?: int, limit?: int = 5}

     Pipeline:
     1. embed question via get_embedding_client().embed([question])
     2. search Qdrant SLICES_COLLECTION with filter:
        - if group_id: must match payload.group_id
        - score_threshold=0.5, limit=limit
     3. if no results (or all below threshold): return {answer: "没有找到相关内容", sources: []}
     4. for each hit: load Slice + its SliceMessages + Messages from PG
        - truncate message text to 500 chars each, max 10 messages per slice
     5. build Claude prompt with context
     6. call anthropic.messages.create(model="claude-sonnet-4-6", max_tokens=1024)
     7. write QaSession + QaContext rows
     8. return {session_id, answer, sources: [{slice_id, topic_id, similarity, time_start, summary_preview}]}

GET /qa/sessions
    query params: limit=20, offset=0, group_id?
    → list {id, question, answer_preview (first 200 chars), group_id, created_at}
    order by created_at DESC
```

### Anthropic client setup in qa.py

```python
import anthropic
from app.config import settings

def get_anthropic_client():
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)
```

### Tests: `backend/tests/test_qa_api.py`

- `test_qa_no_results` — mock Qdrant returns empty → answer is "没有找到相关内容"
- `test_qa_with_results` — mock Qdrant returns 2 hits, mock Claude → returns answer with sources
- `test_qa_writes_session` — verify QaSession + QaContext rows written to DB
- `test_list_sessions_empty` — 200 empty list
- `test_list_sessions` — returns sessions with answer_preview truncated

Use `unittest.mock.patch` / `pytest-mock` for Qdrant and Anthropic calls.

### Update `backend/app/main.py`
- `from app.api.qa import router as qa_router`
- `app.include_router(qa_router, prefix="/qa", tags=["qa"])`

### Acceptance Criteria
- All 5 tests pass
- No actual Qdrant/Anthropic calls in tests (mocked)

---

## Task 4: WebSocket Real-Time Endpoint

### File: `backend/app/api/ws.py` (new)

```python
from fastapi import WebSocket, WebSocketDisconnect
from typing import Any
import asyncio
import json

class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket):
        self._connections.remove(ws)

    async def broadcast(self, event: str, payload: Any, dedup_key: str = ""):
        msg = json.dumps({"event": event, "payload": payload, "dedup_key": dedup_key})
        dead = []
        for ws in self._connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)

manager = ConnectionManager()  # module-level singleton

router = APIRouter()

@router.websocket("/ws/realtime")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep alive — client can send pings
            await asyncio.wait_for(websocket.receive_text(), timeout=30)
    except (WebSocketDisconnect, asyncio.TimeoutError):
        manager.disconnect(websocket)
```

### Integration: broadcast from worker

In `backend/app/worker/processor.py`, after `process_slice` completes successfully:

```python
from app.api.ws import manager

# After topic updated:
await manager.broadcast(
    event="topic_updated",
    payload={"topic_id": str(topic.id), "group_id": topic.group_id, "name": topic.name},
    dedup_key=str(slice_obj.id),
)
```

In `historical_sync.py`, after checkpoint update:

```python
await manager.broadcast(
    event="sync_progress",
    payload={"job_id": str(job.id), "group_id": job.group_id, "checkpoint_message_id": job.checkpoint_message_id},
    dedup_key=f"sync_{job.id}_{job.checkpoint_message_id}",
)
```

### Tests: `backend/tests/test_ws.py`

- `test_websocket_connect_and_receive` — connect, broadcast one event, verify received via TestClient
- `test_websocket_broadcast_format` — verify JSON shape: event, payload, dedup_key fields present

Use FastAPI's `TestClient` with `with client.websocket_connect("/ws/realtime") as ws:`.

### Update `backend/app/main.py`
- `from app.api.ws import router as ws_router`
- `app.include_router(ws_router, tags=["ws"])`
- Export `manager` for worker imports

### Acceptance Criteria
- Both tests pass
- `manager.broadcast()` callable from worker without circular imports

---

## Task 5: Frontend Scaffold

### Directory: `frontend/`

Initialize with Vite + React + TypeScript:

```
frontend/
  package.json           ← Vite + React + TS + dependencies
  vite.config.ts         ← proxy /api → http://backend:8000
  tsconfig.json
  index.html
  src/
    main.tsx             ← ReactDOM root
    App.tsx              ← Router + QueryClientProvider + layout
    api/
      client.ts          ← axios instance (baseURL from env or /api)
      topics.ts          ← topics API functions
      terms.ts           ← terms API functions
      qa.ts              ← QA API functions
      groups.ts          ← groups API functions
      auth.ts            ← auth API functions
    hooks/
      useWebSocket.ts    ← connects to /ws/realtime, exposes last event
      useGroups.ts       ← TanStack Query wrapper
    components/
      Layout.tsx         ← sidebar nav + outlet
      TopicCard.tsx      ← reusable card for a topic
      SyncProgress.tsx   ← sync job progress bar
    pages/
      Home.tsx           ← placeholder "Home"
      Topics.tsx         ← placeholder "Topics"
      History.tsx        ← placeholder "History"
      Glossary.tsx       ← placeholder "Glossary"
      Settings.tsx       ← placeholder "Settings"
    types/
      index.ts           ← TypeScript interfaces (Topic, Term, QaSession, Group, etc.)
  Dockerfile
  nginx.conf
```

### Dependencies (package.json)

```json
{
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0",
    "@tanstack/react-query": "^5.56.2",
    "axios": "^1.7.7",
    "recharts": "^2.12.7",
    "lucide-react": "^0.462.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.3",
    "vite": "^5.4.2",
    "tailwindcss": "^3.4.11",
    "postcss": "^8.4.45",
    "autoprefixer": "^10.4.20"
  }
}
```

**Note:** Do NOT use shadcn/ui CLI (requires interactive setup). Instead use Tailwind + lucide-react for icons and build simple components directly. This avoids scaffold complexity while matching the spirit of the spec.

### vite.config.ts

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      }
    }
  }
})
```

### TypeScript interfaces (`src/types/index.ts`)

```typescript
export interface Group { id: number; name: string; type: string; last_synced_at: string | null }
export interface Topic { id: string; name: string; summary: string; is_active: boolean; slice_count: number; time_start: string; time_end: string; group_id: number; group_name?: string }
export interface Slice { id: string; time_start: string; time_end: string; summary: string; messages: Message[] }
export interface Message { id: number; text: string; ts: string; sender_id: number }
export interface TopicDetail extends Topic { slices: Slice[] }
export interface Term { id: string; word: string; variants: string[]; meanings: {meaning: string; confidence: number}[]; examples: string[]; status: string; needs_review: boolean; group_id: number | null }
export interface QaSession { id: string; question: string; answer_preview: string; group_id: number | null; created_at: string }
export interface SyncJob { id: string; group_id: number; status: string; from_ts: string; to_ts: string; checkpoint_message_id: number | null; error_message: string | null }
export interface WsEvent { event: string; payload: Record<string, unknown>; dedup_key: string }
```

### API client (`src/api/client.ts`)

```typescript
import axios from 'axios'
const client = axios.create({ baseURL: '/api' })
export default client
```

### useWebSocket hook (`src/hooks/useWebSocket.ts`)

```typescript
import { useEffect, useRef, useState } from 'react'
import type { WsEvent } from '../types'

export function useWebSocket() {
  const [lastEvent, setLastEvent] = useState<WsEvent | null>(null)
  const ws = useRef<WebSocket | null>(null)

  useEffect(() => {
    const connect = () => {
      ws.current = new WebSocket(`ws://${window.location.host}/ws/realtime`)
      ws.current.onmessage = (e) => setLastEvent(JSON.parse(e.data))
      ws.current.onclose = () => setTimeout(connect, 3000)  // auto-reconnect
    }
    connect()
    return () => ws.current?.close()
  }, [])

  return lastEvent
}
```

### Layout (`src/components/Layout.tsx`)

```tsx
// Sidebar with nav links: Home, Topics, History, Glossary, Settings
// Uses react-router-dom NavLink, Outlet for page content
```

### App.tsx

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Home from './pages/Home'
import Topics from './pages/Topics'
import History from './pages/History'
import Glossary from './pages/Glossary'
import Settings from './pages/Settings'

const queryClient = new QueryClient()

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="topics" element={<Topics />} />
            <Route path="history" element={<History />} />
            <Route path="glossary" element={<Glossary />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
```

### Dockerfile (`frontend/Dockerfile`)

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

### nginx.conf (`frontend/nginx.conf`)

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://backend:8000/;
    }

    location /ws/ {
        proxy_pass http://backend:8000/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Acceptance Criteria
- `npm run build` succeeds with no TypeScript errors
- All 5 page routes render without console errors (placeholder content OK at this stage)
- Dockerfile builds successfully

---

## Task 6: Home Page + Topics Page

### Home Page (`src/pages/Home.tsx`)

Display active topics across all groups.

**Data:** `GET /topics/active` → list of topics with group_name

**Layout:**
- Page title "正在讨论" (What's being discussed)
- TopicCard grid (2-3 columns)
- Each TopicCard shows: group_name badge, topic name (large), summary (2 lines truncated), slice_count, time_end (relative: "5 minutes ago")
- WebSocket: on `topic_updated` event, invalidate `['topics', 'active']` query → auto-refresh
- Loading skeleton while fetching
- Empty state: "暂无活跃话题"

**TopicCard component** (`src/components/TopicCard.tsx`): reusable, receives `topic: Topic` prop, links to `/topics?group={group_id}&topic={topic_id}`

### Topics Page (`src/pages/Topics.tsx`)

Timeline view for a selected group.

**Controls:**
- Group selector dropdown (from `GET /groups`)
- Date range picker (from_ts / to_ts) — plain HTML date inputs
- "Load" button

**Data:** `GET /groups/{id}/topics?from_ts=...&to_ts=...`

**Timeline layout:**
- Vertical timeline sorted by time_end DESC
- Each item: topic name, summary, slice_count, time range
- Click → fetch `GET /groups/{id}/topics/{topic_id}` → expand accordion below the item
  - Show slices list; each slice shows time range + summary + message count
  - Click slice → show raw messages (sender_id, text, ts)

**RAG panel:**
- Fixed bottom bar (or right panel): text input + "Ask" button
- POST /qa with selected group_id
- Shows answer + source slice IDs

**Acceptance Criteria:**
- Group selector populates from API
- Topics load when group selected
- Click topic → details expand
- RAG query shows answer (or "没有找到相关内容")

---

## Task 7: History Page + Glossary Page

### History Page (`src/pages/History.tsx`)

Historical sync management.

**Sections:**

1. **Sync Jobs** (`GET /groups/sync_jobs`)
   - Table: group_id, status (colored badge), from_ts, to_ts, checkpoint_message_id
   - Status colors: pending=yellow, running=blue, done=green, failed=red
   - "Cancel" button for pending/running jobs → `POST /groups/sync_jobs/{id}/cancel`
   - WebSocket: on `sync_progress` event, invalidate sync_jobs query

2. **Trigger Historical Sync**
   - Group selector + from_days number input (default 30)
   - "Sync" button → `POST /groups/{id}/sync?from_days=N`
   - Success: shows new job_id in table

3. **Activity Chart** (Recharts)
   - Bar chart: x=date (last 7 days), y=approximate topic count per group
   - Data: client-side aggregate from topics list (group by date(time_end))
   - Show up to 3 groups in different colors

**Acceptance Criteria:**
- Sync jobs table loads and refreshes on WS events
- Cancel works and job status updates
- Trigger form creates sync job

### Glossary Page (`src/pages/Glossary.tsx`)

Term library management.

**Layout:**

1. **Filter bar**: status dropdown (all/auto/confirmed/rejected), "needs_review only" checkbox, group selector

2. **Terms list** (`GET /terms?...`)
   - Card per term: word (large), variants as tags, meanings list (meaning + confidence %), examples (collapsible)
   - `needs_review=true` → yellow highlight + "Review needed" badge
   - Status badge: auto=gray, confirmed=green, rejected=red

3. **Actions per term:**
   - "Confirm" button → `PATCH /terms/{id}` with `{status: "confirmed", needs_review: false}`
   - "Reject" button → `PATCH /terms/{id}` with `{status: "rejected"}`
   - Inline edit: click word → editable input → save → PATCH

4. **Add term form:**
   - word input, optional variants (comma-separated), optional group selector
   - Submit → `POST /terms`

**Acceptance Criteria:**
- Filter controls filter the list
- Confirm/Reject actions update card immediately (optimistic update via query invalidation)
- Add term form works

---

## Task 8: Settings Page

### Settings Page (`src/pages/Settings.tsx`)

System administration.

**Sections:**

1. **Telegram Connection**
   - `GET /auth/status` → shows "已连接" (green) or "未连接" (red)
   - If not connected: phone number input + "发送验证码" button → `POST /auth/login`
   - Verification code input + optional password + "验证" button → `POST /auth/verify`
   - If connected: show current status, "重新登录" link (shows login form)

2. **Group Management**
   - List of groups (`GET /groups`) — name, type, last_synced_at
   - "Add group" form: group_id (number), name, type (group/channel/supergroup)
     → `POST /groups` → shows new sync_job_id on success
   - "Remove" button per group → `DELETE /groups/{id}` → confirm dialog

3. **Embedding / Qdrant Info**
   - Read-only display of env-based config: EMBEDDING_MODEL, EMBEDDING_DIM, QDRANT_HOST
   - "Rebuild Qdrant collection" button → shows warning modal, on confirm call a future endpoint
     (for now: show "功能暂未开放" toast)

**Acceptance Criteria:**
- Auth status loads and shows correct state
- Login flow renders form correctly (no need for real Telegram in tests)
- Group management CRUD renders correctly

---

## Task 9: Docker Frontend Service

### Update `docker-compose.yml`

Add frontend service:

```yaml
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:80"
    depends_on:
      - backend
```

### Verify `frontend/Dockerfile` and `nginx.conf` are correct

The nginx config proxies:
- `/api/*` → `http://backend:8000/*`
- `/ws/*` → `ws://backend:8000/ws/*` (WebSocket upgrade headers)
- All other paths → SPA `index.html`

### Build test

```bash
sudo docker-compose build frontend
```

Verify image builds without error.

### Acceptance Criteria
- `sudo docker-compose build frontend` succeeds
- `sudo docker-compose up frontend` serves React app on port 3000
- `/api/health` proxied correctly to backend

---

## Task 10: Plan 3 Verification

### Backend verification

Run full test suite (should now have more tests):
```bash
sudo docker-compose run --rm backend bash -c "cd /app && pytest tests/ -v --tb=short"
```

Expected: all tests pass (22 existing + new tests from Tasks 1-4).

### Frontend verification

```bash
cd frontend && npm run build
```

TypeScript compile with no errors. Build output in `dist/`.

### Integration smoke test

```bash
sudo docker-compose up -d
curl http://localhost:8000/health           # → {"status":"ok"}
curl http://localhost:8000/topics/active    # → []
curl http://localhost:8000/terms            # → []
curl http://localhost:3000/                 # → React app HTML
```

### Final commit

```bash
git add -A
git commit -m "feat: plan 3 complete — API layer, WebSocket, React dashboard"
```

### Acceptance Criteria
- All backend tests pass
- Frontend builds without errors
- All 4 smoke test URLs return expected responses
- Docker compose up starts all 4 services (postgres, qdrant, backend, frontend)
