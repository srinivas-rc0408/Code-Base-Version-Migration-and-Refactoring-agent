"""Verified skill promotion (mra.skills): one test group per gate.

1 candidates · 2 codemod · 3 validation · 4 human approval · 5 rules fire
first and are reported · 6 anti-poisoning (GREEN-only, provenance, revoke,
purge, expiry) · 7 ablation F. Docker-free tests come first.
"""

from __future__ import annotations

import copy
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mra.benchmark.runner import CONFIGS, null_corrector, run_matrix, run_one
from mra.cli import main as cli
from mra.memory.experience import ExperienceStore, fully_green
from mra.skills import (
    MIN_INDEPENDENT_TASKS,
    apply_rule,
    compare_edge,
    compare_matrix,
    derive_rule,
    from_config,
    skill_id,
)
from tests.conftest import unique_id

REPO_ROOT = Path(__file__).resolve().parents[1]
TASK03 = REPO_ROOT / "corpus" / "tierA" / "task03_half_migration"
EDGE = REPO_ROOT / "corpus" / "edge"
CONTRACT = {"source_api": "datetime.utcnow", "target_api": "datetime.now(timezone.utc)"}
MESSAGE = "TypeError: can't subtract offset-naive and offset-aware datetimes"
DIFF = """\
-from datetime import datetime
+from datetime import datetime, timezone
-    return datetime.utcnow()
+    return datetime.now(timezone.utc)
"""
#: The same fix learnt from a different file: different lines, the same rule.
DIFF_ELSEWHERE = """\
-from datetime import datetime, timedelta
+from datetime import datetime, timedelta, timezone
-    end = datetime.utcnow()
+    end = datetime.now(timezone.utc)
"""
RULE = {
    "replace": [["datetime.utcnow()", "datetime.now(timezone.utc)"]],
    "imports": [["datetime", "timezone"]],
}
CONFIG = {c.name: c for c in CONFIGS}

needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "info"], capture_output=True).returncode != 0,
    reason="needs a working Docker daemon",
)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("MRA_SKILLS", raising=False)
    monkeypatch.setenv("MRA_EXPERIENCE_DB", str(tmp_path / "experience.db"))
    return tmp_path / "experience.db"


def seed(store: ExperienceStore, tasks: int, runs: int = 1, diff: str = DIFF, **contract) -> None:
    for t in range(tasks):
        for r in range(runs):
            store.record(
                "behaviour",
                MESSAGE,
                {**CONTRACT, **contract},
                diff,
                run_id=f"run-{len(diff)}-{t}-{r}",
                task_id=f"task-{t}-{contract}",
            )


def skill(rule: dict[str, Any] = RULE) -> dict[str, Any]:
    return {
        "id": skill_id("behaviour", CONTRACT["source_api"], CONTRACT["target_api"], rule),
        "failure_class": "behaviour",
        **CONTRACT,
        "rule": rule,
    }


GREEN_MODEL = {
    "meta": {"run_id": "r1", "task_id": "t1"},
    "verdict": {"status": "GREEN", "reasons": []},
    "verification": {
        "post": {"total": 4, "passed": 4, "failed": 0, "errors": 0},
        "residual": {"sites": [], "skipped": []},
    },
}


# -- 1. candidates ---------------------------------------------------------


def test_candidate_needs_three_independent_tasks(db: Path) -> None:
    store = ExperienceStore(db)
    seed(store, MIN_INDEPENDENT_TASKS - 1)
    assert store.candidates() == []
    seed(store, MIN_INDEPENDENT_TASKS)
    [candidate] = store.candidates()
    assert candidate["tasks"] == MIN_INDEPENDENT_TASKS
    assert candidate["rule"] == RULE and candidate["failure_class"] == "behaviour"


def test_repeats_of_one_task_are_not_independent(db: Path) -> None:
    store = ExperienceStore(db)
    seed(store, tasks=1, runs=5)
    assert store.candidates() == []


def test_candidates_group_by_rule_not_by_line(db: Path) -> None:
    store = ExperienceStore(db)
    seed(store, tasks=2, diff=DIFF)
    store.record("behaviour", MESSAGE, CONTRACT, DIFF_ELSEWHERE, run_id="x", task_id="other")
    [candidate] = store.candidates()
    assert candidate["tasks"] == 3 and len(candidate["patterns"]) == 2


def test_candidates_never_mix_contracts(db: Path) -> None:
    store = ExperienceStore(db)
    seed(store, tasks=2)
    seed(store, tasks=1, target_api="datetime.now(UTC)")
    assert store.candidates() == []


