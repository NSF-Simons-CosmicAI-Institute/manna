from manna._archive_label import _CACHE, archive_label

# Cache isolation is handled globally by the autouse _clear_archive_label_cache
# fixture in tests/conftest.py.


def test_static_fastpath_hit_datalab():
    assert archive_label("https://datalab.noirlab.edu/tap") == "datalab"


def test_static_fastpath_hit_alma():
    assert archive_label("https://almascience.nrao.edu/tap") == "alma"


def test_unknown_url_derives_label_from_hostname_and_caches():
    url = "https://made-up-archive.example.org/tap"
    assert archive_label(url) == "example"
    # Result memoized under the full URL key.
    assert _CACHE[url] == "example"


def test_hostname_label_strips_subdomains():
    assert archive_label("https://mast.stsci.edu/tap") == "stsci"


def test_hostname_label_handles_multipart_public_suffix():
    # Ordinary 2-label suffix (.de) -> registrable label 'aip'
    assert archive_label("https://tap.gavo.aip.de/tap") == "aip"
    # 'ac.jp' is a multi-label suffix -> registrable label 'nao'
    assert archive_label("https://foo.nao.ac.jp/tap") == "nao"


def test_malformed_or_hostless_url_falls_back_to_other():
    assert archive_label("not-a-url") == "other"


def test_static_hits_skip_hostname_derivation_and_cache():
    url = "https://datalab.noirlab.edu/tap"
    assert archive_label(url) == "datalab"
    # Static map short-circuits before the cache write.
    assert url not in _CACHE


def test_archive_label_never_touches_the_network(monkeypatch):
    """Regression: archive_label must not import or call RegistryClient.
    The cosmetic label is derived offline; a RegTAP scan here was the
    latency footgun this change removed."""
    import manna.backends.registry as registry_module

    def _boom(*_a, **_k):
        raise AssertionError("archive_label hit the registry/network")

    monkeypatch.setattr(registry_module, "RegistryClient", _boom)
    assert archive_label("https://some-unregistered.example.net/tap") == "example"
