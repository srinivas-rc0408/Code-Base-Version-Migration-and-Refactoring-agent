"""P4 acceptance: the LangGraph state machine, batching, and the context budget.

Four claims, each with its own group below:

* the graph reproduces the P3 loop's outcomes on task03 — same verdicts, same
  metrics, now driven by ``StateGraph`` instead of a ``while``;
* ``plan_node`` orders batches so no file is edited on top of an unmigrated
  dependency (FR-3), and collapses an import cycle into one atomic batch;
* the trajectory is *reconstructed* from the SqliteSaver checkpoint file, not
  from anything the process kept in memory — the database is reopened from
  disk to prove it;
* the per-call LLM payload does not grow with the repo (NFR-12): task04 has
  more than twice task03's modules and its prompt is the same size.

As in P3, everything here runs without an API key; only the live-model test
skips. The fake DeepSeek client exercises the whole LLM path — prompt
assembly, token billing, fence extraction, libcst validation — offline.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import libcst as cst
import networkx as nx
import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from libcst.codemod import CodemodContext

from mra.analysis import analyze, from_state_adjacency
from mra.analysis import call_sites as call_sites_module
from mra.analysis import dep_graph as dep_graph_module
from mra.codemods.datetime_utcnow import TARGET, ConvertUtcnowCommand
from mra.graph import (
    DEFAULT_RECURSION_LIMIT,
    NODE_LABELS,
    build_graph,
    route_after_test,
    run_migration,
    trajectory_from_checkpoints,
)
from mra.memory import (
    MAX_NEIGHBOURS,
    SUMMARY_MAX_CHARS,
    progress_facts,
    summarize,
)
from mra.models import ROLES, TIER, Endpoint, Router, live_ready
from mra.models.providers import FakeProvider
from mra.nodes.correct_node import LLMCorrector, is_test_path
from mra.nodes.plan_node import DEFAULT_EDIT_BATCH_SIZE, cycles, plan_batches, violations
from mra.recovery import DEFAULT_MAX_FIX_ATTEMPTS
from mra.sandbox import SandboxRunner
from mra.state import new_state

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS = REPO_ROOT / "corpus" / "tierA"
TASK03 = CORPUS / "task03_half_migration"
TASK04 = CORPUS / "task04_multimodule"

#: The two modules that import each other. They must share a batch.
CYCLE = ["src/pkg/audit.py", "src/pkg/ledger.py"]

needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(["docker", "info"], capture_output=True).returncode != 0,
    reason="needs a working Docker daemon",
)
needs_key = pytest.mark.skipif(
    not live_ready(),
    reason="needs the mra.toml live provider and its key; the live-LLM path is optional",
)


# -- correctors ------------------------------------------------------------


def stub_corrector(repo: Path, failure: dict[str, Any], context: dict[str, Any]) -> list[str]:
    """The known-correct fix: finish the migration wherever the trace points."""
    from mra.nodes.correct_node import locate
    from mra.nodes.edit_node import apply_codemod

    located = locate(repo, failure, TARGET)
    return [] if located is None else apply_codemod(repo, {located["file"]: located["sites"]})


def bad_corrector(repo: Path, failure: dict[str, Any], context: dict[str, Any]) -> list[str]:
    """Claims a fix, changes nothing. The signature survives every round."""
    return []


def _codemod(source: str) -> str:
    """Run the deterministic codemod over source text, in memory."""
    command = ConvertUtcnowCommand(CodemodContext())
    return command.transform_module(cst.parse_module(source)).code


class FakeDeepSeek(FakeProvider):
    """A provider that answers from the codemod instead of a model.

    Exists so the whole LLM path — routing, prompt assembly, token accounting,
    fence extraction, libcst validation, NB-4 refusal — is exercised with no
    key and no network. It replies with the *correct* patch, so what is under
    test is the plumbing, never the model's judgement.
    """

    def __init__(self) -> None:
        super().__init__("fake-deepseek", reply=self._reply)
        self.prompts: list[tuple[str, str]] = []

    def _reply(self, messages: list[dict[str, str]], model: str) -> str:
        system, user = messages[0]["content"], messages[1]["content"]
        self.prompts.append((model, user))
        if "one word" in system:  # classify (cheap tier)
            return "behaviour"
        if "progress note" in system:  # rolling summary (cheap tier)
            return "Most files migrated; one cross-module break outstanding."
        source = user.split("```python\n", 1)[1].rsplit("```", 1)[0]  # corrective patch
        return f"```python\n{_codemod(source)}```"


def fake_router(provider: FakeProvider) -> Router:
    """Every role served by ``provider``, the model named after the role's tier."""
    return Router(roles={role: [Endpoint(provider, f"fake-{TIER[role]}")] for role in ROLES})


