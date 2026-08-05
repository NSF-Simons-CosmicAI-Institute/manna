import manna._archive_label as label_module
from manna._archive_label import archive_label


def test_static_fastpath_hit_datalab():
    assert archive_label("https://datalab.noirlab.edu/tap") == "datalab"


def test_static_fastpath_hit_alma():
    assert archive_label("https://almascience.nrao.edu/tap") == "alma"


def test_unknown_url_derives_label_from_hostname():
    url = "https://made-up-archive.example.org/tap"
    assert archive_label(url) == "example"
    # Deterministic: repeat calls agree without any memoization behind them.
    assert archive_label(url) == "example"


def test_hostname_label_strips_subdomains():
    assert archive_label("https://mast.stsci.edu/tap") == "stsci"


def test_hostname_label_handles_multipart_public_suffix():
    # Ordinary 2-label suffix (.de) -> registrable label 'aip'
    assert archive_label("https://tap.gavo.aip.de/tap") == "aip"
    # 'ac.jp' is a multi-label suffix -> registrable label 'nao'
    assert archive_label("https://foo.nao.ac.jp/tap") == "nao"


def test_malformed_or_hostless_url_falls_back_to_other():
    assert archive_label("not-a-url") == "other"


def test_static_hits_short_circuit_hostname_derivation(monkeypatch):
    """A static-map hit must return before any hostname parsing."""

    def _boom(_host):
        raise AssertionError("static hit fell through to hostname derivation")

    monkeypatch.setattr(label_module, "_label_from_host", _boom)
    assert archive_label("https://datalab.noirlab.edu/tap") == "datalab"


def test_module_holds_no_unbounded_request_keyed_cache():
    """No process-global dict keyed on user-supplied URLs.

    `_CACHE` used to memoize label-by-endpoint for the life of the process,
    with no cap and no eviction, in a server every tenant shares. Its keys came
    straight from tool arguments, so one caller could grow it without bound —
    `vo_tap_abort` in particular swallows upstream errors and still labels the
    response, so every call was a guaranteed write. It bought ~0.01us per call
    against tool calls costing 10ms-1s of network, so it is gone rather than
    merely capped.
    """
    assert not hasattr(label_module, "_CACHE")
    unbounded = [
        name
        for name, val in vars(label_module).items()
        if isinstance(val, dict) and not name.startswith("__") and name != "_STATIC_MAP"
    ]
    assert not unbounded, f"unbounded module-level dicts reintroduced: {unbounded}"


def test_archive_label_never_touches_the_network(monkeypatch):
    """Regression: archive_label must not import or call RegistryClient.
    The cosmetic label is derived offline; a RegTAP scan here was the
    latency footgun this change removed."""
    import manna.backends.registry as registry_module

    def _boom(*_a, **_k):
        raise AssertionError("archive_label hit the registry/network")

    monkeypatch.setattr(registry_module, "RegistryClient", _boom)
    assert archive_label("https://some-unregistered.example.net/tap") == "example"
