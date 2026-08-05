from manna.archives._count import CountTarget, Q3CRadial
from manna.archives._model import Archive


def test_archive_count_target_defaults_none():
    a = Archive(short_name="x", display_name="X", host_substrings=("x.example",))
    assert a.count_target is None


def test_archive_carries_count_target():
    ct = CountTarget(table="t.object", geometry=Q3CRadial("ra", "dec"))
    a = Archive(
        short_name="x",
        display_name="X",
        host_substrings=("x.example",),
        tap_url="http://x/tap",
        count_target=ct,
    )
    assert a.count_target is ct
    assert a.count_target.table == "t.object"