def _tree_digest(root: Path) -> str:
    sha = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        sha.update(str(path.relative_to(root)).encode())
        sha.update(path.read_bytes())
    return sha.hexdigest()


@pytest.fixture(scope="session")
def corpus_digests() -> dict[str, str]:
    """Taken before any run, compared after: the corpus must be read-only in practice."""
    return {task.name: _tree_digest(task) for task in (TASK03, TASK04)}


@pytest.fixture(scope="session")
def graph03(tmp_path_factory: pytest.TempPathFactory, corpus_digests: dict[str, str]):
    return run_migration(
        TASK03,
        run_id="p4_task03",
        corrector=stub_corrector,
        runs_dir=tmp_path_factory.mktemp("runs"),
    )


@pytest.fixture(scope="session")
def graph04(tmp_path_factory: pytest.TempPathFactory, corpus_digests: dict[str, str]):
    return run_migration(
        TASK04,
        run_id="p4_task04",
        corrector=stub_corrector,
        runs_dir=tmp_path_factory.mktemp("runs"),
    )


@pytest.fixture(scope="session")
def capped03(tmp_path_factory: pytest.TempPathFactory, corpus_digests: dict[str, str]):
    return run_migration(
        TASK03,
        run_id="p4_task03_cap",
        corrector=bad_corrector,
        runs_dir=tmp_path_factory.mktemp("runs"),
    )


def _nodes(trajectory: list[dict[str, Any]]) -> list[str]:
    return [event["node"] for event in trajectory]


# -- 1. the graph reproduces the P3 loop -----------------------------------


@needs_docker
def test_graph_reaches_the_same_verdict_as_the_p3_loop(graph03: dict[str, Any]) -> None:
    """Same outcome and same scores on task03, now driven by LangGraph."""
    from mra.run import migrate_task

    loop = migrate_task(
        TASK03,
        run_id="p3_reference",
        runs_dir=graph03["out_dir"].parent / "p3ref",
        edit_only=("src/pkg/core.py", "src/pkg/audit.py"),
        corrector=stub_corrector,
    )
    compared = (
        "outcome",
        "m1_recall",
        "m1_precision",
        "m2_pass_rate",
        "m2_regressions",
        "recovery_used",
    )
    assert {k: graph03["metrics"][k] for k in compared} == {k: loop["metrics"][k] for k in compared}
    # m3_steps legitimately differs: the graph runs MAP/PLAN/FINISH as steps.
    assert graph03["metrics"]["outcome"] == "success"


@needs_docker
def test_graph_visits_the_nodes_of_the_documented_state_machine(
    graph03: dict[str, Any],
) -> None:
    """docs/04 §2.4: MAP -> PLAN -> EDIT -> TEST -> {CORRECT | EDIT | FINISH}."""
    nodes = _nodes(graph03["trajectory"])
    assert nodes[0] == "MAP" and nodes[1] == "PLAN" and nodes[-1] == "FINISH"
    assert nodes == ["MAP", "PLAN", "EDIT", "TEST", "CORRECT", "TEST", "EDIT", "TEST", "FINISH"]
    assert set(nodes) <= set(NODE_LABELS.values())
    assert graph03["trajectory"][-1]["detail"]["outcome"] == "success"
    assert graph03["trajectory"][-1]["detail"]["flagged"] is False


@needs_docker
def test_graph_gives_up_at_the_cap_and_flags_the_run(capped03: dict[str, Any]) -> None:
    """FR-9's second stop condition, through the router instead of a while loop."""
    trajectory = capped03["trajectory"]
    corrections = [e for e in trajectory if e["node"] == "CORRECT"]
    assert capped03["metrics"]["outcome"] == "gave_up"
    assert len(corrections) == DEFAULT_MAX_FIX_ATTEMPTS
    assert len({c["detail"]["signature"] for c in corrections}) == 1
    assert [c["detail"]["attempt"] for c in corrections] == list(
        range(1, DEFAULT_MAX_FIX_ATTEMPTS + 1)
    )
    assert trajectory[-1]["node"] == "FINISH"
    assert trajectory[-1]["detail"]["flagged"] is True
    assert trajectory[-1]["detail"]["blocked_signatures"] == [corrections[0]["detail"]["signature"]]


