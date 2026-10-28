"""P3 acceptance: the recovery loop, proved without a paid API key.

The loop and the model are tested separately on purpose. Three of the four
groups below use no LLM at all:

* **deterministic** — a stub corrector that returns the known-correct fix.
  It proves the *state machine*: red tree in, EDIT->TEST(fail)->CORRECT->TEST(pass)
  out, terminating on success. If this passes and the live run fails, the
  problem is the model, not the loop.
* **retry cap** — a corrector that never fixes anything. It proves the ceiling
  fires at exactly ``MAX_FIX_ATTEMPTS`` on one stable signature (NFR-1, FR-9).
* **oracle safety** — a corrector that tries to edit a test file. It proves
  NB-4 is enforced, not merely documented.
* **live** — the real model from ``mra.toml``, skipped unless every role has a
  provider whose key is set. A suite that cannot run without a funded account
  is a suite nobody runs.

The fixture is ``corpus/tierA/task03_half_migration``: |A| = 3 sites, and the
run migrates only two of them, leaving the break the loop has to finish.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mra.analysis import call_sites as call_sites_module
from mra.codemods.datetime_utcnow import TARGET
from mra.models import Router, live_ready, total_tokens
from mra.nodes.correct_node import (
    FAILURE_CLASSES,
    LLMCorrector,
    classify_offline,
    is_test_path,
    locate,
)
from mra.nodes.edit_node import apply_codemod
from mra.recovery import DEFAULT_MAX_FIX_ATTEMPTS
from mra.run import migrate_task
from mra.state import new_state

REPO_ROOT = Path(__file__).resolve().parents[1]
TASK = REPO_ROOT / "corpus" / "tierA" / "task03_half_migration"

#: The half-migration: everything except report.py, which is the file whose
#: naive clock reading then collides with core.py's aware one.
FIRST_BATCH = ("src/pkg/core.py", "src/pkg/audit.py")
BROKEN_FILE = "src/pkg/report.py"
BREAKING_TEST = "tests/test_report.py::test_stamp_age_is_non_negative"

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
    """The known-correct fix: finish the migration the batch left half-done.

    Localizes exactly as the LLM corrector does — same :func:`locate` — then
    applies the deterministic codemod instead of asking a model. That keeps the
    loop mechanics under test while removing every source of nondeterminism.
    """
    located = locate(repo, failure, TARGET)
    if located is None:
        return []
    return apply_codemod(repo, {located["file"]: located["sites"]})


def bad_corrector(repo: Path, failure: dict[str, Any], context: dict[str, Any]) -> list[str]:
    """Claims a fix, changes nothing. The failure — and its signature — survive."""
    return []


def oracle_tampering_corrector(
    repo: Path, failure: dict[str, Any], context: dict[str, Any]
) -> list[str]:
    """Deletes the failing assertion instead of fixing the code. Must be rejected."""
    victim = repo / "tests" / "test_report.py"
    victim.write_text(
        victim.read_text().replace("assert stamp_age_seconds(generated_at) >= 0", "assert True")
    )
    return ["tests/test_report.py"]


def _tree_digest(root: Path) -> str:
    sha = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        sha.update(str(path.relative_to(root)).encode())
        sha.update(path.read_bytes())
    return sha.hexdigest()


def _nodes(trajectory: list[dict[str, Any]]) -> list[str]:
    return [event["node"] for event in trajectory]


@pytest.fixture(scope="session")
def corpus_digest() -> str:
    """Taken before any run, compared after: the corpus must be read-only in practice."""
    return _tree_digest(TASK)


# -- the fixture itself ----------------------------------------------------


def test_half_migration_leaves_exactly_one_site(tmp_path: Path) -> None:
    """No sandbox needed: the fixture's shape is a static property."""
    work = tmp_path / "repo"
    shutil.copytree(TASK / "old", work)
    before = call_sites_module.find_in_repo(work, TARGET)
    assert sorted(before) == ["src/pkg/audit.py", "src/pkg/core.py", "src/pkg/report.py"]

    apply_codemod(work, {f: before[f] for f in FIRST_BATCH})
    after = call_sites_module.find_in_repo(work, TARGET)
    assert sorted(after) == [BROKEN_FILE], "the break must survive in exactly one file"


