"""End-to-end test for vo_schema_describe through an in-memory MCP client."""

import pytest
from fastmcp import Client

from astro_archives_mcp.tools import schema as schema_tools
from astro_archives_mcp.tools.schema import vo_schema_describe


class _FakeTap:
    """Stand-in for TapClient returning (column_name, datatype) rows."""

    def __init__(self, rows=None, exc=None):
        self._rows = rows if rows is not None else []
        self._exc = exc
        self.calls = []

    def query(self, *, endpoint, adql, maxrec=10_000):
        self.calls.append({"endpoint": endpoint, "adql": adql, "maxrec": maxrec})
        if self._exc:
            raise self._exc
        return self._rows


@pytest.fixture
def fake_columns(monkeypatch):
    """Opt in to a stubbed column fetch, overriding the offline autouse default."""

    def _install(rows=None, exc=None):
        fake = _FakeTap(rows=rows, exc=exc)
        monkeypatch.setattr(schema_tools, "_get_tap", lambda: fake)
        return fake

    return _install


@pytest.mark.asyncio
async def test_known_entry_returns_envelope_with_curated_fields(mcp_server):
    """Pins the structured fields for the NRAO obscore entry so a regression
    in the seed data fails loudly."""
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_schema_describe",
            {"archive": "nrao", "table": "tap_schema.obscore"},
        )
        payload = result.structured_content

    assert payload["known"] is True
    assert payload["archive"] == "nrao"
    assert payload["table"] == "tap_schema.obscore"
    assert "dataproduct_subtype" in payload["missing_standard_columns"]
    assert payload["value_enums"]["instrument_name"] == [
        "EVLA",
        "VLA",
        "VLBA",
        "GBT",
    ]
    assert payload["value_enums"]["facility_name"] == ["NRAO"]


@pytest.mark.asyncio
async def test_notes_are_plain_strings_with_no_audit_leak(mcp_server):
    """§7 envelope invariant: `notes` is a list[str] — Audit metadata must
    never leak into the LLM-facing payload."""
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_schema_describe",
            {"archive": "nrao", "table": "tap_schema.obscore"},
        )
        payload = result.structured_content

    assert payload["known"] is True
    notes = payload["notes"]
    assert isinstance(notes, list)
    assert len(notes) > 0
    for note in notes:
        assert isinstance(note, str)
        assert not isinstance(note, dict)


@pytest.mark.asyncio
async def test_unknown_pair_returns_known_false_with_no_other_keys(mcp_server):
    """On miss, only known/archive/table appear — no other Schema fields."""
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_schema_describe",
            {"archive": "bogus", "table": "bogus.bogus"},
        )
        payload = result.structured_content

    assert payload == {
        "known": False,
        "archive": "bogus",
        "table": "bogus.bogus",
    }


@pytest.mark.asyncio
async def test_empty_archive_returns_validation_error(mcp_server):
    """Empty input is a validation error, not a soft-miss."""
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_schema_describe",
            {"archive": "", "table": "tap_schema.obscore"},
        )
        payload = result.structured_content

    assert payload["error_class"] == "validation_error"
    assert payload["retry_strategy"] == "fix_and_retry"


# --------------------------------------------------------------------------- #
# column list
#
# The defect this closes: the HIT payload told the model "~99 columns wide.
# Always project an explicit column list" and then supplied neither the columns
# nor a route to them — a directive with no means to comply, so a model that
# obeyed had to invent column names. The pointer to vo_registry_describe lived
# only on the MISS path, so the better-curated a table was, the blinder the
# model got.
# --------------------------------------------------------------------------- #
def test_hit_returns_real_columns(fake_columns):
    fake_columns(rows=[("ra", "adql:DOUBLE"), ("gmag", "adql:REAL")])
    result = vo_schema_describe(archive="datalab", table="nsc_dr2.object")

    assert result["known"] is True
    assert result["columns"] == [
        {"name": "ra", "datatype": "adql:DOUBLE"},
        {"name": "gmag", "datatype": "adql:REAL"},
    ]
    assert "column_list_recipe" not in result


