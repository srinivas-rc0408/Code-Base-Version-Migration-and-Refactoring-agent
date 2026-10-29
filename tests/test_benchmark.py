"""P5 acceptance: the ablations, the results artifacts and the baseline tools.

Everything here is offline. The two ablations the paper leads with — the
recovery loop (A) and the edit order (B) — run with the deterministic
corrector, so their contrast is reproducible on a machine with no API key and
no model to be non-deterministic about. The live-model arms (C) are skipped by
the matrix itself, not by this file.

The assertions are on the *direction* of each result, never on an exact number:
a benchmark whose test pins its own output cannot report a surprise, and the
surprise is what the failure analysis is for.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mra.benchmark import baseline_table, ruff_baseline, run_one
from mra.benchmark.baselines import pyupgrade_baseline
from mra.benchmark.runner import CONFIGS, Config, failure_analysis, render_markdown, run_matrix
from mra.nodes.correct_node import is_test_path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS = REPO_ROOT / "corpus" / "tierA"
TASK01 = CORPUS / "task01_datetime"
TASK03 = CORPUS / "task03_half_migration"
TASK04 = CORPUS / "task04_multimodule"
TASK05 = CORPUS / "task05_signature_break"

BY_NAME = {config.name: config for config in CONFIGS}

needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "info"], capture_output=True).returncode != 0,
    reason="needs a working Docker daemon",
)

pytestmark = needs_docker


def _tree_digest(root: Path) -> str:
    sha = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        sha.update(str(path.relative_to(root)).encode())
        sha.update(path.read_bytes())
    return sha.hexdigest()


@pytest.fixture(scope="session")
def corpus_digests() -> dict[str, str]:
    return {task.name: _tree_digest(task) for task in (TASK01, TASK03, TASK04, TASK05)}


@pytest.fixture(scope="session")
def runs_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("benchmark")


@pytest.fixture(scope="session")
def ablation_a(runs_dir: Path, corpus_digests: dict[str, str]) -> dict[str, dict[str, Any]]:
    """`baseline` and `no-recovery` on every task the loop is supposed to matter for."""
    rows = {}
    for task in (TASK01, TASK03, TASK04):
        for name in ("baseline", "no-recovery"):
            rows[(name, task.name)] = run_one(task, BY_NAME[name], runs_dir=runs_dir)
    return rows


@pytest.fixture(scope="session")
def ablation_b(runs_dir: Path, corpus_digests: dict[str, str]) -> dict[str, dict[str, Any]]:
    """The three edit orders on task04, at one file per batch and with recovery on.

    Batch size is pinned to 1 in all three arms because at the default 3 a
    six-file task is two batches wide, and then "order" and "granularity" are
    the same variable.
    """
    arms = {
        "dependency": Config("b-dep", order="dependency", batch_size=1),
        "alphabetical": Config("b-alpha", order="alphabetical", batch_size=1),
        "fr3_violating": Config("b-fr3", order="fr3_violating", batch_size=1),
        "dependency-off": Config("b-dep-off", order="dependency", batch_size=1, recovery=False),
        "fr3_violating-off": Config(
            "b-fr3-off", order="fr3_violating", batch_size=1, recovery=False
        ),
    }
    return {name: run_one(TASK04, config, runs_dir=runs_dir) for name, config in arms.items()}


@pytest.fixture(scope="session")
def ablation_b_task05(runs_dir: Path, corpus_digests: dict[str, str]) -> dict[str, dict[str, Any]]:
    """The same three orders on the task built so that order alone decides the outcome.

    ``task05_signature_break`` is asymmetric where ``task04`` is symmetric: its
    contract owner upgrades a naive stamp it is handed but refuses to strip a
    ``tzinfo``, so the dependency order never opens a window and the other two
    always do. One file per batch in every arm, so order is the only variable.
    """
    arms = {
        "dependency": Config("b5-dep", order="dependency", batch_size=1),
        "alphabetical": Config("b5-alpha", order="alphabetical", batch_size=1),
        "fr3_violating": Config("b5-fr3", order="fr3_violating", batch_size=1),
        "dependency-off": Config("b5-dep-off", order="dependency", batch_size=1, recovery=False),
        "alphabetical-off": Config(
            "b5-alpha-off", order="alphabetical", batch_size=1, recovery=False
        ),
        "fr3_violating-off": Config(
            "b5-fr3-off", order="fr3_violating", batch_size=1, recovery=False
        ),
    }
    return {name: run_one(TASK05, config, runs_dir=runs_dir) for name, config in arms.items()}


# -- A. the recovery loop, offline -----------------------------------------


@pytest.mark.parametrize("task", ["task03_half_migration", "task04_multimodule"])
def test_without_the_loop_the_half_migrations_regress(
    ablation_a: dict[str, dict[str, Any]], task: str
) -> None:
    """Ablation A, the project's core claim, on the two cross-file tasks."""
    off, on = ablation_a[("no-recovery", task)], ablation_a[("baseline", task)]

    assert off["outcome"] == "gave_up"
    assert off["m2_regressions"] > 0
    assert off["m2_pass_rate"] < 100
    assert not off["recovery_used"]

    assert on["outcome"] == "success"
    assert on["m2_regressions"] == 0
    assert on["m2_pass_rate"] == 100
    assert on["recovery_used"], "the green run must have gone through CORRECT"

    assert on["m1_recall"] > off["m1_recall"], "the loop is what finishes the migration"


