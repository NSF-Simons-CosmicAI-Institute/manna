import logging

import pyvo
from astropy.table import Table
from pyvo.dal.exceptions import DALAccessError, DALQueryError

from manna.errors import ArchiveError, DalQueryError

log = logging.getLogger(__name__)


class ConeSearchClient:
    """Sync wrapper over pyvo.dal.SCSService.search()."""

    def search(
        self,
        *,
        endpoint: str,
        ra: float,
        dec: float,
        radius_deg: float,
        maxrec: int = 10_000,
    ) -> Table:
        try:
            svc = pyvo.dal.SCSService(endpoint)
            result = svc.search(pos=(ra, dec), radius=radius_deg, maxrec=maxrec)
        except DALQueryError as e:
            raise DalQueryError(message=str(e)) from e
        except DALAccessError as e:
            raise ArchiveError(message=str(e)) from e

        table = result.to_table()
        # Defensive cap — pyvo respects maxrec server-side, but verify locally.
        if len(table) > maxrec:
            table = table[:maxrec]
        return table
