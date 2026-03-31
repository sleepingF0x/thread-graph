# Thread Graph — Plan 2: Processing Pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full message processing pipeline: delayed-confirm slicing → embedding → Qdrant clustering → incremental topic summarization → jargon extraction, orchestrated by an asyncio worker loop.

**Architecture:** All pipeline components are pure async functions with no global state. The worker loop (`processor.py`) polls PostgreSQL for unprocessed slices and pending slice messages, calls each stage in order, and writes results back. Claude API handles summarization and jargon extraction. An OpenAI-compatible embedding client handles vectorization. Qdrant stores slice embeddings for clustering.

**Tech Stack:** Python 3.11, anthropic SDK (Claude), openai SDK (embedding), qdrant-client, SQLAlchemy async, asyncio

---

## File Structure

```
backend/app/
├── embedding.py                   # OpenAI-compatible embedding client
├── pipeline/
│   ├── __init__.py
│   ├── slicer.py                  # BFS reply-chain + time-window slicing
│   ├── clusterer.py               # Qdrant similarity clustering → topic assignment
│   ├── summarizer.py              # Claude: slice summary + incremental topic summary
│   └── jargon.py                  # Claude: structured term extraction
└── worker/
    ├── __init__.py
    └── processor.py               # asyncio loop: pending_slice_messages → pipeline

backend/tests/
├── test_slicer.py
├── test_clusterer.py
├── test_summarizer.py
└── test_jargon.py
```

---

## Task 1: Embedding Client

**Files:**
- Create: `backend/app/embedding.py`
- Create: `backend/tests/test_embedding.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_embedding.py
import pytest
from unittest.mock import MagicMock, patch


def test_embedding_client_calls_openai():
    from app.embedding import EmbeddingClient

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

    mock_openai = MagicMock()
    mock_openai.embeddings.create.return_value = mock_response

    with patch("app.embedding.OpenAI", return_value=mock_openai):
        client = EmbeddingClient(
            base_url="https://api.example.com/v1",
            api_key="test-key",
            model="test-model",
        )
        result = client.embed_sync(["hello"])

    assert result == [[0.1, 0.2, 0.3]]
    mock_openai.embeddings.create.assert_called_once_with(
        input=["hello"], model="test-model"
    )


def test_embedding_client_batches():
    from app.embedding import EmbeddingClient

    calls = []

    def fake_create(input, model):
        calls.append(len(input))
        return MagicMock(data=[MagicMock(embedding=[float(i)]) for i in range(len(input))])

    mock_openai = MagicMock()
    mock_openai.embeddings.create.side_effect = fake_create

    with patch("app.embedding.OpenAI", return_value=mock_openai):
        client = EmbeddingClient("url", "key", "model", batch_size=2)
        texts = ["a", "b", "c", "d", "e"]
        result = client.embed_sync(texts)

    assert len(result) == 5
    assert calls == [2, 2, 1]  # batched: [a,b], [c,d], [e]
```

- [ ] **Step 2: Run to verify it fails**

```bash
sudo docker-compose run --rm backend bash -c "cd /app && pytest tests/test_embedding.py -v 2>&1 | head -20"
```

Expected: ImportError — `EmbeddingClient` doesn't exist.

- [ ] **Step 3: Write embedding.py**

```python
# backend/app/embedding.py
import asyncio
import logging
from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        batch_size: int = 100,
    ):
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.batch_size = batch_size

    def embed_sync(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in batches. Returns list of embedding vectors."""
        if not texts:
            return []
        results: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            response = self._client.embeddings.create(input=batch, model=self.model)
            results.extend(item.embedding for item in response.data)
        return results

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Async wrapper around embed_sync."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self.embed_sync, texts
        )


def get_embedding_client() -> EmbeddingClient:
    return EmbeddingClient(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        model=settings.embedding_model,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
sudo docker-compose run --rm backend bash -c "cd /app && pytest tests/test_embedding.py -v 2>&1"
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/embedding.py backend/tests/test_embedding.py
git commit -m "feat: OpenAI-compatible embedding client with batching"
```

---

## Task 2: Slicer