# -- 2. codemod ------------------------------------------------------------


def test_derive_rule_reduces_to_the_changed_expression() -> None:
    assert derive_rule(DIFF) == RULE
    assert derive_rule(DIFF_ELSEWHERE) == RULE


@pytest.mark.parametrize(
    "pattern",
    [
        "-x = foo(\n+x = bar(\n",  # multi-line statement
        "-a = 1\n+a = 2\n+b = 3\n",  # unequal -/+ counts
        "-a = utcnow\n+a = now\n",  # bare-name rename
        "-from datetime import datetime, timezone\n+from datetime import datetime\n",
        "",
    ],
)
def test_irreducible_patterns_give_no_rule(pattern: str) -> None:
    assert derive_rule(pattern) is None


@pytest.mark.parametrize("relative", ["src/pkg/audit.py", "src/pkg/report.py"])
def test_rule_reproduces_the_gold_file_byte_for_byte(tmp_path: Path, relative: str) -> None:
    shutil.copytree(TASK03 / "old", tmp_path / "repo")
    assert apply_rule(tmp_path / "repo", relative, RULE) == [relative]
    assert (tmp_path / "repo" / relative).read_bytes() == (TASK03 / "gold" / relative).read_bytes()
    assert apply_rule(tmp_path / "repo", relative, RULE) == []  # idempotent


def test_rule_never_edits_a_test_file(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match="NB-4"):
        apply_rule(tmp_path, "tests/test_core.py", RULE)


# -- 3. validation ---------------------------------------------------------


def test_compare_edge_flags_any_changed_verdict() -> None:
    committed = {"cases": [{"case": "a", "actual": "GREEN", "pass": True, "problems": []}]}
    assert compare_edge(copy.deepcopy(committed), committed) == []
    changed = copy.deepcopy(committed)
    changed["cases"][0].update(actual="YELLOW", **{"pass": False})
    assert compare_edge(changed, committed)
    assert compare_edge({"cases": []}, committed) == ["edge a: missing"]


def test_compare_matrix_flags_any_changed_result() -> None:
    entry = {
        "config": "baseline",
        "task_id": "t",
        "outcomes": {"success": 3},
        "m1_recall_mean": 100.0,
        "m1_precision_mean": 100.0,
        "m2_pass_rate_mean": 100.0,
        "m2_regressions_mean": 0.0,
        "corrections_mean": 1.0,
        "m3_tokens_mean": 0.0,
        "m3_steps_mean": 9.0,
        "cost_usd_mean": 0.0,
        "wall_clock_s_mean": 1.0,
    }
    committed = {"aggregates": [entry]}
    slower = {**entry, "wall_clock_s_mean": 9.0}
    assert compare_matrix({"aggregates": [slower]}, committed) == []
    assert compare_matrix({"aggregates": [{**entry, "corrections_mean": 2.0}]}, committed)


# -- 4. human approval -----------------------------------------------------


def test_nothing_is_promoted_automatically(db: Path) -> None:
    store = ExperienceStore(db)
    seed(store, tasks=5)
    assert store.candidates() and store.promoted() == []
    with pytest.raises(ValueError, match="validation"):
        store.promote(store.candidates()[0], {"ok": False})
    assert store.promoted() == []


def test_review_lists_evidence_and_rule(db: Path, capsys: pytest.CaptureFixture) -> None:
    seed(ExperienceStore(db), tasks=3)
    assert cli(["skills", "review"]) == 0
    out = capsys.readouterr().out
    candidate = ExperienceStore(db).candidates()[0]
    assert candidate["id"] in out and "3 independent GREEN task(s)" in out
    assert "- datetime.utcnow()" in out and "+ datetime.now(timezone.utc)" in out
    assert all(run in out for run in candidate["runs"])


