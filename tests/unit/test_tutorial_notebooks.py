"""Every tutorial notebook under docs/tutorials/ is committed executed and error-free.

The site renders committed outputs (nb_execution_mode = "off"), so a half-run
or errored notebook would publish silently. This is the offline guard.
"""

from pathlib import Path

import pytest

nbformat = pytest.importorskip("nbformat")

TUTORIALS = Path(__file__).resolve().parents[2] / "docs" / "tutorials"
EXPECTED_NOTEBOOKS = [
    "01-first-query.ipynb",
    "02-large-results.ipynb",
    "03-images-and-catalogs.ipynb",
    "04-archive-notes-and-errors.ipynb",
]


@pytest.mark.parametrize("name", EXPECTED_NOTEBOOKS)
def test_notebook_is_executed_without_errors(name: str) -> None:
    path = TUTORIALS / name
    assert path.exists(), f"{name} is missing from docs/tutorials/"
    nb = nbformat.read(path, as_version=4)
    code_cells = [c for c in nb.cells if c.cell_type == "code"]
    assert code_cells, f"{name} has no code cells"
    for i, cell in enumerate(code_cells):
        assert cell.execution_count is not None, f"{name}: code cell {i} was never executed"
        for out in cell.outputs:
            assert out.output_type != "error", (
                f"{name}: code cell {i} raised {out.get('ename')}: {out.get('evalue')}"
            )

    counts = [c.execution_count for c in code_cells]
    expected = list(range(1, len(code_cells) + 1))
    assert counts == expected, (
        f"{name}: execution_count {counts} is not a fresh top-to-bottom run 1..{len(code_cells)}"
    )


def test_no_unexpected_notebooks() -> None:
    found = sorted(p.name for p in TUTORIALS.glob("*.ipynb"))
    assert found == EXPECTED_NOTEBOOKS, (
        "add new notebooks to EXPECTED_NOTEBOOKS and tutorials/index.md"
    )
