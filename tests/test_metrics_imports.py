"""Import accuracy (docs/05 §2.3a): spurious and missing imports, scored apart from M1."""

from __future__ import annotations

from mra.metrics import imports

OLD = {
    "pkg/core.py": b"from datetime import datetime\n",
    "pkg/report.py": b"import datetime as dt\n",
}
WANT = [{"file": "pkg/core.py", "add": ["timezone"], "remove": []}]


def test_the_expected_import_scores_100() -> None:
    new = {**OLD, "pkg/core.py": b"from datetime import datetime, timezone\n"}
    assert imports(OLD, new, WANT) == {
        "accuracy": 100.0,
        "expected": 1,
        "spurious": [],
        "missing": [],
    }


def test_a_redundant_import_is_spurious() -> None:
    """task02 warm r1: `import datetime as dt` already gives dt.timezone."""
    new = {**OLD, "pkg/report.py": b"import datetime as dt\nfrom datetime import timezone\n"}
    score = imports(OLD, new, [{"file": "pkg/report.py", "add": [], "remove": []}])
    assert score["spurious"] == ["pkg/report.py: +timezone"] and score["accuracy"] == 0.0


def test_a_required_import_left_out_is_missing() -> None:
    score = imports(OLD, OLD, WANT)
    assert score["missing"] == ["pkg/core.py: +timezone"] and score["accuracy"] == 0.0


def test_undefined_without_ground_truth_and_perfect_when_nothing_is_due() -> None:
    assert imports(OLD, OLD, None) is None
    assert imports(OLD, OLD, [])["accuracy"] == 100.0