def test_route_after_test_implements_the_documented_table() -> None:
    """The four branches of docs/04 §2.3, as a pure function."""
    green = {"failed": 0, "errors": 0, "failures": []}
    red = {"failed": 1, "errors": 0, "failures": [{"signature": "s"}]}
    batches = [["a.py"], ["b.py"]]
    assert (
        route_after_test({"last_test_report": green, "current_batch": 2, "edit_batches": batches})
        == "success"
    )
    assert (
        route_after_test({"last_test_report": green, "current_batch": 1, "edit_batches": batches})
        == "next_batch"
    )
    assert (
        route_after_test(
            {
                "last_test_report": red,
                "current_batch": 1,
                "edit_batches": batches,
                "fix_attempts": {"s": 0},
            }
        )
        == "correct"
    )
    assert (
        route_after_test(
            {
                "last_test_report": red,
                "current_batch": 1,
                "edit_batches": batches,
                "fix_attempts": {"s": DEFAULT_MAX_FIX_ATTEMPTS},
            }
        )
        == "give_up"
    )


# -- 2. batching: dependency order, cycles, size ---------------------------


def test_task04_batches_are_dependency_ordered_and_collapse_the_cycle() -> None:
    """The FR-3 property, asserted on the real plan rather than described."""
    graph = dep_graph_module.build(TASK04 / "old")
    sites = analyze(TASK04 / "old", TARGET)["call_sites"]
    batches = plan_batches(graph, sites)

    assert violations(batches, graph) == [], "a file was edited before its dependency"
    assert cycles(graph) == [CYCLE], "the fixture must contain exactly one import cycle"
    # The cyclic modules share a batch — collapsed, not merely detected.
    containing = [batch for batch in batches if set(CYCLE) & set(batch)]
    assert len(containing) == 1 and sorted(containing[0]) == CYCLE
    # clock.py is what everything else reads, so it is migrated first.
    assert batches[0] == ["src/pkg/clock.py"]
    assert sum(len(batch) for batch in batches) == 6
    assert sorted(f for batch in batches for f in batch) == sorted(sites)


def test_fr3_property_holds_for_every_task_in_the_corpus() -> None:
    """Not a task04 accident: the ordering rule holds wherever it is applied."""
    for task in sorted(CORPUS.glob("task*")):
        graph = dep_graph_module.build(task / "old")
        batches = plan_batches(graph, analyze(task / "old", TARGET)["call_sites"])
        assert violations(batches, graph) == [], task.name


def test_batch_size_caps_independent_files_but_never_splits_a_cycle() -> None:
    """NFR-5 bounds the blast radius; rule 1 outranks it when they conflict."""
    independent = nx.DiGraph()
    independent.add_nodes_from(f"f{i}.py" for i in range(7))
    sites = {f"f{i}.py": [{"line": 1}] for i in range(7)}
    assert [len(b) for b in plan_batches(independent, sites, batch_size=3)] == [3, 3, 1]
    assert [len(b) for b in plan_batches(independent, sites, batch_size=7)] == [7]

    ring = nx.DiGraph()
    ring.add_edges_from([("a.py", "b.py"), ("b.py", "c.py"), ("c.py", "a.py"), ("d.py", "a.py")])
    ring_sites = {f: [{"line": 1}] for f in ("a.py", "b.py", "c.py", "d.py")}
    batches = plan_batches(ring, ring_sites, batch_size=2)
    assert ["a.py", "b.py", "c.py"] in batches, "a 3-cycle must survive a cap of 2"
    assert violations(batches, ring) == []


def test_default_batch_size_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = nx.DiGraph()
    graph.add_nodes_from(f"f{i}.py" for i in range(6))
    sites = {f"f{i}.py": [{"line": 1}] for i in range(6)}
    assert DEFAULT_EDIT_BATCH_SIZE == 3
    monkeypatch.setenv("MRA_EDIT_BATCH_SIZE", "2")
    assert [len(b) for b in plan_batches(graph, sites)] == [2, 2, 2]


