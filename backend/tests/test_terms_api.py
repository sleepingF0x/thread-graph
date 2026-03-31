# backend/tests/test_terms_api.py
"""
Tests for the Terms API endpoints.

Uses httpx.AsyncClient with ASGITransport and app.dependency_overrides
to inject the async test db_session fixture.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main import app
from app.models.term import Term


# ---------------------------------------------------------------------------
# Helper: async context manager for an overridden client
# ---------------------------------------------------------------------------

def make_override(db_session: AsyncSession):
    async def override_get_db():
        yield db_session
    return override_get_db


async def _aclient(db_session: AsyncSession) -> httpx.AsyncClient:
    app.dependency_overrides[get_db] = make_override(db_session)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


# ---------------------------------------------------------------------------
# DB fixture helpers
# ---------------------------------------------------------------------------

async def _create_term(
    db: AsyncSession,
    *,
    word: str = "testword",
    status: str = "auto",
    needs_review: bool = False,
    group_id: int | None = None,
    variants: list[str] | None = None,
    meanings: list[dict] | None = None,
    examples: list[str] | None = None,
) -> Term:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    term = Term(
        id=uuid4(),
        word=word,
        status=status,
        needs_review=needs_review,
        group_id=group_id,
        variants=variants,
        meanings=meanings if meanings is not None else [],
        examples=examples,
        created_at=now,
        updated_at=now,
    )
    db.add(term)
    await db.flush()
    return term


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_terms_empty(db_session: AsyncSession):
    """GET /terms returns 200 + empty list when no terms exist."""
    async with await _aclient(db_session) as client:
        resp = await client.get("/terms")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_terms_filter_needs_review(db_session: AsyncSession):
    """GET /terms?needs_review=true returns only terms with needs_review=True."""
    await _create_term(db_session, word="review-me", needs_review=True)
    await _create_term(db_session, word="no-review", needs_review=False)
    await db_session.commit()

    async with await _aclient(db_session) as client:
        resp = await client.get("/terms", params={"needs_review": "true"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["word"] == "review-me"
    assert data[0]["needs_review"] is True


@pytest.mark.asyncio
async def test_list_terms_filter_status(db_session: AsyncSession):
    """GET /terms?status=confirmed returns only confirmed terms."""
    await _create_term(db_session, word="auto-term", status="auto")
    await _create_term(db_session, word="confirmed-term", status="confirmed")
    await db_session.commit()

    async with await _aclient(db_session) as client:
        resp = await client.get("/terms", params={"status": "confirmed"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["word"] == "confirmed-term"
    assert data[0]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_create_term(db_session: AsyncSession):
    """POST /terms creates a term with status=confirmed and needs_review=False."""
    async with await _aclient(db_session) as client:
        resp = await client.post(
            "/terms",
            json={
                "word": "newterm",
                "variants": ["variant1"],
                "meanings": [{"meaning": "a definition", "confidence": 0.9}],
                "examples": ["example sentence"],
            },
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["word"] == "newterm"
    assert data["status"] == "confirmed"
    assert data["needs_review"] is False
    assert data["variants"] == ["variant1"]
    assert data["meanings"] == [{"meaning": "a definition", "confidence": 0.9}]
    assert data["examples"] == ["example sentence"]
    assert data["group_id"] is None
    assert "id" in data


@pytest.mark.asyncio
async def test_patch_term_status(db_session: AsyncSession):
    """PATCH /terms/{id} updates status from auto to confirmed."""
    term = await _create_term(db_session, word="patchme", status="auto")
    await db_session.commit()

    async with await _aclient(db_session) as client:
        resp = await client.patch(
            f"/terms/{term.id}",
            json={"status": "confirmed"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "confirmed"
    assert data["word"] == "patchme"
    assert data["id"] == str(term.id)


@pytest.mark.asyncio
async def test_patch_term_not_found(db_session: AsyncSession):
    """PATCH /terms/{random-uuid} returns 404."""
    fake_id = str(uuid4())
    async with await _aclient(db_session) as client:
        resp = await client.patch(
            f"/terms/{fake_id}",
            json={"status": "confirmed"},
        )
    assert resp.status_code == 404
