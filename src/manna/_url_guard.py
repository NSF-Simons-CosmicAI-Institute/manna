"""SSRF guard for every URL the LLM can influence.

The server fetches URLs supplied as tool arguments (TAP/cone/SIA
``endpoint``, registry ``ivoid_or_url``, async ``job_url``). Those fetches
originate *inside* the server's network, which in a shared-service topology
(one server process, many users, no per-user auth) also holds every other
user's session. An unguarded fetch is therefore a pivot into trusted address
space, and pyvo's error strings carry upstream status/body fragments back to
the caller, so it is not even blind.

Policy, in order:

1. Scheme must be http/https — no file://, ftp://, data:, gopher://.
2. Host must be present.
3. If ``MANNA_ALLOWED_HOSTS`` is set, the host must match it (exact or
   subdomain). Unset — the default — permits any *public* host, because
   ``vo_registry_search`` is designed to surface archives MANNA carries no
   curated knowledge of, and a curated-hosts-only allowlist would gate that
   core discovery workflow. See docs/archives-spec.md.
4. The target must resolve entirely to public address space.

Rule 4 is the one that actually stops the attack; rule 3 exists for
locked-down deployments that want to give up discovery in exchange for a
tighter blast radius.

Known residual risk — DNS rebinding: we resolve here and ``requests``
resolves again when it connects, so a hostile authoritative server can return
a public address to us and a private one microseconds later. Closing that
requires pinning the validated address into the connection (a custom
transport adapter), which is deliberately out of scope for this pass. The
guard stops every non-rebinding case, including the ones that matter most
here (``http://mcp:8000``, ``http://hub:8000``, ``169.254.169.254``).
"""

import ipaddress
import socket
from urllib.parse import urlparse

from manna.config import get_settings
from manna.errors import ValidationError

_ALLOWED_SCHEMES = frozenset({"http", "https"})

# Deliberately generic: naming the resolved address would let a caller use the
# guard as an internal-network scanner, confirming which hosts exist.
_BLOCKED_TARGET = (
    "{param} resolves to a non-public network address and will not be "
    "fetched. Supply a public archive service URL."
)


def _resolve(host: str) -> list[str]:
    """Every address ``host`` maps to. Module-level so tests can stub it."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    # sockaddr[0] is the address for both the IPv4 and IPv6 tuple shapes; str()
    # narrows the union typeshed declares for that slot.
    return [str(info[4][0]) for info in infos]


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True only for globally-routable unicast addresses.

    ``is_global`` alone would very nearly do, but the explicit clauses keep the
    intent legible and guard against per-version differences in what
    ``is_global`` folds in.
    """
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or not ip.is_global
    )


def _allowed_hosts() -> tuple[str, ...]:
    raw = get_settings().allowed_hosts
    if not raw:
        return ()
    return tuple(h.strip().lower() for h in raw.split(",") if h.strip())


def _host_matches(host: str, allowed: tuple[str, ...]) -> bool:
    """Exact match, or a genuine subdomain.

    The dot in the suffix test is load-bearing: without it ``eso.org`` would
    also admit ``notaneso.org``.
    """
    return any(host == entry or host.endswith(f".{entry}") for entry in allowed)


def ensure_safe_url(url: str, *, param: str) -> None:
    """Raise ValidationError unless ``url`` is a safe outbound target.

    ``param`` names the offending tool argument so the LLM knows what to fix.
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValidationError(
            message=(f"{param} must be an http(s) URL; got scheme '{parsed.scheme or '(none)'}'."),
            retry_strategy="fix_and_retry",
        )

    host = (parsed.hostname or "").lower()
    if not host:
        raise ValidationError(
            message=f"{param} has no host component.",
            retry_strategy="fix_and_retry",
        )

    allowed = _allowed_hosts()
    if allowed and not _host_matches(host, allowed):
        raise ValidationError(
            message=(
                f"{param} host '{host}' is not in this deployment's MANNA_ALLOWED_HOSTS allow-list."
            ),
            retry_strategy="abandon",
        )

    # An IP literal is checked directly — never resolved — so a literal can't
    # ride in on a permissive resolver.
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(a) for a in _resolve(host)]
        except OSError as e:
            # Fail closed: an unverifiable target is not fetched.
            raise ValidationError(
                message=f"{param} host '{host}' could not be resolved.",
                retry_strategy="abandon",
            ) from e

    # Every address must be public — a split-horizon name that returns one
    # public and one private record is still a pivot.
    if not addresses or not all(_is_public(ip) for ip in addresses):
        raise ValidationError(
            message=_BLOCKED_TARGET.format(param=param),
            retry_strategy="abandon",
        )