def test_state_adjacency_round_trips_to_the_same_plan() -> None:
    """Nodes rebuild the graph from state rather than pickling one into a checkpoint."""
    built = dep_graph_module.build(TASK04 / "old")
    analysis = analyze(TASK04 / "old", TARGET)
    rebuilt = from_state_adjacency(analysis["dep_graph"])
    assert set(rebuilt.edges) == set(built.edges)
    assert plan_batches(rebuilt, analysis["call_sites"]) == plan_batches(
        built, analysis["call_sites"]
    )


@needs_docker
def test_task04_migrates_to_green_across_every_batch(graph04: dict[str, Any]) -> None:
    """M1 and M2 both at 100 over five batches, with a real recovery in the middle."""
    metrics = graph04["metrics"]
    assert metrics["outcome"] == "success"
    assert metrics["m1_recall"] == 100.0
    assert metrics["m1_precision"] == 100.0
    assert metrics["m2_pass_rate"] == 100.0
    assert metrics["m2_regressions"] == 0
    assert metrics["recovery_used"] is True, "the cross-batch break must have fired"
    assert len(graph04["batches"]) == 5
    assert call_sites_module.find_in_repo(graph04["repo"], TARGET) == {}


@needs_docker
def test_task04_edits_every_batch_in_the_planned_order(graph04: dict[str, Any]) -> None:
    """The log shows the plan being executed, not merely produced."""
    edits = [e for e in graph04["trajectory"] if e["node"] == "EDIT"]
    assert [e["detail"]["batch"] for e in edits] == [0, 1, 2, 3, 4]
    assert [e["detail"]["files"] for e in edits] == graph04["batches"]
    plan = next(e for e in graph04["trajectory"] if e["node"] == "PLAN")
    assert plan["detail"]["fr3_violations"] == []
    assert plan["detail"]["cycles_collapsed"] == [CYCLE]


@needs_docker
def test_task04_breaks_only_after_the_batch_that_crosses_the_contract(
    graph04: dict[str, Any],
) -> None:
    """The break is where the fixture puts it: once invoice.py moves, not before."""
    tests = [e for e in graph04["trajectory"] if e["node"] == "TEST"]
    assert tests[0]["detail"]["failed"] == 0, "migrating the clock breaks nothing"
    assert tests[1]["detail"]["failed"] == 0, "migrating the cycle breaks nothing"
    assert tests[2]["detail"]["failed"] > 0, "migrating invoice.py must break report.py"
    assert tests[-1]["detail"]["failed"] == 0


# -- 3. the checkpointer IS the audit log ----------------------------------


@needs_docker
def test_trajectory_is_reconstructed_from_the_checkpoint_file_on_disk(
    graph04: dict[str, Any],
) -> None:
    """Reopen the database in a fresh saver: the log must come back identical.

    This is the claim that there is no parallel logger. Nothing from the
    original run is in scope here except the path to ``state.db``.
    """
    db = graph04["checkpoint_db"]
    assert db.is_file() and db.stat().st_size > 0
    with sqlite3.connect(db) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "checkpoints" in tables

    graph = build_graph(
        runner=SandboxRunner(runs_dir=db.parent),
        corrector=stub_corrector,
        task_id=graph04["task_id"],
        run_id=graph04["run_id"],
    )
    config = {
        "configurable": {"thread_id": graph04["run_id"]},
        "recursion_limit": DEFAULT_RECURSION_LIMIT,
    }
    with SqliteSaver.from_conn_string(str(db)) as saver:
        replayed = trajectory_from_checkpoints(graph.compile(checkpointer=saver), config)
    assert replayed == graph04["trajectory"]


@needs_docker
def test_trajectory_events_match_the_srs_shape(graph04: dict[str, Any]) -> None:
    """mra:trajectory_event (SRS §4.1): seq, ts, node, action, detail."""
    written = json.loads((graph04["out_dir"] / "trajectory.json").read_text())
    assert written == graph04["trajectory"]
    for index, event in enumerate(written):
        assert set(event) == {"seq", "ts", "node", "action", "detail"}
        assert event["seq"] == index
        assert event["node"] in NODE_LABELS.values()
        assert isinstance(event["action"], str) and event["action"]
        assert isinstance(event["detail"], dict)


@needs_docker
def test_run_writes_every_artifact(graph04: dict[str, Any]) -> None:
    for name in (
        "migration.patch",
        "metrics.json",
        "trajectory.json",
        "test_report.json",
        "test_report_pre.json",
        "state.db",
    ):
        assert (graph04["out_dir"] / name).is_file(), name
    assert "b/src/pkg/report.py" in graph04["patch"]
    assert graph04["pre_report"]["failed"] == 0, "NB-10: the baseline must be green"