# -- DETERMINISTIC: the loop mechanics, no LLM -----------------------------


@pytest.fixture(scope="session")
def recovered(tmp_path_factory: pytest.TempPathFactory, corpus_digest: str) -> dict[str, Any]:
    return migrate_task(
        TASK,
        run_id="p3_recovery_stub",
        runs_dir=tmp_path_factory.mktemp("runs"),
        edit_only=FIRST_BATCH,
        corrector=stub_corrector,
    )


@needs_docker
def test_half_migration_starts_red_then_recovers_to_green(recovered: dict[str, Any]) -> None:
    """The headline: a broken half-migration is finished automatically."""
    assert recovered["recovery"] is not None, "the post-edit suite must have been red"
    assert recovered["recovery"]["outcome"] == "success"
    assert recovered["metrics"]["outcome"] == "success"
    assert recovered["metrics"]["recovery_used"] is True
    assert recovered["test_report"]["failed"] == 0
    assert recovered["test_report"]["errors"] == 0


@needs_docker
def test_the_break_was_the_designed_one(recovered: dict[str, Any]) -> None:
    """Recovery from the wrong failure would prove nothing about this fixture."""
    first = recovered["recovery"]["corrections"][0]
    correct_events = [
        e for e in recovered["trajectory"] if e["node"] == "CORRECT" and e["detail"].get("exc_type")
    ]
    assert correct_events[0]["detail"]["exc_type"] == "TypeError"
    assert BREAKING_TEST in correct_events[0]["action"]
    assert first["changed"] == [BROKEN_FILE]


@needs_docker
def test_trajectory_shows_edit_test_correct_test(recovered: dict[str, Any]) -> None:
    """FR-7's audit trail: the sequence, not just the outcome (SRS §4.1)."""
    nodes = _nodes(recovered["trajectory"])
    # MAP, TEST(pre), EDIT x3 (snapshot, batch restriction, codemod), TEST(post, red),
    # CORRECT, TEST(recovery, green), CORRECT(summary).
    assert nodes == ["MAP", "TEST", "EDIT", "EDIT", "EDIT", "TEST", "CORRECT", "TEST", "CORRECT"]
    post, recovery_test = [e for e in recovered["trajectory"] if e["node"] == "TEST"][1:3]
    assert post["detail"]["failed"] == 1, "the post-edit suite must be red"
    assert recovery_test["detail"]["failed"] == 0, "the recovery suite must be green"
    assert recovered["trajectory"][-1]["detail"]["flagged"] is False


@needs_docker
def test_recovered_tree_is_fully_migrated_and_scores_perfectly(
    recovered: dict[str, Any],
) -> None:
    """M1 and M2 both at 100: the loop finished the migration, it did not mask it."""
    assert call_sites_module.find_in_repo(recovered["repo"], TARGET) == {}
    assert recovered["metrics"]["m2_pass_rate"] == 100.0
    assert recovered["metrics"]["m2_regressions"] == 0
    assert recovered["metrics"]["m1_recall"] == 100.0
    assert recovered["metrics"]["m1_precision"] == 100.0


@needs_docker
def test_recovery_patch_is_the_whole_migration(recovered: dict[str, Any]) -> None:
    """FR-10: the deliverable covers the corrected file too, not just the batch."""
    patch = recovered["patch"]
    for file in (*FIRST_BATCH, BROKEN_FILE):
        assert f"b/{file}" in patch, f"{file} missing from the patch"
    # The new name lands in its sorted slot, matching gold/ (the old prepended
    # `timezone, datetime` order was the defect ruff's I001 flagged).
    assert "+from datetime import datetime, timezone" in patch


# -- RETRY CAP: give up at exactly MAX_FIX_ATTEMPTS, no LLM ----------------