**Files:**
- Create: `backend/app/pipeline/__init__.py`
- Create: `backend/app/pipeline/slicer.py`
- Create: `backend/tests/test_slicer.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_slicer.py
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock


def _msg(id: int, ts_offset_min: int, reply_to: int | None = None) -> MagicMock:
    m = MagicMock()
    m.id = id
    m.group_id = 1
    m.text = f"msg {id}"
    m.ts = datetime(2026, 1, 1, 12, tzinfo=timezone.utc) + timedelta(minutes=ts_offset_min)
    m.reply_to_id = reply_to
    return m


def test_single_message_becomes_one_slice():
    from app.pipeline.slicer import slice_messages
    msgs = [_msg(1, 0)]
    slices = slice_messages(msgs)
    assert len(slices) == 1
    assert slices[0] == [msgs[0]]


def test_reply_chain_stays_together():
    from app.pipeline.slicer import slice_messages
    # msg 2 replies to msg 1, msg 3 replies to msg 2 — all in same slice
    msgs = [_msg(1, 0), _msg(2, 5, reply_to=1), _msg(3, 10, reply_to=2)]
    slices = slice_messages(msgs)
    assert len(slices) == 1
    assert len(slices[0]) == 3


def test_time_gap_splits_independent_messages():
    from app.pipeline.slicer import slice_messages
    # Two independent messages 35 minutes apart → two slices
    msgs = [_msg(1, 0), _msg(2, 35)]
    slices = slice_messages(msgs)
    assert len(slices) == 2


def test_messages_within_window_stay_together():
    from app.pipeline.slicer import slice_messages
    # Two independent messages 20 minutes apart → one slice
    msgs = [_msg(1, 0), _msg(2, 20)]
    slices = slice_messages(msgs)
    assert len(slices) == 1


def test_reply_chain_bridges_time_gap():
    from app.pipeline.slicer import slice_messages
    # msg 2 replies to msg 1 even though 2 hours apart → same slice
    msgs = [_msg(1, 0), _msg(2, 120, reply_to=1)]
    slices = slice_messages(msgs)
    assert len(slices) == 1


def test_empty_messages_returns_empty():
    from app.pipeline.slicer import slice_messages
    assert slice_messages([]) == []
```

- [ ] **Step 2: Run to verify tests fail**

```bash
sudo docker-compose run --rm backend bash -c "cd /app && pytest tests/test_slicer.py -v 2>&1 | head -20"
```

Expected: ImportError.

- [ ] **Step 3: Create pipeline/__init__.py**

```python
# backend/app/pipeline/__init__.py
```

- [ ] **Step 4: Write slicer.py**

```python
# backend/app/pipeline/slicer.py
"""
Slicing algorithm:
1. Build a reply graph: edge from child → parent (reply_to_id)
2. Find connected components via BFS/DFS
3. Within each component, split by 30-minute time window on messages
   that have no reply relationship bridging the gap
4. Return list of message lists (each list = one slice)
"""
from collections import defaultdict

WINDOW_MINUTES = 30


def slice_messages(messages: list) -> list[list]:
    """
    Split messages into conversation slices.

    Args:
        messages: list of message objects with .id, .reply_to_id, .ts attributes

    Returns:
        List of slices, each slice is a list of messages.
    """
    if not messages:
        return []

    # Index messages by id
    by_id: dict[int, object] = {m.id: m for m in messages}

    # Build adjacency: undirected graph connecting replies
    adj: dict[int, set[int]] = defaultdict(set)
    for m in messages:
        if m.reply_to_id and m.reply_to_id in by_id:
            adj[m.id].add(m.reply_to_id)
            adj[m.reply_to_id].add(m.id)

    # Find connected components via BFS
    visited: set[int] = set()
    components: list[list] = []

    for m in messages:
        if m.id in visited:
            continue
        component = []
        queue = [m.id]
        while queue:
            mid = queue.pop()
            if mid in visited or mid not in by_id:
                continue
            visited.add(mid)
            component.append(by_id[mid])
            queue.extend(adj[mid] - visited)
        components.append(component)

    # Within each component, apply time-window splitting
    slices: list[list] = []
    for component in components:
        sorted_msgs = sorted(component, key=lambda m: m.ts)
        slices.extend(_split_by_time_window(sorted_msgs))

    return slices


def _split_by_time_window(messages: list) -> list[list]:
    """Split a time-sorted message list by 30-minute gaps."""
    if not messages:
        return []

    from datetime import timedelta

    window = timedelta(minutes=WINDOW_MINUTES)
    groups: list[list] = [[messages[0]]]

    for msg in messages[1:]:
        last_ts = groups[-1][-1].ts
        if msg.ts - last_ts <= window:
            groups[-1].append(msg)
        else:
            groups.append([msg])

    return groups
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
sudo docker-compose run --rm backend bash -c "cd /app && pytest tests/test_slicer.py -v 2>&1"
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline/__init__.py backend/app/pipeline/slicer.py backend/tests/test_slicer.py
git commit -m "feat: BFS reply-chain slicer with time-window splitting"
```