def test_approve_validates_then_promotes(db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seed(ExperienceStore(db), tasks=3)
    ident = ExperienceStore(db).candidates()[0]["id"]
    monkeypatch.setattr(
        "mra.skills.validate", lambda c: {"ok": False, "edge": "38/39", "problems": ["x"]}
    )
    assert cli(["skills", "approve", ident]) == 1
    assert ExperienceStore(db).promoted() == []
    monkeypatch.setattr(
        "mra.skills.validate",
        lambda c: {"ok": True, "edge": "39/39", "matrix_runs": 165, "problems": []},
    )
    assert cli(["skills", "approve", ident]) == 0
    [promoted] = ExperienceStore(db).promoted()
    assert promoted["id"] == ident and promoted["validation"]["edge"] == "39/39"
    assert ExperienceStore(db).candidates() == []  # decided: not offered again


# -- 6. anti-poisoning -----------------------------------------------------


def test_fully_green_means_green_and_no_residual_and_suite_green() -> None:
    assert fully_green(GREEN_MODEL)
    residual = copy.deepcopy(GREEN_MODEL)
    residual["verification"]["residual"]["sites"] = [{"file": "a.py", "line": 3}]
    assert not fully_green(residual)  # even if a verdict said GREEN
    yellow = copy.deepcopy(GREEN_MODEL)
    yellow["verdict"]["status"] = "YELLOW"
    assert not fully_green(yellow)
    red_suite = copy.deepcopy(GREEN_MODEL)
    red_suite["verification"]["post"]["failed"] = 1
    assert not fully_green(red_suite)
    empty = copy.deepcopy(GREEN_MODEL)
    empty["verification"]["post"]["total"] = 0
    assert not fully_green(empty)


def test_learn_refuses_a_run_that_is_not_fully_green(db: Path) -> None:
    yellow = copy.deepcopy(GREEN_MODEL)
    yellow["verdict"]["status"] = "YELLOW"
    # The gate comes first: the trajectory is never even read.
    assert ExperienceStore(db).learn("/nonexistent", [{"node": "CORRECT"}], CONTRACT, yellow) == 0
    assert not db.exists()


def test_provenance_keeps_run_ids_but_no_task_name(db: Path) -> None:
    store = ExperienceStore(db)
    store.record("behaviour", MESSAGE, CONTRACT, DIFF, run_id="abc123", task_id="acme-billing")
    rows = sqlite3.connect(db).execute("SELECT run_id, task_key FROM observations").fetchall()
    assert rows[0][0] == "abc123" and "acme" not in rows[0][1]


def test_revoke_stops_a_rule_and_blocks_it_returning(db: Path, capsys: Any) -> None:
    store = ExperienceStore(db)
    seed(store, tasks=3)
    store.promote(store.candidates()[0], {"ok": True})
    ident = store.promoted()[0]["id"]
    assert cli(["skills", "revoke", ident]) == 0
    assert store.promoted() == [] and store.candidates() == []
    seed(store, tasks=6)  # more evidence does not resurrect it
    assert store.candidates() == []
    assert cli(["skills", "revoke", "nope"]) == 2


def test_purge_removes_fixes_provenance_and_skills(db: Path) -> None:
    store = ExperienceStore(db)
    seed(store, tasks=3)
    store.promote(store.candidates()[0], {"ok": True})
    assert cli(["memory", "purge"]) == 0
    assert store.rows() == [] and store.skills() == [] and store.candidates() == []
    assert from_config({"skills": {"enabled": True}}) == []


def test_expired_entries_give_no_hint_and_no_candidate(db: Path) -> None:
    store = ExperienceStore(db, ttl_days=30)
    seed(store, tasks=3)
    assert store.candidates() and store.hints("behaviour", MESSAGE, CONTRACT)
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE fixes SET created_at = '2000-01-01T00:00:00+00:00'")
        connection.execute("UPDATE observations SET created_at = '2000-01-01T00:00:00+00:00'")
    assert store.candidates() == []
    assert store.hints("behaviour", MESSAGE, CONTRACT) == []


# -- opt-in ----------------------------------------------------------------


def test_skills_off_by_default_and_env_off_wins(db: Path, monkeypatch: Any) -> None:
    store = ExperienceStore(db)
    seed(store, tasks=3)
    store.promote(store.candidates()[0], {"ok": True})
    assert from_config({}) == []
    assert len(from_config({"skills": {"enabled": True}})) == 1
    monkeypatch.setenv("MRA_SKILLS", "off")
    assert from_config({"skills": {"enabled": True}}) == []


# -- docker: the gates end to end ------------------------------------------


@needs_docker
def test_poisoned_run_never_stored_or_promoted(db: Path, tmp_path: Path) -> None:
    """A fix that turned the suite green but left residual sites behind."""
    from mra.benchmark.runner import codemod_corrector
    from mra.report import run_with_report

    store = ExperienceStore(db)
    result = run_with_report(
        TASK03, run_id=unique_id("poison"), runs_dir=tmp_path, corrector=codemod_corrector
    )
    trajectory = __import__("json").loads((result["out_dir"] / "trajectory.json").read_text())
    assert any(e["node"] == "CORRECT" for e in trajectory)  # a real, green-tested fix
    poisoned = copy.deepcopy(result["model"])
    poisoned["verdict"]["status"] = "YELLOW"
    poisoned["verification"]["residual"]["sites"] = [{"file": "src/pkg/x.py", "line": 1}]
    for t in range(MIN_INDEPENDENT_TASKS + 1):
        poisoned["meta"].update(run_id=f"p{t}", task_id=f"task{t}")
        assert store.learn(result["out_dir"] / "repo", trajectory, CONTRACT, poisoned) == 0
    assert store.rows() == [] and store.candidates() == [] and store.promoted() == []
    # The same run, unpoisoned, is learnt: the gate is the only difference.
    assert store.learn(result["out_dir"] / "repo", trajectory, CONTRACT, result["model"]) >= 1


@pytest.mark.slow
@needs_docker
def test_validation_rejects_a_harmful_rule_and_passes_a_sound_one() -> None:
    from mra.skills import validate

    subset = {
        "edge_cases": ["cross_file_recovery"],
        "tasks": ["task03_half_migration"],
        "configs": ["baseline"],
    }
    harmful = skill({"replace": [["datetime.utcnow()", "datetime.now()"]], "imports": []})
    verdict = validate(harmful, **subset)
    assert not verdict["ok"] and verdict["problems"]
    assert validate(skill(), **subset)["ok"]


@needs_docker
def test_rule_fires_before_the_llm_and_is_reported(tmp_path: Path) -> None:
    from mra.codemods.datetime_utcnow import TARGET
    from mra.models import ROLES, Endpoint, Router
    from mra.models.providers import FakeProvider
    from mra.nodes.correct_node import LLMCorrector
    from mra.report import run_with_report, terminal_summary
    from mra.state import new_state

    def reply(messages: list, model: str) -> str:
        raise AssertionError("the LLM was called although a promoted rule applied")

    state = new_state("fired", "", {"task_id": TASK03.name, **CONTRACT})
    router = Router(
        state["tokens"],
        roles={r: [Endpoint(FakeProvider("fake", reply=reply), "m")] for r in ROLES},
    )
    corrector = LLMCorrector(router, TARGET, state["contract"])
    result = run_with_report(
        TASK03,
        run_id=unique_id("fired"),
        runs_dir=tmp_path,
        router=router,
        corrector=corrector,
        state=state,
        rules=[skill()],
    )
    model = result["model"]
    assert model["verdict"]["status"] == "GREEN"
    assert model["skills_fired"] and model["skills_fired"][0]["rule"] == skill()["id"]
    assert any("via promoted rule" in row["text"] for row in model["timeline"])
    assert "Promoted rule" in terminal_summary(model, result["pdf"], color=False)
    assert model["metrics"]["m3_tokens"] == 0 and router.calls == []


@needs_docker
def test_rules_are_off_in_the_benchmark(db: Path, tmp_path: Path, monkeypatch: Any) -> None:
    store = ExperienceStore(db)
    seed(store, tasks=3)
    store.promote(store.candidates()[0], {"ok": True})
    monkeypatch.setenv("MRA_SKILLS", "on")  # the user turned skills on ...
    row = run_one(TASK03, CONFIG["baseline"], runs_dir=tmp_path)
    assert row["rules_fired"] == 0  # ... and the benchmark still never used them.


@needs_docker
def test_ablation_f_learns_on_training_tasks_and_helps_a_held_out_one(tmp_path: Path) -> None:
    """Warm on three distinct training tasks -> one candidate -> repairs task03."""
    train = tmp_path / "train"
    for name in ("copy_a", "copy_b", "copy_c"):
        shutil.copytree(EDGE / "cross_file_recovery", train / name)
    results = run_matrix(
        ["task03_half_migration"],
        [CONFIG["rules-off"], CONFIG["rules-on"]],
        repeats=1,
        out_dir=tmp_path / "out",
        baselines=False,
        train_corpus=train,
    )
    [candidate] = results["experience_warmup"]["candidates"]
    assert candidate["tasks"] == 3 and candidate["rule"] == RULE
    rows = {r["config"]: r for r in results["rows"]}
    assert rows["rules-off"]["outcome"] == "gave_up" and rows["rules-off"]["rules_fired"] == 0
    assert rows["rules-on"]["outcome"] == "success" and rows["rules-on"]["rules_fired"] >= 1
    assert rows["rules-on"]["m1_recall"] == 100.0
    assert "### F. Promoted rules OFF vs ON" in (tmp_path / "out" / "results.md").read_text()
    assert null_corrector(tmp_path, {}, {}) == []
