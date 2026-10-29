"""Hunt 3 — hostile model replies through the real recovery loop.

The loop (:func:`mra.recovery.recover`) drives :class:`LLMCorrector` with a
router whose provider is hostile. The sandbox is replaced by a runner that
keeps reporting the same failure, so every reply gets the full attempt budget.
Each reply must be rejected or fail cleanly, count as an attempt, and leave
the working tree byte-identical (nothing written in or outside the repo).

Two modes, because they parse replies differently: **residual** (task03 with
report.py left unmigrated — the model rewrites one located file) and
**consequence** (task06 after EDIT — the model names a ``FILE:``).

Transport faults (500, malformed JSON, slow reply, ``finish_reason=length``)
go through the real OpenAI SDK against a local HTTP server.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from mra.analysis import call_sites as call_sites_module
from mra.codemods.datetime_utcnow import TARGET, family
from mra.models import ROLES, Endpoint, ProviderError, Router
from mra.models.providers import FakeProvider, OpenAICompatibleProvider
from mra.nodes.correct_node import LLMCorrector
from mra.nodes.edit_node import apply_codemod
from mra.recovery import recover
from tests.hunt.conftest import BLIND, TIER_A, bug

CAP = 3
CONTRACT = {
    "task_id": "hunt",
    "source_api": "datetime.utcnow",
    "target_api": "datetime.now(timezone.utc)",
}

# -- fixtures: a red tree in each mode -----------------------------------------

RESIDUAL_FAILURE = {
    "nodeid": "tests/test_report.py::test_stamp_age_seconds",
    "signature": "residual0000",
    "exc_type": "TypeError",
    "message": "TypeError: can't subtract offset-naive and offset-aware datetimes",
    "file": "src/pkg/report.py",
    "line": 20,
    "trace": "src/pkg/report.py:20: TypeError",
}
CONSEQUENCE_FAILURE = {
    "nodeid": "tests/test_report.py::test_age_days_is_non_negative_int",
    "signature": "consequence0",
    "exc_type": "TypeError",
    "message": "TypeError: can't subtract offset-naive and offset-aware datetimes",
    "file": "src/app/report.py",
    "line": 7,
    "trace": ">       return (clock.now() - config.EPOCH).days\nsrc/app/report.py:7: TypeError",
}


def _residual_repo(root: Path) -> Path:
    work = root / "repo"
    shutil.copytree(TIER_A / "task03_half_migration" / "old", work)
    sites = call_sites_module.find_in_repo(work, family(TARGET))
    apply_codemod(work, {f: s for f, s in sites.items() if f != "src/pkg/report.py"})
    return work


def _consequence_repo(root: Path) -> Path:
    work = root / "repo"
    shutil.copytree(BLIND / "task06_scheduler" / "old", work)
    apply_codemod(work, call_sites_module.find_in_repo(work, family(TARGET)))
    return work


MODES = {
    "residual": (_residual_repo, RESIDUAL_FAILURE, "src/pkg/report.py"),
    "consequence": (_consequence_repo, CONSEQUENCE_FAILURE, "src/app/config.py"),
}


class StuckRunner:
    """The sandbox, minus the sandbox: the same failure every time."""

    def __init__(self, failure: dict[str, Any]) -> None:
        self.failure = failure
        self.calls = 0

    def run(self, repo: Path, **_: Any) -> dict[str, Any]:
        self.calls += 1
        return _report(self.failure)


def _report(failure: dict[str, Any]) -> dict[str, Any]:
    return {"total": 5, "passed": 4, "failed": 1, "errors": 0, "failures": [failure]}


class Trajectory:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, node: str, action: str, **detail: Any) -> None:
        self.events.append({"node": node, "action": action, "detail": detail})


def _tree(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` (the repo's parent), minus git internals."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


def _router(reply: Any) -> Router:
    def answer(messages: list[dict[str, str]], model: str) -> str:
        if "one word" in messages[0]["content"]:
            return "behaviour"
        return reply(messages) if callable(reply) else reply

    return Router(roles={r: [Endpoint(FakeProvider("fake", reply=answer), "m")] for r in ROLES})


def drive(tmp_path: Path, mode: str, router: Router) -> dict[str, Any]:
    """Run the loop to the cap; return what happened and whether the tree moved."""
    make, failure, _ = MODES[mode]
    work = make(tmp_path)
    before = _tree(tmp_path)
    attempts: dict[str, int] = {}
    corrector = LLMCorrector(router, TARGET, CONTRACT)
    error: BaseException | None = None
    result = None
    try:
        result = recover(
            work,
            _report(failure),
            runner=StuckRunner(failure),
            corrector=corrector,
            task_id="hunt",
            trajectory=Trajectory(),
            fix_attempts=attempts,
            max_attempts=CAP,
            context={"call_sites": {"src/app/clock.py": [], "src/app/config.py": []}},
        )
    except Exception as exc:  # noqa: BLE001 - the hunt records it
        error = exc
    after = _tree(tmp_path)
    return {
        "error": error,
        "result": result,
        "attempts": attempts.get(failure["signature"], 0),
        "changed": sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k)),
        "after": after,
        "log": corrector.log,
    }


def assert_clean(outcome: dict[str, Any]) -> None:
    assert outcome["error"] is None, f"escaped the loop: {outcome['error']!r}"
    assert outcome["result"]["outcome"] == "gave_up"
    assert outcome["attempts"] == CAP, f"only {outcome['attempts']}/{CAP} attempts counted"
    assert not outcome["changed"], f"tree changed: {outcome['changed']}"


# -- the replies --------------------------------------------------------------

GOLD_REPORT = (TIER_A / "task03_half_migration" / "gold" / "src/pkg/report.py").read_text()
GOLD_CONFIG = (BLIND / "task06_scheduler" / "gold" / "src/app/config.py").read_text()
OLD_CLOCK = (BLIND / "task06_scheduler" / "old" / "src/app/clock.py").read_text()


def _fence(source: str, file: str | None) -> str:
    return (f"FILE: {file}\n" if file else "") + f"```python\n{source}```\n"


def _truncated(source: str) -> str:
    """A prefix cut at a top-level statement boundary: it still parses."""
    cut = source.index("\ndef stamp_age_seconds") if "stamp_age" in source else len(source) // 2
    return source[:cut] + "\n"


HOSTILE: dict[str, dict[str, str]] = {
    "no_code_block": {
        "residual": "Replace utcnow() with now(timezone.utc) and import timezone.",
        "consequence": "Make EPOCH timezone-aware in config.py.",
    },
    "reasoning_only": {
        "residual": "<think>The fix is to make report.py aware.</think>",
        "consequence": "<think>config.EPOCH is naive; it should carry tzinfo.</think>",
    },
    "reasoning_cut_off": {
        "residual": "<think>Let me look at report.py. The subtraction",
        "consequence": "<think>Let me look at config.py. EPOCH is",
    },
    "empty": {"residual": "", "consequence": ""},
    "whitespace": {"residual": "   \n\n", "consequence": "\n"},
    "syntax_error": {
        "residual": _fence("def broken(:\n    pass\n", None),
        "consequence": _fence("def broken(:\n    pass\n", "src/app/config.py"),
    },
    "truncated_fence": {
        "residual": "```python\n" + GOLD_REPORT[: len(GOLD_REPORT) // 2],
        "consequence": "FILE: src/app/config.py\n```python\n" + GOLD_CONFIG[:40],
    },
    "truncated_parseable_no_fence": {
        "residual": _truncated(GOLD_REPORT),
        "consequence": "FILE: src/app/config.py\n```python\n" + _truncated(GOLD_CONFIG) + "```",
    },
    "test_file": {
        "residual": _fence("def test_x():\n    assert True\n", "tests/test_report.py"),
        "consequence": _fence("def test_x():\n    assert True\n", "tests/test_report.py"),
    },
    "path_traversal": {
        "residual": _fence("X = 1\n", "../../outside.py"),
        "consequence": _fence("X = 1\n", "../../outside.py"),
    },
    "absolute_path": {
        "residual": _fence("X = 1\n", "/tmp/mra_hunt_outside.py"),
        "consequence": _fence("X = 1\n", "/tmp/mra_hunt_outside.py"),
    },
    "outside_scope": {
        "residual": _fence("X = 1\n", "src/pkg/__init__.py"),
        "consequence": _fence("X = 1\n", "src/app/decoys.py"),
    },
    "reintroduce_deprecated": {
        "residual": _fence(GOLD_REPORT + "\n\ndef again():\n    return datetime.utcnow()\n", None),
        "consequence": _fence(OLD_CLOCK, "src/app/clock.py"),
    },
}

# Replies the current code accepts or crashes on; each is a BUGS.md entry.
KNOWN = {
    **{
        (name, "residual"): ("BUG-03", "unparseable reply escapes the loop as ParserSyntaxError")
        for name in ("no_code_block", "syntax_error", "truncated_fence")
    },
    ("reintroduce_deprecated", "residual"): (
        "BUG-06",
        "reversal guard counts net sites: fix one + add one is accepted",
    ),
}


def _case(name: str, mode: str) -> Any:
    marks = [bug(*KNOWN[(name, mode)])] if (name, mode) in KNOWN else []
    return pytest.param(name, mode, marks=marks, id=f"{name}-{mode}")


@pytest.mark.parametrize(
    ("name", "mode"),
    [_case(name, mode) for name in HOSTILE for mode in ("residual", "consequence")],
)
def test_hostile_reply_is_rejected_and_counted(tmp_path: Path, name: str, mode: str) -> None:
    outcome = drive(tmp_path, mode, _router(HOSTILE[name][mode]))
    assert_clean(outcome)
    assert not Path("/tmp/mra_hunt_outside.py").exists()


@bug("BUG-06", "a residual patch that fixes one site and adds utcnow elsewhere is accepted")
def test_net_zero_reintroduction_is_rejected(tmp_path: Path) -> None:
    """Migrate the located site but plant ``utcnow()`` in a new function: still a reversal."""
    planted = GOLD_REPORT + "\n\ndef legacy_stamp():\n    return datetime.utcnow()\n"
    # report.py holds 1 site; the patch removes it and adds 1 -> net zero.
    outcome = drive(tmp_path, "residual", _router(_fence(planted, None)))
    assert "datetime.utcnow()" not in outcome["after"].get("repo/src/pkg/report.py", b"").decode()


def test_correct_patch_still_lands(tmp_path: Path) -> None:
    """Control: the harness is not rejecting everything."""
    outcome = drive(tmp_path, "residual", _router(_fence(GOLD_REPORT, None)))
    assert outcome["after"]["repo/src/pkg/report.py"].decode() == GOLD_REPORT


# -- transport faults through the real SDK -------------------------------------


class _Server:
    """A local OpenAI-compatible endpoint that misbehaves on demand."""

    def __init__(self) -> None:
        self.mode = "ok"
        self.content = ""
        self.delay = 0.0
        self.hits = 0
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802
                server.hits += 1
                self.rfile.read(int(self.headers.get("content-length", 0)))
                if server.delay:
                    time.sleep(server.delay)
                if server.mode == "500":
                    body, status = b'{"error": {"message": "boom"}}', 500
                elif server.mode == "malformed":
                    body, status = b'{"id": "x", "choices": [', 200
                else:
                    body, status = (
                        json.dumps(
                            {
                                "id": "x",
                                "object": "chat.completion",
                                "created": 0,
                                "model": "m",
                                "choices": [
                                    {
                                        "index": 0,
                                        "message": {"role": "assistant", "content": server.content},
                                        "finish_reason": "length"
                                        if server.mode == "length"
                                        else "stop",
                                    }
                                ],
                                "usage": {
                                    "prompt_tokens": 1,
                                    "completion_tokens": 1,
                                    "total_tokens": 2,
                                },
                            }
                        ).encode(),
                        200,
                    )
                try:
                    self.send_response(status)
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def router(self, timeout_s: float = 2.0) -> Router:
        provider = OpenAICompatibleProvider(name="local", base_url=self.url, timeout_s=timeout_s)
        classify = FakeProvider("cls", reply=lambda m, model: "behaviour")
        roles = {r: [Endpoint(provider, "m")] for r in ROLES}
        roles["classify"] = [Endpoint(classify, "m")]
        return Router(roles=roles)


@pytest.fixture
def server() -> Any:
    s = _Server()
    yield s
    s.httpd.shutdown()


@pytest.mark.parametrize("mode", ["residual", "consequence"])
@pytest.mark.parametrize("fault", ["500", "malformed", "slow"])
def test_transport_fault_fails_cleanly(
    tmp_path: Path, server: _Server, fault: str, mode: str
) -> None:
    """A dead endpoint ends in ProviderError (RED 'provider'), bounded in time, tree intact."""
    server.mode = "ok" if fault == "slow" else fault
    server.delay = 4.0 if fault == "slow" else 0.0
    server.content = _fence(GOLD_REPORT, None)
    started = time.perf_counter()
    outcome = drive(tmp_path, mode, server.router(timeout_s=1.0))
    elapsed = time.perf_counter() - started
    assert not outcome["changed"], f"tree changed: {outcome['changed']}"
    assert outcome["attempts"] >= 1, "the failed call was not counted as an attempt"
    assert isinstance(outcome["error"], ProviderError) or outcome["result"] is not None, (
        f"raw {type(outcome['error']).__name__} escaped instead of ProviderError"
    )
    # TRANSIENT_RETRIES=1: at most two tries per call, ~2 x timeout for a dead endpoint.
    assert server.hits <= 2 * CAP, f"{server.hits} requests"
    assert elapsed < 2 * CAP * (1.0 + 4.0) + 10, f"took {elapsed:.1f}s"


def test_finish_reason_length_is_rejected(tmp_path: Path, server: _Server) -> None:
    server.mode = "length"
    server.content = _truncated(GOLD_REPORT)  # cut off by max_tokens, happens to parse
    outcome = drive(tmp_path, "residual", server.router())
    assert not outcome["changed"], f"truncated reply was applied: {outcome['changed']}"
