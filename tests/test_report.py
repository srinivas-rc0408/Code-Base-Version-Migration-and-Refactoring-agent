"""Verdict, evidence, the 14-page PDF report, and the codemod's import placement.

Offline: one verdict test per RED/YELLOW condition plus precedence, the
evidence scanners, the page budget on a synthetic 200-file run, the filename,
the terminal banner. Docker-backed: a real GREEN corpus run, a forced YELLOW
run, a crashed RED run — each must print its status on page 1 and the last
page — and a report rebuilt from state.db that matches the original.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import libcst as cst
import pytest
from libcst.codemod import CodemodContext
from pypdf import PdfReader

from mra.codemods.datetime_utcnow import ConvertUtcnowCommand
from mra.report import build_report, report_filename, run_with_report, sanitize, terminal_summary
from mra.report.evidence import parse_patch, residual_scan, semantic_checks
from mra.report.model import build_model
from mra.report.pdf import MAX_PAGES, render
from mra.verdict import new_lint, verdict

ROOT = Path(__file__).resolve().parents[1]
TIER_A = ROOT / "corpus" / "tierA"
TARGET = "datetime.datetime.utcnow"


def _docker_ok() -> bool:
    try:
        return (
            subprocess.run(
                ["docker", "image", "inspect", "mra-sandbox:py312"],
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
    except FileNotFoundError:
        return False


needs_docker = pytest.mark.skipif(not _docker_ok(), reason="needs docker + mra-sandbox:py312")


# -- verdict: one test per condition ---------------------------------------


GREEN_RUN: dict[str, Any] = {
    "crash": None,
    "pre_report": {"total": 5, "passed": 5, "failed": 0, "errors": 0, "failures": []},
    "post_report": {"total": 5, "passed": 5, "failed": 0, "errors": 0, "failures": []},
    "metrics": {"outcome": "success", "m1_precision": 100.0, "m3_tokens": 0},
    "tamper": [],
    "rejected_tamper": [],
    "apply_check": {"ok": True, "detail": "applies cleanly"},
    "token_budget": 1000,
    "run_timeout_s": 60,
    "wall_clock_s": 5.0,
    "residual": {"sites": [], "skipped": [], "unparseable": []},
    "has_ground_truth": True,
    "expected_sites": 1,
    "found_sites": 1,
    "scanned_files": 1,
    "semantic": [{"check": "aware", "file": "a.py", "passed": True, "detail": "ok"}],
    "lint": {"pre": [], "post": [], "exempt": []},
    "coverage": {"available": True, "files": {"a.py": {"changed": [3], "executed": [3]}}},
}
FINDING = {"code": "F401", "file": "a.py", "message": "`os` imported but unused"}


def _with(**changes: Any) -> dict[str, Any]:
    run = copy.deepcopy(GREEN_RUN)
    run.update(changes)
    return run


def _codes(run: dict[str, Any]) -> list[str]:
    return [r["code"] for r in verdict(run)["reasons"]]


def test_green_when_nothing_is_wrong() -> None:
    assert verdict(GREEN_RUN) == {"status": "GREEN", "reasons": []}


RED_CASES = {
    "pre-suite not green": (
        _with(pre_report={**GREEN_RUN["pre_report"], "failed": 1}),
        "precondition",
    ),
    "pre-suite has zero tests": (
        _with(pre_report={**GREEN_RUN["pre_report"], "total": 0, "passed": 0}),
        "precondition",
    ),
    "crashed": (_with(crash="Traceback ...\nRuntimeError: boom", metrics=None), "crashed"),
    "gave up": (_with(metrics={**GREEN_RUN["metrics"], "outcome": "gave_up"}), "gave_up"),
    "final suite has a failure": (
        _with(
            post_report={
                **GREEN_RUN["post_report"],
                "failed": 1,
                "failures": [{"nodeid": "tests/test_a.py::t"}],
            }
        ),
        "suite_red",
    ),
    "final suite has a collection error": (
        _with(
            post_report={
                **GREEN_RUN["post_report"],
                "errors": 1,
                "failures": [{"nodeid": "tests/test_a.py"}],
            }
        ),
        "suite_red",
    ),
    "no final suite at all": (_with(post_report=None), "suite_red"),
    "test file in the patch": (_with(tamper=["tests/test_a.py"]), "tamper"),
    "rejected tamper attempt": (_with(rejected_tamper=["tests/conftest.py"]), "tamper"),
    "patch does not apply": (
        _with(apply_check={"ok": False, "detail": "corrupt patch"}),
        "apply_check",
    ),
    "token budget exceeded": (
        _with(metrics={**GREEN_RUN["metrics"], "m3_tokens": 1001}),
        "token_budget",
    ),
    "timeout exceeded": (_with(wall_clock_s=61.0), "timeout"),
    "no file scanned": (_with(scanned_files=0, found_sites=0), "no_files_scanned"),
}


@pytest.mark.parametrize("case", sorted(RED_CASES))
def test_red_condition(case: str) -> None:
    run, code = RED_CASES[case]
    result = verdict(run)
    assert result["status"] == "RED"
    assert code in _codes(run)
    assert all(r["text"] and r["evidence"] and r["action"] for r in result["reasons"])


YELLOW_CASES = {
    "residual call site": (
        _with(residual={"sites": [{"file": "b.py", "line": 4}], "skipped": [], "unparseable": []}),
        "residual",
    ),
    "skipped star import": (
        _with(
            residual={
                "sites": [],
                "unparseable": [],
                "skipped": [{"file": "b.py", "line": 1, "kind": "star-import"}],
            }
        ),
        "residual",
    ),
    "over-editing (precision < 100)": (
        _with(metrics={**GREEN_RUN["metrics"], "m1_precision": 80.0}),
        "precision",
    ),
    "semantic check fails": (
        _with(
            semantic=[
                {
                    "check": "aware",
                    "file": "a.py",
                    "passed": False,
                    "detail": "tz not imported: timezone.utc",
                }
            ]
        ),
        "semantic",
    ),
    "new ruff error": (_with(lint={"pre": [], "post": [FINDING], "exempt": []}), "lint"),
    "unparseable file": (
        _with(residual={"sites": [], "skipped": [], "unparseable": ["bad.py"]}),
        "unparseable",
    ),
    "edited file never executed": (
        _with(coverage={"available": True, "files": {"a.py": {"changed": [3, 4], "executed": []}}}),
        "unexecuted",
    ),
    "coverage unavailable": (
        _with(
            coverage={
                "available": False,
                "error": "no coverage.json",
                "files": {"a.py": {"changed": [3], "executed": []}},
            }
        ),
        "unexecuted",
    ),
    "no sites found where the ground truth expects some": (
        _with(found_sites=0),
        "nothing_to_migrate",
    ),
}


@pytest.mark.parametrize("case", sorted(YELLOW_CASES))
def test_yellow_condition(case: str) -> None:
    run, code = YELLOW_CASES[case]
    assert verdict(run)["status"] == "YELLOW"
    assert _codes(run) == [code]


def test_no_sites_is_green_when_the_ground_truth_expects_none() -> None:
    """Already migrated: nothing found, nothing expected."""
    assert verdict(_with(found_sites=0, expected_sites=0))["status"] == "GREEN"
    assert verdict(_with(found_sites=0, expected_sites=None))["status"] == "GREEN"


def test_precision_is_not_judged_when_nothing_was_edited() -> None:
    """Already migrated: 0/0 is undefined, not over-editing."""
    run = _with(edited_files=0, metrics={**GREEN_RUN["metrics"], "m1_precision": 0.0})
    assert verdict(run)["status"] == "GREEN"


def test_lint_message_text_is_not_part_of_the_key() -> None:
    """B008 quotes the call it flags, so migrating the call changes the message."""
    before = {"code": "B008", "file": "a.py", "message": "call `datetime.utcnow` in default"}
    after = {**before, "message": "call `datetime.now` in default"}
    assert new_lint({"pre": [before], "post": [after], "exempt": []}) == []


def test_unreachable_provider_and_refusals_have_their_own_reasons() -> None:
    provider = _with(
        crash="ProviderError: role 'classify': every provider was unreachable", metrics=None
    )
    assert _codes(provider)[0] == "provider"
    refused = _with(
        refused="PrivacyError: MRA_PRIVACY=local-only: role 'edit' ...",
        pre_report=None,
        post_report=None,
        metrics=None,
    )
    assert _codes(refused) == ["refused"]


def test_precondition_names_the_network_when_that_is_the_cause() -> None:
    pre = {
        "total": 2,
        "passed": 1,
        "failed": 1,
        "errors": 0,
        "failures": [
            {
                "nodeid": "tests/test_a.py::test_fetch",
                "exc_type": "gaierror",
                "message": "[Errno -3] Temporary failure in name resolution",
            }
        ],
    }
    reason = verdict(_with(pre_report=pre))["reasons"][0]
    assert reason["code"] == "precondition" and "--network none" in reason["evidence"]


def test_precision_is_not_judged_without_ground_truth() -> None:
    run = _with(has_ground_truth=False, metrics={**GREEN_RUN["metrics"], "m1_precision": 50.0})
    assert verdict(run)["status"] == "GREEN"


def test_red_beats_yellow_and_both_are_reported() -> None:
    run = _with(
        tamper=["tests/test_a.py"],
        residual={"sites": [{"file": "b.py", "line": 4}], "skipped": [], "unparseable": []},
    )
    result = verdict(run)
    assert result["status"] == "RED"
    assert [r["level"] for r in result["reasons"]] == ["RED", "YELLOW"]


def test_lint_is_a_multiset_and_contract_exemptions_are_honoured() -> None:
    upgrade = {"code": "UP017", "file": "a.py", "message": "Use `datetime.UTC` alias"}
    # One fixed, one introduced: a count would see no change; the multiset does.
    swapped = {"pre": [FINDING], "post": [{**FINDING, "code": "E711"}], "exempt": []}
    assert [f["code"] for f in new_lint(swapped)] == ["E711"]
    # UP017 is declared by the migration contract, so it is not "new".
    assert new_lint({"pre": [], "post": [upgrade], "exempt": ["UP017"]}) == []
    assert (
        verdict(_with(lint={"pre": [], "post": [upgrade], "exempt": ["UP017"]}))["status"]
        == "GREEN"
    )


# -- evidence scanners -----------------------------------------------------


def test_residual_scan_reports_calls_skips_and_unparseable(tmp_path: Path) -> None:
    (tmp_path / "left.py").write_text("from datetime import datetime\nx = datetime.utcnow()\n")
    (tmp_path / "star.py").write_text("from datetime import *\n")
    (tmp_path / "bare.py").write_text("from datetime import datetime\nclock = datetime.utcnow\n")
    (tmp_path / "broken.py").write_text("def (:\n")
    (tmp_path / "clean.py").write_text(
        "from datetime import datetime, timezone\nx = datetime.now(timezone.utc)\n"
    )
    found = residual_scan(tmp_path, TARGET)
    assert [(s["file"], s["line"]) for s in found["sites"]] == [("left.py", 2)]
    assert sorted((s["file"], s["kind"]) for s in found["skipped"]) == [
        ("bare.py", "bare-reference"),
        ("star.py", "star-import"),
    ]
    assert found["unparseable"] == ["broken.py"]


def test_semantic_check_catches_unimported_tz_and_new_naive_now(tmp_path: Path) -> None:
    base, repo = tmp_path / "base", tmp_path / "repo"
    for root in (base, repo):
        root.mkdir()
    (base / "a.py").write_text("from datetime import datetime\nx = datetime.utcnow()\n")
    (repo / "a.py").write_text("from datetime import datetime\nx = datetime.now(timezone.utc)\n")
    (base / "b.py").write_text("from datetime import datetime\nx = datetime.utcnow()\n")
    (repo / "b.py").write_text("from datetime import datetime\nx = datetime.now()\n")
    (base / "c.py").write_text("from datetime import datetime\nx = datetime.utcnow()\n")
    (repo / "c.py").write_text(
        "from datetime import datetime, timezone\nx = datetime.now(timezone.utc)\n"
    )
    checks = {
        c["file"]: c
        for c in semantic_checks(base, repo, ["a.py", "b.py", "c.py"], TARGET)
        if c["check"] != "line endings preserved"
    }
    assert not checks["a.py"]["passed"] and "tz not imported" in checks["a.py"]["detail"]
    assert not checks["b.py"]["passed"] and "naive" in checks["b.py"]["detail"]
    assert checks["c.py"]["passed"]
    other = semantic_checks(base, repo, ["a.py"], "os.path.join")
    assert [c["check"] for c in other] == ["line endings preserved"], "only the generic check"


def test_parse_patch_counts_lines_and_new_line_numbers() -> None:
    patch = (
        "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n"
        "@@ -1,3 +1,3 @@\n-from datetime import datetime\n"
        "+from datetime import datetime, timezone\n \n"
        "@@ -8,1 +8,1 @@\n-    return datetime.utcnow()\n"
        "+    return datetime.now(timezone.utc)\n"
    )
    parsed = parse_patch(patch)["src/a.py"]
    assert (parsed["added"], parsed["removed"]) == (2, 2)
    assert parsed["new_lines"] == [1, 8]


# -- the codemod's import placement (NB-2) ----------------------------------


def _migrate(source: str) -> str:
    return ConvertUtcnowCommand(CodemodContext()).transform_module(cst.parse_module(source)).code


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("from datetime import datetime\n", "from datetime import datetime, timezone\n"),
        (
            "from datetime import date, datetime\n",
            "from datetime import date, datetime, timezone\n",
        ),
        (
            "from datetime import datetime, tzinfo\n",
            "from datetime import datetime, timezone, tzinfo\n",
        ),
        (
            "from datetime import (\n    date,\n    datetime,\n)\n",
            "from datetime import (\n    date,\n    datetime,\n    timezone,\n)\n",
        ),
        ("from datetime import datetime, timezone\n", "from datetime import datetime, timezone\n"),
    ],
)
def test_timezone_lands_in_its_sorted_slot(before: str, after: str) -> None:
    assert (
        _migrate(before + "x = datetime.utcnow()\n") == after + "x = datetime.now(timezone.utc)\n"
    )


def test_other_import_lines_are_not_touched() -> None:
    source = "import sys\nfrom datetime import datetime, date\nimport os\nx = datetime.utcnow()\n"
    assert _migrate(source) == (
        "import sys\nfrom datetime import datetime, date, timezone\n"
        "import os\nx = datetime.now(timezone.utc)\n"
    )


def test_aliased_import_gets_its_own_timezone_line() -> None:
    """ruff keeps `as` imports on their own line (I001); appending would break that."""
    assert _migrate("from datetime import datetime as DT\nx = DT.utcnow()\n") == (
        "from datetime import datetime as DT\nfrom datetime import timezone\n"
        "x = DT.now(timezone.utc)\n"
    )


def test_utcfromtimestamp_gains_the_timezone_argument() -> None:
    assert (
        _migrate("from datetime import datetime\nx = datetime.utcfromtimestamp(t)\n")
        == "from datetime import datetime, timezone\nx = datetime.fromtimestamp(t, timezone.utc)\n"
    )


@pytest.mark.parametrize(
    ("source", "site", "expected_head"),
    [
        # datetime arrived through a re-export: a new stdlib line goes above first party,
        (
            "from pkg import datetime\n\nx = datetime.utcnow()\n",
            (3, 4),
            "from datetime import timezone\n\nfrom pkg import datetime\n",
        ),
        # ...joins an existing stdlib block without a blank line,
        (
            "import os\n\nfrom pkg import datetime\n\nx = datetime.utcnow()\n",
            (5, 4),
            "import os\nfrom datetime import timezone\n\nfrom pkg import datetime\n",
        ),
        # ...and sits above a relative import.
        (
            "from .compat import datetime\n\nx = datetime.utcnow()\n",
            (3, 4),
            "from datetime import timezone\n\nfrom .compat import datetime\n",
        ),
    ],
)
def test_new_timezone_import_lands_where_isort_puts_it(
    source: str, site: tuple[int, int], expected_head: str
) -> None:
    out = (
        ConvertUtcnowCommand(CodemodContext(), sites={site})
        .transform_module(cst.parse_module(source))
        .code
    )
    assert out.startswith(expected_head), out


def test_given_sites_only_those_calls_change() -> None:
    """A shadowed `datetime` the analyzer rejected must not be edited by the codemod."""
    source = (
        "from datetime import datetime\n\n\ndef fake():\n    datetime = Clock()\n"
        "    return datetime.utcnow()\n\n\ndef real():\n    return datetime.utcnow()\n"
    )
    out = (
        ConvertUtcnowCommand(CodemodContext(), sites={(10, 11)})
        .transform_module(cst.parse_module(source))
        .code
    )
    assert "    return datetime.utcnow()\n\n\ndef real" in out, "shadowed call untouched"
    assert out.endswith("    return datetime.now(timezone.utc)\n")


def test_crlf_survives_a_bytes_round_trip(tmp_path: Path) -> None:
    from mra.nodes.edit_node import apply_codemod

    (tmp_path / "m.py").write_bytes(b"from datetime import datetime\r\nx = datetime.utcnow()\r\n")
    apply_codemod(tmp_path, {"m.py": [{"line": 2, "col": 4}]})
    assert (
        (tmp_path / "m.py").read_bytes()
        == b"from datetime import datetime, timezone\r\nx = datetime.now(timezone.utc)\r\n"
    )


def test_module_import_still_adds_no_import() -> None:
    """task02's point: `import datetime as dt` already reaches dt.timezone."""
    assert (
        _migrate("import datetime as dt\nx = dt.datetime.utcnow()\n")
        == "import datetime as dt\nx = dt.datetime.now(dt.timezone.utc)\n"
    )


