"""End-to-end slice: analyse -> snapshot -> codemod -> verify -> recover -> score.

One task, one batch, no planner. Everything runs on a writable copy under
``runs/<run_id>/repo``; the corpus source is only ever read.

Two P3 seams sit on top of the P2 path, both optional so the deterministic
run is unchanged when they are unused:

* ``edit_only`` restricts EDIT to a subset of the flagged files. That is what
  batching does in P4, and it is how the half-migration recovery fixture is
  produced (``corpus/tierA/task03_half_migration``).
* ``corrector`` turns on the recovery loop: if the post-edit suite is red, the
  loop runs CORRECT/TEST until green or ``MAX_FIX_ATTEMPTS`` (FR-7, FR-9).

Outputs land in ``runs/<run_id>/`` (NFR-13):
``migration.patch``, ``metrics.json``, ``trajectory.json``, ``test_report.json``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from collections.abc import Collection
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mra.analysis import analyze, flat_sites
from mra.codemods.datetime_utcnow import TARGET
from mra.metrics import imports, m1, m2, source_tree
from mra.models import cost_usd, total_tokens
from mra.nodes.edit_node import apply_codemod
from mra.recovery import recover
from mra.sandbox import SandboxRunner, diff, snapshot
from mra.state import MigrationState, new_state

#: Ground-truth comparison key. Matches tests/test_analyzer.py; a column error
#: would pass a looser (file, line, symbol) key and break a positional edit.
KEY_FIELDS = ("file", "line", "col", "symbol")


def _key(site: dict[str, Any]) -> tuple:
    return tuple(site[field] for field in KEY_FIELDS)


class Trajectory:
    """Append-only event log, the ``mra:trajectory_event`` shape (SRS §4.1)."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, node: str, action: str, **detail: Any) -> None:
        self.events.append(
            {
                "seq": len(self.events),
                "ts": datetime.now(UTC).isoformat(),
                "node": node,
                "action": action,
                "detail": detail,
            }
        )


