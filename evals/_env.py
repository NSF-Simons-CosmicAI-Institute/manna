"""Load ``evals/.env`` into the process environment (dependency-free, dotenv-style).

Config convention for the eval harness: put the EVAL_MODEL_* / EVAL_JUDGE_* vars
(including the judge API key) in a **gitignored** ``evals/.env``; the CLI entrypoints
call ``load_env()`` at startup so no manual ``source`` is needed. Real shell env vars
win over the file (``setdefault``), so per-run overrides still work. Copy
``evals/.env.example`` to ``evals/.env`` to get started.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_PATH = Path(__file__).with_name(".env")


def load_env(path: Path | None = None) -> None:
    p = path or _ENV_PATH
    if not p.exists():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, sep, val = line.partition("=")
        if not sep:
            continue
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        os.environ.setdefault(key, val)  # real env wins over the file


def refresh_active_set() -> None:
    """The active set is cached at import (tools/tap.py builds its endpoint
    examples at import time), before .env is loaded. Re-read it so a
    MANNA_ARCHIVES line in evals/.env can re-enable a paused archive.
    """
    from manna.archives import get_active_archives
    from manna.config import get_settings

    get_settings.cache_clear()
    get_active_archives.cache_clear()