# -- the page budget, on a synthetic 200-file run ---------------------------


def _synthetic_run(n: int = 200) -> dict[str, Any]:
    files = [f"src/pkg/mod{i:03d}.py" for i in range(n)]
    sites = {f: [{"file": f, "line": 8, "col": 11, "symbol": TARGET}] for f in files}
    batches = [files[i : i + 3] for i in range(0, n, 3)]
    trajectory = [
        {"seq": 0, "node": "MAP", "action": f"found {n} call site(s)", "detail": {}},
        {
            "seq": 1,
            "node": "PLAN",
            "action": f"planned {len(batches)} batch(es)",
            "detail": {
                "batches": batches,
                "cycles_collapsed": [],
                "batch_size": 3,
                "fr3_violations": [],
            },
        },
    ]
    for i, batch in enumerate(batches):
        trajectory += [
            {
                "node": "EDIT",
                "action": f"batch {i}: codemod changed {len(batch)} file(s)",
                "detail": {"batch": i, "files": batch, "changed": batch},
            },
            {
                "node": "TEST",
                "action": f"suite after batch {i + 1}: {n}/{n} passed",
                "detail": {"total": n, "passed": n, "failed": 0, "errors": 0, "failures": []},
            },
        ]
    trajectory.append({"node": "FINISH", "action": "success", "detail": {"outcome": "success"}})
    for seq, event in enumerate(trajectory):
        event.update(seq=seq, ts="2026-10-01T00:00:00+00:00")
    patch = "".join(
        f"diff --git a/{f} b/{f}\n--- a/{f}\n+++ b/{f}\n@@ -1,8 +1,8 @@\n"
        "-from datetime import datetime\n+from datetime import datetime, timezone\n \n \n"
        ' def make() -> datetime:\n     """Now."""\n'
        "-    return datetime.utcnow()\n+    return datetime.now(timezone.utc)\n"
        for f in files
    )
    report = {"total": n, "passed": n, "failed": 0, "errors": 0, "failures": []}
    evidence = {
        "target": TARGET,
        "inventory": [{"file": f, "loc": 12} for f in files],
        "residual": {"sites": [], "skipped": [], "unparseable": []},
        "apply_check": {"ok": True, "detail": "applies cleanly"},
        "semantic": [{"check": "aware", "file": f, "passed": True, "detail": "ok"} for f in files],
        "coverage": {
            "available": True,
            "files": {f: {"changed": [1, 7], "executed": [1, 7]} for f in files},
        },
        "lint": {"pre": [], "post": []},
    }
    return {
        "meta": {
            "run_id": "synthetic200",
            "repo_name": "big repo",
            "agent_version": "0.2.0",
            "source_api": "datetime.utcnow",
            "target_api": "datetime.now(timezone.utc)",
            "started_at": "2026-10-01T00:00:00+00:00",
            "has_ground_truth": True,
        },
        "state": {
            "call_sites": sites,
            "dep_graph": {f: [files[i + 1]] for i, f in enumerate(files[:-1])},
            "file_status": dict.fromkeys(files, "migrated"),
            "contract": {},
        },
        "trajectory": trajectory,
        "patch": patch,
        "evidence": evidence,
        **{k: v for k, v in GREEN_RUN.items() if k not in ("semantic", "coverage", "lint")},
        "pre_report": report,
        "post_report": report,
        "metrics": {
            "outcome": "success",
            "m1_recall": 100.0,
            "m1_precision": 100.0,
            "m2_pass_rate": 100.0,
            "m2_regressions": 0,
            "m3_tokens": 0,
            "m3_steps": len(trajectory),
            "m3_cost_usd": 0.0,
        },
        "semantic": evidence["semantic"],
        "coverage": evidence["coverage"],
        "lint": {"pre": [], "post": [], "exempt": []},
    }