def test_datatype_passes_through_verbatim(fake_columns):
    """The archives disagree — datalab 'adql:DOUBLE', alma 'int', nrao
    'votable:char' (different TAP_SCHEMA versions). An LLM reads all three, so
    normalizing would only add a way to be wrong about a type."""
    fake_columns(rows=[("s_ra", "votable:double"), ("obs_id", "char")])
    result = vo_schema_describe(archive="nrao", table="tap_schema.obscore")

    assert [c["datatype"] for c in result["columns"]] == ["votable:double", "char"]


def test_fetch_failure_degrades_to_recipe(fake_columns):
    fake_columns(exc=RuntimeError("archive down"))
    result = vo_schema_describe(archive="datalab", table="nsc_dr2.object")

    assert result["known"] is True, "a dead archive must not destroy the curated notes"
    assert "columns" not in result
    assert result["column_list_recipe"].startswith("SELECT")
    assert result["notes"], "curated notes still served while degraded"


def test_recipe_uses_the_fully_qualified_table_name(fake_columns):
    """Verified live: table_name='object' returns 0 rows with NO error on Data
    Lab, while 'nsc_dr2.object' returns 99. A recipe that dropped the schema
    prefix would be worse than no recipe at all."""
    fake_columns(exc=RuntimeError("archive down"))
    recipe = vo_schema_describe(archive="datalab", table="nsc_dr2.object")["column_list_recipe"]

    assert "table_name = 'nsc_dr2.object'" in recipe
    assert "tap_schema.columns" in recipe


def test_exactly_one_of_columns_or_recipe_for_a_known_archive(fake_columns):
    """The model must never have to infer which case it got."""
    for rows, exc in ([("ra", "adql:DOUBLE")], None), (None, RuntimeError("x")):
        fake_columns(rows=rows, exc=exc)
        result = vo_schema_describe(archive="datalab", table="nsc_dr2.object")
        assert ("columns" in result) ^ ("column_list_recipe" in result)


def test_miss_on_known_archive_still_returns_columns(fake_columns):
    """A miss is where columns matter MOST — there are no curated notes at all.
    `known: false` means 'no curated notes', not 'no such table'."""
    fake_columns(rows=[("id", "adql:BIGINT")])
    result = vo_schema_describe(archive="datalab", table="nsc_dr2.not_curated")

    assert result["known"] is False
    assert result["columns"] == [{"name": "id", "datatype": "adql:BIGINT"}]


def test_unknown_archive_keeps_the_bare_miss_envelope(fake_columns):
    """No endpoint to ask, and a recipe naming an archive we can't identify is
    noise. Pins the pre-existing contract: a miss carries no other keys."""
    fake = fake_columns(rows=[("ra", "adql:DOUBLE")])
    result = vo_schema_describe(archive="bogus", table="bogus.bogus")

    assert result == {"known": False, "archive": "bogus", "table": "bogus.bogus"}
    assert fake.calls == [], "must not query an archive we have no endpoint for"


def test_empty_column_list_is_flagged_not_silently_empty(fake_columns):
    """0 rows means the table name is wrong (or the table is gone) — Data Lab
    returns 0 rows with NO error for table_name='object'. Say so."""
    fake_columns(rows=[])
    result = vo_schema_describe(archive="datalab", table="nsc_dr2.bogus")

    assert result["columns"] == []
    assert "fully qualified" in result["hint"]


def test_column_fetch_targets_the_archives_own_tap_url(fake_columns):
    fake = fake_columns(rows=[("ra", "adql:DOUBLE")])
    vo_schema_describe(archive="datalab", table="nsc_dr2.object")

    assert "noirlab" in fake.calls[0]["endpoint"]
    assert "nsc_dr2.object" in fake.calls[0]["adql"]


def test_offline_autouse_fixture_keeps_describe_hermetic():
    """Without opting in, the fetch must not touch the network — it degrades."""
    result = vo_schema_describe(archive="datalab", table="nsc_dr2.object")

    assert "columns" not in result
    assert "column_list_recipe" in result