---

## Task 3: Clusterer

**Files:**
- Create: `backend/app/pipeline/clusterer.py`
- Create: `backend/tests/test_clusterer.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_clusterer.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


@pytest.mark.asyncio
async def test_find_similar_topic_returns_match():
    from app.pipeline.clusterer import find_similar_topic

    mock_qdrant = AsyncMock()
    mock_result = MagicMock()
    mock_result.score = 0.85
    mock_result.payload = {"topic_id": "abc-123"}
    mock_qdrant.search.return_value = [mock_result]

    topic_id = await find_similar_topic(
        mock_qdrant, group_id=1, embedding=[0.1, 0.2], threshold=0.75
    )
    assert topic_id == "abc-123"


@pytest.mark.asyncio
async def test_find_similar_topic_returns_none_below_threshold():
    from app.pipeline.clusterer import find_similar_topic

    mock_qdrant = AsyncMock()
    mock_result = MagicMock()
    mock_result.score = 0.60
    mock_result.payload = {"topic_id": "abc-123"}
    mock_qdrant.search.return_value = [mock_result]

    topic_id = await find_similar_topic(
        mock_qdrant, group_id=1, embedding=[0.1, 0.2], threshold=0.75
    )
    assert topic_id is None


@pytest.mark.asyncio
async def test_find_similar_topic_returns_none_when_empty():
    from app.pipeline.clusterer import find_similar_topic

    mock_qdrant = AsyncMock()
    mock_qdrant.search.return_value = []

    topic_id = await find_similar_topic(
        mock_qdrant, group_id=1, embedding=[0.1, 0.2], threshold=0.75
    )
    assert topic_id is None


@pytest.mark.asyncio
async def test_upsert_slice_embedding():
    from app.pipeline.clusterer import upsert_slice_embedding

    mock_qdrant = AsyncMock()
    slice_id = uuid4()

    await upsert_slice_embedding(
        mock_qdrant,
        slice_id=slice_id,
        embedding=[0.1, 0.2, 0.3],
        payload={"group_id": 1, "topic_id": "t1"},
    )

    mock_qdrant.upsert.assert_called_once()
    call_kwargs = mock_qdrant.upsert.call_args
    assert call_kwargs[1]["collection_name"] == "slices"
```

- [ ] **Step 2: Run to verify they fail**

```bash
sudo docker-compose run --rm backend bash -c "cd /app && pytest tests/test_clusterer.py -v 2>&1 | head -20"
```

- [ ] **Step 3: Write clusterer.py**

```python
# backend/app/pipeline/clusterer.py
import logging
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, PointStruct

from app.qdrant_client import SLICES_COLLECTION

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.75


async def find_similar_topic(
    qdrant: AsyncQdrantClient,
    group_id: int,
    embedding: list[float],
    threshold: float = SIMILARITY_THRESHOLD,
) -> str | None:
    """Search Qdrant for a slice with similar embedding in the same group.
    Returns topic_id of the best match if above threshold, else None."""
    results = await qdrant.search(
        collection_name=SLICES_COLLECTION,
        query_vector=embedding,
        query_filter=Filter(
            must=[FieldCondition(key="group_id", match=MatchValue(value=group_id))]
        ),
        limit=1,
        with_payload=True,
    )
    if results and results[0].score >= threshold:
        return results[0].payload.get("topic_id")
    return None


async def upsert_slice_embedding(
    qdrant: AsyncQdrantClient,
    slice_id: UUID,
    embedding: list[float],
    payload: dict,
) -> None:
    """Write or update a slice's embedding in Qdrant."""
    await qdrant.upsert(
        collection_name=SLICES_COLLECTION,
        points=[
            PointStruct(
                id=str(slice_id),
                vector=embedding,
                payload=payload,
            )
        ],
    )
    logger.debug(f"Upserted embedding for slice {slice_id}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
sudo docker-compose run --rm backend bash -c "cd /app && pytest tests/test_clusterer.py -v 2>&1"
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/clusterer.py backend/tests/test_clusterer.py
git commit -m "feat: qdrant-based slice clustering with similarity threshold"
```

