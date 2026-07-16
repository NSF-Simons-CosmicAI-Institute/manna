"""Archive registry — discovery, selection, and the active-set accessor.

Each `archives/<short_name>.py` module exports a module-level ``ARCHIVE`` of
type :class:`Archive`. This package discovers every archive physically present,
validates the full set, then narrows to the deployment's active set via
``STABLE_ARCHIVES`` (an optional comma-separated allow-list of short_names;
unset/empty => all).

Two ways to shape a deployment:

* **Physical** — delete an ``archives/<name>.py`` file (forking a deployment).
* **Runtime** — set ``STABLE_ARCHIVES=datalab,alma`` from a shared image.

Archives here are purely additive: absence removes the server's *claims* about
an archive (usage_notes, schema quirks, endpoint examples, cosmetic label),
never its reachability. See docs/archives-spec.md.

`get_active_archives()` is cached like `get_settings()`; tests that toggle the
environment call ``get_active_archives.cache_clear()``.
"""

import importlib
import pkgutil
from functools import lru_cache

from astro_archives_mcp.archives import _select
from astro_archives_mcp.archives._audit import Audit
from astro_archives_mcp.archives._model import Archive, Note, Schema
from astro_archives_mcp.config import get_settings

__all__ = [
    "Archive",
    "Audit",
    "Note",
    "Schema",
    "discover_archives",
    "get_active_archives",
]


def discover_archives() -> tuple[Archive, ...]:
    """Import every archive module in this package and collect its ``ARCHIVE``.

    Modules whose name starts with ``_`` are skipped: the leaf dataclasses and
    pure helpers (``_model``, ``_select``, ``_audit``) plus the derived-view
    helper modules (``_endpoints``, ``_knowledge``) — none of them define an
    ``ARCHIVE``. A non-underscore module without an ``ARCHIVE`` attribute is a
    developer error and raises. The returned tuple is validated
    (:func:`_select.validate_archives`) and sorted by (priority, short_name).
    """
    archives: list[Archive] = []
    for module_info in pkgutil.iter_modules(__path__):
        if module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        archive = getattr(module, "ARCHIVE", None)
        if archive is None:
            raise ValueError(
                f"Archive module {module_info.name!r} defines no module-level "
                f"ARCHIVE. Every archives/<name>.py must export "
                f"`ARCHIVE = Archive(...)`."
            )
        archives.append(archive)

    result = tuple(archives)
    _select.validate_archives(result)
    return _select.sort_archives(result)


@lru_cache(maxsize=1)
def get_active_archives() -> tuple[Archive, ...]:
    """The archives active for this deployment, ordered.

    Discovers all physically-present archives, then narrows by
    ``STABLE_ARCHIVES`` (unset/empty => all). Resolved once per process;
    frozen at first call.
    """
    settings = get_settings()
    all_archives = discover_archives()
    allow = _select.parse_allow(settings.archives)
    return _select.select_archives(all_archives, allow=allow)
