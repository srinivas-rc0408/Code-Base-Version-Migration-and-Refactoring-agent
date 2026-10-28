"""Run directory -> report model: one complete, untruncated dict.

``load_run`` gathers the artifacts (state.db first, the JSON files beside
it), ``build_model`` shapes them into the nine report sections. The PDF
renders a page-budgeted view of the model; ``report.json`` is the model
itself. Both are pure functions of the run directory, which is what lets
``mra report <run_id>`` rebuild a report text-identically later.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from mra.nodes.correct_node import classify_offline, is_test_path
from mra.report.evidence import parse_patch
from mra.verdict import exempted_lint, headline, new_lint, verdict

EXCERPT_LINES = 12


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _from_state_db(db: Path, run_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Final state and the reconstructed trajectory, straight from the checkpointer."""
    if not db.is_file() or not run_id:
        return {}, []
    from langgraph.checkpoint.sqlite import SqliteSaver

    from mra.graph import build_graph, trajectory_from_checkpoints

    config = {"configurable": {"thread_id": run_id}}
    # Only the topology is needed to read the history; nothing here runs a node.
    graph = build_graph(runner=None, corrector=None, task_id="")
    with SqliteSaver.from_conn_string(str(db)) as saver:
        app = graph.compile(checkpointer=saver)
        snapshot = app.get_state(config)
        return dict(snapshot.values or {}), trajectory_from_checkpoints(app, config)


def load_run(out_dir: Path | str) -> dict[str, Any]:
    """Every artifact the verdict and the report read, keyed as :func:`verdict` expects."""
    out_dir = Path(out_dir)
    meta = _json(out_dir / "run_meta.json") or {}
    state, trajectory = _from_state_db(out_dir / "state.db", meta.get("run_id", ""))
    if not trajectory:
        trajectory = _json(out_dir / "trajectory.json") or []
    # The final suite: the file run_migration writes last, else the checkpointed
    # state. A crash can leave the *pre* report under that name; it never counts.
    candidates = [_json(out_dir / "test_report.json"), state.get("last_test_report")]
    post = next((r for r in candidates if r and r.get("phase") != "pre"), None)
    patch_path = out_dir / "migration.patch"
    # A latin-1 source makes a non-UTF-8 patch; undecodable bytes become U+FFFD here.
    patch = patch_path.read_text(errors="replace") if patch_path.is_file() else ""
    evidence = _json(out_dir / "verification.json") or {}
    return {
        "meta": meta,
        "state": state,
        "trajectory": trajectory,
        "patch": patch,
        "evidence": evidence,
        # -- the verdict's inputs --
        "crash": meta.get("crash_summary") or meta.get("crash"),
        "refused": meta.get("refused"),
        "edited_files": sum(1 for f in parse_patch(patch) if not is_test_path(f)),
        "pre_report": _json(out_dir / "test_report_pre.json"),
        "post_report": post,
        "metrics": _json(out_dir / "metrics.json"),
        "tamper": sorted(f for f in parse_patch(patch) if is_test_path(f)),
        "rejected_tamper": sorted(
            {
                path
                for e in trajectory
                if e["node"] == "CORRECT"
                for path in e["detail"].get("rejected", [])
            }
        ),
        "apply_check": evidence.get("apply_check"),
        "token_budget": meta.get("token_budget"),
        "run_timeout_s": meta.get("run_timeout_s"),
        "wall_clock_s": meta.get("wall_clock_s"),
        "residual": evidence.get("residual"),
        "has_ground_truth": meta.get("has_ground_truth", False),
        "expected_sites": meta.get("expected_sites"),
        # MAP's findings and the files python_files() saw; None when never recorded.
        "found_sites": (
            sum(len(s) for s in state["call_sites"].values()) if "call_sites" in state else None
        ),
        "scanned_files": (
            len(evidence["inventory"]) if evidence.get("inventory") is not None else None
        ),
        "semantic": evidence.get("semantic", []),
        "lint": {
            **(evidence.get("lint") or {}),
            "exempt": (state.get("contract") or {}).get("expected_lint", []),
        },
        "coverage": evidence.get("coverage"),
    }


