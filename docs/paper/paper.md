---
title: "Dependency-Ordered, Self-Correcting Codebase Migration: An Agent and a Controlled Benchmark"
author: "TODO — author list"
date: "TODO"
---

<!--
  P5 paper draft.

  PROVENANCE RULE: every number in this document must carry an HTML comment
  naming the file and the cell it came from. Nothing is typed from memory.
  A SOURCE comment covers every line above it, back to the previous SOURCE
  comment or the nearest heading — so a claim sentence and the table it
  introduces share one pointer. That rule is what makes the coverage check
  mechanical: no numeric line in §7 may sit in a span that ends without one.
  The two sources are:
    - runs/benchmark/results.md          (generated 2026-09-21T05:49:48Z)
    - runs/benchmark/RESULTS_SUMMARY.md  (same source results.json)
  Regenerate with `python -m mra.benchmark` and re-check §7 if either moves.

  STATUS: Abstract, §1 and §3-§9 are written. §2, §10 and References are the
  deliberate stubs — bullet outlines only, to be written by hand. Do not
  auto-fill them.
  §2 carries [CITE: ...] placeholders; fill from docs/02_LITERATURE_REVIEW.md
  only, and only after verifying each reference exists.
-->

# Abstract

When a software library releases a breaking change, the update can break
callers across many files, and some of these breaks are invisible to static
analysis — the code still imports, and the failure appears only when the tests
run. This project presents a headless autonomous agent, built as a five-node
LangGraph state machine, that maps every affected call site, plans
dependency-ordered edit batches, applies them, runs the test suite in an
isolated sandbox, and repairs its own edits by reading the resulting stack
traces. On a five-task benchmark, a deterministic linter (Ruff) detects every
breaking change but repairs none, while the agent completes all five tasks;
ablating the recovery loop causes three of the five to fail. These results show
that for cross-file version migration, a verification-driven repair loop
succeeds where single-pass code generation does not. The repair is scoped:
every correction measured here repaired residual call sites of the deprecated
API. On a blind held-out task whose break lies outside any call site, the
agent stops with a RED verdict and edits nothing it should not; recovery from
such breaks is not supported in this version.

<!-- SOURCE (Ruff detects every breaking change, repairs none): runs/benchmark/results.md
     §3 "Deterministic baselines — ruff (DTZ) and pyupgrade", the `ruff (DTZ)` row of
     every task: detect recall 100%, `fixed` 0, `M1 recall after fix` 0%. Equivalently
     results.json baselines[<task>].tools["ruff (DTZ)"]: detect_recall 100.0,
     fixed_files 0, m1_recall_after_fix 0.0. Expanded in §7.3. -->
<!-- SOURCE (agent completes all five tasks): runs/benchmark/results.md §2A, the
     `baseline` row of each per-task table reads `3× success` on all five tasks. Equivalently
     results.json aggregates[config="baseline"].outcomes == {"success": 3} for every
     task. Expanded in §7.2. -->
<!-- SOURCE (three of five fail without the loop): runs/benchmark/results.md §2A, the
     `no-recovery` row reads `3× gave_up` on task02_datetime_aliased,
     task03_half_migration and task04_multimodule, `3× success` on task01 and task05.
     Equivalently results.json aggregates[config="no-recovery"].outcomes. Cross-checked
     against runs/benchmark/RESULTS_SUMMARY.md claim (a). Expanded in §7.2. -->
<!-- SOURCE (scope; blind held-out task RED): corpus/blind/task06_scheduler/results.json —
     verdict RED in every run, patch_files = the two call-site files, tests_untouched true.
     Expanded in §4.5, §7.9 and §8.2. -->

---

# 1. Introduction

When a library releases a breaking change, a single altered API contract can
break callers spread across many interdependent files. Some of these breaks are
invisible to static analysis: the code still parses and imports, and the failure
surfaces only when the test suite runs. In our datetime migration, replacing a
deprecated call left one module returning a timezone-aware value while its
callers still passed naive ones — a TypeError that no linter could see and that
appeared only when the tests executed.

Deterministic tools detect these deprecations but cannot resolve them. In our
benchmarks Ruff reached full detection parity with our analyzer yet fixed none
of the sites, leaving migration completeness at zero while the suite stayed
green (M1 0 / M2 100) — the sharpest evidence that detection and repair are
different problems. Generative LLM agents attempt the repair but, without a
dependency model, edit files in an unsafe order, and without execution they
cannot verify their own output against the tests.

<!-- SOURCE: runs/benchmark/results.md §3 "Deterministic baselines — ruff (DTZ) and
     pyupgrade", the `ruff (DTZ)` row of every task: `fixed` 0, `M1 recall after fix`
     0%, `suite after fix` n/n passed. Equivalently results.json
     baselines[<task>].tools["ruff (DTZ)"]: fixed_files 0, m1_recall_after_fix 0.0,
     detect_recall 100.0, suite_green true. Expanded with the per-task table in §7.3. -->

We built a five-node self-correcting agent that applies a fix, runs the test
suite, and uses the resulting stack traces to iteratively repair its own edits.
Across a five-task benchmark, three tasks fail without this recovery loop and
all five succeed with it. The same experiment shows that edit order changes cost
and failure risk but never the final outcome once recovery is present — order is
a cost, not a verdict. What the loop repairs is residual call sites: a break the
migration causes in code that holds no deprecated call, such as a naive constant
that the newly aware clock is subtracted from, never reaches the model. On a
blind held-out task built that way, the agent fails safely (§8.2).

<!-- SOURCE: runs/benchmark/results.md §2A "Recovery loop ON vs OFF" — the
     `no-recovery` arm reads `3× gave_up` on task02_datetime_aliased,
     task03_half_migration and task04_multimodule, and `3× success` on all five
     tasks under `baseline`. Cross-checked against runs/benchmark/RESULTS_SUMMARY.md
     claim (a) table. Expanded with the per-task table in §7.2. -->

---

# 2. Related Work

> **STUB — outline only. Do not ghost-write. Every citation below is a
> placeholder; fill only from `docs/02_LITERATURE_REVIEW.md` after verifying
> the reference exists. Do not invent.**

- **Automated program repair / test-driven repair.** Position our CORRECT
  node against classical APR: we repair *our own* regression against a known
  contract, not an arbitrary bug. [CITE: APR survey]
- **Agentic software engineering benchmarks.** SWE-bench and successors
  measure issue-resolution on real repos; we measure *migration completeness*
  on controlled repos where ground truth is total rather than proxied by a
  PR diff. Explain why that trade (external validity down, attributability
  up) is the right one for an ablation study. [CITE: SWE-bench]
  [CITE: SWE-agent or comparable agent scaffold]
- **LLM agent scaffolds and state machines.** Why an explicit graph rather
  than a free-running tool-use loop. [CITE: LangGraph / state-machine agent
  reference] [CITE: ReAct or equivalent tool-use loop]
- **Deterministic codemods and refactoring tools.** libcst, ruff, pyupgrade,
  2to3-lineage tooling: exact, cheap, and unable to cross a file boundary or
  repair a consequence. This is the row we beat in §7.2.
  [CITE: libcst] [CITE: ruff] [CITE: pyupgrade]
- **Dependency-aware change impact analysis.** Prior work on ordering edits
  by module dependency; what is new here is coupling the order to a
  *verification* loop and measuring the coupling. [CITE: change impact
  analysis]
- **Positioning paragraph.** One paragraph naming the gap the above leaves:
  no existing line of work reports an ablation that separates "the loop" from
  "the ordering" on a corpus where both are exercised.

---

# 3. System

The agent is a LangGraph 1.x `StateGraph` over a single typed `MigrationState`
object. Five nodes, one conditional router, and a SQLite checkpointer that is
not a debugging aid but the deliverable audit log.

<!-- SOURCE: docs/04_ARCHITECTURE_HLD_LLD.md §2 (LLD). No benchmark numbers in this section. -->

## 3.1 The state machine

```
[*] → MAP → PLAN → EDIT → TEST ─┬─ green ∧ batches remain ──→ EDIT (k+1)
                                 ├─ green ∧ all done ────────→ SUCCESS
                                 ├─ red ∧ attempts[sig] < N ─→ CORRECT → TEST
                                 └─ red ∧ attempts[sig] ≥ N ─→ GIVE_UP
```

The canonical rendering is the `stateDiagram-v2` figure in
`docs/04_ARCHITECTURE_HLD_LLD.md` §2.1; the HLD component diagram is §1.1 of
the same document. Both should be reproduced as figures in the typeset
version (Figure 1: components; Figure 2: state machine).

Each node is a pure `state → partial state update` function; side effects
(file writes, sandbox invocations) are explicit rather than incidental.

| Node | Reads | Writes | Side effects |
|---|---|---|---|
| **MAP** | `repo_path`, `contract` | `call_sites`, `dep_graph`, `file_status` | none — read-only analysis |
| **PLAN** | `dep_graph`, `call_sites` | `edit_batches`, `current_batch = 0` | none |
| **EDIT** | `edit_batches[k]`, contract, graph slice, rolling summary | edited files, `file_status`, `tokens` | file writes, `git` snapshot |
| **TEST** | `repo_path` | `last_test_report` | `pytest` + `ruff` in the sandbox |
| **CORRECT** | `last_test_report.failures[0]` | corrective edit, `fix_attempts[sig] += 1`, `tokens` | file writes |

<!-- SOURCE: docs/04 §2.2 node contract table, reproduced. -->

Two implementation defects in the design pseudocode were found during P4 and
are worth reporting rather than silently fixing, because both are the kind of
error the architecture invites:

1. The router in `docs/04` §2.3 increments `current_batch` inside
   `route_after_test`. A LangGraph router receives a read-only view of the
   state and returns only an edge name, so the write is discarded and the run
   re-edits batch 0 indefinitely. The counter is advanced by `edit_node` after
   it consumes its batch; the routing *decision* is unchanged.
2. The batching pseudocode in `docs/04` §3.4 topologically sorts the
   dependency graph directly. Edges run `importer → imported`, so the plain
   order yields importers first — the exact inverse of the intended rule.
   The sort must be taken over the reversed graph. This inversion is not
   merely corrected: it is preserved as an experimental arm
   (`order-fr3-violating`, §6) so its cost can be measured.

<!-- SOURCE: docs/04 §2.3 implementation note (P4). -->

## 3.2 Dependency-ordered batching

A migration changes a symbol's contract; every module that uses that symbol
may break. Editing in arbitrary order produces circular regressions — fixing
A breaks B, fixing B breaks A — and makes each intermediate TEST
uninterpretable. The planner therefore derives edit order from the import
graph.

The graph is built by parsing every module with `libcst`, resolving `Import`
and `ImportFrom` nodes to in-repo module paths (third-party imports are
ignored), and adding a directed edge `importer → imported` to a
`networkx.DiGraph` whose nodes are module files. Call sites of the migrated
symbol are recorded separately, scope- and alias-resolved; that set is what
M1 scores against and what EDIT targets.

Batching then follows three rules:

- **Condensation, then topological order.** `networkx.condensation` reduces
  the graph to a DAG over strongly connected components;
  `networkx.topological_sort` over the *reversed* graph orders those
  components leaf-most first, so no batch is edited on top of an unmigrated
  dependency. This is requirement **FR-3**.
- **Atomic cycles.** An import cycle is a strongly connected component with
  more than one member. No safe internal order exists, so the whole component
  is emitted as one batch and tested once. `task04` exists to exercise this.