@pytest.fixture(scope="session")
def gave_up(tmp_path_factory: pytest.TempPathFactory, corpus_digest: str) -> dict[str, Any]:
    return migrate_task(
        TASK,
        run_id="p3_recovery_cap",
        runs_dir=tmp_path_factory.mktemp("runs"),
        edit_only=FIRST_BATCH,
        corrector=bad_corrector,
    )


@needs_docker
def test_unfixable_failure_stops_at_the_cap_and_is_flagged(gave_up: dict[str, Any]) -> None:
    """FR-9's second stop condition. Without it the loop never terminates."""
    recovery = gave_up["recovery"]
    assert recovery["outcome"] == "gave_up"
    assert recovery["flagged"] is True
    assert recovery["rounds"] == DEFAULT_MAX_FIX_ATTEMPTS
    assert gave_up["metrics"]["outcome"] == "gave_up"
    assert gave_up["trajectory"][-1]["detail"]["flagged"] is True
    assert "gave up" in gave_up["trajectory"][-1]["action"]


@needs_docker
def test_the_cap_counts_one_stable_signature(gave_up: dict[str, Any]) -> None:
    """The signature must survive re-running the same break (P0's normalization)."""
    signatures = {c["signature"] for c in gave_up["recovery"]["corrections"]}
    assert len(signatures) == 1, "the same break must hash the same every round"
    attempts = [c["attempt"] for c in gave_up["recovery"]["corrections"]]
    assert attempts == list(range(1, DEFAULT_MAX_FIX_ATTEMPTS + 1))


@needs_docker
def test_giving_up_still_scores_the_partial_migration(gave_up: dict[str, Any]) -> None:
    """2 of 3 sites migrated, and nothing wrong touched: recall down, precision intact."""
    assert gave_up["metrics"]["m1_recall"] == pytest.approx(200 / 3)
    assert gave_up["metrics"]["m1_precision"] == 100.0
    assert gave_up["metrics"]["m2_regressions"] == 1


@needs_docker
def test_custom_cap_is_honoured(tmp_path: Path) -> None:
    """The ceiling is configurable (MRA_MAX_FIX_ATTEMPTS), not hard-coded at 3."""
    result = migrate_task(
        TASK,
        run_id="p3_cap_one",
        runs_dir=tmp_path / "runs",
        edit_only=FIRST_BATCH,
        corrector=bad_corrector,
        max_attempts=1,
    )
    assert result["recovery"]["rounds"] == 1
    assert result["recovery"]["outcome"] == "gave_up"


# -- NB-4: the oracle is off limits ----------------------------------------


@needs_docker
def test_correct_may_not_edit_the_test_oracle(tmp_path: Path) -> None:
    """Golden rule 1. A patch that edits tests is reverted, not just logged."""
    result = migrate_task(
        TASK,
        run_id="p3_oracle",
        runs_dir=tmp_path / "runs",
        edit_only=FIRST_BATCH,
        corrector=oracle_tampering_corrector,
        max_attempts=2,
    )
    assert result["recovery"]["outcome"] == "gave_up"
    assert all(c["changed"] == [] for c in result["recovery"]["corrections"])
    assert all(c["rejected"] == ["tests/test_report.py"] for c in result["recovery"]["corrections"])
    # Reverted on disk, not merely refused in the report.
    original = (TASK / "old" / "tests" / "test_report.py").read_text()
    assert (result["repo"] / "tests" / "test_report.py").read_text() == original
    assert "tests/" not in result["patch"]


@needs_docker
def test_recovery_never_touches_test_files_or_the_corpus(
    recovered: dict[str, Any], gave_up: dict[str, Any], corpus_digest: str
) -> None:
    """NB-4 on the happy path, plus: edits land on the copy, never on corpus/."""
    for result in (recovered, gave_up):
        touched = [f for c in result["recovery"]["corrections"] for f in c["changed"]]
        assert not any(is_test_path(f) for f in touched)
        for name in ("test_core.py", "test_report.py", "test_audit.py"):
            assert (result["repo"] / "tests" / name).read_text() == (
                TASK / "old" / "tests" / name
            ).read_text()
    assert _tree_digest(TASK) == corpus_digest