# -- sections ---------------------------------------------------------------


def _egress_line(llm: dict[str, Any]) -> str:
    egress = llm.get("egress") or {}
    calls = sum(h["calls"] for h in egress.values())
    if not calls:
        mode = " (MRA_PRIVACY=local-only)" if llm.get("privacy") == "local-only" else ""
        return f"0 remote calls{mode}"
    hosts = ", ".join(
        f"{host} {h['calls']} call(s) / {h['bytes_sent']:,} B" for host, h in sorted(egress.items())
    )
    return f"{calls} remote call(s): {hosts}"


def _llm(meta: dict[str, Any]) -> dict[str, Any]:
    llm = meta.get("llm") or {}
    calls = llm.get("calls") or []
    providers: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"calls": 0, "tokens": 0}
    )
    by_role: dict[str, int] = defaultdict(int)
    for call in calls:
        tokens = call.get("tokens_in", 0) + call.get("tokens_out", 0)
        entry = providers[(call.get("provider", "?"), call.get("model", "?"))]
        entry["calls"] += 1
        entry["tokens"] += tokens
        by_role[f"{call.get('task', '?')} / {call.get('provider', '?')}"] += tokens
    return {
        "calls": len(calls),
        "providers": [{"provider": p, "model": m, **v} for (p, m), v in sorted(providers.items())],
        "tokens_by_role": sorted(by_role.items()),
        "egress": llm.get("egress") or {},
        "egress_line": _egress_line(llm),
        "privacy": llm.get("privacy", ""),
    }