def test_the_loop_is_not_what_makes_the_single_file_task_work(
    ablation_a: dict[str, dict[str, Any]],
) -> None:
    """The control: with no cross-file break there is nothing to recover, so A is flat."""
    off, on = (
        ablation_a[("no-recovery", "task01_datetime")],
        ablation_a[("baseline", "task01_datetime")],
    )
    assert off["outcome"] == on["outcome"] == "success"
    assert off["m1_recall"] == on["m1_recall"] == 100
    assert off["corrections"] == on["corrections"] == 0


# -- B. edit order ---------------------------------------------------------


def test_a_dependents_first_order_costs_more_corrective_edits(
    ablation_b: dict[str, dict[str, Any]],
) -> None:
    """FR-3 order is not free to violate: the loop pays for it in CORRECT visits."""
    dependency, violating = ablation_b["dependency"], ablation_b["fr3_violating"]
    assert violating["corrections"] > dependency["corrections"]
    assert violating["m3_steps"] > dependency["m3_steps"]


def test_without_the_loop_a_dependents_first_order_stops_sooner(
    ablation_b: dict[str, dict[str, Any]],
) -> None:
    """With nothing to repair the regression, the wrong order leaves less migrated.

    Both orders break — the fixture's break is semantic, and editing one file at
    a time opens the producer/consumer window whichever end you start from — so
    the ordering result is *how far the run got*, not whether it broke at all.
    """
    dependency, violating = ablation_b["dependency-off"], ablation_b["fr3_violating-off"]
    assert dependency["m2_regressions"] >= 1 and violating["m2_regressions"] >= 1
    assert violating["m1_recall"] < dependency["m1_recall"]


def test_every_order_is_still_a_complete_migration_when_the_loop_runs(
    ablation_b: dict[str, dict[str, Any]],
) -> None:
    """The honest half of B: on a six-file task, recovery rescues all three orders."""
    for arm in ("dependency", "alphabetical", "fr3_violating"):
        row = ablation_b[arm]
        assert row["outcome"] == "success", arm
        assert row["m1_recall"] == 100 and row["m2_regressions"] == 0, arm


# -- B on task05: the task where the order is the whole result ---------------


@pytest.mark.parametrize("arbitrary", ["alphabetical", "fr3_violating"])
def test_dependency_order_is_never_worse_than_an_arbitrary_one_on_task05(
    ablation_b_task05: dict[str, dict[str, Any]], arbitrary: str
) -> None:
    """Direction only: the graph order costs no more than ignoring the graph."""
    dependency, other = ablation_b_task05["dependency"], ablation_b_task05[arbitrary]

    assert dependency["outcome"] == "success"
    assert dependency["corrections"] <= other["corrections"]
    assert dependency["m3_steps"] <= other["m3_steps"]
    assert dependency["m1_recall"] >= other["m1_recall"]
    assert dependency["m2_regressions"] <= other["m2_regressions"]


def test_the_dependency_order_needs_no_corrective_edit_on_task05(
    ablation_b_task05: dict[str, dict[str, Any]],
) -> None:
    """The asymmetry: migrating the contract owner first never opens the window."""
    dependency = ablation_b_task05["dependency"]
    assert dependency["corrections"] == 0
    assert not dependency["recovery_used"]
    assert dependency["m1_recall"] == 100 and dependency["m2_pass_rate"] == 100