def _pages(data: bytes) -> list[str]:
    import io

    return [page.extract_text() for page in PdfReader(io.BytesIO(data)).pages]


def test_a_200_file_run_fits_in_14_pages_by_truncating() -> None:
    model = build_model(_synthetic_run())
    data, pages, cuts = render(model, generated="2026-10-01 00:00 UTC")
    text = _pages(data)
    assert pages == len(text) <= MAX_PAGES
    assert cuts, "a 200-file run must need truncation"
    assert cuts.get("diff_files") == 0, "diff excerpts are the first thing cut"
    assert "see report.json" in "".join(text)
    assert "GREEN" in text[0] and "GREEN" in text[-1]
    assert len(model["files"]) == 200 and len(model["changes"]) == 200, "model is never cut"


# -- filename + terminal ----------------------------------------------------


def test_filename_matches_the_pattern() -> None:
    from datetime import datetime

    from mra import __version__

    name = report_filename("my repo/ü!", datetime(2026, 10, 1, 9, 5))
    assert name == f"my_repo_MigrationReport_v{__version__}_20261001-0905.pdf"
    assert re.fullmatch(r"[A-Za-z0-9_-]+_MigrationReport_v\d+\.\d+\.\d+_\d{8}-\d{4}\.pdf", name)
    assert sanitize("../..") == "repo"