---

## Task 4: Summarizer

**Files:**
- Create: `backend/app/pipeline/summarizer.py`
- Create: `backend/tests/test_summarizer.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_summarizer.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_summarize_slice_returns_text():
    from app.pipeline.summarizer import summarize_slice

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Summary of discussion.")]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    result = await summarize_slice(mock_client, messages=["msg1", "msg2"])
    assert result == "Summary of discussion."
    mock_client.messages.create.assert_called_once()


@pytest.mark.asyncio
async def test_update_topic_summary_incremental():
    from app.pipeline.summarizer import update_topic_summary

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Updated summary.")]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    result = await update_topic_summary(
        mock_client,
        topic_name="Tech news",
        current_summary="Old summary.",
        new_slice_summary="New development happened.",
    )
    assert result == "Updated summary."


@pytest.mark.asyncio
async def test_update_topic_summary_with_no_prior_summary():
    from app.pipeline.summarizer import update_topic_summary

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="First summary.")]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    result = await update_topic_summary(
        mock_client,
        topic_name="New topic",
        current_summary=None,
        new_slice_summary="First discussion.",
    )
    assert result == "First summary."


@pytest.mark.asyncio
async def test_generate_topic_name():
    from app.pipeline.summarizer import generate_topic_name

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="AI 进展")]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    name = await generate_topic_name(mock_client, slice_summary="Discussion about GPT-5")
    assert name == "AI 进展"
```

- [ ] **Step 2: Run to verify they fail**

```bash
sudo docker-compose run --rm backend bash -c "cd /app && pytest tests/test_summarizer.py -v 2>&1 | head -20"
```

- [ ] **Step 3: Write summarizer.py**

```python
# backend/app/pipeline/summarizer.py
import logging

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"


async def summarize_slice(client, messages: list[str]) -> str:
    """Generate a 1-2 sentence summary for a conversation slice."""
    text = "\n".join(messages)
    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": (
                    "Summarize this conversation in 1-2 sentences. "
                    "Be concise and factual. Focus on what was discussed.\n\n"
                    f"{text}"
                ),
            }
        ],
    )
    return response.content[0].text.strip()


async def update_topic_summary(
    client,
    topic_name: str,
    current_summary: str | None,
    new_slice_summary: str,
) -> str:
    """Incrementally update a topic summary with a new slice.
    Only sends current summary + new slice to Claude (not all history)."""
    if current_summary:
        prompt = (
            f"Topic: {topic_name}\n\n"
            f"Current summary:\n{current_summary}\n\n"
            f"New discussion:\n{new_slice_summary}\n\n"
            "Update the topic summary to incorporate the new discussion. "
            "Keep it to 3-5 sentences. Be concise."
        )
    else:
        prompt = (
            f"Topic: {topic_name}\n\n"
            f"Discussion:\n{new_slice_summary}\n\n"
            "Write a 2-3 sentence summary of this topic."
        )

    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text.strip()


async def generate_topic_name(client, slice_summary: str) -> str:
    """Generate a short 3-5 character/word topic label in the language of the content."""
    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=20,
        messages=[
            {
                "role": "user",
                "content": (
                    "Give this discussion a short topic label (3-5 words max). "
                    "Use the same language as the content. No punctuation.\n\n"
                    f"{slice_summary}"
                ),
            }
        ],
    )
    return response.content[0].text.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
sudo docker-compose run --rm backend bash -c "cd /app && pytest tests/test_summarizer.py -v 2>&1"
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/summarizer.py backend/tests/test_summarizer.py
git commit -m "feat: incremental topic summarizer and slice summarizer (Claude)"
```

