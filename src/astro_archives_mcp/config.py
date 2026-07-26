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
    # Optional comma-separated allow-list of archive short_names
    # (e.g. "datalab,alma"). Unset/empty => every archive physically present in
    # the `archives/` package is active. See archives/__init__.py and
    # docs/archives-spec.md.
    archives: str | None = None
    # EVAL-ONLY: serve with curated context stripped — every active archive
    # loses its usage_notes and per-table Schema entries, so vo_archive_list
    # carries no quirk guidance, vo_schema_describe always reports known:false,
    # and the vo_tap_query cheat-sheet disappears. Lets an MCP client A/B the
    # value of curated context against a live container without patching server
    # internals. Archives stay reachable. Never enable in production.
    ablate_context: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Slice 5: async TAP family.
    tap_sync_timeout_seconds: float = 20.0
    job_ttl_seconds: int = 3600
    # Inline response caps (shaper.py). A TAP result larger than EITHER limit
    # is routed to an async job whose result the client fetches itself (the
    # server never holds the bytes); discovery tools (cone / SIA search)
    # truncate inline instead. Defaults are sized for small-context backends
    # (e.g. a 64K-token local vLLM), where a single fat inline result can
    # overflow the model window. Raise them for frontier models with large
    # context windows.
    inline_row_limit: int = 200
    inline_byte_limit: int = 48 * 1024
    # vo_registry_describe degrades from full per-column detail to a table
    # catalog (names + descriptions + column counts) once the full introspection
    # payload would exceed this many bytes. Prevents a large service (e.g. Gaia,
    # ~127k tokens of tables × columns) from overflowing the model context. See
    # shape_registry_describe_result.
    registry_describe_byte_limit: int = 48 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide Settings singleton.

    Cached so runtime consumers (the lazy backend accessors, job_store
    writes) read environment / .env once rather than re-parsing per call.
    Tests that mutate the environment must call ``get_settings.cache_clear()``
    to force a re-read.
    """
    return Settings()