- **Only files with call sites.** A module in the order that contains no site
  of the migrated symbol is dropped from the plan rather than edited as a
  no-op.

<!-- SOURCE: docs/04 §3.2-§3.4. -->

## 3.3 Codemod first, model second

Deterministic edits are implemented as `libcst` codemods, not model calls.
The T1 codemod rewrites `datetime.utcnow()` to `datetime.now(timezone.utc)`
under every binding form it can resolve — `from datetime import datetime`,
`import datetime`, and `import datetime as dt` — and adds
`from datetime import timezone` **only** for the from-import form, because
under a module import the timezone is already reachable through the existing
binding. Adding the import there would be an unnecessary edit, which is
precisely the precision failure `task02` was built to catch (§4).

This split is a correctness and a cost decision. A codemod is exact,
reproducible, and costs zero tokens against M3; the model is reserved for
genuinely ambiguous edits and for failure recovery. It is also the constraint
that shapes the corpus: because the agent runs one fixed codemod, a migration
that changes a *first-party* function's arity is not expressible in this
system, and the corpus reflects that (§4.3, §9).

<!-- SOURCE: src/mra/codemods/datetime_utcnow.py module docstring; CLAUDE.md golden rule 5. -->

## 3.4 The verifier and the sandbox

All execution happens inside a Docker `python:3.12-slim` sandbox with a
writable copy of the repository and no network at agent runtime. `pytest` is
run under `pytest-json-report` and `ruff` alongside it; their output is
normalized into a single `test_report` JSON contract rather than scraped from
free text. `git` inside the sandbox provides snapshot, rollback, and the final
unified `migration.patch`. A bad edit therefore cannot reach the host, and a
run is reproducible from its checkpoint database.

<!-- SOURCE: docs/04 §1.2 component table; docs/05 §4; CLAUDE.md golden rule 3. -->

## 3.5 Recovery and the signature-based retry cap

When TEST is red, CORRECT takes the first surviving failure and runs three
steps: **classify** the failure into the taxonomy
(`import` / `signature` / `behaviour` / `assertion`), **locate** the broken
contract by mapping the traceback's `file:line` back to a call site or a
dependency edge, and **patch** that one file. The located file is filtered so
a test file is never edited (boundary **NB-4**) — the suite is the oracle and
editing it is a hard failure.

The retry cap is keyed on a *normalized failure signature*, not on a global
counter. `fix_attempts[sig]` increments per signature, and the run gives up
when any signature reaches `MAX_FIX_ATTEMPTS = 3`. Keying on the signature is
what makes "gave up" a defined outcome rather than a timeout: the agent stops
when it has demonstrably failed to move the *same* failure three times, while
a run that keeps uncovering new failures keeps working. Setting the cap to
zero disables recovery entirely, which is how ablation A is run without adding
a dead branch to the production path (§6).

<!-- SOURCE: docs/04 §2.3 route_after_test, §2.5 recovery internals; src/mra/benchmark/runner.py module docstring. -->

**Consequence repair (v0.3.0).** Through v0.2.0, `locate()` chose the file to
patch by re-scanning for residual call sites, so a break in code that holds no
deprecated call never reached the model (§8.2). Since v0.3.0, when no residual
call site is left, CORRECT switches to a consequence mode. The patch scope is
the non-test files the failing traceback names, plus their dependency-graph
neighbours that are migrated files or import one; the model names the file it
rewrites in a `FILE: <path>` header, and that file must be in scope.

**The anti-reversal guard.** Every corrective patch, in either mode, is checked
before it is written. A patch is rejected unapplied, and still counts as an
attempt, if it raises the number of residual call sites in its file or adds a
match for one of the contract's `forbidden_patterns`. Those patterns are
migration-specific: the datetime contract forbids `tzinfo=None` and
`timetuple()` / `utctimetuple()`, the edits that make an aware value naive
again, and any other migration gets an empty list. The residual check counts
sites, so a patch that removes one deprecated call and adds another passes it
(BUG-06, open; §9).

<!-- SOURCE: commit 06da274 (v0.3.0) message; docs/03_SRS.md revision 0.3 (§4.1
     contract.forbidden_patterns); src/mra/nodes/correct_node.py consequence_scope() and reversal();
     src/mra/codemods/datetime_utcnow.py FORBIDDEN_PATTERNS; src/mra/graph.py, forbidden_patterns
     set only when target == TARGET; BUGS.md BUG-06. -->

**Safety in v0.4.0.** A bug hunt against v0.3.0 (§8.3) led to five further
guards. A link in the input tree that resolves outside the repository refuses
the run (RED `unsafe_symlink`), and the copy is deleted before anything reads
it. A model reply that is empty, reasoning only, names a file other than the
located one, drops a top-level function or class, or shrinks the file below
half its lines is rejected unapplied as a counted attempt, unless the contract
allows deletion. A reply cut off by `max_tokens` is
detected from the provider's finish reason and retried once with a larger
budget; the retry is its own trajectory step, so it counts in M3 steps and its
tokens in M3 cost. A run holds an OS lock on its run ID for its whole length,
so a second run with a live ID refuses before touching the directory. And the
verdict can no longer be GREEN on an empty result: 0 files scanned is RED
`no_files_scanned`, and 0 sites where the ground truth expects some is YELLOW
`nothing_to_migrate`.

<!-- SOURCE: BUGS.md "Fixed" — BUG-11 (unsafe_symlink), BUG-04 (rejected replies), BUG-05 (truncation
     retry, trajectory event, M3), BUG-10 (flock, RunBusy), BUG-07 (no_files_scanned,
     nothing_to_migrate); src/mra/verdict.py reason codes; src/mra/report/__init__.py RunBusy. -->

## 3.6 Verdict, providers and memory

**The verdict engine.** Every run ends in one verdict that answers a single
question — can a human merge this patch? — computed only from the artefacts
the run left behind. **RED** means it must not be merged as is: the
pre-migration suite was not green, the run crashed or gave up, the final suite
is red, the test oracle was touched, the patch does not apply to a fresh
checkout, a budget was exceeded, the input held a link out of the repository,
or no file was scanned at all. **YELLOW** means the suite is green but the
evidence is weaker than it looks: sites remain, MAP found none where the
ground truth expects some, the agent over-edited, a
semantic check failed, lint got worse, a file could not be parsed, or an edited
line never ran under any test. **GREEN** means none of these holds. Precedence
is RED over YELLOW over GREEN, and every reason that applies is reported, not
only the first.

<!-- SOURCE: src/mra/verdict.py module docstring; the rule lists in _red() and _yellow(). -->

**Providers and local-only privacy.** Model calls go through a router that maps
each role — edit, recover, summarize, classify — to an ordered chain of
providers named in `mra.toml`: any OpenAI-compatible server, including a local
Ollama or vLLM endpoint, or the Anthropic SDK. No model name or URL is written
in code. Under `MRA_PRIVACY=local-only` the router admits only loopback and
private-network hosts and raises `PrivacyError` before a socket opens or a DNS
lookup happens. The rule covers fallbacks too, so a failed local provider never
hands the prompt to a remote one, and a role whose chain is entirely remote is
refused when the router is constructed, before any I/O. Remote calls have
secret-shaped strings redacted before sending. None of this is on the offline
path that produced §7.

<!-- SOURCE: CONFIGURATION.md §3 (per-role provider chains) and §5 (Privacy); src/mra/models/router.py
     ROLES; src/mra/models/privacy.py. -->

**The experience store.** An opt-in local SQLite store records, after each
corrective edit whose re-test is green, the failure class, the error message
with paths stripped and secrets redacted, the migration contract, and the
changed lines of the fix. On a later failure with the same class and contract,
the most similar stored fixes are offered to CORRECT as hints, capped at 1200
characters. The store is **off by default**: `mra run` enables it only through
`[experience] enabled = true` or `MRA_EXPERIENCE=on`, and `MRA_EXPERIENCE=off`
always wins. The benchmark and edge runners never read that switch, so every
result in §7 except ablation E ran without memory. Ablation E (§7.8) builds its
own throwaway store, warmed on the edge corpus and never on Tier A.

<!-- SOURCE: src/mra/memory/experience.py module docstring and HINT_BUDGET_CHARS = 1200;
     src/mra/benchmark/runner.py TRAIN_CORPUS = corpus/edge, and warm_store's refusal of Tier-A tasks. -->
---

# 4. Corpus & Ground Truth

## 4.1 Construction

Tier A is five controlled Python packages authored for this study. Each task
is a directory holding `old/` (a tree whose suite **passes** on the old API),
`gold/` (a hand-verified migrated tree whose suite passes on the new API),
`ground_truth.json`, and `task.yaml`. The agent always operates on a fresh
copy of `old/`; `gold/` is the scoring reference and is pinned by commit
hash in `ground_truth.json` so the state is reproducible.

Four authoring rules are non-negotiable:

1. `old/` must be green, or M2 is undefined.
2. `ground_truth.json` lists **every** site that must change — it is M1's
   denominator, not a sample.
3. Every task must contain cross-file breakage: a contract change in one file
   that breaks a caller in another. Without it the dependency graph is never
   exercised.
4. Tasks vary **one factor at a time**, so a difference in results is
   attributable to that factor.

`gold/` additionally carries assertions the shared suite does not, so a
migration that leaves any single module behind fails the gold check even when
the shared suite is green. These are the `semantic_checks` in
`ground_truth.json`.

