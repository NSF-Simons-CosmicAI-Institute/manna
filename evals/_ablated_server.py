"""Boot the MANNA HTTP server with its archive notes stripped — the with-and-without
comparison (``condition: ablated``) for a real agent client.

The custom loop strips notes in-process (``evals.context.ablated_context`` patches module
globals around an in-memory client). A persona (``persona_run.py``) talks to the server over
HTTP in a separate process, so this entrypoint applies the same context manager around
``uvicorn.run``: the tools resolve their archive-note references at call time, and
``build_app`` derives the up-front-note cheatsheet at build time, so building and serving
inside the context strips exactly what the loop strips — ``usage_notes`` (hence the
cheatsheet and error hints), and every ``describe_table`` lookup misses.

Usage (persona_run does this for you): ``MANNA_PORT=8127 uv run python -m evals._ablated_server``
"""

from __future__ import annotations

import uvicorn

from evals.context import ablated_context
from manna.app import build_app
from manna.config import get_settings
from manna.observability import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    with ablated_context():
        uvicorn.run(
            build_app(), host=settings.host, port=settings.port, log_config=None, access_log=False
        )


if __name__ == "__main__":
    main()
