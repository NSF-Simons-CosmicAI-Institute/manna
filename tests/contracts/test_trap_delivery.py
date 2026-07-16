"""Contract tests for trap delivery (issue #57).

Knowledge the model *can* reach is not knowledge it *uses*: the NRAO LOWER/UPPER
note was true, live-probed and served by vo_archive_list, and the model still
wrote LOWER() in both eval conditions. These pin the two push channels:

- silent traps -> appended to the registered vo_tap_query description
- loud traps   -> the error payload's `hint`, next to error_class/retry_strategy
"""

import pytest
from fastmcp import Client

from astro_archives_mcp.app import build_mcp
from astro_archives_mcp.archives._traps import CHEATSHEET_TOKEN_BUDGET, estimate_tokens
from astro_archives_mcp.errors import DalQueryError, TimeoutArchiveError, error_to_payload
from astro_archives_mcp.tools import tap as tap_tool

NRAO = "https://data-query.nrao.edu/tap"
LOWER_ADQL = "SELECT TOP 10 * FROM tap_schema.obscore WHERE LOWER(target_name) = 'm87'"


async def _tap_description() -> str:
    """The description as an MCP client actually receives it — the only view
    that proves the injection survived registration."""
    async with Client(build_mcp()) as client:
        tools = await client.list_tools()
    return next(t.description or "" for t in tools if t.name == "vo_tap_query")


# ---------- channel 1: description injection ----------


@pytest.mark.asyncio
async def test_registered_tap_description_carries_the_cheatsheet():
    desc = await _tap_description()
    assert "COUNT(DISTINCT member_ous_uid)" in desc
    assert "q3c_radial_query" in desc


@pytest.mark.asyncio
async def test_injection_appends_and_does_not_replace_the_docstring():
    """The cheatsheet is additive — the tool's own guidance (and the shared
    error docstring) must survive it."""
    desc = await _tap_description()
    assert "Run an ADQL query against any IVOA-compliant TAP service" in desc
    assert "error_class" in desc  # _ERROR_DOCSTRING still appended


@pytest.mark.asyncio
async def test_cheatsheet_is_a_small_share_of_the_description():
    """Guardrail on the expensive channel: the injected blob must stay within
    budget as a *registered* description, not just in isolation."""
    base = tap_tool.vo_tap_query.__doc__ or ""
    injected = len(await _tap_description()) - len(base)
    assert 0 < estimate_tokens("x" * injected) <= CHEATSHEET_TOKEN_BUDGET


# ---------- channel 2: error-hint enrichment ----------


def test_rejected_lower_query_against_nrao_gets_the_curated_hint(monkeypatch):
    """A DalQueryError means the archive understood the ADQL and refused it —
    that's when curated guidance is trustworthy."""

    def _boom(**_kwargs):
        raise DalQueryError(message="Error in query: unknown function LOWER")

    monkeypatch.setattr(
        tap_tool, "_get_tap", lambda: type("C", (), {"query": staticmethod(_boom)})()
    )

    payload = tap_tool.vo_tap_query(endpoint=NRAO, adql=LOWER_ADQL, mode="sync")

    assert payload["error_class"] == "tap_query_error"
    assert payload["retry_strategy"] == "fix_and_retry"
    assert "LOWER()" in payload["hint"]


def test_hint_rides_every_mode(monkeypatch):
    """auto and async must not lose the hint — auto only intercepts timeouts,
    and async fails at submit."""

    def _boom(**_kwargs):
        raise DalQueryError(message="rejected")

    monkeypatch.setattr(
        tap_tool,
        "_get_tap",
        lambda: type(
            "C", (), {"query": staticmethod(_boom), "submit_async": staticmethod(_boom)}
        )(),
    )

    for mode in ("sync", "auto", "async"):
        payload = tap_tool.vo_tap_query(endpoint=NRAO, adql=LOWER_ADQL, mode=mode)
        assert "LOWER()" in payload.get("hint", ""), f"mode={mode} lost the hint"


def test_clean_adql_gets_no_hint(monkeypatch):
    """No curated trap matched -> no invented advice."""

    def _boom(**_kwargs):
        raise DalQueryError(message="some other syntax error")

    monkeypatch.setattr(
        tap_tool, "_get_tap", lambda: type("C", (), {"query": staticmethod(_boom)})()
    )

    payload = tap_tool.vo_tap_query(
        endpoint=NRAO, adql="SELECT TOP 1 * FROM tap_schema.obscore", mode="sync"
    )
    assert "hint" not in payload


def test_timeout_gets_no_hint(monkeypatch):
    """A timeout says nothing about the ADQL, so it must not attract ADQL
    advice — only DalQueryError is a semantic rejection."""

    def _boom(**_kwargs):
        raise TimeoutArchiveError(message="read timed out")

    monkeypatch.setattr(
        tap_tool, "_get_tap", lambda: type("C", (), {"query": staticmethod(_boom)})()
    )

    payload = tap_tool.vo_tap_query(endpoint=NRAO, adql=LOWER_ADQL, mode="sync")
    assert payload["error_class"] == "archive_error"
    assert "hint" not in payload


def test_existing_hint_is_never_overwritten(monkeypatch):
    def _boom(**_kwargs):
        raise DalQueryError(message="rejected", hint="upstream hint wins")

    monkeypatch.setattr(
        tap_tool, "_get_tap", lambda: type("C", (), {"query": staticmethod(_boom)})()
    )

    payload = tap_tool.vo_tap_query(endpoint=NRAO, adql=LOWER_ADQL, mode="sync")
    assert payload["hint"] == "upstream hint wins"


def test_hint_never_displaces_the_error_contract():
    """The reliability contract: error_class + retry_strategy always present."""
    err = DalQueryError(message="rejected", hint="do the other thing")
    payload = error_to_payload(err, request_id="r1")
    assert payload["error_class"] == "tap_query_error"
    assert payload["retry_strategy"] == "fix_and_retry"
    assert payload["hint"] == "do the other thing"
