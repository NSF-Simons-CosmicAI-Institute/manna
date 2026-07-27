import logging
import re
from urllib.parse import urlparse

import pyvo
import pyvo.registry
from pyvo.dal.exceptions import DALQueryError, DALServiceError

from manna.errors import ArchiveError, DalQueryError, ValidationError

log = logging.getLogger(__name__)


_IVOID_RE = re.compile(r"^ivo://", re.IGNORECASE)


class RegistryClient:
    """Sync wrapper over pyvo.registry. No async.

    Two operations:
      * search(keywords/servicetype/waveband) -> list of service dicts
      * describe(ivoid_or_url) -> service dict with capabilities + tables
    """

    def search(
        self,
        *,
        keywords: list[str] | None = None,
        servicetype: str | None = None,
        waveband: str | None = None,
        maxrec: int = 50,
    ) -> list[dict]:
        kwargs: dict = {"maxrec": maxrec}
        if keywords:
            kwargs["keywords"] = keywords
        if servicetype:
            kwargs["servicetype"] = servicetype
        if waveband:
            kwargs["waveband"] = waveband
        try:
            results = pyvo.registry.search(**kwargs)
        except DALQueryError as e:
            raise DalQueryError(message=str(e)) from e
        except DALServiceError as e:
            raise ArchiveError(message=str(e)) from e

        out: list[dict] = []
        for r in list(results)[:maxrec]:  # belt-and-braces cap in case RegTAP returns more
            out.append(_resource_to_dict(r))
        return out

    def describe(self, *, ivoid_or_url: str) -> dict:
        if _IVOID_RE.match(ivoid_or_url):
            return self._describe_by_ivoid(ivoid_or_url)
        if _looks_like_url(ivoid_or_url):
            return self._describe_by_url(ivoid_or_url)
        raise ValidationError(
            message=(
                f"Expected an IVOID (e.g. 'ivo://...') or a TAP service URL. Got: {ivoid_or_url!r}"
            ),
        )

    # ---------- internals ----------

    def _describe_by_ivoid(self, ivoid: str) -> dict:
        try:
            results = list(pyvo.registry.search(ivoid=ivoid))
        except DALQueryError as e:
            raise DalQueryError(message=str(e)) from e
        except DALServiceError as e:
            raise ArchiveError(message=str(e)) from e

        if not results:
            raise ArchiveError(message=f"No such service: {ivoid}", retry_strategy="abandon")
        return _resource_to_describe_dict(results[0])

    def _describe_by_url(self, url: str) -> dict:
        # First try RegTAP — gives us richer metadata (title, publisher,
        # description) than direct introspection can.
        try:
            results = pyvo.registry.search(servicetype="tap")
            for r in results:
                if _normalized_url(r.access_url) == _normalized_url(url):  # pyright: ignore[reportAttributeAccessIssue]
                    return _resource_to_describe_dict(r)
        except (DALQueryError, DALServiceError) as e:
            # Registry itself is down or slow. Don't give up — fall
            # through to direct introspection.
            log.warning(
                "RegistryClient._describe_by_url: RegTAP lookup failed (%s); "
                "falling back to direct TAP introspection",
                e,
            )

        # Fallback: the service either isn't IVOA-registered (e.g. NRAO's
        # first-party archive) or registry was unreachable. Introspect
        # the service's own TAP capability directly.
        return self._describe_via_direct_tap(url)

    def _describe_via_direct_tap(self, url: str) -> dict:
        """Introspect a TAP service without going through the registry.

        Used as a fallback when the IVOA registry doesn't know the
        service. Output shape matches `_resource_to_describe_dict` for
        consistency — `ivoid` and `title` are None because we only have
        what the service publishes about itself.
        """
        try:
            tap_svc = pyvo.dal.TAPService(url)
            tables = [_table_to_dict(t) for t in tap_svc.tables.values()]
        except (DALQueryError, DALServiceError) as e:
            raise ArchiveError(
                message=(
                    f"Could not introspect TAP service at {url}: {e}. "
                    "Service is not IVOA-registered and direct introspection "
                    "failed — check the URL or try again later."
                ),
                retry_strategy="wait_and_retry",
            ) from e

        return {
            "ivoid": None,
            "title": None,
            "description": (f"Direct TAP introspection (not IVOA-registered): {url}"),
            "capabilities": ["tap"],
            "tables": tables,
        }


# ---------- pure helpers (module-level for unit-testability) ----------


def _looks_like_url(s: str) -> bool:
    try:
        p = urlparse(s)
        return bool(p.scheme in ("http", "https") and p.netloc)
    except Exception:  # noqa: BLE001
        return False


def _normalized_url(url: str | None) -> str:
    if not url:
        return ""
    return url.rstrip("/").lower()


def _capability_urls(resource) -> dict[str, str | None]:
    """Pull out (tap_url, sia_url, scs_url, ssa_url). None when absent."""
    out: dict[str, str | None] = {
        "tap_url": None,
        "sia_url": None,
        "scs_url": None,
        "ssa_url": None,
    }
    for stype_key, attr in (
        ("tap_url", "tap"),
        ("sia_url", "sia"),
        ("scs_url", "conesearch"),
        ("ssa_url", "ssa"),
    ):
        try:
            svc = resource.get_service(attr)
            out[stype_key] = getattr(svc, "baseurl", None) or getattr(svc, "access_url", None)
        except Exception:  # noqa: BLE001
            out[stype_key] = None
    return out


def _resource_to_dict(resource) -> dict:
    """Search-result shape."""
    caps = _capability_urls(resource)
    return {
        "ivoid": getattr(resource, "ivoid", None),
        "title": getattr(resource, "res_title", None) or getattr(resource, "short_name", None),
        "description": getattr(resource, "res_description", None),
        "publisher": getattr(resource, "publisher", None)
        or getattr(resource, "creator_name", None),
        "waveband": getattr(resource, "waveband", None),
        **caps,
    }


def _resource_to_describe_dict(resource) -> dict:
    """Describe shape: capabilities + tables/columns when TAP."""
    caps = _capability_urls(resource)
    capability_list = [k.removesuffix("_url") for k, v in caps.items() if v]

    tables: list[dict] = []
    if caps["tap_url"]:
        try:
            tap_svc = resource.get_service("tap")
            for t in tap_svc.tables.values():
                tables.append(_table_to_dict(t))
        except Exception:  # noqa: BLE001
            pass

    return {
        "ivoid": getattr(resource, "ivoid", None),
        "title": getattr(resource, "res_title", None) or getattr(resource, "short_name", None),
        "description": getattr(resource, "res_description", None),
        "capabilities": capability_list,
        "tables": tables,
    }


def _table_to_dict(table) -> dict:
    cols = []
    for c in getattr(table, "columns", []) or []:
        cols.append(
            {
                "name": getattr(c, "name", None),
                "type": str(getattr(c, "datatype", "") or ""),
                "unit": getattr(c, "unit", None) or None,
                "ucd": getattr(c, "ucd", None) or None,
                "description": getattr(c, "description", None) or None,
            }
        )
    return {
        "name": getattr(table, "name", None),
        "description": getattr(table, "description", None) or None,
        "columns": cols,
    }
