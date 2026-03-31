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
    assert terms[0]["needs_review"] is False


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
    assert terms[0]["needs_review"] is True


@pytest.mark.asyncio
async def test_extract_terms_handles_invalid_json():
    from app.pipeline.jargon import extract_terms

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="not valid json")]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

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
