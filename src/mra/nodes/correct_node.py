"""CORRECT node: turn one test failure back into a green tree (FR-7).

The node reads a single entry from the ``mra:test_report`` the sandbox
produced (SRS §4.3) and runs the four steps of docs/04 §2.5:

    classify (V4-Flash)  ->  locate (analyzer + dep graph)
                         ->  patch (V4-Pro)  ->  apply

Two rules shape the whole module. **NB-4**: a corrective patch may never touch
a test file — the suite is the oracle, and repairing the oracle is how an agent
fakes a green run — so test paths are filtered out at localization and refused
again at apply. **NFR-12**: the patch prompt gets the failing file, the trace,
the contract and the graph slice around that file, and nothing else. Sending
the repo is how a long-horizon run runs out of context and out of budget.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import libcst as cst

from mra.analysis import call_sites as call_sites_module
from mra.analysis import dep_graph as dep_graph_module
from mra.analysis.call_sites import is_test_path
from mra.memory import edit_context
from mra.memory.experience import format_hint
from mra.models import Router, TruncatedReply

#: docs/04 §2.5 taxonomy. "non_fixable" is the class that ends the loop.
FAILURE_CLASSES = ("import", "signature", "behaviour", "assertion", "non_fixable")

#: How an exception maps onto the taxonomy, checked in order. A bare
#: ``TypeError`` is deliberately NOT a signature break: the half-migration's
#: "can't subtract offset-naive and offset-aware" raises TypeError but no
#: signature moved, and its fix is the semantic transform — a behaviour break
#: in docs/04 §2.5 terms. Only argument-shaped TypeErrors are signature breaks.
_CLASS_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("import", ("ImportError", "ModuleNotFoundError")),
    (
        "signature",
        (
            "unexpected keyword argument",
            "positional argument",
            "missing 1 required",
            "takes no arguments",
        ),
    ),
    ("assertion", ("AssertionError",)),
)

_PY_PATH = re.compile(r"([\w./-]+\.py)")
_CODE_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)

CLASSIFY_SYSTEM = (
    "You triage Python test failures during a library migration. "
    "Answer with exactly one word from this list and nothing else: "
    + ", ".join(FAILURE_CLASSES)
    + "."
)

PATCH_SYSTEM = (
    "You finish partially applied Python migrations. You are given ONE source "
    "file that still uses the old API, the failure it caused, and the migration "
    "contract. Rewrite that one file so the contract holds everywhere in it.\n"
    "Rules:\n"
    "- Change only what the contract requires. Keep all other code, comments, "
    "docstrings, formatting and public behaviour byte-identical.\n"
    "- Add any import the new API needs.\n"
    "- Never modify, add or delete tests.\n"
    "- Reply with the complete corrected file inside one ```python fence, and "
    "no prose before or after it."
)

CONSEQUENCE_SYSTEM = (
    "You finish Python migrations. The migration has already been applied at "
    "every call site of the old API, yet the test suite still fails: code that "
    "the migrated values flow into was not adapted to the new contract. You are "
    "given the failure, the contract, and the only files you may edit.\n"
    "Rules:\n"
    "- Fix the root cause so the new contract holds everywhere. Fix a value where "
    "it is defined, not at each place it is used.\n"
    "- Never undo the migration: never reintroduce the old API and never add a "
    "forbidden pattern.\n"
    "- Edit exactly one of the listed files. Keep all other code, comments, "
    "docstrings and formatting byte-identical, and add any import the change needs.\n"
    "- Never modify, add or delete tests.\n"
    "- Reply with one line `FILE: <path>` naming the file, then the complete "
    "corrected file inside one ```python fence, and no other prose."
)
_FILE_PATCH = re.compile(r"FILE:\s*`?([^\s`]+)`?\s*\n+```(?:python|py)?\s*\n(.*?)```", re.S)


# -- (a) classify ----------------------------------------------------------


def classify_offline(failure: dict[str, Any]) -> str:
    """Taxonomy class from the exception alone — the fallback when no LLM is available.

    Deliberately crude. It exists so the loop still classifies when the key is
    absent, and so the LLM has a defined answer to be compared against.
    """
    blob = f"{failure.get('exc_type', '')}: {failure.get('message', '')}"
    for label, needles in _CLASS_HINTS:
        if any(needle in blob for needle in needles):
            return label
    return "behaviour"


def classify(failure: dict[str, Any], router: Router | None = None) -> str:
    """Classify one failure into the docs/04 §2.5 taxonomy (V4-Flash)."""
    if router is None or not router.available:
        return classify_offline(failure)
    prompt = (
        f"exception: {failure.get('exc_type', '')}\n"
        f"message: {failure.get('message', '')}\n"
        f"test: {failure.get('nodeid', '')}\n"
        f"trace:\n{str(failure.get('trace', ''))[:1500]}"
    )
    answer = router.complete("classify", CLASSIFY_SYSTEM, prompt).strip().lower()
    for label in FAILURE_CLASSES:
        if label in answer:
            return label
    return classify_offline(failure)


# -- (b) locate ------------------------------------------------------------


def _hinted_files(failure: dict[str, Any]) -> set[str]:
    """Repo-relative .py paths the failure points at: its crash site and its trace."""
    blob = f"{failure.get('file', '')}\n{failure.get('trace', '')}"
    return {match for match in _PY_PATH.findall(blob) if not is_test_path(match)}


def locate(
    repo: Path | str,
    failure: dict[str, Any],
    target: str,
    dep_graph: Any = None,
) -> dict[str, Any] | None:
    """Map a failure onto the source file that still holds an unmigrated call site.

    Re-runs the analyzer over the *current* tree, so "what is left to migrate"
    is measured rather than remembered — the half-migrated files have already
    dropped out of the result. The failure's own crash path and trace pick
    which of the remaining files to repair first; the dependency graph supplies
    the slice of neighbours that goes into the patch prompt (NFR-12).

    Returns ``None`` when nothing is left to migrate, which means the failure
    is not a half-migration and this node cannot fix it.
    """
    repo = Path(repo)
    from mra.codemods.datetime_utcnow import family

    remaining = call_sites_module.find_in_repo(repo, family(target))
    candidates = {path: sites for path, sites in remaining.items() if not is_test_path(path)}
    if not candidates:
        return None

    hinted = _hinted_files(failure) & candidates.keys()
    chosen = sorted(hinted)[0] if hinted else sorted(candidates)[0]

    graph = dep_graph if dep_graph is not None else dep_graph_module.build(repo)
    return {
        "file": chosen,
        "source": (repo / chosen).read_text(),
        "sites": candidates[chosen],
        # Who breaks if this file's contract moves, and what it depends on.
        "importers": sorted(graph.predecessors(chosen)) if graph.has_node(chosen) else [],
        "imports": sorted(graph.successors(chosen)) if graph.has_node(chosen) else [],
        "hinted_by_trace": bool(hinted),
        "remaining_files": sorted(candidates),
    }


def consequence_scope(
    repo: Path | str, failure: dict[str, Any], migrated: set[str], dep_graph: Any = None
) -> list[str]:
    """Files a consequence repair may edit, when :func:`locate` found no residual site.

    The non-test files the failure's trace names, plus their dependency-graph
    neighbours that are migrated files or import one: the break is downstream
    of the migration, so the fix lives where a migrated value is defined or
    consumed. Never a test file (NB-4).
    """
    repo = Path(repo)
    graph = dep_graph if dep_graph is not None else dep_graph_module.build(repo)
    traced = {f for f in _hinted_files(failure) if (repo / f).is_file()}

    def touches_migration(node: str) -> bool:
        return node in migrated or any(n in migrated for n in graph.successors(node))

    neighbours = {
        n
        for f in traced
        if graph.has_node(f)
        for n in (*graph.successors(f), *graph.predecessors(f))
        if touches_migration(n)
    }
    return sorted(f for f in traced | neighbours if not is_test_path(f))


# -- (c) generate ----------------------------------------------------------


def patch_prompt(
    failure: dict[str, Any],
    located: dict[str, Any],
    contract: dict[str, Any],
    klass: str,
    summary: str = "",
    hints: list[str] | None = None,
) -> str:
    """The whole context a corrective edit gets. Nothing else is sent (NFR-12).

    Assembled by :mod:`mra.memory`, which caps every component that would
    otherwise grow with the repo — the neighbour list, the trace and the
    rolling summary — so the payload tracks the file being fixed, not the
    number of files around it.
    """
    return edit_context(failure, located, contract, klass, summary, hints)


def extract_source(reply: str) -> str:
    """Pull the corrected file out of the model's reply and prove it parses.

    A patch that does not parse is worse than no patch: it turns a semantic
    failure into a collection error and hides the original break.
    """
    fences = _CODE_FENCE.findall(reply)
    # The last fence: any earlier one is a draft or quoted code, not the answer.
    source = (fences[-1] if fences else reply).strip() + "\n"
    cst.parse_module(source)  # raises ParserSyntaxError on garbage
    return source


def consequence_prompt(
    failure: dict[str, Any],
    sources: dict[str, str],
    contract: dict[str, Any],
    klass: str,
    forbidden: list[str],
    summary: str = "",
) -> str:
    """The whole context a consequence repair gets: the trace and the scoped files (NFR-12)."""
    from mra.memory import SUMMARY_MAX_CHARS, TRACE_MAX_CHARS

    return "\n".join(
        [
            f"# migration contract: {contract.get('source_api')} -> {contract.get('target_api')}",
            f"# forbidden patterns (regex) your edit may not add: {forbidden}",
            f"# failure class: {klass}",
            f"# failing test: {failure.get('nodeid')}",
            f"# exception: {failure.get('exc_type')}: {failure.get('message')}",
            "",
            "# progress so far",
            f"# {summary[:SUMMARY_MAX_CHARS]}" if summary else "# (first correction of this run)",
            "",
            "# trace",
            str(failure.get("trace", ""))[:TRACE_MAX_CHARS],
            "",
            "# files you may edit (exactly one)",
            *(f"FILE: {path}\n```python\n{source}```" for path, source in sources.items()),
        ]
    )


def extract_patch(reply: str) -> tuple[str, str]:
    """``(file, source)`` from a ``FILE: <path>`` + fence reply; the source must parse."""
    matches = _FILE_PATCH.findall(reply)
    if not matches:
        raise ValueError("no `FILE: <path>` followed by a python fence")
    file, source = matches[-1]  # the last one: earlier ones are drafts
    source = source.strip() + "\n"
    cst.parse_module(source)
    return file, source


def reversal(
    repo: Path | str, relative: str, source: str, target: str, forbidden: list[str]
) -> str | None:
    """Why ``source`` would reverse the migration in ``relative``, or None if it would not.

    Only what the patch *adds* counts, so a pattern the file already held does
    not block it. The source API is re-scanned with the analyzer over the whole
    repo, the one resolver, with the patch written in and then restored.
    """
    from mra.codemods.datetime_utcnow import family

    path = Path(repo) / relative
    before = path.read_bytes()
    old = before.decode("utf-8", errors="surrogateescape")
    for pattern in forbidden:
        if len(re.findall(pattern, source)) > len(re.findall(pattern, old)):
            return f"adds forbidden pattern {pattern!r}"

    def residual() -> int:
        return len(call_sites_module.find_in_repo(repo, family(target)).get(relative, []))

    sites = residual()
    try:
        path.write_text(source)
        if residual() > sites:
            return f"reintroduces the source API ({target}) in {relative}"
    finally:
        path.write_bytes(before)
    return None


def last_rejection(corrector: Any) -> str | None:
    """The reason the corrector's most recent patch was rejected, if it was."""
    log = getattr(corrector, "log", None)
    return log[-1].get("rejected") if log else None


