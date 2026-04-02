# backend/tests/test_summarizer.py
import pytest
from unittest.mock import AsyncMock, MagicMock


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


@pytest.mark.asyncio
async def test_summarize_slice_skips_empty_first_content_block():
    from app.pipeline.summarizer import summarize_slice

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=None), MagicMock(text="  usable summary  ")]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    result = await summarize_slice(mock_client, messages=["msg1"])
    assert result == "usable summary"