def test_terminal_summary_respects_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    model = build_model(_synthetic_run(3))
    monkeypatch.setenv("NO_COLOR", "1")
    plain = terminal_summary(model, Path("r.pdf"))
    assert "\033[" not in plain and plain.startswith("[GREEN]")
    monkeypatch.delenv("NO_COLOR")
    assert "\033[" in terminal_summary(model, Path("r.pdf"))
    assert str(Path("r.pdf").resolve()) in plain


# -- real runs: GREEN, forced YELLOW, crashed RED ----------------------------


def _codemod_corrector() -> Any:
    from mra.benchmark.runner import codemod_corrector

    return codemod_corrector


def _status_on_first_and_last_page(pdf: Path, status: str) -> list[str]:
    pages = [p.extract_text() for p in PdfReader(pdf).pages]
    assert len(pages) <= MAX_PAGES
    assert status in pages[0], f"{status} missing from page 1"
    assert status in pages[-1], f"{status} missing from the last page"
    return pages


@pytest.fixture(scope="module")
def green_run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    runs = tmp_path_factory.mktemp("runs")
    return run_with_report(
        TIER_A / "task01_datetime", run_id="green", runs_dir=runs, corrector=_codemod_corrector()
    )


@needs_docker
def test_green_corpus_run_renders_green(green_run: dict[str, Any]) -> None:
    assert green_run["model"]["verdict"]["status"] == "GREEN", green_run["model"]["issues"]
    _status_on_first_and_last_page(green_run["pdf"], "GREEN")
    assert (green_run["out_dir"] / "report.json").is_file()


