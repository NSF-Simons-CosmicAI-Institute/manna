import logging

import httpx
from astropy.table import Table
from pyvo.dal.exceptions import DALAccessError, DALQueryError
from pyvo.dal.sia import SIAService as _SIA1Service
from pyvo.dal.sia2 import SIA2Service as _SIA2Service

from astro_archives_mcp.errors import ArchiveError, DalQueryError

log = logging.getLogger(__name__)

_FETCH_BYTE_CAP = 10 * 1024 * 1024  # 10 MB — matches RESOURCE_BYTE_LIMIT in shaper
_FETCH_TIMEOUT_SECONDS = 60.0


class SiaClient:
    """Sync wrapper over pyvo SIA — SIA 2.0 by default, SIA 1.0 fallback.

    Most modern archives (ALMA, CADC, ESO) speak SIA2. A few major ones —
    notably NOIRLab Astro Data Lab — only expose SIA v1. `version='auto'`
    tries SIA2 first and, when its capabilities probe fails (a
    DALAccessError, the tell that the endpoint isn't SIA2), retries the
    same URL as SIA1.
    """

    def search(
        self,
        *,
        endpoint: str,
        ra: float,
        dec: float,
        size_deg: float,
        band: str | None = None,
        fmt: str | None = None,
        maxrec: int = 1_000,
        version: str = "auto",
    ) -> Table:
        if version == "1":
            return self._search_v1(endpoint, ra, dec, size_deg, fmt, maxrec)
        if version == "2":
            return self._search_v2(endpoint, ra, dec, size_deg, band, fmt, maxrec)
        # auto: SIA2, fall back to SIA1 only on an access/capabilities failure
        try:
            return self._search_v2(endpoint, ra, dec, size_deg, band, fmt, maxrec)
        except ArchiveError:
            log.info("SIA2 unavailable at %s; retrying as SIA1", endpoint)
            return self._search_v1(endpoint, ra, dec, size_deg, fmt, maxrec)

    def _search_v2(
        self,
        endpoint: str,
        ra: float,
        dec: float,
        size_deg: float,
        band: str | None,
        fmt: str | None,
        maxrec: int,
    ) -> Table:
        try:
            svc = _SIA2Service(endpoint)
            # pyvo SIA2 expects pos as (ra, dec, radius) for a CIRCLE region.
            kwargs: dict = {"pos": (ra, dec, size_deg), "maxrec": maxrec}
            if band:
                kwargs["band"] = band
            if fmt:
                kwargs["format"] = fmt
            result = svc.search(**kwargs)
        except DALQueryError as e:
            raise DalQueryError(message=str(e)) from e
        except DALAccessError as e:
            raise ArchiveError(message=str(e)) from e
        # Cap on the (untyped) pyvo result. SIA2 honors maxrec server-side,
        # but enforce it locally as a defensive backstop.
        table = result.to_table()
        return table[:maxrec] if len(table) > maxrec else table

    def _search_v1(
        self,
        endpoint: str,
        ra: float,
        dec: float,
        size_deg: float,
        fmt: str | None,
        maxrec: int,
    ) -> Table:
        try:
            svc = _SIA1Service(endpoint)
            # SIA1 takes a (ra, dec) POS and a rectangular SIZE (degrees); it
            # has no band or maxrec parameters.
            kwargs: dict = {"pos": (ra, dec), "size": size_deg}
            if fmt:
                kwargs["format"] = fmt
            result = svc.search(**kwargs)
        except DALQueryError as e:
            raise DalQueryError(message=str(e)) from e
        except DALAccessError as e:
            raise ArchiveError(message=str(e)) from e
        # SIA1 has no maxrec parameter, so the cap must be applied client-side.
        table = result.to_table()
        return table[:maxrec] if len(table) > maxrec else table

    def fetch(self, access_url: str) -> tuple[bytes, str]:
        """Download bytes from access_url, stream-capped at 10 MB.

        Returns (bytes, content_type). Raises ArchiveError on any HTTP
        failure, on exceeding the 10 MB cap, or on timeout.
        """
        try:
            with httpx.stream(
                "GET",
                access_url,
                follow_redirects=True,
                timeout=_FETCH_TIMEOUT_SECONDS,
            ) as response:
                response.raise_for_status()
                content_type = (
                    response.headers.get("content-type", "application/octet-stream")
                    .split(";")[0]
                    .strip()
                )
                buf = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    buf.extend(chunk)
                    if len(buf) > _FETCH_BYTE_CAP:
                        # Abort mid-stream; do NOT drain the rest.
                        raise ArchiveError(
                            message=("Image exceeds 10 MB cap; reduce size_deg in vo_sia_search"),
                            retry_strategy="abandon",
                        )
                return bytes(buf), content_type
        except httpx.HTTPStatusError as e:
            raise ArchiveError(
                message=f"upstream HTTP {e.response.status_code}",
            ) from e
        except httpx.HTTPError as e:
            raise ArchiveError(message=f"upstream error: {e}") from e
