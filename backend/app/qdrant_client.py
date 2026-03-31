# backend/app/qdrant_client.py
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

from app.config import settings

_client: AsyncQdrantClient | None = None

SLICES_COLLECTION = "slices"


async def get_qdrant() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(
            host=settings.qdrant_host, port=settings.qdrant_port
        )
    return _client


async def init_collections() -> None:
    client = await get_qdrant()
    existing = {c.name for c in (await client.get_collections()).collections}
    if SLICES_COLLECTION not in existing:
        await client.create_collection(
            collection_name=SLICES_COLLECTION,
            vectors_config=VectorParams(
                size=settings.embedding_dim, distance=Distance.COSINE
            ),
        )
