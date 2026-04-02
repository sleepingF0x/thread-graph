# Telegram Dialog Picker Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Settings page dialog picker that loads Telegram dialogs after login, supports client-side search, and prefills the existing monitored-group form.

**Architecture:** The backend will add a normalized `GET /auth/dialogs` API on top of the existing Telethon session. The frontend will fetch once after successful authorization, filter and sort locally, and reuse the current add-group form as the single write path.

**Tech Stack:** FastAPI, Telethon, pytest, React, TanStack Query, axios, Vite

---

### Task 1: Document discovery API behavior with failing backend tests

**Files:**
- Modify: `backend/tests/test_auth_api.py`
- Test: `backend/tests/test_auth_api.py`

**Step 1: Write the failing test**

Add tests that expect:
- `GET /auth/dialogs` returns normalized dialog objects when authorized
- `GET /auth/dialogs` returns `401` when Telegram is not authorized

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm -e DATABASE_URL=postgresql+asyncpg://threadgraph:threadgraph@postgres:5432/threadgraph_test backend pytest tests/test_auth_api.py`

Expected: FAIL because `/auth/dialogs` does not exist yet.

**Step 3: Write minimal implementation**

Add a new auth route and patchable dialog helper in the Telegram client module.

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm -e DATABASE_URL=postgresql+asyncpg://threadgraph:threadgraph@postgres:5432/threadgraph_test backend pytest tests/test_auth_api.py`

Expected: PASS

### Task 2: Implement Telegram dialog normalization

**Files:**
- Modify: `backend/app/ingestion/telegram_client.py`
- Modify: `backend/app/api/auth.py`

**Step 1: Write the failing test**

Cover type mapping and `raw_id`/`dialog_id` normalization via the auth API tests.

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm -e DATABASE_URL=postgresql+asyncpg://threadgraph:threadgraph@postgres:5432/threadgraph_test backend pytest tests/test_auth_api.py`

Expected: FAIL on missing or incorrect fields.

**Step 3: Write minimal implementation**

Add helpers that:
- detect whether the current session is authorized
- iterate dialogs
- normalize to `group`, `supergroup`, `channel`, or `user`

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm -e DATABASE_URL=postgresql+asyncpg://threadgraph:threadgraph@postgres:5432/threadgraph_test backend pytest tests/test_auth_api.py`

Expected: PASS

### Task 3: Add frontend picker state and API binding

**Files:**
- Modify: `frontend/src/api/auth.ts`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/pages/Settings.tsx`

**Step 1: Write the failing test**

No frontend test harness exists, so use Docker build as the verification gate.

**Step 2: Run build to capture the baseline**

Run: `docker compose build frontend`

Expected: PASS on the current app before the new UI is wired in.

**Step 3: Write minimal implementation**

Add:
- `getTelegramDialogs()` API call
- `TelegramDialog` type
- Settings page search input
- local filtering/sorting
- click-to-prefill behavior for the existing form

**Step 4: Run build to verify it passes**

Run: `docker compose build frontend`

Expected: PASS

### Task 4: Verify end-to-end behavior in containers

**Files:**
- Modify: none expected

**Step 1: Rebuild affected services**

Run:
- `docker compose build backend`
- `docker compose build frontend`

**Step 2: Restart the app**

Run: `docker compose up -d backend frontend`

**Step 3: Verify the backend route**

Run: `curl -s http://localhost:8000/auth/dialogs`

Expected: JSON array with normalized dialog entries when authorized.

**Step 4: Verify auth and existing route health**

Run:
- `curl -s http://localhost:8000/auth/status`
- `curl -s http://localhost:8000/health`

Expected: valid JSON responses and no startup regression.