---

## Task 5: Jargon Extractor

**Files:**
- Create: `backend/app/pipeline/jargon.py`
- Create: `backend/tests/test_jargon.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_jargon.py
import pytest
from unittest.mock import AsyncMock, MagicMock
import json


@pytest.mark.asyncio
async def test_extract_terms_returns_high_confidence():
    from app.pipeline.jargon import extract_terms

    mock_client = MagicMock()
    payload = {
        "terms": [
            {
                "word": "拉盘",
                "meanings": [{"meaning": "拉抬价格", "confidence": 0.9}],
                "context_examples": ["今天有人拉盘了"],
            }
        ]
    }
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(payload))]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    terms = await extract_terms(mock_client, messages=["今天有人拉盘了"], group_id=1)
    assert len(terms) == 1
    assert terms[0]["word"] == "拉盘"
    assert terms[0]["needs_review"] is False  # confidence >= 0.8


@pytest.mark.asyncio
async def test_extract_terms_marks_low_confidence_for_review():
    from app.pipeline.jargon import extract_terms

    mock_client = MagicMock()
    payload = {
        "terms": [
            {
                "word": "梭哈",
                "meanings": [{"meaning": "all-in", "confidence": 0.6}],
                "context_examples": ["梭哈了"],
            }
        ]
    }
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(payload))]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    terms = await extract_terms(mock_client, messages=["梭哈了"], group_id=1)
    assert len(terms) == 1
    assert terms[0]["needs_review"] is True  # confidence < 0.8


@pytest.mark.asyncio
async def test_extract_terms_handles_invalid_json():
    from app.pipeline.jargon import extract_terms

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="not valid json")]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    # Should return empty list, not raise
    terms = await extract_terms(mock_client, messages=["test"], group_id=1)
    assert terms == []


@pytest.mark.asyncio
async def test_build_term_context_prompt_includes_confirmed_terms():
    from app.pipeline.jargon import build_system_context

    confirmed = [
        {"word": "kol", "meanings": [{"meaning": "key opinion leader"}]},
    ]
    context = build_system_context(confirmed)
    assert "kol" in context
    assert "key opinion leader" in context
```

- [ ] **Step 2: Run to verify they fail**

```bash
sudo docker-compose run --rm backend bash -c "cd /app && pytest tests/test_jargon.py -v 2>&1 | head -20"
```

- [ ] **Step 3: Write jargon.py**

```python
# backend/app/pipeline/jargon.py
import json
import logging

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"
AUTO_CONFIRM_THRESHOLD = 0.8
MAX_INJECTED_TERMS = 50

EXTRACTION_PROMPT = """Analyze these chat messages and identify jargon, abbreviations, internal terms, slang, and coded language that would be non-obvious to an outsider.

Return ONLY valid JSON in this format:
{{"terms": [{{"word": "term", "meanings": [{{"meaning": "explanation", "confidence": 0.0-1.0}}], "context_examples": ["example sentence"]}}]}}

Rules:
- Only include terms that are non-obvious to outsiders
- confidence: 1.0 = certain, 0.5 = guessing
- If no jargon found, return {{"terms": []}}
- Do not include common words

Messages:
{messages}"""


async def extract_terms(
    client,
    messages: list[str],
    group_id: int,
) -> list[dict]:
    """Extract jargon terms from messages. Returns list of term dicts with needs_review flag."""
    if not messages:
        return []

    text = "\n".join(messages[:100])  # cap at 100 messages per batch
    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1000,
        messages=[
            {
                "role": "user",
                "content": EXTRACTION_PROMPT.format(messages=text),
            }
        ],
    )

    raw = response.content[0].text.strip()

    # Strip markdown code blocks if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(f"Jargon extractor returned invalid JSON: {raw[:200]}")
        return []

    results = []
    for term in data.get("terms", []):
        max_confidence = max(
            (m.get("confidence", 0) for m in term.get("meanings", [])),
            default=0,
        )
        results.append(
            {
                "word": term.get("word", ""),
                "meanings": term.get("meanings", []),
                "examples": term.get("context_examples", []),
                "needs_review": max_confidence < AUTO_CONFIRM_THRESHOLD,
                "group_id": group_id,
            }
        )
    return results


def build_system_context(confirmed_terms: list[dict]) -> str:
    """Build a system prompt snippet from confirmed terms for injection into other prompts."""
    if not confirmed_terms:
        return ""

    lines = ["Known terms in this group:"]
    for term in confirmed_terms[:MAX_INJECTED_TERMS]:
        meanings = term.get("meanings", [])
        if meanings:
            meaning_str = meanings[0].get("meaning", "")
            lines.append(f"- {term['word']}: {meaning_str}")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
sudo docker-compose run --rm backend bash -c "cd /app && pytest tests/test_jargon.py -v 2>&1"
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline/jargon.py backend/tests/test_jargon.py
git commit -m "feat: structured jargon extractor with confidence-based review flagging"
```