@needs_docker
def test_forced_yellow_run_renders_yellow(tmp_path: Path) -> None:
    """An extra module no test imports: migrated, never executed, outside ground truth."""
    task = tmp_path / "task01_untested_module"
    shutil.copytree(TIER_A / "task01_datetime", task)
    (task / "old" / "src" / "pkg" / "orphan.py").write_text(
        "from datetime import datetime\n\n\ndef stamp() -> datetime:\n"
        "    return datetime.utcnow()\n"
    )
    result = run_with_report(
        task, run_id="yellow", runs_dir=tmp_path / "runs", corrector=_codemod_corrector()
    )
    codes = {r["code"] for r in result["model"]["issues"]}
    assert result["model"]["verdict"]["status"] == "YELLOW"
    assert {"unexecuted", "precision"} <= codes
    _status_on_first_and_last_page(result["pdf"], "YELLOW")


@needs_docker
def test_crashed_run_still_writes_a_red_report(tmp_path: Path) -> None:
    def exploding(repo: Path, failure: dict[str, Any], context: dict[str, Any]) -> list[str]:
        raise RuntimeError("corrector exploded")

    result = run_with_report(
        TIER_A / "task03_half_migration",
        run_id="red",
        runs_dir=tmp_path / "runs",
        corrector=exploding,
    )
    assert result["crashed"]
    assert result["model"]["verdict"]["status"] == "RED"
    assert "crashed" in {r["code"] for r in result["model"]["issues"]}
    pages = _status_on_first_and_last_page(result["pdf"], "RED")
    assert "corrector exploded" in "".join(pages)
    meta = json.loads((result["out_dir"] / "run_meta.json").read_text())
    assert "RuntimeError: corrector exploded" in meta["crash"]


