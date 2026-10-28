"""The agent as an explicit LangGraph state machine (docs/04 §2.3-2.4).

``MAP -> PLAN -> EDIT -> TEST -> {CORRECT | next batch | done}``, over
``MigrationState`` (SRS §4.1), checkpointed to ``runs/<run_id>/state.db``.

**The checkpointer is the audit log.** No node keeps its own list of what
happened; each one writes a single-slot ``note`` describing the step it just
took, and the checkpointer persists one state snapshot per step. The trajectory
is then *reconstructed* by walking that history — which node was next, what the
state looked like after it ran, when. Delete the database and the log is gone,
because there is no second copy of it anywhere.

Two places where the implementation departs from the pseudocode in docs/04,
both because the pseudocode cannot run as written:

* ``route_after_test`` in §2.3 increments ``state["current_batch"]`` inside the
  router. A LangGraph router receives a read-only view and returns an edge
  name; it has no channel to write to, so the increment would be silently
  dropped and every run would re-edit batch 0 forever. The counter is advanced
  by ``edit_node`` instead. The routing *decision* is identical.
* §2.4 wires both terminal branches straight to ``END``. The verdict then has
  nowhere to be recorded, since only a node can write to state, so both route
  through a ``finish`` node that stamps ``done`` and ``outcome`` and ends.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from mra.codemods.datetime_utcnow import EXPECTED_LINT, FORBIDDEN_PATTERNS, TARGET
from mra.metrics import imports, m1, m2, source_tree
from mra.models import Router, cost_usd, total_tokens
from mra.nodes.correct_node import make_correct_node
from mra.nodes.edit_node import make_edit_node
from mra.nodes.map_node import make_map_node
from mra.nodes.plan_node import plan_node
from mra.nodes.test_node import make_test_node
from mra.recovery.loop import DEFAULT_MAX_FIX_ATTEMPTS
from mra.sandbox import SandboxRunner, diff, snapshot
from mra.state import MigrationState, new_state

#: Node name -> the ``trajectory_event.node`` enum in SRS §4.1.
NODE_LABELS = {
    "map": "MAP",
    "plan": "PLAN",
    "edit": "EDIT",
    "test": "TEST",
    "correct": "CORRECT",
    "finish": "FINISH",
}

#: EDIT+TEST per batch, plus corrections, plus MAP/PLAN/FINISH. Well clear of
#: any Tier-A task; a real ceiling, not the framework's default 25.
DEFAULT_RECURSION_LIMIT = 200

KEY_FIELDS = ("file", "line", "col", "symbol")


class PreconditionError(RuntimeError):
    """NB-10: the pre-migration suite is not green (or collects nothing); refuse to edit."""


def precondition_problem(pre: dict[str, Any]) -> str | None:
    """Why ``pre`` is not a usable baseline, or None when it is."""
    from mra.sandbox.runner import needs_network

    if pre.get("total", 0) == 0:
        return "the pre-migration suite collected no tests"
    if is_green(pre):
        return None
    failing = [f.get("nodeid", "?") for f in pre.get("failures", [])]
    problem = (
        f"the pre-migration suite is not green: {pre.get('failed', 0)} failed, "
        f"{pre.get('errors', 0)} errors ({', '.join(failing[:3])})"
    )
    if offline := needs_network(pre):
        problem += (
            f"; {', '.join(offline[:3])} need(s) the network, which the sandbox "
            "does not have (--network none)"
        )
    return problem


def _cap() -> int:
    return int(os.environ.get("MRA_MAX_FIX_ATTEMPTS", str(DEFAULT_MAX_FIX_ATTEMPTS)))


def _key(site: dict[str, Any]) -> tuple:
    return tuple(site[field] for field in KEY_FIELDS)


# -- routing ---------------------------------------------------------------


def is_green(report: dict[str, Any]) -> bool:
    return report.get("failed", 0) == 0 and report.get("errors", 0) == 0


def all_batches_done(state: dict[str, Any]) -> bool:
    """``current_batch`` names the batch that is *next*, so this is the end test."""
    return int(state.get("current_batch", 0)) >= len(state.get("edit_batches") or [])


def route_after_test(state: dict[str, Any]) -> str:
    """docs/04 §2.3, as a pure function: success / next_batch / correct / give_up."""
    report = state["last_test_report"]
    if is_green(report):
        return "success" if all_batches_done(state) else "next_batch"
    cap = _cap()
    attempts = state.get("fix_attempts") or {}
    if any(attempts.get(f["signature"], 0) < cap for f in report["failures"]):
        return "correct"
    return "give_up"


def outcome_of(state: dict[str, Any]) -> str:
    """The same predicate ``route_after_test`` used, recomputed where it can be stored."""
    return (
        "success" if is_green(state["last_test_report"]) and all_batches_done(state) else "gave_up"
    )


def finish_node(state: dict[str, Any]) -> dict[str, Any]:
    """Terminal node: stamp the verdict so the audit log carries it."""
    outcome = outcome_of(state)
    report = state["last_test_report"]
    blocked = sorted({f["signature"] for f in report["failures"]}) if not is_green(report) else []
    return {
        "done": outcome == "success",
        "note": {
            "action": f"{outcome} after batch "
            f"{state.get('current_batch', 0)}/{len(state.get('edit_batches') or [])}",
            "detail": {
                "outcome": outcome,
                "flagged": outcome != "success",
                "blocked_signatures": blocked,
                "attempts": dict(state.get("fix_attempts") or {}),
            },
        },
    }


# -- wiring ----------------------------------------------------------------


def build_graph(
    *,
    runner: SandboxRunner,
    corrector: Any,
    task_id: str,
    target: str = TARGET,
    run_id: str | None = None,
    router: Router | None = None,
    planner: Any = plan_node,
    rules: list[dict[str, Any]] | tuple = (),
) -> StateGraph:
    """The graph of docs/04 §2.4, with the sandbox and corrector bound in.

    ``planner`` is the PLAN node. It defaults to the dependency-ordered one and
    is a parameter only so P5's ordering ablation can swap in a deliberately
    worse order (``mra.benchmark``) and measure what FR-3 buys.
    """
    graph = StateGraph(MigrationState)
    for name, node in (
        ("map", make_map_node(target)),
        ("plan", planner),
        ("edit", make_edit_node()),
        ("test", make_test_node(runner, task_id, run_id)),
        ("correct", make_correct_node(corrector, router, rules, target)),
        ("finish", finish_node),
    ):
        graph.add_node(name, node)

    graph.add_edge(START, "map")
    graph.add_edge("map", "plan")
    graph.add_edge("plan", "edit")
    graph.add_edge("edit", "test")
    graph.add_conditional_edges(
        "test",
        route_after_test,
        {
            "correct": "correct",
            "next_batch": "edit",
            "success": "finish",
            "give_up": "finish",
        },
    )
    graph.add_edge("correct", "test")
    graph.add_edge("finish", END)
    return graph


# -- the audit log, reconstructed from the checkpointer --------------------


def trajectory_from_checkpoints(app: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Rebuild the ``mra:trajectory_event`` list from the checkpoint history.

    Each snapshot's ``next`` names the node that is about to run, and the
    following snapshot holds the state it produced — including the ``note`` it
    wrote. Pairing consecutive snapshots therefore recovers (node, action,
    detail, timestamp) without any node having logged anything itself.
    """
    history = list(app.get_state_history(config))[::-1]  # oldest first
    events: list[dict[str, Any]] = []
    for previous, current in zip(history, history[1:], strict=False):
        node = previous.next[0] if previous.next else None
        if node not in NODE_LABELS:
            continue  # __start__, and any internal step that is not one of ours
        note = (current.values or {}).get("note") or {}
        events.append(
            {
                "seq": len(events),
                "ts": current.created_at,
                "node": NODE_LABELS[node],
                "action": note.get("action", ""),
                "detail": note.get("detail", {}),
            }
        )
    return events