# -- classification and localization, no network ---------------------------


def test_the_half_migration_failure_classifies_as_a_behaviour_break() -> None:
    """docs/04 §2.5: a bare TypeError with no signature change is behavioural."""
    failure = {
        "exc_type": "TypeError",
        "message": "can't subtract offset-naive and offset-aware datetimes",
    }
    assert classify_offline(failure) == "behaviour"
    assert classify_offline({"exc_type": "ImportError", "message": "no name"}) == "import"
    assert (
        classify_offline({"exc_type": "TypeError", "message": "got an unexpected keyword argument"})
        == "signature"
    )
    assert set(FAILURE_CLASSES) >= {"import", "signature", "behaviour", "assertion"}


def test_locate_uses_the_trace_and_the_graph_not_a_guess(tmp_path: Path) -> None:
    """The trace names report.py; the slice reports who imports it."""
    work = tmp_path / "repo"
    shutil.copytree(TASK / "old", work)
    before = call_sites_module.find_in_repo(work, TARGET)
    apply_codemod(work, {f: before[f] for f in FIRST_BATCH})

    located = locate(
        work,
        {
            "file": BROKEN_FILE,
            "trace": "src/pkg/report.py:20: TypeError",
            "exc_type": "TypeError",
        },
        TARGET,
    )
    assert located is not None
    assert located["file"] == BROKEN_FILE
    assert located["hinted_by_trace"] is True
    assert located["importers"] == ["tests/test_report.py"]
    assert located["imports"] == ["src/pkg/core.py"]
    assert [s["line"] for s in located["sites"]] == [20]


def test_locate_returns_none_once_the_migration_is_complete(tmp_path: Path) -> None:
    """Nothing left to migrate means this node cannot be the fix. Say so."""
    work = tmp_path / "repo"
    shutil.copytree(TASK / "gold", work)
    assert locate(work, {"file": BROKEN_FILE, "trace": ""}, TARGET) is None


def test_locate_never_proposes_a_test_file(tmp_path: Path) -> None:
    """NB-4 at the localization step, before a model is ever asked for a patch."""
    work = tmp_path / "repo"
    shutil.copytree(TASK / "old", work)
    (work / "tests" / "test_clock.py").write_text(
        "from datetime import datetime\n\n\ndef test_x() -> None:\n"
        "    assert datetime.utcnow() is not None\n"
    )
    for _ in range(4):
        located = locate(work, {"file": "tests/test_clock.py", "trace": ""}, TARGET)
        if located is None:
            break
        assert not is_test_path(located["file"])
        apply_codemod(work, {located["file"]: located["sites"]})
    assert "utcnow" in (work / "tests" / "test_clock.py").read_text()


def test_reasoning_model_reply_applies_only_the_final_patch(tmp_path: Path) -> None:
    """A <think> block with its own draft code, then the answer: only the answer lands."""
    from mra.models import ROLES, Endpoint
    from mra.models.providers import FakeProvider

    work = tmp_path / "repo"
    shutil.copytree(TASK / "old", work)
    before = call_sites_module.find_in_repo(work, TARGET)
    apply_codemod(work, {f: before[f] for f in FIRST_BATCH})
    gold = (TASK / "gold" / BROKEN_FILE).read_text()

    def reply(messages: list[dict[str, str]], model: str) -> str:
        if "one word" in messages[0]["content"]:
            return "<think>could be import, or signature... no.</think>\nbehaviour"
        return (
            "<think>The trace points at report.py. Draft:\n"
            "```python\nDRAFT = 'never applied'\n```\n"
            "No, keep the docstrings.</think>\n"
            f"Here is the corrected file:\n```python\n{gold}```\n"
        )

    fake = FakeProvider("reasoner", reply=reply)
    router = Router(roles={role: [Endpoint(fake, "r1")] for role in ROLES})
    corrector = LLMCorrector(router, TARGET, {"source_api": "a", "target_api": "b"})
    failure = {
        "file": BROKEN_FILE,
        "trace": "src/pkg/report.py:20: TypeError",
        "exc_type": "TypeError",
        "message": "can't subtract offset-naive and offset-aware datetimes",
    }
    assert corrector(work, failure, {}) == [BROKEN_FILE]
    assert (work / BROKEN_FILE).read_text() == gold
    assert corrector.log[-1]["class"] == "behaviour"  # not "import" from the reasoning