<!-- SOURCE: docs/05_DATA_EVALUATION_PROTOCOL.md §1.1 authoring rules; corpus/tierA/*/ground_truth.json. -->

## 4.2 The five tasks

All five migrate the same contract, **T1**: `datetime.utcnow()` →
`datetime.now(timezone.utc)`. Holding the contract fixed is what makes the
factor that varies attributable.

| Task | \|A\| | Files | Tests | Difficulty | The one factor it varies |
|---|---|---|---|---|---|
| `task01_datetime` | 1 | 1 | 5 | easy | Baseline. From-import style, single site. The control. |
| `task02_datetime_aliased` | 2 | 2 | 5 | easy | **Alias resolution.** `import datetime` and `import datetime as dt`. Its `expected_import_changes` name both files with an empty `add` list — adding `from datetime import timezone` here is an unnecessary edit, so the task scores *precision*, not just recall. |
| `task03_half_migration` | 3 | 3 | 7 | medium | **Recovery.** The tree starts partially migrated; one module subtracts its own clock reading from another module's, so the mixed state is already broken. Asks whether the agent can finish from the failure alone. |
| `task04_multimodule` | 6 | 6 | 11 | hard | **Scale and cycles.** Seven modules with a genuine import cycle that must be migrated atomically, and a break that only surfaces after an earlier batch lands. Exercises condensation and batch planning. |
| `task05_signature_break` | 6 | 6 | 14 | hard | **Edit order.** An asymmetric break: migrating the contract owner first is always safe, migrating any caller first raises at import time. The only task on which order changes the verdict. |

<!-- SOURCE: |A| and file counts from corpus/tierA/*/ground_truth.json (call_sites length, distinct file count).
     Test counts from runs/benchmark/results.md §3 "suite after fix" column: 5/5, 5/5, 7/7, 11/11, 14/14.
     Difficulty from each ground_truth.json "difficulty" field.
     Factor descriptions from each corpus/tierA/*/README.md. -->

`task02`'s empty-`add` `expected_import_changes` deserve emphasis because they
are the corpus's only precision trap. A matcher tuned to `task01` looks for
`Attribute(value=Name("datetime"), attr=Name("utcnow"))`; in `task02` the
receiver is itself an `Attribute`, so that matcher — and a
`datetime\.utcnow\(` regex — finds **zero** of the two sites. Correct
enumeration requires reading the import statements first and resolving `dt`
back to the `datetime` module.

<!-- SOURCE: corpus/tierA/task02_datetime_aliased/README.md. -->

## 4.3 `task05` and one honest limitation

`task01`–`task04` cannot separate the batching orders. Their breaks are
symmetric: every order opens some window, and the recovery loop closes all of
them, so ablation B had nothing to measure. `task05` was authored to close
that gap.

Its contract owner, `pkg.timebase`, normalizes every stamp it is handed
through a deliberately one-way shim. A *naive* stamp from a module that has
not migrated yet is read as UTC, because the old contract promised it was
UTC. An *aware* stamp handed to a still-naive clock is **not** downgraded,
because stripping a `tzinfo` silently reinterprets the value;
`elapsed_since` checks the mismatch before doing any arithmetic and raises a
named `TypeError` describing the ordering violation. `pkg.boot` performs that
handback at **module scope**, so a caller migrated ahead of the contract owner
raises during *import* and pytest reports collection errors rather than test
failures.

**The limitation, stated plainly.** The task name promises a signature break,
and what it delivers is a *contract* break. The signature that moves is the
tz-awareness of `timebase.utc_now()`'s return value, enforced at the package
boundary — not a first-party arity change with a parameter threaded through
call sites. An arity change is **not expressible in this system**: the agent
runs one fixed codemod (§3.3) that only rewrites `datetime.utcnow()` calls,
so a gold state requiring new arguments at call sites would be unreachable by
construction. The property the fixture was built for — a caller edited before
its callee fails hard, at import/collection time — is fully realized; the
mechanism is a guard rather than an arity mismatch. Consequently the offline
classifier files the resulting failure as `behaviour`, not `signature`, since
it reserves `signature` for argument-shaped messages (§8).

<!-- SOURCE: corpus/tierA/task05_signature_break/README.md; runs/benchmark/RESULTS_SUMMARY.md "Scope and honesty notes". -->

## 4.4 The edge-case suite

Tier A measures the migration; a second corpus measures the verdict.
`corpus/edge/` holds **39** small repositories, each with hand-written ground
truth located by the literal call text, never by the analyzer, and a
`case.json` naming the expected verdict, the reason that must produce it and,
for byte-level cases, `gold/` files the result must match exactly. The cases
fall into four categories: **common (10)**; **rare (15)**; **twisted (7)**,
inputs built to mislead the analyzer or the judge, such as star imports, bare
references and already-migrated code; and **failure (7)**, where RED is the
correct answer. The expected verdicts are 28 GREEN, 4 YELLOW and 7 RED. A judge
checks the verdict, the reason code and its evidence, byte-exact gold, M1 recall
of 100 for every non-RED case so no GREEN can be silent about a missed site,
and an empty patch for every refusal. Results are in `corpus/edge/RESULTS.md`
and §7.7.

<!-- SOURCE: corpus/edge/results.json — total 39; cases[].category: common 10, rare 15, twisted 7,
     failure 7; cases[].expected: GREEN 28, YELLOW 4, RED 7. Judge criteria: src/mra/benchmark/edge.py
     run_case and commit ab9e267. -->

## 4.5 A blind held-out task

Every Tier-A task and edge case existed while the agent was being built, so
none of them can show how it does on a repository it was not shaped by.
`corpus/blind/task06_scheduler` was written after the agent was frozen, with
`src/mra/` frozen at `f97bf67`, and nothing in the agent was changed or tuned
against it. It follows the Tier-A layout and contract, with **|A| = 2**: an
aliased class import in `clock.py` (`DT.utcnow()`, which needs a new
`timezone` import) and `utcfromtimestamp` through a module alias in
`config.py` (which needs none). Three features are new to the corpus. A naive
module constant, `config.EPOCH`, is subtracted from the clock in `report.py`
but holds no call site, so once the clock is aware the suite breaks in code
MAP never lists. `jobs.py` and `scheduler.py` import each other at module
level. `decoys.py` calls a `FakeClock.utcnow()` method and carries the literal
text `datetime.utcnow()` in a docstring and a log message, both pinned
byte-for-byte by the suite. The right repair makes `EPOCH` aware in
`config.py`. Stripping `tzinfo` in `report.py` would also turn the visible
suite green, but that is the wrong repair, and two hidden semantic tests,
present only in `gold/`, catch it.

<!-- SOURCE: corpus/blind/task06_scheduler/ground_truth.json (call_sites: 2;
     expected_import_changes clock add ["timezone"], config add []), task.yaml and README.md;
     `git diff --quiet f97bf67 10ebb17 -- src/` is empty: src/ did not change between the freeze
     and the commit that recorded the blind result (checked by verify_paper.py). -->

## 4.6 A second blind task

`corpus/blind/task07_cache` was written after v0.3.0, with `src/` frozen at
`06da274`, and the agent was not changed between that commit and the one that
recorded the result, `bcf2c90`. It follows the same contract, with **|A| = 1**:
`datetime.datetime.utcnow()` under `import datetime` in `stamp.py`, which needs
no new import. The break is again off the call sites, this time in a parser.
`store.save()` writes `stamp().isoformat()`; once the stamp is aware, that
string ends in `+00:00`, and `store.load()`'s `strptime` with a fixed format
raises `ValueError`. `store.py` holds no deprecated call. The right repair is
`fromisoformat(s)`, or a `%z` format, in `store.py`. Dropping the offset, by
stripping `tzinfo` or slicing the string, makes `load()` stop raising, but the
visible suite still compares an aware stamp with a naive one, and two hidden
semantic tests in `gold/` catch it. `legacy.py` is a decoy: a
`LegacyClock.utcnow()` call and the literal `datetime.utcnow()` in a docstring.

<!-- SOURCE: corpus/blind/task07_cache/ground_truth.json (call_sites: 1; expected_import_changes
     stamp.py add []), README.md and task.yaml; `git diff --quiet 06da274 bcf2c90 -- src/` is empty
     (checked by verify_paper.py); commit bcf2c90 message. -->
---

# 5. Metrics

Three metrics, defined in `docs/05_DATA_EVALUATION_PROTOCOL.md` §2. For a
task, let $A$ be the set of affected call sites listed in
`ground_truth.json`, $X$ the set of sites the agent actually modified,
$\mathrm{TP}$ the sites in $A$ that the agent modified *and* matched gold
semantics, $T$ the total number of tests, and $T_{\text{post}}$ the number
passing after migration.

## 5.1 M1 — Migration Completeness

$$
M_1^{\text{recall}} = \frac{\mathrm{TP}}{|A|}\times 100
\qquad
M_1^{\text{precision}} = \frac{\mathrm{TP}}{|X|}\times 100
\qquad
M_1^{F_1} = \frac{2\,M_1^{\text{recall}}M_1^{\text{precision}}}{M_1^{\text{recall}} + M_1^{\text{precision}}}
$$

**Why both halves are reported.** Recall alone is trivially gamed by editing
everything; precision alone is trivially gamed by editing one site correctly
and stopping. The corpus contains a live instance of the precision half:
`task02`'s `expected_import_changes` require no import to be added, so an agent that helpfully
adds `from datetime import timezone` under a module-import binding is
*correct-looking and wrong*, and only precision records it.

The clearest argument for reporting M1 at all is the baseline row in §7.2:
`ruff` detects 100 % of the ground-truth sites on all five tasks and rewrites
none of them, so its M1 recall after `--fix` is 0 % while M2 remains 100 %.
A migration that never happened is indistinguishable from a successful one if
M2 is the only metric on the page.

<!-- SOURCE: docs/05 §2.1 formulas; §7.2 of this paper for the ruff figures. -->

## 5.2 M2 — Post-Migration Test Pass Rate

$$
M_2 = \frac{T_{\text{post}}}{T}\times 100
\qquad
R = T_{\text{pre}} - T_{\text{post}}
$$

with the precondition $T_{\text{pre}} = T$ (the suite is green before
migration — authoring rule 1). $M_2 = 100\,\%$ with $R = 0$ is a fully
successful migration. $R$ is reported separately because on suites of 5–14
tests a raw regression count is more informative than a percentage — and
because a collection error, which takes out whole test modules at once,
shows up in $R$ far more legibly than in $M_2$.

<!-- SOURCE: docs/05 §2.2. -->

## 5.3 M3 — Token / Step Overhead

$$
\text{Tokens} = \sum_m (t^{\text{in}}_m + t^{\text{out}}_m)
\qquad
\text{Steps} = (\text{LLM calls}) + (\text{tool calls})
\qquad
\text{Cost} = \sum_m (t^{\text{in}}_m p^{\text{in}}_m + t^{\text{out}}_m p^{\text{out}}_m)
$$

normalized per call site as $\text{Tokens}/|A|$ and $\text{Steps}/|A|$ for
cross-task comparison. In the offline matrix that carries this paper's
results, the corrector is a codemod rather than a model, so tokens and cost
are identically zero and **Steps is the meaningful M3 column** (§7.1).

<!-- SOURCE: docs/05 §2.3 formulas. Zero-token claim: runs/benchmark/results.md §1, "tokens" and "cost $" columns are 0 / 0.0000 in all 55 rows. -->

We additionally report **corrective edits** (`corr`) — one CORRECT visit per
retry attempt — because it is where the cost of a bad edit order is paid long
before it is paid in a failed run.

---

# 6. Experimental Setup

**Configurations.** Each row of the matrix is one `Config` that changes
exactly one thing about a named `baseline` (recovery on, dependency-ordered
batches of 3, deterministic corrector). Eleven configurations run offline;
two more (ablation C) require an API key.

| Ablation | Arms | Question |
|---|---|---|
| **A** | `baseline`, `no-recovery` | How much does self-correction contribute? |
| **B** | `order-alphabetical`, `order-fr3-violating` (batch 3); the same two plus `batch-1` at batch size 1; and all three again with the loop off (`*-b1-norecovery`) | Does principled edit order prevent regressions? |
| **C** | `edit-v4-pro`, `edit-v4-flash` | Capability vs. cost on the live model path. **Not run** — needs two live models; the live runs used one (`nvidia/nemotron-3-super-120b-a12b`). |
| **D** | `batch-1`, `baseline`, `batch-5` | Effect of batch size on localization and overhead. |

<!-- SOURCE: src/mra/benchmark/runner.py CONFIGS tuple; runs/benchmark/results.md §4 "Configuration key". -->

**Why ablation B has three groups.** At batch size 3 a Tier-A task is only
one or two batches wide, so edit order and batch size are confounded: an
order that happens to put a producer and its consumer in the same batch never
exposes an intermediate state at all. The `-b1` group edits one file per
batch, where sequence is the only remaining variable. The `-norecovery` group
then removes the loop, which is the only condition under which an order's
cost can appear as an *outcome* rather than as corrective edits.

**How recovery is switched off.** `MRA_MAX_FIX_ATTEMPTS=0` means no failure
ever has an attempt left, so the router takes `give_up` on the first red
suite. No flag is added to the agent and no dead branch enters the production
path. `MAX_FIX_ATTEMPTS = 3` in every other arm.

**The offline corrector.** The CORRECT node is run with the model replaced by
the codemod. It localizes through the same `locate` the LLM corrector uses —
same trace parsing, same dependency slice, same NB-4 test-file filter — and
then applies the deterministic transform instead of requesting a file from
the live model (`nvidia/nemotron-3-super-120b-a12b` via NVIDIA's API). The loop *mechanics* under test are therefore identical; only the
patch generator is reproducible. This is what makes ablation A demonstrable
without an API key.

**Repeats and determinism.** Every (task, configuration) pair is run
`repeats = 3` times and the tables report mean ± spread (max − min). Because
the offline path contains no model call, **the spread is zero on every metric
except wall clock**, which is the point of having a deterministic arm: it is
reproducible byte-for-byte. The live arms (ablation C) are the ones the repeat
count exists for; they are marked *requires key* and are absent from
`results.json.rows` rather than estimated.

**Isolation.** Each run executes in the Docker sandbox against a fresh
writable copy of `old/`, with no network. Test files are never editable
(NB-4), and the suite asserts that the corpus tree digest is unchanged after
the entire benchmark — including the deliberately bad orders.

**Totals.** 5 tasks × 11 offline configurations × 3 repeats = **165 runs**,
with 10 (task, config) pairs skipped for want of a key.

<!-- SOURCE: runs/benchmark/results.md header line ("3 repeat(s) per (task, config)");
     runs/benchmark/RESULTS_SUMMARY.md opening paragraph ("5 tasks × 11 offline configurations × 3 repeats = 165 runs");
     results.json "skipped" = 10 entries across edit-v4-pro / edit-v4-flash;
     src/mra/benchmark/runner.py module docstring for the MRA_MAX_FIX_ATTEMPTS=0 mechanism. -->

---

# 7. Results

All figures in this section are drawn from `runs/benchmark/results.md` and
`runs/benchmark/RESULTS_SUMMARY.md`, both generated from `results.json` at
**2026-09-21T05:49:48Z**. Each claim carries an HTML comment naming its
source table.

<!-- SOURCE: runs/benchmark/results.md line 3, "Generated 2026-09-21T05:49:48.150512+00:00 · 3 repeat(s) per (task, config)". -->

Three columns are constant across all 55 offline rows and are stated once
rather than repeated: **M1 precision = 100.0**, **tokens = 0**, **cost =
$0.0000**. Nothing was over-edited in any configuration, and the offline path
makes no model call.

<!-- SOURCE: runs/benchmark/results.md §1 — the "M1 prec", "tokens" and "cost $" columns read 100.0 / 0 / 0.0000 in every one of the 55 rows. -->

## 7.1 The consolidated matrix

Every (task, configuration) pair, mean ± spread over 3 repeats. Reproduced
verbatim from `runs/benchmark/results.md` §1.

<!-- SOURCE: runs/benchmark/results.md §1 "The whole offline matrix", all 55 rows, transcribed without modification. -->

| task / config | outcome | M1 recall | M1 prec | M1 F1 | M2 % | regr | corr | steps | tokens | cost $ | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `task01_datetime / baseline` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 5 | 0 | 0.0000 | 1.90 ±0.14 |
| `task01_datetime / batch-1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 5 | 0 | 0.0000 | 1.72 ±0.05 |
| `task01_datetime / batch-5` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 5 | 0 | 0.0000 | 1.74 ±0.05 |
| `task01_datetime / no-recovery` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 5 | 0 | 0.0000 | 1.74 ±0.09 |
| `task01_datetime / order-alphabetical` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 5 | 0 | 0.0000 | 1.72 ±0.06 |
| `task01_datetime / order-alphabetical-b1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 5 | 0 | 0.0000 | 1.73 ±0.05 |
| `task01_datetime / order-alphabetical-b1-norecovery` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 5 | 0 | 0.0000 | 1.72 ±0.03 |
| `task01_datetime / order-dependency-b1-norecovery` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 5 | 0 | 0.0000 | 1.73 ±0.05 |
| `task01_datetime / order-fr3-violating` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 5 | 0 | 0.0000 | 1.72 ±0.06 |
| `task01_datetime / order-fr3-violating-b1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 5 | 0 | 0.0000 | 1.73 ±0.11 |
| `task01_datetime / order-fr3-violating-b1-norecovery` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 5 | 0 | 0.0000 | 1.76 ±0.02 |
| `task02_datetime_aliased / baseline` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 9 | 0 | 0.0000 | 3.53 ±0.09 |
| `task02_datetime_aliased / batch-1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 9 | 0 | 0.0000 | 3.37 ±0.09 |
| `task02_datetime_aliased / batch-5` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 9 | 0 | 0.0000 | 3.38 ±0.10 |
| `task02_datetime_aliased / no-recovery` | 3× gave_up | 50.0 | 100.0 | 66.7 | 80.0 | 1 | 0 | 5 | 0 | 0.0000 | 1.73 ±0.09 |
| `task02_datetime_aliased / order-alphabetical` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 5 | 0 | 0.0000 | 1.72 ±0.03 |
| `task02_datetime_aliased / order-alphabetical-b1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 9 | 0 | 0.0000 | 3.46 ±0.25 |
| `task02_datetime_aliased / order-alphabetical-b1-norecovery` | 3× gave_up | 50.0 | 100.0 | 66.7 | 80.0 | 1 | 0 | 5 | 0 | 0.0000 | 1.71 ±0.08 |
| `task02_datetime_aliased / order-dependency-b1-norecovery` | 3× gave_up | 50.0 | 100.0 | 66.7 | 80.0 | 1 | 0 | 5 | 0 | 0.0000 | 1.69 ±0.02 |
| `task02_datetime_aliased / order-fr3-violating` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 9 | 0 | 0.0000 | 3.37 ±0.12 |
| `task02_datetime_aliased / order-fr3-violating-b1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 9 | 0 | 0.0000 | 3.48 ±0.25 |
| `task02_datetime_aliased / order-fr3-violating-b1-norecovery` | 3× gave_up | 50.0 | 100.0 | 66.7 | 80.0 | 1 | 0 | 5 | 0 | 0.0000 | 1.69 ±0.02 |
| `task03_half_migration / baseline` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 9 | 0 | 0.0000 | 3.70 ±0.13 |
| `task03_half_migration / batch-1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 11 | 0 | 0.0000 | 4.54 ±0.12 |
| `task03_half_migration / batch-5` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 9 | 0 | 0.0000 | 3.72 ±0.33 |
| `task03_half_migration / no-recovery` | 3× gave_up | 33.3 | 100.0 | 50.0 | 85.7 | 1 | 0 | 5 | 0 | 0.0000 | 1.81 ±0.01 |
| `task03_half_migration / order-alphabetical` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 5 | 0 | 0.0000 | 1.90 ±0.04 |
| `task03_half_migration / order-alphabetical-b1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 11 | 0 | 0.0000 | 4.49 ±0.07 |
| `task03_half_migration / order-alphabetical-b1-norecovery` | 3× gave_up | 66.7 | 100.0 | 80.0 | 85.7 | 1 | 0 | 7 | 0 | 0.0000 | 2.71 ±0.09 |
| `task03_half_migration / order-dependency-b1-norecovery` | 3× gave_up | 33.3 | 100.0 | 50.0 | 85.7 | 1 | 0 | 5 | 0 | 0.0000 | 1.85 ±0.07 |
| `task03_half_migration / order-fr3-violating` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 9 | 0 | 0.0000 | 3.63 ±0.25 |
| `task03_half_migration / order-fr3-violating-b1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 11 | 0 | 0.0000 | 4.44 ±0.08 |
| `task03_half_migration / order-fr3-violating-b1-norecovery` | 3× gave_up | 66.7 | 100.0 | 80.0 | 85.7 | 1 | 0 | 7 | 0 | 0.0000 | 2.66 ±0.04 |
| `task04_multimodule / baseline` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 2 | 17 | 0 | 0.0000 | 8.06 ±0.08 |
| `task04_multimodule / batch-1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 2 | 17 | 0 | 0.0000 | 7.92 ±0.09 |
| `task04_multimodule / batch-5` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 2 | 17 | 0 | 0.0000 | 8.42 ±0.27 |
| `task04_multimodule / no-recovery` | 3× gave_up | 66.7 | 100.0 | 80.0 | 72.7 | 3 | 0 | 9 | 0 | 0.0000 | 3.97 ±0.17 |
| `task04_multimodule / order-alphabetical` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 7 | 0 | 0.0000 | 3.21 ±0.08 |
| `task04_multimodule / order-alphabetical-b1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 17 | 0 | 0.0000 | 7.74 ±0.22 |
| `task04_multimodule / order-alphabetical-b1-norecovery` | 3× gave_up | 66.7 | 100.0 | 80.0 | 72.7 | 3 | 0 | 11 | 0 | 0.0000 | 4.73 ±0.24 |
| `task04_multimodule / order-dependency-b1-norecovery` | 3× gave_up | 66.7 | 100.0 | 80.0 | 72.7 | 3 | 0 | 9 | 0 | 0.0000 | 3.92 ±0.08 |
| `task04_multimodule / order-fr3-violating` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 3 | 19 | 0 | 0.0000 | 9.16 ±0.18 |
| `task04_multimodule / order-fr3-violating-b1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 3 | 19 | 0 | 0.0000 | 9.14 ±0.04 |
| `task04_multimodule / order-fr3-violating-b1-norecovery` | 3× gave_up | 33.3 | 100.0 | 50.0 | 72.7 | 3 | 0 | 7 | 0 | 0.0000 | 2.97 ±0.10 |
| `task05_signature_break / baseline` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 11 | 0 | 0.0000 | 4.81 ±0.24 |
| `task05_signature_break / batch-1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 15 | 0 | 0.0000 | 6.26 ±0.09 |
| `task05_signature_break / batch-5` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 11 | 0 | 0.0000 | 4.93 ±0.27 |
| `task05_signature_break / no-recovery` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 11 | 0 | 0.0000 | 4.72 ±0.08 |
| `task05_signature_break / order-alphabetical` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 9 | 0 | 0.0000 | 4.53 ±0.15 |
| `task05_signature_break / order-alphabetical-b1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 2 | 19 | 0 | 0.0000 | 9.07 ±0.04 |
| `task05_signature_break / order-alphabetical-b1-norecovery` | 3× gave_up | 33.3 | 100.0 | 50.0 | 0.0 | 14 | 0 | 7 | 0 | 0.0000 | 3.12 ±0.06 |
| `task05_signature_break / order-dependency-b1-norecovery` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 0 | 15 | 0 | 0.0000 | 6.25 ±0.02 |
| `task05_signature_break / order-fr3-violating` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 13 | 0 | 0.0000 | 5.91 ±0.06 |
| `task05_signature_break / order-fr3-violating-b1` | 3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0 | 1 | 17 | 0 | 0.0000 | 7.43 ±0.07 |
| `task05_signature_break / order-fr3-violating-b1-norecovery` | 3× gave_up | 50.0 | 100.0 | 66.7 | 78.6 | 3 | 0 | 9 | 0 | 0.0000 | 3.72 ±0.03 |

Spread is `0` on every metric except wall clock in all 55 rows, as expected of
a path with no model call.

<!-- SOURCE: runs/benchmark/results.md §1 — the only cells carrying a "±" are in the "wall s" column. -->

## 7.2 Claim (a) — the recovery loop is what finishes a cross-file migration

**With the CORRECT loop disabled, 3 of the 5 tasks end in `gave_up` with a
regression the agent cannot repair; with it enabled all 5 finish at M1 100 % /
M2 100 % / 0 regressions — and the two tasks that do not move are the two
where nothing ever breaks, which is what makes them controls rather than
counter-evidence.**

| task | loop on (`baseline`) | loop off (`no-recovery`) |
|---|---|---|
| `task01_datetime` *(control: single file)* | success, M1 100, 0 regr | success, M1 100, 0 regr |
| `task02_datetime_aliased` | success, M1 100, M2 100, 1 corr | **gave_up, M1 50, M2 80.0, 1 regr** |
| `task03_half_migration` | success, M1 100, M2 100, 1 corr | **gave_up, M1 33, M2 85.7, 1 regr** |
| `task04_multimodule` | success, M1 100, M2 100, 2 corr | **gave_up, M1 67, M2 72.7, 3 regr** |
| `task05_signature_break` *(control: dependency order opens no window)* | success, M1 100, 0 corr | success, M1 100, 0 regr |

<!-- SOURCE: runs/benchmark/results.md §2A "Recovery loop ON vs OFF"; equivalently §1 rows
     `<task> / baseline` and `<task> / no-recovery`. Cross-checked against
     runs/benchmark/RESULTS_SUMMARY.md claim (a) table. -->

The `task05` row is the control the corpus previously lacked. It is a *hard*
task that the loop does not rescue, because in dependency order there is
nothing to rescue — so ablation A's effect tracks "is there a break?", not
"is the task big?". Without it, the correlation between task difficulty and
loop dependence would be uncontrolled.

**Scope of claim (a).** Every corrective edit behind this claim, and the 12
model-written ones in §7.8, repaired residual call sites: files that still
held a deprecated call when the suite went red. Recovery from a consequence
break outside any call site was not supported in v0.2.0 (§7.9, §8.2); v0.3.0
added it (§3.5), and its only measurement is the second blind task (§7.10).

<!-- SOURCE: src/mra/nodes/correct_node.py locate() — the corrector targets files re-scanned
     as still holding a call site, and consequence_scope() only when none is left;
     runs/benchmark/live/results_live.json corrections sum 12 per arm; agent_version 0.2.0 from
     corpus/edge/results.json; consequence mode from commit 06da274 (v0.3.0). -->

## 7.3 Claim (b) — the existing static tools detect the work and do none of it

**`ruff` (DTZ) reports 100 % of the ground-truth call sites on all five tasks
and rewrites zero of them, so its M1 recall after running with `--fix` is 0 %
on every task — and because it changes nothing, the suite stays green, which
is exactly why M2 alone cannot tell you a migration did not happen.**

| task | \|A\| | ruff detected | ruff fixed | M1 after fix | suite after fix | pyupgrade detected |
|---|---|---|---|---|---|---|
| `task01_datetime` | 1 | 1 (100 %) | 0 | 0 % | 5/5 passed | 0 (0 %) |
| `task02_datetime_aliased` | 2 | 2 (100 %) | 0 | 0 % | 5/5 passed | 0 (0 %) |
| `task03_half_migration` | 3 | 3 (100 %) | 0 | 0 % | 7/7 passed | 0 (0 %) |
| `task04_multimodule` | 6 | 6 (100 %) | 0 | 0 % | 11/11 passed | 0 (0 %) |
| `task05_signature_break` | 6 | 7 (100 % recall, 86 % precision) | 0 | 0 % | 14/14 passed | 0 (0 %) |

<!-- SOURCE: runs/benchmark/results.md §3 "Deterministic baselines — ruff (DTZ) and pyupgrade",
     columns: detected / |A| / detect recall / fixed / M1 recall after fix / suite after fix.
     Cross-checked against runs/benchmark/RESULTS_SUMMARY.md claim (b) table. -->

Two details are reported rather than smoothed over. `ruff`'s seventh hit on
`task05` is a genuine `DTZ001` on the naive datetime constant in
`tests/test_timebase.py` — a false positive against $A$, and the only place
in the corpus where detection precision falls below 100 %. `pyupgrade`
detects nothing at all: this migration is not in its rule set, so its row is
a floor, not a failure.

<!-- SOURCE: results.json baselines[task05_signature_break].tools["ruff (DTZ)"]:
     detected 7 against ground_truth_sites 6, detect_recall 100.0, detect_precision 85.714… (→ 86 %).
     The seventh hit is DTZ001 at corpus/tierA/task05_signature_break/old/tests/test_timebase.py:12,
     `NAIVE = datetime(2024, 1, 1, 12, 0, 0)` — reproduce with
     `ruff check --select DTZ corpus/tierA/task05_signature_break/old`.
     Every other task's detect_precision is 100.0 in the same structure.
     pyupgrade: detected 0 / detect_recall 0.0 on all five tasks. -->

Neither tool can repair a cross-file break, because neither edits across
files at all: on `task03`, `task04` and `task05` the regression the agent
recovers from does not exist for them, since they never create it. That is
the asymmetry the comparison is meant to expose — a tool that does no work
cannot regress, and a metric that only measures regressions will reward it.

## 7.4 Claim (c) — dependency ordering: a cost reduction, and in one case a correctness condition

The ordering result splits in two, and both halves are reported.

**(c-i) Regression avoidance — with the loop off, and only on `task05`.**
With the CORRECT loop disabled and one file per batch, dependency order
completes `task05_signature_break` green while both arbitrary orders give up
with a red suite; on the other four tasks all three orders break, so this
half of the claim rests on `task05` alone.

| task | dependency | file-name | dependents-first |
|---|---|---|---|
| `task01_datetime` | 3× success, 0 regr | 3× success, 0 regr | 3× success, 0 regr |
| `task02_datetime_aliased` | 3× gave_up, M1 50 | 3× gave_up, M1 50 | 3× gave_up, M1 50 |
| `task03_half_migration` | 3× gave_up, M1 33 | 3× gave_up, M1 67 | 3× gave_up, M1 67 |
| `task04_multimodule` | 3× gave_up, M1 67 | 3× gave_up, M1 67 | 3× gave_up, M1 33 |
| **`task05_signature_break`** | **3× success, M1 100, M2 100, 0 regr** | **3× gave_up, M1 33, M2 0.0, 14 regr** | **3× gave_up, M1 50, M2 78.6, 3 regr** |

<!-- SOURCE: runs/benchmark/results.md §2B, group "batch size 1, recovery OFF" — arms
     order-dependency-b1-norecovery / order-alphabetical-b1-norecovery / order-fr3-violating-b1-norecovery.
     Equivalently §1 rows with those config names. Cross-checked against
     runs/benchmark/RESULTS_SUMMARY.md claim (c) claim-1 table. -->

The two arbitrary orders on `task05` break *differently*, and that difference
is the finding, and the planned batch lists explain it exactly.

File-name order plans
`[api] [boot] [handler] [ledger] [metrics] [timebase]` and so reaches
`src/pkg/boot.py` at batch 2 — four batches ahead of the contract owner
`src/pkg/timebase.py` at batch 6. `boot.py` performs its clock handback at
**module scope**, so the `TypeError` is raised during *import*: the run gives
up after batch 2, three test modules never load, and the failing node IDs are
whole files with no `::test_` component — M2 0.0 % with 14 regressions, the
entire suite.

Dependents-first order plans
`[api] [handler] [metrics] [boot] [ledger] [timebase]` and never reaches
`boot.py` at all: it gives up after batch 3 of 6, with `api`, `handler` and
`metrics` migrated ahead of `timebase`. The same guard therefore trips at
*call* time rather than import time, inside three tests in
`tests/test_api.py` and `tests/test_metrics.py` — M2 78.6 % with 3
regressions. Dependency order reaches neither window: 3× success, 0
regressions, 0 corrective edits.

The two arbitrary orders are thus not two degrees of the same break but two
different ones, and only the earlier of the two takes out the suite wholesale.

<!-- SOURCE: runs/benchmark/failure-analysis.md, entries
     "`order-alphabetical-b1-norecovery` on task05_signature_break" — planned batches
     [[api],[boot],[handler],[ledger],[metrics],[timebase]], "gave_up after batch 2/6", M2 0.0%, 14 regressions,
     3 surviving failures whose nodeids are tests/test_api.py, tests/test_boot.py, tests/test_handler.py (no "::")
     — and "`order-fr3-violating-b1-norecovery` on task05_signature_break" — planned batches
     [[api],[handler],[metrics],[boot],[ledger],[timebase]], "gave_up after batch 3/6",
     files actually migrated [api, handler, metrics], M2 78.6%, 3 regressions whose nodeids are
     tests/test_api.py::test_serve_returns_the_whole_response and two in tests/test_metrics.py (all carry "::"). -->

**(c-ii) Corrective-edit cost — with the loop on, and not uniform.**
Dependency order is never the most expensive arm and dependents-first order is
never the cheapest, but the ranking does not hold task-by-task, so this is a
weaker claim than (c-i).

Mean corrective edits, one file per batch, recovery on (lower is better):

| task | dependency (`batch-1`) | file-name (`-b1`) | dependents-first (`-b1`) |
|---|---|---|---|
| `task01_datetime` | 0 | 0 | 0 |
| `task02_datetime_aliased` | 1 | 1 | 1 |
| `task03_half_migration` | 1 | 1 | 1 |
| `task04_multimodule` | 2 | **1** | **3** |
| `task05_signature_break` | **0** | **2** | 1 |

<!-- SOURCE: runs/benchmark/results.md §2B, group "batch size 1, recovery on" — the "corr" column of arms
     batch-1 / order-alphabetical-b1 / order-fr3-violating-b1; also summarized in that section's
     "What the data says" bullet list. Cross-checked against runs/benchmark/RESULTS_SUMMARY.md claim (c) claim-2 table. -->

The `task04` row is reported as found: file-name order costs one edit *fewer*
than dependency order there. That is luck about which files that particular
alphabet happens to group, not evidence against FR-3 — and the same order
costs 2 where dependency order costs 0 on `task05`. Both dependents-first arms
on `task04` — batch 3 and batch 1 — spend the full retry ceiling of 3 attempts
on a *single* failure signature, i.e. they finish one attempt away from failing
the task outright; dependency order spends 2 on the same task.

<!-- SOURCE: runs/benchmark/results.md §2B "What the data says", finding 2, for the ranking.
     The "single signature" detail from results.json rows order-fr3-violating / task04_multimodule
     and order-fr3-violating-b1 / task04_multimodule: fix_attempts == {"2773f89c64a8ae65": 3} in all
     3 repeats of each, against {"…": 2} for baseline / task04_multimodule. -->

**(c-iii) What is *not* shown.** With the loop on, every order completes every
Tier-A task at M1 100 / M2 100, `task05` included. On this corpus, edit order
is a cost and a risk — never a verdict — once recovery is available. Any
quotation of (c-i) must carry this alongside it.

<!-- SOURCE: runs/benchmark/results.md §1 — every row whose config does not end in "-norecovery"
     reads "3× success" at M1 100.0 / M2 100.0 / 0 regr. Cross-checked against
     runs/benchmark/RESULTS_SUMMARY.md claim (c) claim-3. -->

## 7.5 Ablation D — batch size

Batch size caps how many files one EDIT touches before the suite runs again:
smaller batches localize a failure more precisely and cost more TEST steps.
On this corpus the effect on *outcome* is nil and the effect on *cost* is
small and confined to two tasks.

| task | steps @ batch 1 | steps @ batch 3 | steps @ batch 5 | corrective edits (all three) |
|---|---|---|---|---|
| `task01_datetime` | 5 | 5 | 5 | 0 |
| `task02_datetime_aliased` | 9 | 9 | 9 | 1 |
| `task03_half_migration` | **11** | 9 | 9 | 1 |
| `task04_multimodule` | 17 | 17 | 17 | 2 |
| `task05_signature_break` | **15** | 11 | 11 | 0 |

<!-- SOURCE: runs/benchmark/results.md §2D "Batch size 1 vs 3 vs 5", the "steps" and "corr" columns
     of arms batch-1 / baseline / batch-5 for each task. Identical values appear in §1 rows
     `<task> / batch-1`, `<task> / baseline`, `<task> / batch-5`. -->

All fifteen (task, batch size) cells reach M1 100 / M2 100 with 0 regressions
and the same corrective-edit count, so batch size never changes the verdict
here. Steps are identical at batch 3 and batch 5 on every task, because at
those sizes a Tier-A task is already only one or two batches wide — the cap
stops binding. Batch 1 costs extra steps only where it actually splits work
the larger batches fused: `task03` (11 vs 9) and `task05` (15 vs 11).
`task04` is flat at 17 across all three, because its import cycle is collapsed
into one atomic batch regardless of the cap (§3.2), so the batch count does
not move with the size.

The ablation's stated question — does a smaller batch localize failures
better? — is therefore not answered by this corpus: with the recovery loop
enabled no failure survives to be localized, and the arms differ only in step
count. A corpus with more files per contract unit would be needed to separate
them.

<!-- SOURCE: runs/benchmark/results.md §2D — every row across all five tasks reads
     "3× success | 100.0 | 100.0 | 100.0 | 100.0 | 0" for outcome / M1 recall / prec / F1 / M2 / regr. -->

## 7.6 Ablation C — live models

Not run. `edit-v4-pro` and `edit-v4-flash` need a live key and two models; both
read *requires key* in `results.md` §2C and are absent from
`results.json.rows` rather than estimated. 10 (task, config) pairs are
recorded as skipped. The offline matrix is complete without them.

One caveat is recorded for when they do run: the router bills an *edit* to the
pro tier whatever `MRA_EDIT_MODEL` names, so the cost column for the V4-Flash
arm will be an upper bound, not a quote.

<!-- SOURCE: runs/benchmark/results.md §2C "Edit model — V4-Pro vs V4-Flash" (the "Requires a key — not run"
     block and its billing caveat); results.json "skipped" list = 10 entries. -->

## 7.7 Edge-case suite — verdict accuracy

Unlike §7.1–§7.6, this subsection and the three after it draw on
`corpus/edge/results.json`, `runs/benchmark/ablation-e/results.json`, the two
blind tasks' `results.json` and the archived live evidence, not on the P5 matrix.

The agent at version 0.2.0 gives the expected verdict for the expected
reason on **39 of 39** edge cases (generated 2026-10-01T15:09:35Z). Building
the suite surfaced 17 defects in the verdict path, each now pinned by a
regression test that fails on the pre-fix code and passes on the current agent
(§8.1).

<!-- SOURCE: corpus/edge/results.json — agent_version "0.2.0", generated_at
     2026-10-01T15:09:35+00:00, passed 39, total 39 (also corpus/edge/RESULTS.md line 3).
     Defect count: the rows of the §8.1 fix table. -->

## 7.8 Ablation E — experience store

Ablation E holds the agent at its baseline configuration and varies only
memory. `memory-off` has no store. `memory-warm` uses a store warmed by running
the agent, learning on, over 27 edge-corpus tasks (the training split; no
Tier-A task), then frozen read-only so that no evaluation run learns from
another; warm-up stored 1 fix, of class `behaviour`. Both deterministic arms use
a corrector that can only replay recalled fixes, so the contrast measures
whether the store learns, retrieves and transfers a fix — not how much a model
gains from hints.

<!-- SOURCE: runs/benchmark/ablation-e/results.json experience_warmup — 27 train_tasks, fixes 1,
     by_class {"behaviour": 1}; runs/benchmark/ablation-e/results.md §2E prose. -->

| task | config | outcome | corrections | tokens | hints served | hint chars |
|---|---|---|---|---|---|---|
| task01_datetime | `memory-off` | 3× success | 0.0 | 0 | 0.0 | 0 |
| task01_datetime | `memory-warm` | 3× success | 0.0 | 0 | 0.0 | 0 |
| task02_datetime_aliased | `memory-off` | 3× gave_up | 3.0 | 0 | 0.0 | 0 |
| task02_datetime_aliased | `memory-warm` | 3× gave_up | 4.0 | 0 | 1.0 | 285 |
| task03_half_migration | `memory-off` | 3× gave_up | 3.0 | 0 | 0.0 | 0 |
| task03_half_migration | `memory-warm` | 3× success | 1.0 | 0 | 1.0 | 285 |
| task04_multimodule | `memory-off` | 3× gave_up | 9.0 | 0 | 0.0 | 0 |
| task04_multimodule | `memory-warm` | 3× success | 2.0 | 0 | 2.0 | 570 |
| task05_signature_break | `memory-off` | 3× success | 0.0 | 0 | 0.0 | 0 |
| task05_signature_break | `memory-warm` | 3× success | 0.0 | 0 | 0.0 | 0 |

<!-- SOURCE: runs/benchmark/ablation-e/results.md §2E "Experience store OFF vs pre-warmed", spliced
     verbatim (generated 2026-10-02T02:01:37Z, 3 repeats per task and config). -->

With nothing to replay, the control gives up on the three tasks that need a
corrective edit: `task02`, `task03` and `task04`. The warm store turns two of
them green — `task03` with 1 corrective edit and `task04` with 2, each run
served hints. On `task02` the store serves a hint, but the run still gives up
after 4 corrective edits. `task01` and `task05` need no correction in either
arm. In this matrix the live pair, which measures what hints are worth to a
model, has no key: its 10 (task, config) pairs are recorded as skipped. It was
run separately with `nvidia/nemotron-3-super-120b-a12b` via NVIDIA's API for
every role, 3 repeats, store warmed on the same training split: both arms go
green on 15 of 15 runs with the same 12 corrective edits, every edit written by
the model, at 30,023 tokens without hints and 30,850 with. On these tasks memory
changed neither outcome nor edit count for the live corrector.

<!-- SOURCE: runs/benchmark/live/results_live.json (live_model nvidia/nemotron-3-super-120b-a12b;
     memory-off-llm / memory-warm-llm rows: 15 success each, corrections sum 12 each,
     m3_tokens sum 30023 / 30850). -->

<!-- SOURCE: the table above — outcome, corrections and hints served per row;
     runs/benchmark/ablation-e/results.json "skipped" = 10 entries, reason "requires DEEPSEEK_API_KEY". -->

## 7.9 Blind held-out task

The agent was run on the blind task (§4.5) with the live model
`nvidia/nemotron-3-super-120b-a12b` for every role, memory and promoted
skills off, three repeats. It ends RED on **3 of 3** runs and meets 5 of 9
criteria, failing the same way every time. The codemod migrates both call
sites correctly. The one failing test is the `EPOCH` subtraction in
`report.py`, and no corrective edit is ever made: with recover tokens 0 in
every run, the patch-writing role is never called (§8.2).

| # | pass criterion | result | evidence (r1 / r2 / r3) |
|---|---|---|---|
| 1 | verdict GREEN | **FAIL** | RED ×3 |
| 2 | M1 recall and precision 100 %, decoys untouched | PASS | M1 100/100, decoys byte-identical ×3 |
| 3 | M2 100 %, 0 regressions, hidden semantic tests pass | **FAIL** | M2 87.5, 1 regr, hidden 1/2 ×3 |
| 4 | EPOCH fix made by the model | **FAIL** | EPOCH unchanged, recover tokens 0 ×3 |
| 5 | clock.py gains `timezone`, config.py no import | PASS | timezone added, config imports unchanged ×3 |
| 6 | patch touches only clock.py and config.py | PASS | 2 files, report.py untouched ×3 |
| 7 | test files untouched | PASS | byte-identical ×3 |
| 8 | re-run on own output: empty patch, GREEN, 0 model calls | **FAIL** | RED, patch empty, 0 calls ×3 |
| 9 | corrections ≤ 3; tokens and requests reported | PASS | corrections 3 ×3; tokens 2425 / 2282 / 2216; requests 6 ×3 |

<!-- SOURCE: corpus/blind/task06_scheduler/results.json (scored from runs/blind06-r{1,2,3}
     and runs/blind06-r{1,2,3}-rerun); the table is regenerated from it by verify_paper.py and
     must match byte for byte. Criterion 8 fails because the agent's own output starts red
     (7/8), so NB-10 refuses to migrate; the hidden tests are gold/tests/test_semantic.py. -->

This result is v0.2.0's: `src/` was frozen at `f97bf67`, whose `pyproject.toml`
reads version 0.2.0. `task06` has not been re-run since consequence repair was
added, and it cannot be re-run on the same model (§9).

<!-- SOURCE: `git show f97bf67:pyproject.toml` (version = "0.2.0"); `git log -- corpus/blind/task06_scheduler`
     (last result commit 10ebb17, no later re-run). -->

## 7.10 Second blind task, gold check and import accuracy

The agent at v0.3.0 was run on the second blind task (§4.6) the same way:
`nvidia/nemotron-3-super-120b-a12b` for every role, memory and promoted skills
off, three repeats. It ends GREEN on **3 of 3** runs and meets 9 of 9 criteria
on every run. The codemod migrates `stamp.py`; consequence repair puts
`store.py` in front of the model, which rewrites `load()` to
`fromisoformat(s)` in 1 correction per run, accepted on the first attempt. The
patch is the same in every run and equal to gold, and the hidden semantic
suite passes 6/6 on it. Re-run on its own output, the agent makes an empty
patch with 0 model calls and stays GREEN. Tokens per run were 3327 / 3753 /
3206, of which the patch-writing role spent 2200 / 2053 / 2031. No attempt was
rejected, so the anti-reversal guard was not exercised live.

<!-- SOURCE: corpus/blind/task07_cache/results.json (r1-r3: verdict, m1_recall, m1_precision,
     m2_pass_rate, m2_regressions, decoy_untouched, hidden_semantic, store_changed, store_load_line,
     imports_unchanged, patch_files, tests_untouched, rerun, corrections, tokens, recover_tokens,
     agent_version 0.3.0); the nine criteria of corpus/blind/task07_cache/results/RESULTS.md, each
     re-derived from results.json by verify_paper.py. -->

**Gold check.** Every archived live final tree, the 30 ablation-E runs (§7.8)
and the 6 `task07` runs including the re-runs, was compared with its task's
`gold/`: **36 of 36** are clean. None is shorter than gold, none misses a gold
function or class, no hunk falls outside the call sites, gold's consequence
lines and the imports, and tests and config are byte-identical to `old/`. Four
faults planted in one run were all flagged, so the check is not blind.

<!-- SOURCE: runs/benchmark/live/evidence/GOLD_CHECK.md — "Result: 36 runs, 36 clean", the
     per-run table (36 rows, verdict clean) and "Planted faults" (4 flagged). -->

**Import accuracy.** M1 scores call sites, so an import edit is invisible to
it. A separate metric scores each run's import edits against the task's
`expected_import_changes`. Of the 33 scorable runs (the 3 `task07` re-runs
start from the agent's own output and are not scored), **32 of 33** score
100 %. The one that does not is `task02` warm r1, at 0 %: in the memory-warm
arm the model added `from datetime import timezone` to a module that already
reaches `timezone` through `import datetime as dt`. That import is redundant,
and the code is functionally equivalent to gold; its M1 precision is still 100.

<!-- SOURCE: runs/benchmark/live/evidence/GOLD_CHECK.md "Import accuracy (docs/05 §2.3a)" table
     (33 scored rows: 32 at 100.0%, memory-warm-llm-task02_datetime_aliased-r1-f2d390 at 0.0% with
     spurious src/pkg/report.py: +timezone) and "Notes" (m1_precision 100.0 for that run);
     docs/05_DATA_EVALUATION_PROTOCOL.md §2.3a. -->
---

# 8. Failure Analysis

Of 165 runs, **42 did not reach green**, collapsing to **14 distinct
(configuration, task) pairs** once the three identical repeats of each
deterministic outcome are folded together.

<!-- SOURCE: runs/benchmark/failure-analysis.md header, "42 of 165 runs failed";
     the file lists 14 "## `<config>` on <task>" entries. -->

**Every failing pair has the recovery loop disabled.** All 14 come from four
configuration families — `no-recovery` and the three `*-b1-norecovery` arms —
and no configuration with the loop enabled appears anywhere in the failure
analysis. That is the same result as claim (a), read from the other end.

<!-- SOURCE: runs/benchmark/failure-analysis.md — the 14 entry headings name only the configs
     no-recovery, order-dependency-b1-norecovery, order-alphabetical-b1-norecovery,
     order-fr3-violating-b1-norecovery. -->

**By failure class, the distribution is degenerate: all 26 surviving failures
across the 14 pairs classify as `behaviour`, and all 26 carry `TypeError`.**
This is a property of the corpus rather than of the classifier. Every task
migrates the same contract, and a half-migrated tz-awareness contract always
surfaces as a `TypeError` — either from a datetime operation or, in `task05`,
from the explicit contract guard. The taxonomy's other three classes
(`import`, `signature`, `assertion`) are unexercised, and a corpus that
exercises them is future work (§9).

<!-- SOURCE: runs/benchmark/failure-analysis.md — every "surviving failures" bullet across all 14
     entries reads "**behaviour** break, `TypeError`". Count of 26 obtained by summing the
     surviving-failure bullets over the 14 entries (1+1+3+1+1+3+1+1+3+3+1+1+3+3). -->

**By why recovery did not happen**, all 14 pairs carry the same reason:
*"recovery disabled: the run gives up on the first red suite, so the remaining
batches are never edited."* **No run anywhere in the matrix gave up by
exhausting the retry cap.** The highest `fix_attempts` counter observed is
exactly `MAX_FIX_ATTEMPTS = 3`, reached on one signature
(`2773f89c64a8ae65`) by both dependents-first arms on `task04_multimodule` —
and both finish **green**, because the third corrective edit turns the suite
green before the router is asked to take `give_up` (§7.4). Every failure in
this section is a *disabled* loop, never an exhausted one, so this matrix says
nothing about whether 3 is the right ceiling.

<!-- SOURCE: runs/benchmark/failure-analysis.md — the "why it was not recovered" line of all 14 entries
     reads "recovery disabled (ablation A|B)". Cap figures from results.json: max over all 165 rows of
     max(fix_attempts.values()) == 3, attained only by order-fr3-violating / task04_multimodule and
     order-fr3-violating-b1 / task04_multimodule (outcome "success" in all 6 rows); no row with
     outcome "gave_up" has any fix_attempts entry >= 3. -->

**The two shapes of break.** The 14 pairs divide into two failure geometries
that the node IDs distinguish without ambiguity:

- **Call-time failures (13 pairs).** The failing node IDs carry a
  `::test_name` component: the module imported, the test ran, the contract
  broke inside it. M2 degrades proportionally — 80.0 %, 85.7 %, 72.7 %,
  78.6 % depending on how much of the suite touches the half-migrated path.
- **Import-time failures (1 pair).** `order-alphabetical-b1-norecovery` on
  `task05_signature_break`: all three failing node IDs are whole test modules
  with no `::`, because `pkg.boot` raises while being imported. M2 collapses
  to 0.0 % with 14 regressions — the entire suite, not a subset.

<!-- SOURCE: runs/benchmark/failure-analysis.md — nodeid fields of every entry; the single entry whose
     nodeids lack "::" is "`order-alphabetical-b1-norecovery` on task05_signature_break" (M2 0.0%, 14 regr).
     M2 values from the "M1 recall / M2" line of each entry. -->

That single import-time pair is the whole of claim (c-i), and its rarity is
the honest measure of how much the corpus supports the ordering argument: one
designed fixture, one arm, one geometry of break.

**M1 recall under failure is not monotone in order.** The `no-recovery` arms
stop at the first red suite, so M1 recall records how many batches landed
before the break — which depends on where the break sits in that particular
order, not on the order's quality. On `task03` the dependency order records
the *lowest* recall of the three (33 % vs 67 %), because it breaks earlier;
on `task04` the dependents-first order records the lowest (33 % vs 67 %).
Recall under a disabled loop is therefore a diagnostic of break position, and
only the outcome column carries the ordering verdict.

<!-- SOURCE: runs/benchmark/results.md §1, rows task03_half_migration / order-dependency-b1-norecovery
     (M1 33.3) vs / order-alphabetical-b1-norecovery and / order-fr3-violating-b1-norecovery (M1 66.7);
     task04_multimodule / order-fr3-violating-b1-norecovery (M1 33.3) vs the other two (M1 66.7). -->

## 8.1 Verdict-accuracy defects found by the edge suite

The failures above are migration failures. The edge suite (§4.4) tested
something else — whether the verdict can be trusted — and building it surfaced
17 defects in the verdict path itself. A defect is counted only if a regression
test pins it: the test, as committed with the fix, fails on the code before
the fix and passes on the current agent. The most serious was in the test
oracle.

<!-- SOURCE: the fix table below (one row per defect). Method: tests/ as of commit bb1dd07 run
     against src/ as of bb1dd07^ (every listed test fails; ProviderError stubbed so
     tests/test_providers.py imports), and the same tests at HEAD (all pass). -->

**The oracle defect.** The pre- and post-migration suites of one run share an
output directory. When the post-migration suite hung and the sandbox killed it
at the timeout, pytest wrote no new report, and the runner read the report
still in the directory in its place: the green pre-migration one. A hung suite
was reported as passing. The fix deletes stale outputs before every sandbox
run, and its regression test hangs a suite after a green run and asserts that
the timeout is what gets reported.

<!-- SOURCE: commit bb1dd07, "sandbox" bullet; src/mra/sandbox/runner.py, the stale pytest_raw.json /
     ruff.json / coverage.json unlink before each run; found by edge case edit_causes_infinite_loop. -->

| class | defect fixed | regression test |
|---|---|---|
| test oracle | a suite killed by the timeout was read from the stale pre-migration report | `test_sandbox.py::test_timeout_after_a_green_run_is_not_read_as_green` |
| preconditions | a red pre-migration suite did not name the missing network when that was the cause | `test_report.py::test_precondition_names_the_network_when_that_is_the_cause` |
| analysis | test files could enter MAP's work list (NB-4) | `test_analyzer.py::test_map_never_puts_a_test_file_on_the_work_list` |
| analysis | unparseable and non-UTF-8 files crashed the scan | `test_analyzer.py::test_unparseable_and_latin1_files_do_not_crash_the_scan` |
| analysis | relative imports did not resolve against the file's package | `test_analyzer.py::test_relative_import_resolves_against_the_files_package` |
| analysis | re-exports through a package `__init__` did not resolve | `test_analyzer.py::test_reexport_through_package_init_resolves` |
| codemod | rewrites were not confined to the analyzer's positions (a shadowed `datetime` was edited) | `test_report.py::test_given_sites_only_those_calls_change` |
| codemod | `utcfromtimestamp(t)` was neither found nor rewritten to `fromtimestamp(t, timezone.utc)` | `test_analyzer.py::test_utcfromtimestamp_is_part_of_the_family`, `test_report.py::test_utcfromtimestamp_gains_the_timezone_argument` |
| codemod | CRLF line endings were lost in the rewrite | `test_report.py::test_crlf_survives_a_bytes_round_trip` |
| codemod | an aliased import got no `timezone` import of its own | `test_report.py::test_aliased_import_gets_its_own_timezone_line` |
| codemod | a new import was not placed where isort puts it (a new I001) | `test_report.py::test_new_timezone_import_lands_where_isort_puts_it` |
| verdict | the lint delta was keyed on message text, which quotes the edited code | `test_report.py::test_lint_message_text_is_not_part_of_the_key` |
| verdict | precision was judged when nothing was edited | `test_report.py::test_precision_is_not_judged_when_nothing_was_edited` |
| verdict | an unreachable provider and a privacy refusal had no RED reason of their own | `test_report.py::test_unreachable_provider_and_refusals_have_their_own_reasons` |
| verdict | a CRLF file rewritten as LF passed unnoticed (no line-endings check) | `test_report.py::test_semantic_check_catches_unimported_tz_and_new_naive_now` |
| router | under local-only, an all-remote role was not refused at construction | `test_providers.py::test_local_only_refuses_an_all_remote_role_at_construction` |
| router | when every provider failed, the error did not name each one | `test_providers.py::test_last_error_surfaces_when_every_link_fails` |

<!-- SOURCE: commit bb1dd07 (fix bullets) and its tests/ diff; the line-endings (verdict) and
     every-provider (router) rows use existing tests the commit extended, the rest are new. Each
     test fails on bb1dd07^ and passes at HEAD. I001 is ruff's import-order rule. -->

The same commit made four further changes that no regression test pins: a
red or empty pre-migration suite now stops the run before any edit, re-running
a run ID no longer appends to the old checkpoint database, run directories
start clean, and suite-red evidence names the failure type. They are not
counted.

**The published P5 results did not depend on any of them.** After the fixes,
the 165-row matrix was re-run and its scientific payload matched
`results.json` exactly, 165 of 165 rows. Some fixes changed the edit path, but
none changed a Tier-A outcome or metric; every figure in §7.1–§7.6 stands as
published.

<!-- SOURCE: commit bb1dd07 body, "Benchmark matrix re-run: results.json scientific payload
     identical (165/165)". -->

## 8.2 Consequence break off call sites

The blind task (§7.9) exposes a failure class the Tier-A matrix cannot show,
because every Tier-A break sits in a file that still holds a deprecated call.
Call it a **consequence break off call sites**: the migration is correct at
every call site, and the break it causes lies in code that holds none. In
`task06` the codemod makes `clock.now()` aware, and `report.age_days()` then
subtracts the naive constant `config.EPOCH` from it.

In v0.2.0, CORRECT cannot reach this break. Before asking the model for a patch, its
`locate()` re-runs MAP over the current tree to choose the file to repair, and
it returns nothing when no residual call site remains. The corrector then
records "nothing left to migrate" and returns without a patch. Each attempt
spends one `classify` call and one `summarize` call, makes no `recover` call,
and changes no file. After 3 attempts on the same failure signature, the loop
gives up. This happened in all 3 runs. The model's ability is not what is being
measured here: the failing file is never put in front of it.

**The failure was safe.** The agent made no wrong edit: the patch touches only
the two call-site files, both migrated correctly, and `report.py`, where a
wrong fix would land, is untouched. The test files are byte-identical to
`old/`. Recovery stopped at the retry cap rather than looping, and the verdict
is RED, so the run reports that it did not finish rather than passing as
green.

<!-- SOURCE: corpus/blind/task06_scheduler/results.json — correct_attempts: max attempt 3,
     changed [] in every attempt; tokens_by_role has only classify and summarize; patch_files
     = [src/app/clock.py, src/app/config.py]; report_py_edited false; tests_untouched true;
     verdict RED in all 3 runs. Mechanism: src/mra/nodes/correct_node.py locate() returns None
     when find_in_repo finds no residual site, and LLMCorrector.__call__ returns [] before
     corrective_patch. Re-derived by verify_paper.py. -->

## 8.3 The v0.3.0 bug hunt

A find-only bug hunt was run against v0.3.0, with property-based fuzzing of the
codemod, metamorphic tests (renamed, reordered and relocated trees, other line
endings), hostile model replies, environment faults and security probes. It
found **19** bugs: 2 critical, 6 high, 6 medium and 5 low. Each is reproduced
by a strict-xfail test under `tests/hunt/`, so a fix turns its marker into a
failure and cannot go unnoticed. **All 8 critical and high bugs are fixed in
v0.4.0** (§3.5), and so are BUG-18 (medium) and BUG-19 (low); 5 medium and 4 low
remain open (§9).

<!-- SOURCE: BUGS.md — the bug table (19 rows; severity column: critical 2, high 6, medium 6,
     low 5) and the "Fixed" list; open bugs = the strict xfails left in tests/hunt/ (bug("BUG-NN")),
     re-derived by verify_paper.py. -->

**None of the bugs affected a published number.** `results.json`, the source
of every figure in §7.1–§7.6, is unchanged since it was published in commit
`c4815e8`, and re-running the offline matrix on v0.4.0 reproduces its payload
in 165 of 165 rows. The
live and blind figures (§7.8–§7.10) come from runs whose final trees the gold
check compared with gold: all 36 are clean, so no dropped file tail,
overwritten module or copied-in outside file reached them.

<!-- SOURCE: runs/benchmark/results.json unchanged since commit c4815e8 (`git diff --quiet c4815e8
     HEAD -- runs/benchmark/results.json`, checked by verify_paper.py); BUGS.md "Fixed" (matrix
     re-run line); runs/benchmark/live/evidence/GOLD_CHECK.md "Result: 36 runs, 36 clean". -->

**One check had silently stopped asserting.** `test_ctrl_c_mid_batch`
interrupts a run and then looks for containers it left behind, filtering by
the name `^mra-intr$`. Once run IDs became unique per test and container names
gained a per-invocation suffix, no container could match that filter, and the
test passed whatever was left. Fixed to match `^mra-<run_id>-`, it exposed a
real leak, BUG-19: the interrupted client's create can land after the
cleanup's `rm -f`, leaving a container in the Created state. Cleanup now
retries the removal for up to 5 seconds.

<!-- SOURCE: commit 7fac1e6 message and diff (tests/hunt/test_env_faults.py leftover filter;
     src/mra/sandbox/runner.py retry window); BUGS.md BUG-19. -->

---

# 9. Limitations

These limitations bound what the results support. They are stated here in
full rather than distributed through the paper.

1. **One migration family.** All five tasks migrate the same contract,
   `datetime.utcnow()` → `datetime.now(timezone.utc)`. Holding it fixed is
   what makes each task's varied factor attributable, but it means the
   failure taxonomy is exercised in one class only (§8: 26/26 `behaviour`),
   and that conclusions about batching and recovery generalize no further
   than one migration contract on a corpus of this size.
   <!-- SOURCE: runs/benchmark/failure-analysis.md — all 26 surviving-failure bullets across the
        14 entries read "**behaviour** break, `TypeError`". Contract from corpus/tierA/*/task.yaml
        (source_api: datetime.utcnow, target_api: datetime.now(timezone.utc)) in all five tasks. -->

