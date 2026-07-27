import logging

from astropy.table import Table
from pyvo.dal.exceptions import DALAccessError, DALQueryError
from pyvo.dal.sia import SIAService as _SIA1Service
from pyvo.dal.sia2 import SIA2Service as _SIA2Service

from astro_archives_mcp.errors import ArchiveError, DalQueryError

log = logging.getLogger(__name__)


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
        # Constructing the SIA2 service triggers a VOSI capabilities probe. On a
        # SIA1-only endpoint (e.g. NOIRLab Data Lab) that probe fails — sometimes as a
        # DALAccessError, but sometimes as a VOSI capabilities *parse* error (pyvo raises
        # E10, an astropy VOSIWarning/ValueError, NOT a DAL error). Either way the endpoint
        # isn't SIA2, so raise ArchiveError to tell the auto path to fall back to SIA1.
        try:
            svc = _SIA2Service(endpoint)
        except Exception as e:  # noqa: BLE001 — any capabilities-probe failure ⇒ not SIA2
            raise ArchiveError(
                message=f"endpoint is not a SIA2 service (capabilities probe failed): {e}"
            ) from e
        try:
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
