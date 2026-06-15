import functools
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://claims:claims@localhost:5432/claims_db"
    sync_database_url: str = "postgresql://claims:claims@localhost:5432/claims_db"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    policy_file_path: str = "/app/policy_terms.json"
    ollama_url: str = "http://localhost:11434"
    ollama_vision_model: str = "qwen2.5vl:3b"

    class Config:
        env_file = ".env"
        extra = "ignore"


@functools.lru_cache
def get_settings() -> Settings:
    return Settings()