def migrate_task(
    task_dir: Path | str,
    run_id: str | None = None,
    runs_dir: Path | str = "runs",
    target: str = TARGET,
    *,
    edit_only: Collection[str] | None = None,
    corrector: Any = None,
    state: MigrationState | None = None,
    max_attempts: int | None = None,
) -> dict[str, Any]:
    """Migrate a Tier-A task end to end and score it. Returns the run summary."""
    task_dir = Path(task_dir)
    task_id = task_dir.name
    run_id = run_id or uuid.uuid4().hex[:12]
    out_dir = Path(runs_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    truth = json.loads((task_dir / "ground_truth.json").read_text())
    if state is None:
        state = new_state(
            run_id,
            str(out_dir / "repo"),
            {
                "task_id": task_id,
                "source_api": truth["source_api"],
                "target_api": truth["target_api"],
            },
        )
    trajectory = Trajectory()
    work = out_dir / "repo"
    if work.exists():
        shutil.rmtree(work)
    # The user's own .git is never copied: the run's first commit must be its own
    # pre-migration snapshot, which evidence.base_commit() diffs against.
    shutil.copytree(task_dir / "old", work, ignore=shutil.ignore_patterns(".git"))

    # -- MAP ---------------------------------------------------------------
    analysis = analyze(work, target)
    sites = flat_sites(analysis["call_sites"])
    trajectory.record(
        "MAP",
        f"found {len(sites)} call site(s)",
        files=sorted(analysis["call_sites"]),
        target=target,
    )

    # -- TEST (pre) --------------------------------------------------------
    # NB-10: M2 is undefined unless the suite is green before we touch anything.
    runner = SandboxRunner(runs_dir=runs_dir)
    pre = runner.run(work, task_id=task_id, phase="pre", run_id=run_id, lint=False)
    (out_dir / "test_report_pre.json").write_text(json.dumps(pre, indent=2) + "\n")
    trajectory.record(
        "TEST",
        "pre-migration suite",
        total=pre["total"],
        passed=pre["passed"],
        failed=pre["failed"],
    )

    # -- EDIT --------------------------------------------------------------
    base_sha = snapshot(work, "pre-migration snapshot")
    trajectory.record("EDIT", "git snapshot before batch 0", sha=base_sha)
    batch = (
        analysis["call_sites"]
        if edit_only is None
        else {file: found for file, found in analysis["call_sites"].items() if file in edit_only}
    )
    if edit_only is not None:
        trajectory.record(
            "EDIT",
            f"batch restricted to {len(batch)} of {len(analysis['call_sites'])} flagged file(s)",
            files=sorted(batch),
        )
    changed = apply_codemod(work, batch)
    trajectory.record("EDIT", f"codemod applied to {len(changed)} file(s)", files=changed)

    # -- TEST (post) -------------------------------------------------------
    post = runner.run(work, task_id=task_id, phase="post", run_id=run_id)
    trajectory.record(
        "TEST",
        "post-migration suite",
        total=post["total"],
        passed=post["passed"],
        failed=post["failed"],
    )

    # -- CORRECT -----------------------------------------------------------
    recovery: dict[str, Any] | None = None
    green = post["failed"] == 0 and post["errors"] == 0
    if corrector is not None and not green:
        recovery = recover(
            work,
            post,
            runner=runner,
            corrector=corrector,
            task_id=task_id,
            trajectory=trajectory,
            run_id=run_id,
            max_attempts=max_attempts,
            fix_attempts=state.setdefault("fix_attempts", {}),
            context={
                "call_sites": analysis["call_sites"],
                "dep_graph": analysis["dep_graph"],
                "contract": state["contract"],
            },
        )
        post = recovery["report"]
        green = recovery["outcome"] == "success"
        # Files repaired during recovery count as migrated for M1, same as EDIT's.
        changed = sorted({*changed, *(f for c in recovery["corrections"] for f in c["changed"])})

    state["last_test_report"] = post
    # Against the pre-migration snapshot, not HEAD: recovery commits its own
    # rounds, so a HEAD-relative diff would report an empty migration.
    patch = diff(work, base_sha)
    (out_dir / "migration.patch").write_text(patch, errors="surrogateescape")

    # -- score -------------------------------------------------------------
    # The agent's claim is what it actually rewrote — sites in files it left
    # alone were found but not migrated, and a half-finished migration must
    # score as such. Deterministic runs that edit every flagged file are
    # unaffected, since there `edited` is all of `found`.
    edited = {_key(site) for site in sites if site["file"] in set(changed)}
    expected = {_key(site) for site in truth["call_sites"]}
    m1_score = m1(agent_sites=edited, correct_sites=edited, ground_truth_sites=expected)
    m2_score = m2(t_total=pre["total"], t_post_pass=post["passed"])

    tokens = state["tokens"]
    metrics = {
        "task_id": task_id,
        "m1_recall": m1_score["recall"],
        "m1_precision": m1_score["precision"],
        "m2_pass_rate": m2_score["pass_rate"],
        "m2_regressions": m2_score["regressions"],
        # Zero for a purely deterministic run: codemods cost no tokens (rule 5).
        "m3_tokens": total_tokens(tokens),
        "m3_steps": len(trajectory.events),
        "m3_cost_usd": round(cost_usd(tokens), 6),
        "recovery_used": recovery is not None,
        "outcome": "success" if green else "gave_up",
        "imports": imports(
            source_tree(task_dir / "old"), source_tree(work), truth.get("expected_import_changes")
        ),
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    (out_dir / "trajectory.json").write_text(json.dumps(trajectory.events, indent=2) + "\n")
    state["trajectory"] = trajectory.events
    state["done"] = green

    return {
        "state": state,
        "recovery": recovery,
        "run_id": run_id,
        "task_id": task_id,
        "out_dir": out_dir,
        "repo": work,
        "call_sites": analysis["call_sites"],
        "dep_graph": analysis["dep_graph"],
        "changed_files": changed,
        "pre_report": pre,
        "test_report": post,
        "patch": patch,
        "metrics": metrics,
        "trajectory": trajectory.events,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Tier-A migration task end to end.")
    parser.add_argument(
        "--task-dir", required=True, help="task directory holding old/, gold/ and ground_truth.json"
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--runs-dir", default="runs")
    args = parser.parse_args(argv)

    result = migrate_task(args.task_dir, run_id=args.run_id, runs_dir=args.runs_dir)
    metrics = result["metrics"]
    print(f"{result['task_id']}  run {result['run_id']}  -> {metrics['outcome']}")
    print(f"  M1 recall {metrics['m1_recall']:.1f}%  precision {metrics['m1_precision']:.1f}%")
    print(f"  M2 pass rate {metrics['m2_pass_rate']:.1f}%  regressions {metrics['m2_regressions']}")
    print(f"  artifacts: {result['out_dir']}")
    return 0 if metrics["outcome"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