# -- 4. the context budget (NFR-12, M3) ------------------------------------


@pytest.fixture
def payload_sizes(tmp_path: Path) -> dict[str, int]:
    """The real prompt size for one corrective edit on each task, offline.

    Both trees are put in the same state — every module migrated except the one
    that subtracts another module's clock reading — so the only difference
    between the two prompts is how many modules surround the file being fixed.
    """
    from mra.nodes.edit_node import apply_codemod

    sizes: dict[str, int] = {}
    for task, leave in ((TASK03, "src/pkg/report.py"), (TASK04, "src/pkg/report.py")):
        work = tmp_path / task.name
        shutil.copytree(task / "old", work)
        found = call_sites_module.find_in_repo(work, TARGET)
        apply_codemod(work, {f: s for f, s in found.items() if f != leave})

        state = {
            "edit_batches": [[f] for f in found],
            "current_batch": len(found) - 1,
            "file_status": dict.fromkeys(found, "migrated"),
            "fix_attempts": {"sig": 1},
            "last_test_report": {"total": 11, "failed": 1, "errors": 0},
        }
        failure = {
            "nodeid": "tests/test_report.py::t",
            "exc_type": "TypeError",
            "signature": "sig",
            "file": leave,
            "message": "can't subtract offset-naive and offset-aware datetimes",
            "trace": f"{leave}:20: TypeError",
        }
        corrector = LLMCorrector(
            fake_router(FakeDeepSeek()),
            TARGET,
            {"source_api": "datetime.utcnow", "target_api": "datetime.now(timezone.utc)"},
        )
        changed = corrector(work, failure, {"summary": summarize(state)})
        assert changed == [leave], "the fake client must apply a real patch"
        assert call_sites_module.find_in_repo(work, TARGET) == {}
        sizes[task.name] = corrector.payload_chars[0]
    return sizes


def test_llm_payload_does_not_grow_with_the_repo(payload_sizes: dict[str, int]) -> None:
    """NFR-12: task04 has 8 modules to task03's 4, and the prompt is the same size."""
    small = payload_sizes["task03_half_migration"]
    large = payload_sizes["task04_multimodule"]
    assert small > 0 and large > 0
    growth = abs(large - small) / small
    assert growth < 0.25, f"payload grew {growth:.0%} ({small} -> {large} chars) with repo size"


