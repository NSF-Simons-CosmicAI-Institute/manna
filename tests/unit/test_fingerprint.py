"""Fingerprint stability: the client-side cache names files by this value,
so identical queries must collapse to one hash and distinct queries must not."""

import re

from manna._fingerprint import query_fingerprint


def test_is_12_lowercase_hex():
    fp = query_fingerprint("tap", "https://example.org/tap", "SELECT 1")
    assert re.fullmatch(r"[0-9a-f]{12}", fp)


def test_whitespace_variants_collapse():
    a = query_fingerprint(
        "tap", "https://example.org/tap", "SELECT TOP 5 ra,dec\n   FROM ivoa.obscore"
    )
    b = query_fingerprint(
        "tap", "https://example.org/tap", "  SELECT TOP 5 ra,dec FROM ivoa.obscore  "
    )
    assert a == b


def test_case_is_significant():
    # ADQL string literals ('M87' vs 'm87') are case-significant; no folding.
    a = query_fingerprint("tap", "https://example.org/tap", "SELECT * FROM t WHERE x='M87'")
    b = query_fingerprint("tap", "https://example.org/tap", "SELECT * FROM t WHERE x='m87'")
    assert a != b


def test_distinct_inputs_distinct_hashes():
    base = query_fingerprint("tap", "https://example.org/tap", "SELECT 1")
    assert query_fingerprint("tap", "https://example.org/tap", "SELECT 2") != base
    assert query_fingerprint("tap", "https://other.org/tap", "SELECT 1") != base
    assert query_fingerprint("cone", "https://example.org/tap", "SELECT 1") != base