@pytest.mark.parametrize("arbitrary", ["alphabetical-off", "fr3_violating-off"])
def test_without_the_loop_only_the_dependency_order_survives_task05(
    ablation_b_task05: dict[str, dict[str, Any]], arbitrary: str
) -> None:
    """The result task04 could not produce: with recovery off, order decides the run.

    task04's break is symmetric, so every order breaks and the ordering result is
    only *how far* the run got. Here the dependency order does not break at all.
    """
    dependency, other = ablation_b_task05["dependency-off"], ablation_b_task05[arbitrary]

    assert dependency["outcome"] == "success"
    assert dependency["m2_regressions"] == 0 and dependency["m2_pass_rate"] == 100

    assert other["outcome"] == "gave_up"
    assert other["m2_regressions"] > 0
    assert other["m1_recall"] < dependency["m1_recall"]


def test_the_wrong_order_breaks_task05_at_collection_time(
    ablation_b_task05: dict[str, dict[str, Any]],
) -> None:
    """File-name order migrates pkg.boot before pkg.timebase, and boot fails on import.

    A collection error is reported against the *test module* that could not be
    imported, so the failing nodeids are whole files with no ``::test_`` in them.
    """
    failures = ablation_b_task05["alphabetical-off"]["failures"]
    assert failures, "the arm was supposed to break"
    assert all(failure["exc_type"] == "TypeError" for failure in failures)
    collection = [f for f in failures if "::" not in f["nodeid"]]
    assert collection, f"expected an import-time break, got {[f['nodeid'] for f in failures]}"


# -- the baseline tools ----------------------------------------------------


def test_ruff_detects_every_site_and_fixes_none() -> None:
    """The honesty check: detection parity, zero migration (DTZ003 has no autofix)."""
    truth = json.loads((TASK04 / "ground_truth.json").read_text())
    entry = ruff_baseline(TASK04)
    assert entry["detected"] == len(truth["call_sites"])
    assert entry["detect_recall"] == 100.0
    assert entry["fixed_files"] == 0
    assert entry["m1_recall_after_fix"] == 0.0
    # And the suite is still green, which is the trap: M2 alone cannot tell you
    # that nothing was migrated.
    assert entry["suite_green"]


def test_pyupgrade_does_not_migrate_the_contract_either() -> None:
    entry = pyupgrade_baseline(TASK03)
    assert entry["m1_recall_after_fix"] == 0.0
    assert entry["sites_remaining"] == 3


def test_the_baseline_table_records_both_tools_for_every_task() -> None:
    table = baseline_table(["task01_datetime", "task03_half_migration"])
    assert [entry["task_id"] for entry in table] == ["task01_datetime", "task03_half_migration"]
    for entry in table:
        tools = {tool["tool"] for tool in entry["tools"]}
        assert tools == {"ruff (DTZ)", "pyupgrade"}
        assert all("detect_recall" in tool for tool in entry["tools"])


# -- the artifacts ---------------------------------------------------------


ROW_FIELDS = (
    "task_id",
    "config",
    "outcome",
    "m1_recall",
    "m1_precision",
    "m1_f1",
    "m2_pass_rate",
    "m2_regressions",
    "pro_in",
    "pro_out",
    "flash_in",
    "flash_out",
    "m3_tokens",
    "m3_steps",
    "cost_usd",
    "recovery_used",
    "wall_clock_s",
)


@pytest.fixture(scope="session")
def matrix(
    tmp_path_factory: pytest.TempPathFactory, corpus_digests: dict[str, str]
) -> dict[str, Any]:
    """A small matrix, written exactly as the published one is."""
    return run_matrix(
        ["task01_datetime", "task03_half_migration"],
        [BY_NAME["baseline"], BY_NAME["no-recovery"]],
        repeats=2,
        corpus=CORPUS,
        out_dir=tmp_path_factory.mktemp("matrix"),
    )