2. **One fixed codemod, so arity changes are not expressible.** The agent's
   edit path is a deterministic `libcst` codemod (§3.3). A migration that
   adds or renames a parameter on a *first-party* function — threading a new
   argument through every call site — cannot be represented, because the gold
   state would be unreachable by the only transform the agent can apply.
   `task05` therefore realizes the ordering property through a contract guard
   rather than an arity mismatch (§4.3). The property under test is intact;
   the mechanism is a substitute, and the offline classifier records the
   consequence by filing the failure as `behaviour` rather than `signature`.

3. **Tier A only — no real repository yet.** The corpus is authored, not
   sampled. That buys total ground truth (`ground_truth.json` is the complete
   set $A$, not a proxy) and clean attribution, at the cost of external
   validity. The Tier-B protocol — take a real migration pull request, use its
   parent commit as the "before" state and the merged diff as the gold patch —
   is specified in `docs/05` §1.3 but not yet executed. Until it is, nothing
   here is evidence about repositories the authors did not write.

4. **The live-model arms sit outside the paper's matrix.** Ablation C has not
   been run: the live runs used one model, `nvidia/nemotron-3-super-120b-a12b`
   via NVIDIA's API, so it has no second arm (§7.6). The live pair of ablation E
   was run separately and matched the deterministic outcomes (§7.8). Every
   number in this paper's tables comes from the deterministic corrector, which shares the loop's
   mechanics with the LLM corrector but not its patch generator. The claim
   this supports is about the *loop*, not about a model's ability to write a
   patch; the two are not interchangeable and no result here should be read
   as the latter. The live model is no longer served to this project's API
   account, so no live run here can be repeated on the same model; that
   includes re-running `task06` with consequence repair.
   <!-- SOURCE: runs/benchmark/live/evidence/GOLD_CHECK.md "Model availability (2026-10-29)" — the
        provider's 404 "Not found for account" for the model's function; model name from
        runs/benchmark/live/results_live.json and corpus/blind/task07_cache/results/RESULTS.md. -->