def _files(
    state: dict[str, Any], evidence: dict[str, Any], patch: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    sites = state.get("call_sites") or {}
    status = state.get("file_status") or {}
    rows = []
    for item in evidence.get("inventory") or []:
        file = item["file"]
        final = status.get(file) or (
            "changed" if file in patch else "pending" if file in sites else "untouched"
        )
        rows.append(
            {"file": file, "loc": item["loc"], "sites": len(sites.get(file, [])), "status": final}
        )
    return rows


def _plan(trajectory: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    plan = next((e["detail"] for e in trajectory if e["node"] == "PLAN"), {})
    batches = plan.get("batches") or state.get("edit_batches") or []
    cycles = plan.get("cycles_collapsed", [])
    return {
        "batches": batches,
        "cycles": cycles,
        "batch_size": plan.get("batch_size"),
        "fr3_violations": len(plan.get("fr3_violations") or []),
        "rationale": (
            "Files are edited in dependency order (FR-3): a module is migrated before "
            "the modules that import it, so no batch ever runs against a half-migrated "
            f"dependency. {len(cycles)} import cycle(s) were collapsed into single atomic "
            "batches, since a cycle has no safe internal order. Batches are capped at "
            f"{plan.get('batch_size', '?')} file(s), except that a cycle is never split."
        ),
    }


def _timeline(trajectory: list[dict[str, Any]], pre: dict[str, Any] | None) -> list[dict]:
    rows = []
    if pre is not None:
        rows.append(
            {
                "step": "pre",
                "node": "TEST",
                "text": f"pre-migration suite: {pre.get('passed', 0)}/{pre.get('total', 0)} passed",
            }
        )
    for index, event in enumerate(trajectory):
        detail, text = event.get("detail") or {}, event.get("action", "")
        if event["node"] == "TEST" and detail.get("failures"):
            text += f" — failing: {', '.join(detail['failures'][:3])}"
        if event["node"] == "CORRECT":
            klass = classify_offline({"exc_type": detail.get("exc_type") or "", "message": ""})
            following = next((e for e in trajectory[index + 1 :] if e["node"] == "TEST"), None)
            if detail.get("rejected"):
                outcome = "rejected: edited the test oracle"
            elif following is None:
                outcome = "no re-test recorded"
            else:
                bad = following["detail"].get("failed", 0) + following["detail"].get("errors", 0)
                outcome = "suite green" if not bad else f"{bad} still failing"
            text = (
                f"{text} · class {klass} · signature "
                f"{str(detail.get('signature', ''))[:12]} · {outcome}"
            )
        rows.append({"step": str(event.get("seq", index)), "node": event["node"], "text": text})
    return rows


def _changes(patch: dict[str, dict[str, Any]], state: dict[str, Any]) -> list[dict]:
    sites = state.get("call_sites") or {}
    return [
        {
            "file": file,
            "added": p["added"],
            "removed": p["removed"],
            "sites": len(sites.get(file, [])),
            "excerpt": (p["hunks"][0] if p["hunks"] else [])[:EXCERPT_LINES],
        }
        for file, p in sorted(patch.items())
    ]


def _lint_text(lint: dict[str, Any]) -> str:
    if None in (lint.get("pre"), lint.get("post")):
        return "not measured"
    new, waived = new_lint(lint), exempted_lint(lint)
    text = f"{len(lint['pre'])} before -> {len(lint['post'])} after; {len(new)} new"
    if new:
        text += ": " + ", ".join(f"{f['code']} {f['file']}" for f in new[:4])
    if waived:
        text += (
            f"; exempted by migration contract: {', '.join(sorted(lint['exempt']))} "
            f"({len(waived)} finding(s))"
        )
    return text


def _edge_row(suite: dict[str, Any] | None, version: str | None) -> dict[str, Any]:
    """The agent's own accuracy on corpus/edge: context for how far to trust this verdict."""
    check = "Edge-case accuracy suite (corpus/edge)"
    if suite is None:
        return {"check": check, "passed": None, "evidence": "not run"}
    if suite["agent_version"] != version:
        return {
            "check": check,
            "passed": None,
            "evidence": f"results are for agent {suite['agent_version']}, not {version}",
        }
    failing = ", ".join(suite["failing"][:4])
    return {
        "check": check,
        "passed": suite["passed"] == suite["total"],
        "evidence": f"{suite['passed']}/{suite['total']} cases give the expected verdict"
        + (f"; mismatches: {failing}" if failing else ""),
    }


def _checks(a: dict[str, Any]) -> list[dict[str, Any]]:
    """The verification table: one row per check, aggregated so it never grows with N."""
    pre, post, evidence = a["pre_report"] or {}, a["post_report"] or {}, a["evidence"]
    residual = evidence.get("residual") or {}
    lint = a["lint"]
    coverage = evidence.get("coverage") or {}
    semantic = evidence.get("semantic") or []
    apply = evidence.get("apply_check")
    cov_files = coverage.get("files") or {}
    cold = sorted(f for f, c in cov_files.items() if c["changed"] and not c["executed"])
    tampered = a["tamper"] + a["rejected_tamper"]

    def row(check: str, passed: bool | None, text: str) -> dict[str, Any]:
        return {"check": check, "passed": passed, "evidence": text}

    return [
        row(
            "Pre-migration suite green, >= 1 test",
            bool(pre)
            and pre.get("total", 0) > 0
            and not pre.get("failed")
            and not pre.get("errors"),
            f"{pre.get('passed', 0)}/{pre.get('total', 0)} passed",
        ),
        row(
            "Final suite green",
            bool(post) and not post.get("failed") and not post.get("errors"),
            f"{post.get('passed', 0)}/{post.get('total', 0)} passed, {post.get('errors', 0)} errors"
            if post
            else "no final suite run",
        ),
        row(
            "Test oracle untouched (NB-4)",
            not tampered,
            ", ".join(tampered) or "no test file in the patch or in any attempt",
        ),
        row(
            "Patch applies to a fresh checkout",
            None if apply is None else apply["ok"],
            apply["detail"] if apply else "not checked",
        ),
        row(
            "No residual sites (re-run MAP)",
            not residual.get("sites") and not residual.get("skipped"),
            f"{len(residual.get('sites', []))} call(s), {len(residual.get('skipped', []))} "
            f"skipped by design"
            if residual
            else "not checked",
        ),
        row(
            "Every file parsed",
            not residual.get("unparseable"),
            ", ".join(residual.get("unparseable", [])) or "all parsed",
        ),
        row(
            "Semantic checks",
            all(c["passed"] for c in semantic) if semantic else None,
            f"{sum(c['passed'] for c in semantic)}/{len(semantic)} passed"
            if semantic
            else f"none defined for {evidence.get('target', 'this target')}",
        ),
        row(
            "No new ruff errors",
            None if None in (lint.get("pre"), lint.get("post")) else not new_lint(lint),
            _lint_text(lint),
        ),
        _edge_row(evidence.get("edge_suite"), a["meta"].get("agent_version")),
        row(
            "Edited files executed by tests",
            (not cold) if coverage.get("available") and cov_files else None,
            (
                f"{len(cov_files) - len(cold)}/{len(cov_files)} files; not run: "
                f"{', '.join(cold[:5])}"
                if cold
                else f"{len(cov_files)}/{len(cov_files)} files"
            )
            if coverage.get("available") and cov_files
            else "no edited files"
            if coverage.get("available")
            else coverage.get("error", "not measured"),
        ),
    ]


def _graph(state: dict[str, Any], changed: set[str]) -> dict[str, Any]:
    edges = sorted(
        (importer, file)
        for file, importers in (state.get("dep_graph") or {}).items()
        for importer in importers
    )
    nodes = sorted({*(state.get("dep_graph") or {}), *(n for e in edges for n in e)})
    return {"nodes": nodes, "edges": edges, "changed": sorted(changed & set(nodes))}


def build_model(a: dict[str, Any]) -> dict[str, Any]:
    """The whole report as data. Untruncated: this is what report.json holds."""
    meta, state, evidence = a["meta"], a["state"], a["evidence"]
    patch = parse_patch(a["patch"])
    result = verdict(a)
    pre, post = a["pre_report"], a["post_report"]
    tests_series = ([("pre", pre.get("passed", 0), pre.get("total", 0))] if pre else []) + [
        (str(e["seq"]), e["detail"].get("passed", 0), e["detail"].get("total", 0))
        for e in a["trajectory"]
        if e["node"] == "TEST"
    ]
    return {
        "meta": {
            key: meta.get(key)
            for key in (
                "repo_name",
                "task_id",
                "run_id",
                "agent_version",
                "source_api",
                "target_api",
                "started_at",
                "wall_clock_s",
                "completed_at",
                "completed_tz",
                "has_ground_truth",
            )
        },
        "verdict": result,
        "headline": headline(result),
        "metrics": a["metrics"] or {},
        "llm": _llm(meta),
        "files": _files(state, evidence, patch),
        "graph": _graph(state, set(patch)),
        "plan": _plan(a["trajectory"], state),
        "timeline": _timeline(a["trajectory"], pre),
        # Which promoted skill (mra.skills) repaired which step instead of the corrector.
        "skills_fired": [
            {"step": e["seq"], "rule": e["detail"]["rule"], "files": e["detail"].get("changed", [])}
            for e in a["trajectory"]
            if e["node"] == "CORRECT" and e["detail"].get("rule")
        ],
        "changes": _changes(patch, state),
        "verification": {
            "pre": {k: (pre or {}).get(k) for k in ("total", "passed", "failed", "errors")},
            "post": {k: (post or {}).get(k) for k in ("total", "passed", "failed", "errors")},
            "checks": _checks(a),
            "semantic": evidence.get("semantic") or [],
            "coverage": (evidence.get("coverage") or {}).get("files", {}),
            "lint": {
                **a["lint"],
                "new": new_lint(a["lint"]),
                "exempted": exempted_lint(a["lint"]),
                "summary": _lint_text(a["lint"]),
            },
            "residual": evidence.get("residual") or {},
            "errors": evidence.get("errors") or {},
            "patch_salvaged": bool(evidence.get("patch_salvaged")),
        },
        "series": {"tests_per_step": tests_series, "tokens_by_role": _llm(meta)["tokens_by_role"]},
        "issues": result["reasons"],
    }
