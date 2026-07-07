from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="STABLE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8000
    deployment: Literal["local", "adl", "tacc"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Slice 5: async TAP family.
    tap_sync_timeout_seconds: float = 20.0
    job_ttl_seconds: int = 3600
    # Inline-tier response caps (shaper.py). A tabular result larger than
    # EITHER limit spills to the Parquet Resource tier (a small envelope with
    # a resource_uri + 50-row preview) instead of inlining every row. Defaults
    # are sized for small-context backends (e.g. a 64K-token local vLLM), where
    # a single fat inline result can overflow the model window. Raise them for
    # frontier models with large context windows.
    inline_row_limit: int = 200
    inline_byte_limit: int = 48 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide Settings singleton.

    Cached so runtime consumers (the lazy backend accessors, job_store
    writes) read environment / .env once rather than re-parsing per call.
    Tests that mutate the environment must call ``get_settings.cache_clear()``
    to force a re-read.
    """
    return Settings()