@needs_docker
def test_report_rebuilt_from_state_db_is_text_identical(green_run: dict[str, Any]) -> None:
    """Only the one "Report generated" line may differ; the footer timestamp may not."""
    import time

    from mra.report.pdf import completed_at

    generated = re.compile(
        r"Report generated \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \S+ "
        r"\([+-]\d{2}:\d{2}\)"
    )

    def text(pdf: Path) -> tuple[list[str], str]:
        pages = [p.extract_text() for p in PdfReader(pdf).pages]
        assert len(generated.findall("\n".join(pages))) == 1 and generated.search(pages[0])
        return pages, generated.sub("Report generated <ts>", "\n".join(pages))

    out_dir = green_run["out_dir"]
    pages, original = text(green_run["pdf"])  # read first: a same-minute rebuild reuses the name
    stamp = completed_at(json.loads((out_dir / "run_meta.json").read_text()))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \S+ \([+-]\d{2}:\d{2}\)", stamp)
    footer = f"Run {green_run['run_id'][:8]} · completed {stamp}"
    assert all(footer in page and f"of {len(pages)}" in page for page in pages)
    (out_dir / "trajectory.json").unlink()  # the timeline must come from state.db
    time.sleep(1.1)  # a footer that read the clock at render would now differ
    rebuilt, _ = build_report(out_dir)
    assert text(rebuilt)[1] == original