5. **The ordering claim rests on one designed fixture.** `task05` was built
   *after* `task01`–`task04` failed to separate the orders, specifically to
   exercise ablation B. It is a constructed instance, not a sample: it shows
   that dependency order *can* be the difference between a green migration and
   a failed one, not how often that situation arises in practice. The
   complementary negative result is equally part of the finding — with the
   recovery loop enabled, no order changed the verdict on any task (§7.4
   c-iii), and on `task04` an arbitrary order was measurably *cheaper* than
   the dependency order.

6. **Three known YELLOW gaps.** The agent leaves three patterns unmigrated and
   says so rather than guessing: a bare reference to `datetime.utcnow` that is
   stored or passed without being called; a deprecated call reached through a
   star import; and a deprecated call inside a test file, which the agent may
   not edit because the tests are the oracle (NB-4). The residual check finds
   each site and the verdict is YELLOW, never GREEN; the edge suite asserts
   exactly that in `bare_reference`, `star_import` and
   `deprecated_call_in_test_file`. The gaps are reported, not silent, but a
   reviewer has to finish those sites by hand.
   <!-- SOURCE: corpus/edge/results.json — cases bare_reference, star_import and
        deprecated_call_in_test_file: expected YELLOW, actual YELLOW, reason code "residual";
        corpus/edge/<case>/case.json "note" fields. -->