---

## Task 6: Processing Worker Loop

**Files:**
- Create: `backend/app/worker/__init__.py`
- Create: `backend/app/worker/processor.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write worker/__init__.py**

```python
# backend/app/worker/__init__.py
```

- [ ] **Step 2: Write processor.py**

```python
# backend/app/worker/processor.py
"""
Processing worker: polls for work and runs the full pipeline.

Two loops:
1. pending_slice_loop: every 5 min, confirms ready pending_slice_messages into slices
2. pipeline_loop: continuously processes slices with status='pending'

Pipeline per slice:
  messages → embedding → Qdrant upsert → find similar topic → assign/create topic
  → summarize slice → update topic summary → extract jargon → mark done
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

PENDING_CHECK_INTERVAL = 300   # 5 minutes
PIPELINE_SLEEP = 5             # seconds between pipeline polls
SILENCE_WINDOW = timedelta(minutes=30)


# ── Pending slice confirmation ────────────────────────────────────────────────

async def confirm_ready_pending_slices(session: AsyncSession) -> int:
    """Convert pending_slice_messages that are 'done talking' into confirmed slices.
    Returns number of slices created."""
    from app.models.message import PendingSliceMessage, Message
    from app.models.slice import Slice, SliceMessage
    from app.pipeline.slicer import slice_messages

    cutoff = datetime.now(timezone.utc) - SILENCE_WINDOW

    # Load all pending messages older than the silence window
    result = await session.execute(
        select(PendingSliceMessage).where(PendingSliceMessage.ts <= cutoff)
    )
    pending = result.scalars().all()
    if not pending:
        return 0

    # Group by group_id
    by_group: dict[int, list] = {}
    for p in pending:
        by_group.setdefault(p.group_id, []).append(p)

    created = 0
    for group_id, pending_rows in by_group.items():
        # Fetch full message objects
        msg_ids = [p.message_id for p in pending_rows]
        msg_result = await session.execute(
            select(Message).where(
                Message.group_id == group_id,
                Message.id.in_(msg_ids),
            )
        )
        messages = msg_result.scalars().all()

        # Run slicer
        slices = slice_messages(messages)

        for slice_msgs in slices:
            if not slice_msgs:
                continue
            ts_list = [m.ts for m in slice_msgs]
            new_slice = Slice(
                id=uuid4(),
                group_id=group_id,
                time_start=min(ts_list),
                time_end=max(ts_list),
                status="pending",
            )
            session.add(new_slice)
            await session.flush()

            for pos, msg in enumerate(sorted(slice_msgs, key=lambda m: m.ts)):
                session.add(SliceMessage(
                    slice_id=new_slice.id,
                    message_id=msg.id,
                    group_id=group_id,
                    position=pos,
                ))
            created += 1

        # Remove confirmed pending rows
        for p in pending_rows:
            await session.delete(p)

    await session.commit()
    logger.info(f"Confirmed {created} slices from pending messages")
    return created


async def pending_slice_loop() -> None:
    """Every 5 minutes, confirm ready pending messages into slices."""
    logger.info("Pending slice loop started")
    while True:
        try:
            async with AsyncSessionLocal() as session:
                await confirm_ready_pending_slices(session)
        except Exception as e:
            logger.error(f"pending_slice_loop error: {e}")
        await asyncio.sleep(PENDING_CHECK_INTERVAL)


# ── Pipeline: process confirmed slices ───────────────────────────────────────

async def process_slice(session: AsyncSession, slice_obj) -> None:
    """Run the full pipeline on one slice."""
    import anthropic
    from app.config import settings
    from app.embedding import get_embedding_client
    from app.qdrant_client import get_qdrant
    from app.pipeline.clusterer import find_similar_topic, upsert_slice_embedding
    from app.pipeline.summarizer import summarize_slice, update_topic_summary, generate_topic_name
    from app.pipeline.jargon import extract_terms, build_system_context
    from app.models.message import Message
    from app.models.slice import SliceMessage
    from app.models.topic import Topic, SliceTopic
    from app.models.term import Term

    # Load messages for this slice
    result = await session.execute(
        select(SliceMessage)
        .where(SliceMessage.slice_id == slice_obj.id)
        .order_by(SliceMessage.position)
    )
    slice_messages_rows = result.scalars().all()

    if not slice_messages_rows:
        slice_obj.status = "processed"
        await session.commit()
        return

    msg_ids = [sm.message_id for sm in slice_messages_rows]
    msg_result = await session.execute(
        select(Message).where(
            Message.group_id == slice_obj.group_id,
            Message.id.in_(msg_ids),
        )
    )
    messages = msg_result.scalars().all()
    texts = [m.text or "" for m in messages if m.text]

    if not texts:
        slice_obj.status = "processed"
        await session.commit()
        return

    # Load confirmed terms for this group (for context injection)
    term_result = await session.execute(
        select(Term).where(
            Term.status == "confirmed",
            (Term.group_id == slice_obj.group_id) | (Term.group_id.is_(None)),
        ).limit(50)
    )
    confirmed_terms = [
        {"word": t.word, "meanings": t.meanings or []}
        for t in term_result.scalars().all()
    ]
    term_context = build_system_context(confirmed_terms)

    # 1. Generate slice summary
    claude = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    slice_summary = await summarize_slice(claude, texts)
    slice_obj.summary = slice_summary
    slice_obj.llm_done = True
    await session.commit()

    # 2. Generate embedding
    embedder = get_embedding_client()
    summary_with_context = f"{term_context}\n\n{slice_summary}" if term_context else slice_summary
    embeddings = await embedder.embed([summary_with_context])
    embedding = embeddings[0]
    slice_obj.embedding_model = settings.embedding_model
    slice_obj.pg_done = True
    await session.commit()

    # 3. Upsert to Qdrant + find similar topic
    qdrant = await get_qdrant()
    topic_id_str = await find_similar_topic(qdrant, slice_obj.group_id, embedding)

    topic = None
    if topic_id_str:
        from uuid import UUID as UUIDType
        topic = await session.get(Topic, UUIDType(topic_id_str))

    if topic is None:
        # Create new topic
        topic_name = await generate_topic_name(claude, slice_summary)
        topic = Topic(
            id=uuid4(),
            group_id=slice_obj.group_id,
            name=topic_name,
            summary=None,
            is_active=True,
            slice_count=0,
        )
        session.add(topic)
        await session.flush()

    # 4. Update topic summary (incremental)
    new_summary = await update_topic_summary(
        claude,
        topic_name=topic.name or "",
        current_summary=topic.summary,
        new_slice_summary=slice_summary,
    )
    topic.summary = new_summary
    topic.summary_version += 1
    topic.slice_count += 1
    topic.llm_model = "claude-sonnet-4-6"
    topic.time_end = slice_obj.time_end
    if topic.time_start is None:
        topic.time_start = slice_obj.time_start

    # 5. Link slice → topic
    session.add(SliceTopic(
        slice_id=slice_obj.id,
        topic_id=topic.id,
        similarity=None,
    ))

    # 6. Upsert slice embedding to Qdrant with topic_id
    await upsert_slice_embedding(
        qdrant,
        slice_id=slice_obj.id,
        embedding=embedding,
        payload={
            "group_id": slice_obj.group_id,
            "time_start": slice_obj.time_start.isoformat() if slice_obj.time_start else None,
            "time_end": slice_obj.time_end.isoformat() if slice_obj.time_end else None,
            "topic_id": str(topic.id),
            "summary_preview": slice_summary[:100],
        },
    )
    slice_obj.qdrant_done = True

    # 7. Extract jargon (every slice)
    new_terms = await extract_terms(claude, texts, slice_obj.group_id)
    for term_data in new_terms:
        existing = await session.execute(
            select(Term).where(
                Term.word == term_data["word"],
                Term.group_id == term_data["group_id"],
            )
        )
        if existing.scalar_one_or_none() is None:
            session.add(Term(
                id=uuid4(),
                word=term_data["word"],
                meanings=term_data["meanings"],
                examples=term_data["examples"],
                status="auto",
                needs_review=term_data["needs_review"],
                group_id=term_data["group_id"],
                llm_model="claude-sonnet-4-6",
            ))

    slice_obj.status = "processed"
    await session.commit()
    logger.info(f"Processed slice {slice_obj.id} → topic '{topic.name}'")


async def pipeline_loop() -> None:
    """Continuously pick up pending slices and process them."""
    logger.info("Pipeline loop started")
    while True:
        try:
            from app.models.slice import Slice
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Slice)
                    .where(Slice.status == "pending")
                    .order_by(Slice.created_at)
                    .limit(1)
                )
                slice_obj = result.scalar_one_or_none()

                if slice_obj:
                    await process_slice(session, slice_obj)
                else:
                    await asyncio.sleep(PIPELINE_SLEEP)

        except Exception as e:
            logger.error(f"pipeline_loop error: {e}", exc_info=True)
            await asyncio.sleep(PIPELINE_SLEEP)
```

- [ ] **Step 3: Wire loops into main.py lifespan**

Replace `backend/app/main.py` lifespan with:

```python
# backend/app/main.py
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.groups import router as groups_router
from app.qdrant_client import init_collections

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_collections()

    from app.ingestion.telegram_client import get_client, is_authorized
    from app.ingestion.realtime_listener import start_listener
    from app.ingestion.historical_sync import sync_worker_loop
    from app.worker.processor import pending_slice_loop, pipeline_loop

    try:
        client = await get_client()
        if await is_authorized():
            await start_listener(client)
            logger.info("Telegram listener started")
        else:
            logger.warning("Telegram not authorized — use /auth/verify to log in.")
    except Exception as e:
        logger.warning(f"Telegram client init failed: {e}")

    asyncio.create_task(sync_worker_loop())
    asyncio.create_task(pending_slice_loop())
    asyncio.create_task(pipeline_loop())
    yield


app = FastAPI(title="Thread Graph", lifespan=lifespan)
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(groups_router, prefix="/groups", tags=["groups"])


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Verify backend starts without errors**

```bash
sudo docker-compose restart backend
sleep 5
curl http://localhost:8000/health
sudo docker-compose logs backend --tail=20
```

Expected: health returns ok, logs show "Pipeline loop started", "Pending slice loop started".

- [ ] **Step 5: Run full test suite**

```bash
sudo docker-compose run --rm backend bash -c "cd /app && pytest tests/ -v 2>&1"
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/worker/ backend/app/main.py
git commit -m "feat: asyncio processing worker with pending-slice and pipeline loops"
```

---

## Task 7: Plan 2 Verification

- [ ] **Step 1: Run full test suite**

```bash
sudo docker-compose run --rm backend bash -c "cd /app && pytest tests/ -v --tb=short 2>&1"
```

Expected: all tests pass, 0 warnings.

- [ ] **Step 2: Verify backend starts with all loops**

```bash
sudo docker-compose logs backend --tail=30
```

Expected: logs contain:
- "Pending slice loop started"
- "Pipeline loop started"
- "Historical sync worker started"

- [ ] **Step 3: Commit**

```bash
git add .
git commit -m "chore: plan 2 complete — processing pipeline with embedding, clustering, summarization, jargon"
```

---

## Next: Plan 3

Plan 3 will implement:
- REST API for topics, terms, QA (RAG query)
- WebSocket for real-time dashboard push
- React frontend scaffold with 5 pages
