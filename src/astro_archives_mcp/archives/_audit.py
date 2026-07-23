"""Audit — the falsifiable probe (or manual marker) a Note carries.

An `Audit` is the declarative half of a curated claim: how to re-check it live.
It carries NO network code — the live runner (`scripts/knowledge_audit.py`) reads these and
executes them. Keeping `Audit` pure keeps the model layer dependency-free.

`expect` reuses the caveat vocabulary the probe engine already understands:
  ok | error | empty | nonempty | count | manual
`manual` marks a claim that a single ADQL probe can't check (download recipes,
naming conventions, async-only behaviours) — it must carry a `reason`.
"""

from dataclasses import dataclass

AUDIT_EXPECTS: frozenset[str] = frozenset({"ok", "error", "empty", "nonempty", "count", "manual"})


def has_table(table: str) -> str:
    """ADQL asking whether `table` is present in tap_schema.tables."""
    return f"SELECT table_name FROM tap_schema.tables WHERE table_name = '{table}'"


def has_cols(table: str, columns: tuple[str, ...]) -> str:
    """ADQL selecting which of `columns` are present on `table`."""
    inlist = ", ".join(f"'{c}'" for c in columns)
    return (
        f"SELECT column_name FROM tap_schema.columns "
        f"WHERE table_name = '{table}' AND column_name IN ({inlist})"
    )


@dataclass(frozen=True)
class Audit:
    expect: str
    adql: str = ""
    columns: tuple[str, ...] = ()
    reason: str = ""

    def __post_init__(self) -> None:
        if self.expect not in AUDIT_EXPECTS:
            raise ValueError(
                f"unknown audit.expect {self.expect!r}; one of {sorted(AUDIT_EXPECTS)}"
            )
        if self.expect == "manual":
            if not self.reason:
                raise ValueError("manual audit requires a non-empty reason")
            if self.adql:
                raise ValueError("manual audit must not carry adql")
        elif self.expect == "count":
            if not self.columns:
                raise ValueError("count audit requires a non-empty columns tuple")
            if not self.adql:
                raise ValueError("count audit requires adql (use Audit.count)")
        else:  # ok | error | empty | nonempty
            if not self.adql:
                raise ValueError(f"{self.expect} audit requires adql")

    @classmethod
    def probe(cls, *, expect: str, adql: str) -> "Audit":
        return cls(expect=expect, adql=adql)

    @classmethod
    def count(cls, *, table: str, columns) -> "Audit":
        cols = tuple(columns)
        return cls(expect="count", adql=has_cols(table, cols), columns=cols)

    @classmethod
    def manual(cls, reason: str) -> "Audit":
        return cls(expect="manual", reason=reason)