@pytest.mark.slow
def test_results_json_has_every_reported_field(matrix: dict[str, Any]) -> None:
    assert matrix["rows"], "the matrix produced no rows"
    assert len(matrix["rows"]) == 2 * 2 * 2  # tasks x configs x repeats
    for row in matrix["rows"]:
        missing = [field for field in ROW_FIELDS if field not in row]
        assert not missing, f"row is missing {missing}"
        assert 0 <= row["m1_recall"] <= 100 and 0 <= row["m2_pass_rate"] <= 100
        assert row["outcome"] in ("success", "gave_up", "error")
        assert row["wall_clock_s"] > 0


@pytest.mark.slow
def test_aggregates_report_mean_and_spread_over_the_repeats(matrix: dict[str, Any]) -> None:
    for entry in matrix["aggregates"]:
        assert entry["n"] == matrix["repeats"]
        assert sum(entry["outcomes"].values()) == entry["n"]
        # The deterministic path must agree with itself across repeats.
        assert entry["m1_recall_spread"] == 0
        assert entry["m2_regressions_spread"] == 0


@pytest.mark.slow
def test_the_table_renders_every_task_and_configuration(matrix: dict[str, Any]) -> None:
    table = render_markdown(matrix)
    for task in matrix["tasks"]:
        assert f"### {task}" in table
    for config in ("baseline", "no-recovery"):
        assert f"`{config}`" in table
    for heading in (
        "## 1. The whole offline matrix",
        "## 1b. Per task, per configuration",
        "### A. Recovery loop ON vs OFF",
        "## 3. Deterministic baselines",
    ):
        assert heading in table
    for task in matrix["tasks"]:
        assert f"`{task} / baseline`" in table, "the consolidated grid is missing a row"
    assert "ruff (DTZ)" in table, "the baseline section did not render"


@pytest.mark.slow
def test_the_matrix_writes_its_three_artifacts(matrix: dict[str, Any]) -> None:
    base = Path(matrix["out_dir"])
    for name in ("results.json", "results.md", "failure-analysis.md"):
        assert (base / name).read_text().strip(), f"{name} is empty"
    assert json.loads((base / "results.json").read_text())["schema"].startswith("mra:benchmark")


@pytest.mark.slow
def test_failure_analysis_explains_every_failing_run(matrix: dict[str, Any]) -> None:
    report = failure_analysis(matrix)
    failing = [r for r in matrix["rows"] if r["outcome"] != "success"]
    assert failing, "this matrix is supposed to include the no-recovery arm"
    assert "# Failure analysis" in report
    for row in failing:
        assert f"`{row['config']}` on {row['task_id']}" in report
    # Each failure carries its class from the docs/04 §2.5 taxonomy and a reason.
    assert "behaviour** break" in report
    assert "recovery disabled (ablation A)" in report


@pytest.mark.slow
def test_live_model_rows_are_skipped_not_faked(matrix: dict[str, Any]) -> None:
    assert all(config["model"] == "deterministic" for config in matrix["configs"])
    live = [c for c in CONFIGS if c.requires_key]
    assert live and all(c.ablation in ("C", "E", "F") for c in live)


# -- boundaries ------------------------------------------------------------


def test_no_benchmark_run_touched_a_test_file(
    ablation_a: dict[str, dict[str, Any]],
    ablation_b: dict[str, dict[str, Any]],
    ablation_b_task05: dict[str, dict[str, Any]],
) -> None:
    """NB-4 holds across every configuration, including the deliberately bad ones."""
    for row in [*ablation_a.values(), *ablation_b.values(), *ablation_b_task05.values()]:
        offenders = [path for path in row["changed_files"] if is_test_path(path)]
        assert not offenders, f"{row['config']} edited the oracle: {offenders}"


def test_the_corpus_is_unchanged_after_the_whole_suite(
    corpus_digests: dict[str, str],
    ablation_a: dict[str, dict[str, Any]],
    ablation_b: dict[str, dict[str, Any]],
    ablation_b_task05: dict[str, dict[str, Any]],
) -> None:
    for task in (TASK01, TASK03, TASK04, TASK05):
        assert _tree_digest(task) == corpus_digests[task.name], f"{task.name} was modified"


@pytest.mark.slow
def test_the_corpus_is_unchanged_after_the_matrix(
    corpus_digests: dict[str, str], matrix: dict[str, Any]
) -> None:
    for task in (TASK01, TASK03, TASK04, TASK05):
        assert _tree_digest(task) == corpus_digests[task.name], f"{task.name} was modified"