def test_progress_summary_is_constant_size_in_repo_size() -> None:
    """The rolling note carries counts, never file names, so it cannot scale."""

    def state_of(n: int) -> dict[str, Any]:
        return {
            "edit_batches": [[f"m{i}.py"] for i in range(n)],
            "current_batch": n // 2,
            "file_status": {f"m{i}.py": "migrated" for i in range(n // 2)},
            "fix_attempts": {"sig": 2},
            "last_test_report": {"total": 4 * n, "failed": 1, "errors": 0},
        }

    small, large = summarize(state_of(4)), summarize(state_of(4000))
    assert len(large) <= SUMMARY_MAX_CHARS
    assert abs(len(large) - len(small)) < 40, "the summary tracked repo size"
    for n in (4, 4000):
        assert "m0.py" not in summarize(state_of(n)), "the summary must not name files"
    assert progress_facts(state_of(4)).keys() == progress_facts(state_of(4000)).keys()


def test_graph_slice_is_truncated_to_a_constant_number_of_neighbours() -> None:
    """A hub module has hundreds of importers; the prompt shows a handful."""
    from mra.memory import graph_slice

    located = {"file": "core.py", "importers": [f"caller{i}.py" for i in range(300)], "imports": []}
    rendered = graph_slice(located)
    assert rendered.count("caller") == MAX_NEIGHBOURS
    assert f"+{300 - MAX_NEIGHBOURS} more" in rendered
    assert len(rendered) < 300


def test_summarization_is_billed_to_the_cheap_model() -> None:
    """The rolling note is a V4-Flash job; paying V4-Pro rates for it is an M3 bug."""
    client = FakeDeepSeek()
    router = fake_router(client)
    summary = summarize(
        {
            "edit_batches": [["a.py"]],
            "current_batch": 1,
            "file_status": {"a.py": "migrated"},
            "fix_attempts": {},
            "last_test_report": {"total": 3, "failed": 0, "errors": 0},
        },
        router,
    )
    assert summary
    assert router.tokens["flash_in"] > 0 and router.tokens["pro_in"] == 0
    assert client.prompts[0][0] == "fake-flash"


@needs_docker
def test_a_truncation_retry_is_its_own_step_and_spend(tmp_path: Path) -> None:
    """BUG-05: the larger retry after a cut-off reply is an M3 step and its tokens are billed."""
    client = FakeDeepSeek()
    client.truncated = lambda max_tokens: max_tokens <= 4096  # the doubled retry is whole
    state = new_state("bug05", "", {"source_api": TARGET})
    router = fake_router(client)
    router.tokens = state["tokens"]
    result = run_migration(
        TASK03,
        run_id="bug05",
        runs_dir=tmp_path,
        corrector=LLMCorrector(router, TARGET, state["contract"]),
        router=router,
        state=state,
    )
    assert result["metrics"]["outcome"] == "success"

    retried = [c for c in router.calls if c.get("retry")]
    retries = [e for e in result["trajectory"] if e["detail"].get("retry")]
    assert retried and len(retries) == len(retried)
    assert all(e["node"] == "CORRECT" for e in retries)
    assert [e["detail"]["tokens"] for e in retries] == [
        c["tokens_in"] + c["tokens_out"] for c in retried
    ]
    metrics = json.loads((result["out_dir"] / "metrics.json").read_text())
    assert metrics["m3_tokens"] == sum(c["tokens_in"] + c["tokens_out"] for c in router.calls)
    assert metrics["m3_steps"] == len(result["trajectory"])


# -- 5. boundaries still hold ----------------------------------------------


@needs_docker
def test_no_run_touched_a_test_file_or_the_corpus(
    graph03: dict[str, Any],
    graph04: dict[str, Any],
    capped03: dict[str, Any],
    corpus_digests: dict[str, str],
) -> None:
    """NB-4 and sandbox isolation, across all three graph runs."""
    for result in (graph03, graph04, capped03):
        assert not any(is_test_path(f) for f in result["changed_files"])
        assert "a/tests/" not in result["patch"] and "b/tests/" not in result["patch"]
        source = TASK04 if result["task_id"] == "task04_multimodule" else TASK03
        for test_file in (source / "old" / "tests").glob("test_*.py"):
            assert (result["repo"] / "tests" / test_file.name).read_text() == test_file.read_text()
    assert {name: _tree_digest(CORPUS / name) for name in corpus_digests} == corpus_digests


@needs_docker
def test_patch_applies_to_a_fresh_checkout(graph04: dict[str, Any], tmp_path: Path) -> None:
    """FR-10: the deliverable still applies cleanly after five batches and a recovery."""
    fresh = tmp_path / "fresh"
    shutil.copytree(TASK04 / "old", fresh)
    subprocess.run(["git", "init", "-q"], cwd=fresh, check=True)
    result = subprocess.run(
        ["git", "apply", "--check", str(graph04["out_dir"] / "migration.patch")],
        cwd=fresh,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


# -- 6. live model, optional ------------------------------------------------


@pytest.mark.live
@needs_docker
@needs_key
def test_live_llm_drives_the_graph_on_the_multimodule_task(tmp_path: Path) -> None:
    """The real model, through the real graph, on the biggest fixture."""
    from mra.state import new_state

    state = new_state(
        "p4_live",
        "",
        {
            "task_id": "task04_multimodule",
            "source_api": "datetime.utcnow",
            "target_api": "datetime.now(timezone.utc)",
        },
    )
    router = Router(state["tokens"])
    corrector = LLMCorrector(router, TARGET, state["contract"])

    result = run_migration(
        TASK04,
        run_id="p4_live",
        runs_dir=tmp_path / "runs",
        corrector=corrector,
        router=router,
        state=state,
    )

    assert result["metrics"]["outcome"] == "success"
    assert result["metrics"]["m2_pass_rate"] == 100.0
    assert result["metrics"]["m3_tokens"] > 0
    assert state["tokens"]["flash_in"] > 0 and state["tokens"]["pro_in"] > 0
    assert max(corrector.payload_chars) < 12000, "context budget blown (NFR-12)"
    print(
        f"\nlive p4: {result['metrics']['m3_tokens']} tokens, "
        f"${result['metrics']['m3_cost_usd']:.6f}, "
        f"max payload {max(corrector.payload_chars)} chars"
    )