# -- layout: header, footer, metadata, outline --------------------------------


def test_header_footer_metadata_and_outline() -> None:
    import io

    model = build_model(_synthetic_run(60))
    data, pages, _ = render(model, generated="2026-10-01 00:00:00 UTC (+00:00)")
    reader = PdfReader(io.BytesIO(data))
    # Each drawString is its own text run; extraction joins them with newlines.
    text = [" ".join(page.extract_text().split()) for page in reader.pages]
    header = "big repo · datetime.utcnow → datetime.now(timezone.utc)"
    assert header not in text[0], "page 1 is the summary page: no header"
    for number, page in enumerate(text, start=1):
        assert f"Page {number} of {pages}" in page
        assert "Run syntheti · completed 2026-10-01 00:00:00 UTC (+00:00)" in page
        if number > 1:
            assert header in page and "✓ GREEN" in page and "v0.2.0" in page
    info = reader.metadata
    assert info.title and info.author and "GREEN" in info.subject
    assert "big repo" in info["/Keywords"]
    outline = [item.title for item in reader.outline if not isinstance(item, list)]
    for section in (
        "Migration report",
        "Repository map",
        "Plan",
        "Execution timeline",
        "Changes",
        "Verification",
        "Metrics",
        "Issues & residuals",
        "Final status",
    ):
        assert section in outline


def test_status_is_word_and_symbol_never_colour_alone() -> None:
    from mra.report.pdf import status_label

    for status, glyph in (("GREEN", "✓"), ("YELLOW", "!"), ("RED", "✕")):
        assert glyph in status_label(status) and status in status_label(status)


def test_long_paths_are_middle_ellipsized_to_fit() -> None:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from mra.report.pdf import ellipsize

    path = "src/" + "very_long_package_name/" * 8 + "module.py"
    short = ellipsize(path, 120)
    assert "…" in short and short.startswith("src/") and short.endswith(".py")
    assert stringWidth(short, "Helvetica", 8.5) <= 120
    assert ellipsize("a.py", 120) == "a.py"


def test_completion_time_falls_back_to_start_plus_wall_clock() -> None:
    from mra.report.pdf import completed_at

    assert (
        completed_at({"started_at": "2026-10-01T00:00:00+00:00", "wall_clock_s": 61.4})
        == "2026-10-01 00:01:01 UTC (+00:00)"
    )
    assert (
        completed_at({"completed_at": "2026-10-02T19:42:07+05:30", "completed_tz": "IST"})
        == "2026-10-02 19:42:07 IST (+05:30)"
    )
