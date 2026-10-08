from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "Clinical Compass Agent"
    app_env: Literal["local", "test", "production"] = "local"

    app_host: str = "127.0.0.1"
    app_port: int = 8000

    api_v1_prefix: str = "/api/v1"

    database_file: str = "data/clinical_compass.db"

    llm_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def database_path(self) -> Path:
        path = Path(self.database_file)

        if path.is_absolute():
            return path

        return PROJECT_ROOT / path

    @property
    def database_url(self) -> str:
        return f"sqlite+pysqlite:///{self.database_path.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