def changed_files(trajectory: list[dict[str, Any]]) -> list[str]:
    """Every file the agent actually rewrote, per the reconstructed log."""
    return sorted(
        {
            file
            for event in trajectory
            if event["node"] in ("EDIT", "CORRECT")
            for file in event["detail"].get("changed", [])
        }
    )


# -- the run ---------------------------------------------------------------


def run_migration(
    task_dir: Path | str,
    run_id: str | None = None,
    runs_dir: Path | str = "runs",
    target: str = TARGET,
    *,
    corrector: Any = None,
    router: Router | None = None,
    state: MigrationState | None = None,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
    planner: Any = plan_node,
    rules: list[dict[str, Any]] | tuple = (),
) -> dict[str, Any]:
    """Migrate a Tier-A task by driving the graph, and score the result.

    The pre-migration suite runs here rather than as a graph node: NB-10 makes
    a green baseline a *precondition* for the run, not a step of it, and M2 is
    undefined without it. Everything after that is the state machine.

    ``rules`` are promoted skills for the CORRECT node (:mod:`mra.skills`).
    Learning is not done here: a fix may only be stored once the run's verdict
    is known to be fully GREEN, which :func:`mra.report.run_with_report` decides.
    """
    task_dir = Path(task_dir)
    task_id = task_dir.name
    run_id = run_id or uuid.uuid4().hex[:12]
    out_dir = Path(runs_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    truth = json.loads((task_dir / "ground_truth.json").read_text())
    work = out_dir / "repo"
    if work.exists():
        shutil.rmtree(work)
    # The user's own .git is never copied: the run's first commit must be its own
    # pre-migration snapshot, which evidence.base_commit() diffs against.
    shutil.copytree(task_dir / "old", work, ignore=shutil.ignore_patterns(".git"))

    if state is None:
        state = new_state(
            run_id,
            str(work),
            {
                "task_id": task_id,
                "source_api": truth["source_api"],
                "target_api": truth["target_api"],
            },
        )
    state["repo_path"] = str(work)
    state["contract"].setdefault("expected_lint", list(EXPECTED_LINT) if target == TARGET else [])
    state["contract"].setdefault(
        "forbidden_patterns", list(FORBIDDEN_PATTERNS) if target == TARGET else []
    )

    runner = SandboxRunner(runs_dir=runs_dir)
    pre = runner.run(work, task_id=task_id, phase="pre", run_id=run_id, lint=False)
    (out_dir / "test_report_pre.json").write_text(json.dumps(pre, indent=2) + "\n")
    state["last_test_report"] = pre
    if problem := precondition_problem(pre):
        # NB-10: without a green baseline M2 is undefined and a red suite after
        # the edit proves nothing, so nothing is edited at all.
        raise PreconditionError(problem)

    base_sha = snapshot(work, "pre-migration snapshot")

    graph = build_graph(
        runner=runner,
        corrector=corrector,
        task_id=task_id,
        target=target,
        run_id=run_id,
        router=router,
        planner=planner,
        rules=rules,
    )
    config = {"configurable": {"thread_id": run_id}, "recursion_limit": recursion_limit}
    # Re-running a run_id starts a fresh audit log; appending to the old one
    # would interleave two runs' steps in one trajectory.
    for leftover in ("state.db", "state.db-wal", "state.db-shm"):
        (out_dir / leftover).unlink(missing_ok=True)
    with SqliteSaver.from_conn_string(str(out_dir / "state.db")) as saver:
        app = graph.compile(checkpointer=saver)
        final = app.invoke(state, config)
        trajectory = trajectory_from_checkpoints(app, config)

    post = final["last_test_report"]
    outcome = outcome_of(final)
    changed = changed_files(trajectory)

    # Against the pre-migration snapshot: EDIT and CORRECT both commit, so a
    # HEAD-relative diff would report an empty migration.
    patch = diff(work, base_sha)
    # Non-UTF-8 sources come back from git surrogate-escaped; write the original bytes.
    (out_dir / "migration.patch").write_text(patch, errors="surrogateescape")

    edited = {
        _key(site)
        for sites in final.get("call_sites", {}).values()
        for site in sites
        if site["file"] in set(changed)
    }
    expected = {_key(site) for site in truth["call_sites"]}
    m1_score = m1(agent_sites=edited, correct_sites=edited, ground_truth_sites=expected)
    m2_score = m2(t_total=pre["total"], t_post_pass=post["passed"])
    tokens = final.get("tokens") or state["tokens"]

    metrics = {
        "task_id": task_id,
        "m1_recall": m1_score["recall"],
        "m1_precision": m1_score["precision"],
        "m2_pass_rate": m2_score["pass_rate"],
        "m2_regressions": m2_score["regressions"],
        "m3_tokens": total_tokens(tokens),
        "m3_steps": len(trajectory),
        "m3_cost_usd": round(cost_usd(tokens), 6),
        "recovery_used": any(e["node"] == "CORRECT" for e in trajectory),
        "outcome": outcome,
        "imports": imports(
            source_tree(task_dir / "old"), source_tree(work), truth.get("expected_import_changes")
        ),
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    (out_dir / "trajectory.json").write_text(json.dumps(trajectory, indent=2) + "\n")
    (out_dir / "test_report.json").write_text(json.dumps(post, indent=2) + "\n")

    return {
        "run_id": run_id,
        "task_id": task_id,
        "out_dir": out_dir,
        "repo": work,
        "state": final,
        "trajectory": trajectory,
        "batches": final.get("edit_batches") or [],
        "changed_files": changed,
        "pre_report": pre,
        "test_report": post,
        "patch": patch,
        "metrics": metrics,
        "checkpoint_db": out_dir / "state.db",
    }
