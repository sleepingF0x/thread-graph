# backend/app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_api_id: int = 0
    telegram_api_hash: str = ""

    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    llm_model: str = "claude-sonnet-4-6"

    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    database_url: str = "postgresql+asyncpg://threadgraph:threadgraph@postgres:5432/threadgraph"
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333

    session_path: str = "session/threadgraph"


settings = Settings()
