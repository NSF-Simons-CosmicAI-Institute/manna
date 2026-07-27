import sys

import uvicorn

from manna.app import build_app, build_mcp
from manna.config import get_settings
from manna.observability import configure_logging


def main() -> None:
    stdio = "--stdio" in sys.argv

    settings = get_settings()
    configure_logging(settings.log_level)

    if stdio:
        build_mcp().run(transport="stdio")
    else:
        uvicorn.run(
            build_app(),
            host=settings.host,
            port=settings.port,
            log_config=None,
            access_log=False,
        )


if __name__ == "__main__":
    main()
