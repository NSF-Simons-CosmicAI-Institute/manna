"""Name resolver backend — wraps CDS Sesame via astropy.coordinates."""

import logging

from astropy.coordinates import SkyCoord
from astropy.coordinates.name_resolve import NameResolveError

from manna.errors import ArchiveError

log = logging.getLogger(__name__)


class ResolverClient:
    """Wraps CDS Sesame (SIMBAD → NED → VizieR fallback chain) for name resolution."""

    def resolve(self, name: str) -> tuple[float, float] | None:
        """Return ``(ra_deg, dec_deg)`` in ICRS, or ``None`` if the name is unknown.

        Raises ``ArchiveError`` for network / service failures that are distinct
        from a simple name-not-found response. ``cache=False`` ensures the HTTP
        round-trip always occurs so vcrpy can intercept it during test replay.
        """
        try:
            coord = SkyCoord.from_name(name, cache=False)
            # astropy stubs type .ra/.dec as Optional; they are always present here.
            return coord.ra.deg, coord.dec.deg  # pyright: ignore[reportOptionalMemberAccess, reportReturnType]
        except NameResolveError:
            log.debug("Sesame: name not found: %s", name)
            return None
        except Exception as e:
            raise ArchiveError(message=f"Name resolver unavailable: {e}") from e
