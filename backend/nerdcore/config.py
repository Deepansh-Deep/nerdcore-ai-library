from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    corpus_path: Path = ROOT / "data" / "corpus.jsonl.gz"
    db_path: Path = ROOT / "data" / "history.db"
    frontend_dir: Path = ROOT / "frontend"
    cors_origins: str = "*"


@lru_cache
def get_settings() -> Settings:
    return Settings()
