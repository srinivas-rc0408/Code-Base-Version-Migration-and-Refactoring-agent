"""Import accuracy — the import edits a migration makes, scored against ground truth.

Defined in ``docs/05_DATA_EVALUATION_PROTOCOL.md`` §2.3a. Separate from M1, which
scores call sites only: an import line is never a site, so M1 cannot see a
redundant or missing import. Here every name a file starts or stops importing is
one change, and ``ground_truth.json`` ``expected_import_changes`` lists the ones
a correct migration makes. A change gold does not make is *spurious*; an expected
change the run did not make is *missing*.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from mra.analysis.call_sites import is_test_path
from mra.analysis.dep_graph import python_files


def import_names(source: bytes) -> set[str]:
    """Names bound by import statements anywhere in ``source`` (``as`` aliases win)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names |= {a.asname or a.name.partition(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names |= {a.asname or a.name for a in node.names}
    return names


def source_tree(repo: Path) -> dict[str, bytes]:
    """Repo-relative path -> bytes for every non-test source file (NB-4 scope)."""
    files = {p.relative_to(repo).as_posix(): p for p in python_files(repo)}
    return {rel: p.read_bytes() for rel, p in files.items() if not is_test_path(rel)}


def _changes(old: dict[str, bytes], new: dict[str, bytes]) -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    for path in sorted({*old, *new}):
        try:
            before = import_names(old.get(path, b""))
            after = import_names(new.get(path, b""))
        except SyntaxError:
            continue  # an unparseable file is reported by the residual scan
        out |= {(path, "add", n) for n in after - before}
        out |= {(path, "remove", n) for n in before - after}
    return out


def imports(
    old: dict[str, bytes], new: dict[str, bytes], expected: list[dict[str, Any]] | None
) -> dict[str, Any] | None:
    """``{accuracy, expected, spurious, missing}`` or ``None`` without ground truth.

    ``old``/``new`` map repo-relative source paths to bytes before and after the
    migration. ``accuracy`` is correct / (expected ∪ actual) × 100, and 100 when
    nothing was expected and nothing changed.
    """
    if expected is None:
        return None
    want = {
        (e["file"], kind, name)
        for e in expected
        for kind in ("add", "remove")
        for name in e.get(kind, [])
    }
    got = _changes(old, new)
    union = want | got
    fmt = lambda c: f"{c[0]}: {'+' if c[1] == 'add' else '-'}{c[2]}"  # noqa: E731
    return {
        "accuracy": 100 * len(want & got) / len(union) if union else 100.0,
        "expected": len(want),
        "spurious": sorted(fmt(c) for c in got - want),
        "missing": sorted(fmt(c) for c in want - got),
    }
