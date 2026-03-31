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
        if not texts:
            return []
        results: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            response = self._client.embeddings.create(input=batch, model=self.model)
            results.extend(item.embedding for item in response.data)
        return results

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.get_running_loop().run_in_executor(
            None, self.embed_sync, texts
        )


_embedding_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = EmbeddingClient(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
        )
    return _embedding_client
