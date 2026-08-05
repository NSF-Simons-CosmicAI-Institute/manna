import pytest

import manna.tools._select as sel
import manna.tools.survey as survey_mod
from manna.archives._count import ContainsPoint, CountTarget, Q3CRadial
from manna.archives._model import Archive


def _arch(name, wb, mode="sync", geom=None, priority=100):
    return Archive(
        short_name=name,
        display_name=name.upper(),
        host_substrings=(f"{name}.x",),
        tap_url=f"http://{name}/tap",
        waveband=wb,
        priority=priority,
        count_target=CountTarget(
            table=f"{name}.obj", geometry=geom or Q3CRadial("ra", "dec"), mode=mode
        ),
    )


@pytest.fixture
def fleet(monkeypatch):
    archives = (
        _arch("datalab", "optical", priority=1),
        _arch("alma", "millimeter", geom=ContainsPoint("s_ra", "s_dec"), priority=2),
        _arch("nrao", "radio", mode="async", geom=ContainsPoint("s_ra", "s_dec"), priority=3),
    )
    monkeypatch.setattr(sel, "active_archives", lambda: archives)
    monkeypatch.setattr(
        sel, "get_resolver", lambda: type("R", (), {"resolve": lambda s, n: (187.7, 12.4)})()
    )
    return archives


def test_survey_aggregates_all_countable(fleet, monkeypatch):
    # datalab + alma return counts synchronously; nrao stays pending
    def fake_run_count(*, endpoint, adql, mode):
        if mode == "async":
            return {
                "status": "pending",
                "count": None,
                "job_url": "http://nrao/job/1",
            }
        n = 842 if "datalab" in endpoint else 37
        return {"status": "ok", "count": n, "job_url": None}

    monkeypatch.setattr(survey_mod, "_run_count", fake_run_count)

    out = survey_mod.vo_survey_target(target="M87")

    by = {r["archive"]: r for r in out["archives"]}
    assert by["datalab"]["count"] == 842 and by["datalab"]["status"] == "ok"
    assert by["alma"]["count"] == 37
    assert by["nrao"]["status"] == "pending" and by["nrao"]["job_url"] == "http://nrao/job/1"
    assert "next_steps" in by["nrao"]
    assert out["summary"]["archives_with_data"] == 2
    assert out["summary"]["pending"] == 1
    assert set(out["summary"]["wavebands"]) == {"optical", "millimeter"}


def test_survey_wavebands_filter(fleet, monkeypatch):
    monkeypatch.setattr(
        survey_mod, "_run_count", lambda **k: {"status": "ok", "count": 1, "job_url": None}
    )
    out = survey_mod.vo_survey_target(target="M87", wavebands=["optical"])
    assert [r["archive"] for r in out["archives"]] == ["datalab"]


def test_survey_per_archive_error_isolated(fleet, monkeypatch):
    from manna.errors import ArchiveError

    def flaky(*, endpoint, adql, mode):
        if "alma" in endpoint:
            raise ArchiveError(message="boom")
        return {"status": "ok", "count": 5, "job_url": None}

    monkeypatch.setattr(survey_mod, "_run_count", flaky)

    out = survey_mod.vo_survey_target(target="M87")
    by = {r["archive"]: r for r in out["archives"]}
    assert by["alma"]["status"] == "error"
    assert by["datalab"]["count"] == 5
    assert out["summary"]["errors"] == 1


def test_survey_unresolvable_soft_fails(fleet, monkeypatch):
    monkeypatch.setattr(
        sel, "get_resolver", lambda: type("R", (), {"resolve": lambda s, n: None})()
    )
    out = survey_mod.vo_survey_target(target="XYZZY")
    assert out["resolved"] is False


def test_survey_empty_target_validation_error(fleet):
    out = survey_mod.vo_survey_target(target="")
    assert out.get("error_class") == "validation_error"


def test_survey_whitespace_target_validation_error(fleet):
    out = survey_mod.vo_survey_target(target="   ")
    assert out.get("error_class") == "validation_error"