7. **Consequence repair rests on one task.** Through v0.2.0 recovery
   repaired residual call sites only, and on the first blind task, whose
   break lies off the call sites, the agent stopped RED on every run, without
   a wrong edit (§8.2). v0.3.0 added consequence repair (§3.5), and the second
   blind task is its only measurement: 3 of 3 runs GREEN (§7.10). One task
   cannot say how often the repair scope finds the right file in real
   migrations. The anti-reversal guard was never exercised live, and an
   offline probe on `task07` shows it rejects only one of that task's two
   wrong-fix shapes (stripping `tzinfo`); the visible suite, not the guard,
   stops the offset-dropping ones.
   <!-- SOURCE: corpus/blind/task06_scheduler/results.json (verdict RED in every run);
        corpus/blind/task07_cache/results.json (verdict GREEN r1-r3); corpus/blind/task07_cache/
        results/RESULTS.md "The guard against this task's wrong fixes" (strip tzinfo rejected; slice
        and literal +00:00 format accepted). -->

8. **Open bugs.** Of the 19 bugs the hunt found (§8.3), 5 medium and 4 low
   are open, each pinned by a strict xfail. Medium: BUG-01 (a class reached
   through an in-repo module gets a broken `timezone` reference), BUG-03 (an
   unparseable residual reply ends the run instead of costing one attempt),
   BUG-06 (the residual-count guard accepts a net-zero reintroduction),
   BUG-08 (a stopped Docker daemon is reported as a red pre-migration suite)
   and BUG-13 (a secret in diff context reaches `report.json` and the PDF).
   Low: BUG-02 (an alias named `timezone` is clobbered), BUG-14 (a read-only
   runs directory ends in a traceback), BUG-15 (the codemod writes through a
   symlinked file when called directly) and BUG-16 (Cyrillic and CJK paths
   vanish from the PDF).
   <!-- SOURCE: BUGS.md bug table (severity per ID) and "Fixed" list; the bug("BUG-NN") strict
        xfail markers in tests/hunt/, re-derived by verify_paper.py. -->

