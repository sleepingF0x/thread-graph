# backend/tests/test_clusterer.py
import pytest
from unittest.mock import AsyncMock, MagicMock
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
