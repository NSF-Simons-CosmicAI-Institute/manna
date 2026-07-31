"""Guard against SSRF via user-supplied URLs.

Every URL the LLM can influence (TAP/cone/SIA endpoints, registry
ivoid_or_url, async job_urls) reaches an HTTP client inside the server's
network. In the shared-service deployment that network also holds the
JupyterHub and every other user's container, so an unguarded fetch is a
pivot into trusted space.

DNS is stubbed via the `_resolve` seam — these tests never touch the
network.
"""

import pytest

from manna._url_guard import ensure_safe_url
from manna.config import get_settings
from manna.errors import ValidationError

PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    """Default: every hostname resolves to a public address."""
    monkeypatch.setattr("manna._url_guard._resolve", lambda host: [PUBLIC_IP])


@pytest.fixture(autouse=True)
def _clear_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_public_https_endpoint_is_allowed():
    ensure_safe_url("https://almascience.eso.org/tap", param="endpoint")


def test_public_http_endpoint_is_allowed():
    ensure_safe_url("http://almascience.eso.org/tap", param="endpoint")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.org/data",
        "gopher://example.org:70/_x",
        "data:text/plain,hello",
    ],
)
def test_non_http_schemes_are_rejected(url):
    with pytest.raises(ValidationError) as exc:
        ensure_safe_url(url, param="endpoint")
    assert exc.value.retry_strategy == "fix_and_retry"


@pytest.mark.parametrize("url", ["not-a-url", "https://", "://missing"])
def test_malformed_urls_are_rejected(url):
    with pytest.raises(ValidationError) as exc:
        ensure_safe_url(url, param="endpoint")
    assert exc.value.retry_strategy == "fix_and_retry"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/mcp/",  # the MCP server itself
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.0.0.5/tap",  # RFC1918
        "http://192.168.1.10/tap",  # RFC1918
        "http://172.16.4.4/tap",  # RFC1918
        "http://[::1]:8000/tap",  # IPv6 loopback
        "http://[fd00::1]/tap",  # IPv6 unique-local
        "http://0.0.0.0:8000/tap",  # unspecified
    ],
)
def test_internal_ip_literals_are_rejected(url):
    with pytest.raises(ValidationError) as exc:
        ensure_safe_url(url, param="endpoint")
    assert exc.value.retry_strategy == "abandon"


def test_hostname_resolving_to_private_space_is_rejected(monkeypatch):
    """`http://mcp:8000` — the compose-network service name — must not pass."""
    monkeypatch.setattr("manna._url_guard._resolve", lambda host: ["172.18.0.2"])
    with pytest.raises(ValidationError) as exc:
        ensure_safe_url("http://mcp:8000/mcp/", param="endpoint")
    assert exc.value.retry_strategy == "abandon"


def test_rejected_when_any_resolved_address_is_private(monkeypatch):
    """A split-horizon name with one public and one private A record is unsafe."""
    monkeypatch.setattr("manna._url_guard._resolve", lambda host: [PUBLIC_IP, "192.168.0.9"])
    with pytest.raises(ValidationError):
        ensure_safe_url("https://sneaky.example.org/tap", param="endpoint")


def test_unresolvable_host_is_rejected(monkeypatch):
    """Fail closed: if we cannot verify the target, we do not fetch it."""

    def _boom(host):
        raise OSError("Name or service not known")

    monkeypatch.setattr("manna._url_guard._resolve", _boom)
    with pytest.raises(ValidationError):
        ensure_safe_url("https://nonexistent.invalid/tap", param="endpoint")


def test_rejection_message_does_not_disclose_resolved_address(monkeypatch):
    """Do not turn the guard into an internal-network scanner.

    Echoing the resolved IP back would confirm which internal hosts exist.
    """
    monkeypatch.setattr("manna._url_guard._resolve", lambda host: ["172.18.0.2"])
    with pytest.raises(ValidationError) as exc:
        ensure_safe_url("http://mcp:8000/mcp/", param="endpoint")
    assert "172.18.0.2" not in exc.value.message


def test_rejection_message_names_the_offending_parameter():
    with pytest.raises(ValidationError) as exc:
        ensure_safe_url("http://127.0.0.1/tap", param="job_url")
    assert "job_url" in exc.value.message


def test_allowed_hosts_unset_permits_any_public_host():
    ensure_safe_url("https://anything.example.org/tap", param="endpoint")


def test_allowed_hosts_blocks_unlisted_public_host(monkeypatch):
    monkeypatch.setenv("MANNA_ALLOWED_HOSTS", "almascience.eso.org,datalab.noirlab.edu")
    get_settings.cache_clear()
    with pytest.raises(ValidationError) as exc:
        ensure_safe_url("https://evil.example.org/tap", param="endpoint")
    assert exc.value.retry_strategy == "abandon"


def test_allowed_hosts_permits_listed_host(monkeypatch):
    monkeypatch.setenv("MANNA_ALLOWED_HOSTS", "almascience.eso.org,datalab.noirlab.edu")
    get_settings.cache_clear()
    ensure_safe_url("https://almascience.eso.org/tap", param="endpoint")


def test_allowed_hosts_permits_subdomain_of_listed_host(monkeypatch):
    monkeypatch.setenv("MANNA_ALLOWED_HOSTS", "eso.org")
    get_settings.cache_clear()
    ensure_safe_url("https://almascience.eso.org/tap", param="endpoint")


def test_allowed_hosts_does_not_match_suffix_lookalike(monkeypatch):
    """`eso.org` must not admit `notaneso.org`."""
    monkeypatch.setenv("MANNA_ALLOWED_HOSTS", "eso.org")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        ensure_safe_url("https://notaneso.org/tap", param="endpoint")


def test_allowed_hosts_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("MANNA_ALLOWED_HOSTS", "ESO.org")
    get_settings.cache_clear()
    ensure_safe_url("https://AlmaScience.ESO.ORG/tap", param="endpoint")


def test_allowlist_does_not_override_private_address_block(monkeypatch):
    """Allowlisting a name that resolves internally must still be refused."""
    monkeypatch.setenv("MANNA_ALLOWED_HOSTS", "mcp")
    get_settings.cache_clear()
    monkeypatch.setattr("manna._url_guard._resolve", lambda host: ["172.18.0.2"])
    with pytest.raises(ValidationError):
        ensure_safe_url("http://mcp:8000/mcp/", param="endpoint")