9. **Report size.** The PDF report is capped at 14 pages. The truncation
   ladder fits a 1,000-file run into exactly 14, so a larger run can still
   exceed the cap, and then it gets no PDF.
   <!-- SOURCE: src/mra/report/pdf.py MAX_PAGES = 14 and the RuntimeError after the last ladder
        level; BUGS.md BUG-17 fix (500 files → 12 pages, 1,000 → 14). -->

10. **The run lock is POSIX only.** The per-run lock uses `fcntl.flock`, which
    exists on Linux and macOS. On Windows the report module does not import.
    <!-- SOURCE: src/mra/report/__init__.py `import fcntl` and its ponytail note. -->

A smaller caveat: suites of 5–14 tests make M2 coarse. A single
collection error takes out an entire module, which is why regressions are
reported as a count alongside the percentage (§5.2).

<!-- SOURCE: runs/benchmark/results.md §3, "suite after fix" column of the ruff (DTZ) rows:
     5/5 (task01, task02) to 14/14 (task05). -->

---

# 10. Conclusion

> **STUB — outline only. Do not ghost-write.**

- Restate what was built and what was measured, in two sentences, without
  new claims.
- The one-line version of each result: loop load-bearing; static tools detect
  but do not fix; ordering is cost in general and correctness in the
  constructed case.
- The methodological point worth generalizing: an ablation is only as good as
  the fixture that can separate its arms — `task01`–`task04` could not
  separate the orders, and building `task05` was a *result*, not a detour.
- Future work, one clause each: Tier-B external validity; a second migration
  family to exercise the rest of the failure taxonomy; the live-model arms;
  an editor expressive enough to represent arity changes.
- Closing sentence — no new claims.

---

# References

> **STUB.** To be filled from `docs/02_LITERATURE_REVIEW.md` once each entry
> is verified. Every `[CITE: ...]` placeholder in §2 must resolve to an entry
> here. Do not add a reference that has not been checked against the source.
