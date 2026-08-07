"""Runtime configuration. Secrets come from the environment, never the repo (spec §9)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HAULIER_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    data_dir: Path = Path("data")
    """Local mirror of what will live at r2://raw/... in production."""

    contact_email: str = "alastairmrushworth@gmail.com"
    """Included in the User-Agent so GOV.UK can reach us — spec §8.2 requires
    an honest, contactable identifier rather than a spoofed browser string."""

    request_delay_seconds: float = 1.0
    """Politeness delay between requests to the same host."""

    request_timeout_seconds: float = 60.0
    http_retries: int = 3

    @property
    def user_agent(self) -> str:
        return f"FirstMover/0.1 (+HGV licence lead research; contact: {self.contact_email})"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
