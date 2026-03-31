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