@pytest.mark.parametrize(
    ("raw", "answer"),
    [
        ("<think>a\nb</think>\n\nok", "ok"),
        ("<THINKING>x</THINKING>ok", "ok"),
        ("implicit opener, then</think>ok", "ok"),
        ("<think>cut off by max_tokens", ""),
        ("plain answer", "plain answer"),
    ],
)
def test_final_answer_strips_reasoning(raw: str, answer: str) -> None:
    from mra.models.router import final_answer

    assert final_answer(raw) == answer


# -- the router ------------------------------------------------------------


def test_router_is_unavailable_without_a_key_instead_of_crashing() -> None:
    """No usable provider must mean "skip the live path", never an explosion."""
    router = Router(roles={})
    assert router.available is False
    with pytest.raises(RuntimeError, match="no provider configured"):
        router.complete("classify", "s", "u")


def test_router_bills_each_tier_separately() -> None:
    """M3 needs per-tier counts: routing everything to V4-Pro must be visible."""
    tokens = new_state("r", "p", {"task_id": "t"})["tokens"]
    router = Router(tokens, roles={})
    router._bill("recover", "strong-model", 1000, 200)
    router._bill("classify", "cheap-model", 500, 10)
    assert tokens == {
        "pro_in": 1000,
        "pro_out": 200,
        "flash_in": 500,
        "flash_out": 10,
        "tool_calls": 2,
    }
    assert total_tokens(tokens) == 1710
    assert router.cost_usd() == pytest.approx(
        1000 * 0.66e-6 + 200 * 1.98e-6 + 500 * 0.22e-6 + 10 * 0.66e-6
    )


# -- LIVE: the mra.toml model, skipped without its key ---------------------


@needs_docker
@pytest.mark.live
@needs_key
def test_live_llm_recovers_the_half_migration(tmp_path: Path) -> None:
    """FR-7 end to end with the real model. Reports its own token cost."""
    state = new_state(
        "p3_live",
        str(tmp_path),
        {
            "task_id": "task03_half_migration",
            "source_api": "datetime.utcnow",
            "target_api": "datetime.now(timezone.utc)",
        },
    )
    router = Router(state["tokens"])
    corrector = LLMCorrector(router, TARGET, state["contract"])

    result = migrate_task(
        TASK,
        run_id="p3_recovery_live",
        runs_dir=tmp_path / "runs",
        edit_only=FIRST_BATCH,
        corrector=corrector,
        state=state,
    )

    assert result["recovery"]["outcome"] == "success", "live model failed to recover"
    assert result["recovery"]["rounds"] <= DEFAULT_MAX_FIX_ATTEMPTS
    assert result["metrics"]["m2_pass_rate"] == 100.0
    assert result["metrics"]["m2_regressions"] == 0
    assert call_sites_module.find_in_repo(result["repo"], TARGET) == {}

    # M3: tokens were actually logged, split across both tiers (FR-8).
    assert result["metrics"]["m3_tokens"] > 0
    assert state["tokens"]["flash_in"] > 0, "classification should use the cheap model"
    assert state["tokens"]["pro_in"] > 0, "the patch should use the strong model"
    assert result["metrics"]["m3_cost_usd"] > 0
    # NB-4 holds for the model too, not just for the stubs.
    assert not any(is_test_path(c["file"]) for c in corrector.log if c["file"])
    print(
        f"\nlive recovery: {result['recovery']['rounds']} round(s), "
        f"{result['metrics']['m3_tokens']} tokens, "
        f"${result['metrics']['m3_cost_usd']:.6f}"
    )