#: The trajectory action of a truncation retry, on either execution path.
RETRY_ACTION = "retried a reply cut off by max_tokens with a larger limit"


def model_calls(corrector: Any) -> list[dict[str, Any]]:
    """The corrector's router call log, or [] for a corrector that asks no model."""
    return getattr(getattr(corrector, "router", None), "calls", [])


def retries(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Truncation retries (BUG-05) among ``calls``: each is its own step and spend."""
    return [
        {"retry": c["retry"], "tokens": c["tokens_in"] + c["tokens_out"]}
        for c in calls
        if c.get("retry")
    ]


def corrective_patch(
    router: Router,
    failure: dict[str, Any],
    located: dict[str, Any],
    contract: dict[str, Any],
    klass: str,
    summary: str = "",
    hints: list[str] | None = None,
) -> str:
    """Ask V4-Pro for the corrected file (whole-file, libcst-validated)."""
    reply = router.complete(
        "recover",
        PATCH_SYSTEM,
        patch_prompt(failure, located, contract, klass, summary, hints),
        complete_only=True,
    )
    return extract_source(reply)


# -- (d) apply -------------------------------------------------------------


def apply_source(repo: Path | str, relative: str, source: str) -> list[str]:
    """Write a corrected file, refusing test paths and no-op writes."""
    if is_test_path(relative):
        raise PermissionError(f"NB-4: CORRECT may not edit the test oracle ({relative})")
    path = Path(repo) / relative
    if path.read_text() == source:
        return []
    path.write_text(source)
    return [relative]


class LLMCorrector:
    """The CORRECT node as a corrector callable, for :func:`mra.recovery.recover`.

    One call = one repaired file. The loop re-tests after every call, so a
    migration left half-done across several files converges one file per round
    instead of being guessed at in one shot.

    Two modes. **residual**: a file still holds an unmigrated call site, and
    that file is rewritten. **consequence** (v0.3.0): no residual site is left,
    so the break is downstream of a correct migration; the model picks one file
    from :func:`consequence_scope`. In both, a patch that :func:`reversal` flags
    is rejected unapplied, and the attempt it spent still counts.
    """

    def __init__(
        self, router: Router, target: str, contract: dict[str, Any], experience: Any = None
    ) -> None:
        from mra.codemods.datetime_utcnow import FORBIDDEN_PATTERNS, TARGET

        self.router = router
        self.target = target
        self.contract = contract
        self.forbidden: list[str] = contract.get(
            "forbidden_patterns", list(FORBIDDEN_PATTERNS) if target == TARGET else []
        )
        #: Opt-in :class:`mra.memory.experience.ExperienceStore`; None = no hints.
        self.experience = experience
        #: What each round decided, for the trajectory.
        self.log: list[dict[str, Any]] = []
        #: Size of every prompt sent, so the context budget is measurable
        #: rather than asserted (NFR-12, M3).
        self.payload_chars: list[int] = []

    def __call__(self, repo: Path, failure: dict[str, Any], context: dict[str, Any]) -> list[str]:
        klass = classify(failure, self.router)
        if klass == "non_fixable":
            self.log.append({"class": klass, "file": None, "reason": "non_fixable"})
            return []
        located = locate(repo, failure, self.target, dep_graph=context.get("graph"))
        if located is None:
            return self._consequence(repo, failure, context, klass)
        summary = context.get("summary", "")
        hints = (
            []
            if self.experience is None
            else [
                format_hint(fix)
                for fix in self.experience.hints(
                    classify_offline(failure), failure.get("message", ""), self.contract
                )
            ]
        )
        self.payload_chars.append(
            len(patch_prompt(failure, located, self.contract, klass, summary, hints))
        )
        try:
            source = corrective_patch(
                self.router, failure, located, self.contract, klass, summary, hints
            )
        except TruncatedReply:
            return self._reject(klass, located["file"], "residual", "truncated reply")
        reason = reversal(repo, located["file"], source, self.target, self.forbidden)
        if reason:
            return self._reject(klass, located["file"], "residual", reason)
        changed = apply_source(repo, located["file"], source)
        self.log.append(
            {
                "class": klass,
                "mode": "residual",
                "file": located["file"],
                "hinted_by_trace": located["hinted_by_trace"],
                "memory_hints": len(hints),
                "changed": changed,
            }
        )
        return changed

    def _consequence(
        self, repo: Path, failure: dict[str, Any], context: dict[str, Any], klass: str
    ) -> list[str]:
        """Repair a break downstream of a complete migration (no residual call site)."""
        scope = consequence_scope(
            repo, failure, set(context.get("call_sites") or {}), context.get("graph")
        )
        if not scope:
            return self._reject(klass, None, "consequence", "no editable file in the trace")
        prompt = consequence_prompt(
            failure,
            {f: (repo / f).read_text() for f in scope},
            self.contract,
            klass,
            self.forbidden,
            context.get("summary", ""),
        )
        self.payload_chars.append(len(prompt))
        try:
            reply = self.router.complete("recover", CONSEQUENCE_SYSTEM, prompt, complete_only=True)
        except TruncatedReply:
            return self._reject(klass, None, "consequence", "truncated reply")
        try:
            file, source = extract_patch(reply)
        except (ValueError, cst.ParserSyntaxError) as exc:
            return self._reject(klass, None, "consequence", f"unusable reply: {exc}")
        if file not in scope:
            return self._reject(klass, file, "consequence", f"{file} is outside scope {scope}")
        reason = reversal(repo, file, source, self.target, self.forbidden)
        if reason:
            return self._reject(klass, file, "consequence", reason)
        changed = apply_source(repo, file, source)
        self.log.append(
            {
                "class": klass,
                "mode": "consequence",
                "file": file,
                "scope": scope,
                "changed": changed,
            }
        )
        return changed

    def _reject(self, klass: str, file: str | None, mode: str, reason: str) -> list[str]:
        """Record a patch that was not applied. The loop has already counted the attempt."""
        self.log.append(
            {"class": klass, "mode": mode, "file": file, "rejected": reason, "changed": []}
        )
        return []


def make_correct_node(
    corrector: Any,
    router: Router | None = None,
    rules: list[dict[str, Any]] | tuple = (),
    target: str | None = None,
):
    """Bind a corrector and return the node LangGraph calls.

    One visit repairs one failure. The node owns the two invariants the loop
    cannot delegate: the per-signature attempt counter (NFR-1), and the NB-4
    guard that reverts a patch which touched the test oracle before it can be
    tested against it.

    ``rules`` are promoted skills (:mod:`mra.skills`), tried in order before the
    corrector; the first that changes the located file is the repair, and its id
    goes into the note. Empty — the default — means the corrector always runs.
    """
    from mra.codemods.datetime_utcnow import TARGET
    from mra.memory import summarize
    from mra.sandbox import changed_paths, rollback, snapshot
    from mra.skills import apply_rule, matching

    target = target or TARGET

    def correct_node(state: dict[str, Any]) -> dict[str, Any]:
        report = state["last_test_report"]
        attempts = dict(state.get("fix_attempts") or {})
        cap = _cap()
        failure = next(
            (f for f in report["failures"] if attempts.get(f["signature"], 0) < cap), None
        )
        if failure is None:  # pragma: no cover - the router routes to give_up first
            return {"note": {"action": "no failure left with attempts to spend", "detail": {}}}

        signature = failure["signature"]
        attempts[signature] = attempts.get(signature, 0) + 1
        repo = Path(state["repo_path"])
        # A rule repair makes no model call at all, the rolling summary included.
        summary = state.get("summary", "")

        base_sha = snapshot(repo, f"pre-correction ({signature})")
        fired, changed = None, []
        for rule in matching(list(rules), classify_offline(failure), state.get("contract") or {}):
            located = locate(repo, failure, target)
            if located and (changed := apply_rule(repo, located["file"], rule["rule"])):
                fired = rule["id"]
                break
        retried: list[dict[str, Any]] = []
        if fired is None:
            summary = summarize(state, router)
            seen = len(model_calls(corrector))
            changed = corrector(
                repo,
                failure,
                {
                    "call_sites": state.get("call_sites") or {},
                    "dep_graph": state.get("dep_graph") or {},
                    "contract": state.get("contract") or {},
                    "summary": summary,
                },
            )
            retried = retries(model_calls(corrector)[seen:])

        tampered = [p for p in changed_paths(repo, base_sha) if is_test_path(p)]
        if tampered:
            # Golden rule 1: revert first, report second.
            rollback(repo, base_sha)
            return {
                "fix_attempts": attempts,
                "summary": summary,
                "note": {
                    "action": "rejected a patch that edited the test oracle (NB-4)",
                    "detail": {
                        "signature": signature,
                        "attempt": attempts[signature],
                        "rejected": tampered,
                        "changed": [],
                        "retries": retried,
                    },
                },
            }

        sha = snapshot(repo, f"correction {attempts[signature]} for {signature}")
        status = dict(state.get("file_status") or {})
        for file in changed:
            status[file] = "migrated"
        return {
            "fix_attempts": attempts,
            "file_status": status,
            "summary": summary,
            "note": {
                "action": f"attempt {attempts[signature]}/{cap} on {failure['nodeid']}"
                + (f" via promoted rule {fired}" if fired else ""),
                "detail": {
                    "rule": fired,
                    "signature": signature,
                    "attempt": attempts[signature],
                    "exc_type": failure.get("exc_type"),
                    "changed": changed,
                    "sha": sha,
                    # Store and lookup key on the offline class: stable across runs.
                    "failure_class": classify_offline(failure),
                    "message": failure.get("message", ""),
                    "retries": retried,
                    **(
                        {"rejected": reason}
                        if fired is None and (reason := last_rejection(corrector))
                        else {}
                    ),
                },
            },
        }

    return correct_node


def _cap() -> int:
    from mra.recovery.loop import DEFAULT_MAX_FIX_ATTEMPTS

    return int(os.environ.get("MRA_MAX_FIX_ATTEMPTS", str(DEFAULT_MAX_FIX_ATTEMPTS)))
