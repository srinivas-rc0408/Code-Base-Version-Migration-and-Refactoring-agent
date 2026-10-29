# Graph Report - mra  (2026-10-29)

## Corpus Check
- 579 files · ~230,601 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 4125 nodes · 6291 edges · 308 communities (216 shown, 92 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 358 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `846b33c9`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- SandboxRunner
- analysis/__init__.py
- test_analyzer.py
- Project Synopsis & Charter
- make_timestamp
- make_timestamp
- Migration Agent — Master Resource Pack
- make_timestamp
- make_timestamp
- 2. Low-Level Design (LLD) — the LangGraph state machine
- Data & Evaluation Protocol
- Software Requirements Specification (SRS)
- call_sites.py
- test_p2_end_to_end.py
- Literature Review & State of the Art
- paper.md
- task05_signature_break — Tier-A edit-order fixture
- CLAUDE.md
- README.md
- task01_datetime/gold/src/pkg/__init__.py
- task01_datetime/old/src/pkg/__init__.py
- task02_datetime_aliased/gold/src/pkg/__init__.py
- task02_datetime_aliased/old/src/pkg/__init__.py
- pkg
- pkg
- pkg
- pkg
- mra
- imports.py
- graph.py
- cli.py
- correct_node.py
- test_p4_graph.py
- test_recovery.py
- test_benchmark.py
- make_timestamp
- verdict
- make_timestamp
- baselines.py
- test_consequence.py
- recover
- issue
- gold_check.py
- post
- task04_multimodule/gold/src/pkg/audit.py
- task04_multimodule/old/src/pkg/audit.py
- issue
- Product Requirements Document (PRD)
- Codebase-Wide Version Migration & Refactoring Agent (MRA)
- make_timestamp
- old/src/pkg/api.py
- post
- make_timestamp
- KeyedProvider
- ExperienceStore
- handle
- old/src/pkg/ledger.py
- test_providers.py
- gold/src/pkg/api.py
- datetime_utcnow.py
- plan_batches
- Failure analysis
- test_issue_stamps_and_posts
- task03_half_migration/gold/src/pkg/__init__.py
- task03_half_migration/old/src/pkg/__init__.py
- task04_multimodule/gold/src/pkg/__init__.py
- task04_multimodule/old/src/pkg/__init__.py
- pkg
- pkg
- pkg
- pkg
- providers/__init__.py
- model.py
- snapshot
- 1b. Per task, per configuration
- post
- elapsed_since
- post
- elapsed_since
- serve
- uptime_s
- apply_codemod
- uptime_s
- benchmark/runner.py
- handle
- snapshot
- handle
- old/tests/test_timebase.py
- pdf.py
- verify_paper.py
- check_invariants
- verdict.py
- task05_signature_break/gold/src/pkg/__init__.py
- task05_signature_break/old/src/pkg/__init__.py
- pkg
- pkg
- evidence.py
- _Skipped
- Router
- test_experience.py
- test_report_robustness.py
- OpenAICompatibleProvider
- edge.py
- skills.py
- CodemodContext
- 1b. Per task, per configuration
- _ImportCollector
- test_many.py
- _build.py
- stamp
- stamp
- stamp
- stamp
- a.py
- test_all
- other_object_with_utcnow/old/src/pkg/core.py
- shadowed_local_name/old/src/pkg/core.py
- stamp
- llm_server
- test_all
- stamp
- stamp
- stamp
- stamp
- stamp
- stamp
- stamp
- job
- stamp
- stamp
- stamp
- test_both
- tests/test_report.py
- stamp
- stamp
- stamp
- stamp
- stamp
- stamp
- wait_for
- stamp
- label
- stamp
- stamp
- stamp
- test_long
- Clock
- crlf_line_endings/gold/src/pkg/core.py
- zero_tests/old/src/pkg/core.py
- RESULTS.md
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- pkg
- 1b. Per task, per configuration
- experience.py
- Gold check — live and blind07 runs
- migrate_task
- test_llm_payload_does_not_grow_with_the_repo
- edge_results_live.md
- edge_results_live_memory.md
- LLMCorrector
- test_hostile_replies.py
- test_edge.py
- repogen.py
- _codemod
- gold/src/app/clock.py
- old/src/app/clock.py
- load
- Contributors
- summarize
- gold/tests/test_timebase.py
- stamp
- new_state
- test_metamorphic.py
- 2. Ablations
- test_fuzz_codemod.py
- test_determinism.py
- ImportBindings
- ._with_keys
- What the Tier-A benchmark shows
- module_specs
- 1b. Per task, per configuration
- BUGS — v0.3.0 bug hunt (find only, nothing fixed)
- FakeClock
- FakeClock
- LegacyClock
- LegacyClock
- report/__init__.py
- Config
- fuzz_with_module_attribute_reexport/repo/pkg/m0.py
- task07_cache: blind held-out result #2 (2026-10-06)
- .complete
- test_ordinary_code_is_not_redacted
- h_Clock
- task06_scheduler/gold/tests/test_semantic.py
- task06_scheduler — blind held-out fixture
- task07_cache — blind held-out fixture #2
- pull_request_template.md
- task06_scheduler: blind held-out result (2026-10-06)
- run.sh
- app
- app
- svc
- svc

## God Nodes (most connected - your core abstractions)
1. `ExperienceStore` - 62 edges
2. `Router` - 52 edges
3. `run_migration()` - 33 edges
4. `LLMCorrector` - 32 edges
5. `migrate_task()` - 32 edges
6. `SandboxRunner` - 32 edges
7. `FakeProvider` - 30 edges
8. `run_one()` - 27 edges
9. `Endpoint` - 27 edges
10. `apply_codemod()` - 26 edges

## Surprising Connections (you probably didn't know these)
- `analyses()` --calls--> `analyze()`  [INFERRED]
  tests/test_analyzer.py → src/mra/analysis/analyzer.py
- `test_map_never_puts_a_test_file_on_the_work_list()` --calls--> `analyze()`  [INFERRED]
  tests/test_analyzer.py → src/mra/analysis/analyzer.py
- `test_fr3_property_holds_for_every_task_in_the_corpus()` --calls--> `analyze()`  [INFERRED]
  tests/test_p4_graph.py → src/mra/analysis/analyzer.py
- `test_task04_batches_are_dependency_ordered_and_collapse_the_cycle()` --calls--> `analyze()`  [INFERRED]
  tests/test_p4_graph.py → src/mra/analysis/analyzer.py
- `test_no_benchmark_run_touched_a_test_file()` --calls--> `is_test_path()`  [INFERRED]
  tests/test_benchmark.py → src/mra/analysis/call_sites.py

## Import Cycles
- None detected.

## Communities (308 total, 92 thin omitted)

### Community 0 - "SandboxRunner"
Cohesion: 0.06
Nodes (58): Phase, _exc_type_from(), _failure_from_collector(), _failure_from_test(), failure_signature(), _lint_counts(), needs_network(), normalize_message() (+50 more)

### Community 1 - "analysis/__init__.py"
Cohesion: 0.13
Nodes (24): analyze(), Collection, Path, MAP-node analysis: locate the work, map the dependencies. Nothing else.…, Scan ``repo`` for ``target`` and map its imports. Args: repo: repository root…, build(), from_state_adjacency(), module_index() (+16 more)

### Community 2 - "test_analyzer.py"
Cohesion: 0.13
Nodes (32): flat_sites(), Any, Flatten the per-file map into one list, the form ground truth uses., m1(), analyses(), _found(), _ground_truth(), _key() (+24 more)

### Community 3 - "Project Synopsis & Charter"
Cohesion: 0.17
Nodes (12): 10. Open items for first guide meeting, 1. Problem statement, 2. Proposed solution, 3. Scope and finalized migration targets, 4. Deliverables, 5. Success criteria (metrics), 6. Technology stack (summary), 7. Timeline (indicative, aligned to the build phases) (+4 more)

### Community 4 - "make_timestamp"
Cohesion: 0.12
Nodes (19): make_timestamp(), datetime, Timestamp helpers. Defines the contract that the migration changes., Return the current UTC time as a timezone-aware datetime., build_report(), datetime, Report building. Imports :mod:`pkg.core`, creating the cross-file dependency…, Return how many seconds ago ``generated_at`` was produced. (+11 more)

### Community 5 - "make_timestamp"
Cohesion: 0.12
Nodes (19): make_timestamp(), datetime, Timestamp helpers. Defines the contract that the migration changes., Return the current UTC time as a timezone-aware datetime., build_report(), datetime, Report building. Imports :mod:`pkg.core`, creating the cross-file dependency…, Return how many seconds ago ``generated_at`` was produced. Reads the clock… (+11 more)

### Community 6 - "Migration Agent — Master Resource Pack"
Cohesion: 0.09
Nodes (23): 0. Read this first — the one thing that will sink you, 10. Trap checklist (expanded with the version facts I found), 11. Questions for Dr Nimrita Koul (first meeting) — refined, 12. The paper plan (start the skeleton in week 1, not week 9), 13. Your one-sentence story (memorize it — this is the interview weapon), 1. Verified stack (checked 24 Aug 2026), 2.1 `datetime.utcnow()` → timezone-aware (EASY — build this first), 2.2 Python 3.8 → 3.12 modernization (EASY–MEDIUM, has a baseline) (+15 more)

### Community 7 - "make_timestamp"
Cohesion: 0.13
Nodes (17): make_timestamp(), datetime, Timestamp helpers. Defines the contract that the migration changes., Return the current UTC time as a naive datetime., build_report(), datetime, Report building. Imports :mod:`pkg.core`, creating the cross-file dependency…, Return how many seconds ago ``generated_at`` was produced. (+9 more)

### Community 8 - "make_timestamp"
Cohesion: 0.13
Nodes (17): make_timestamp(), datetime, Timestamp helpers. Defines the contract that the migration changes., Return the current UTC time as a naive datetime., build_report(), datetime, Report building. Imports :mod:`pkg.core`, creating the cross-file dependency…, Return how many seconds ago ``generated_at`` was produced. Reads the clock… (+9 more)

### Community 9 - "2. Low-Level Design (LLD) — the LangGraph state machine"
Cohesion: 0.10
Nodes (19): 1.1 Component diagram, 1.2 Component responsibilities, 1.3 Data flow (one task, happy path then recovery), 1.4 Key architectural decisions (ADR summary), 1. High-Level Design (HLD), 2.1 State machine diagram, 2.2 Nodes (contracts), 2.3 Conditional routing after TEST (the graded logic) (+11 more)

### Community 10 - "Data & Evaluation Protocol"
Cohesion: 0.10
Nodes (19): 1.1 Tier A — controlled repos you author (gold standard), 1.2 Tier A git-tagging strategy, 1.3 Tier B — real OSS repos (external validity), 1. Corpus specification, 2.1 M1 — Migration Completeness, 2.2 M2 — Post-Migration Test Pass Rate, 2.3 M3 — Token / Step Overhead, 2.3a Import accuracy (separate from M1) (+11 more)

### Community 11 - "Software Requirements Specification (SRS)"
Cohesion: 0.11
Nodes (18): 1.1 Purpose, 1.2 Definitions, 1.3 Actors, 1. Introduction, 2. Overall description, 3. Functional requirements, 4.1 `MigrationState` (the agent's working memory), 4.2 `ground_truth.json` (Tier-A scoring key) (+10 more)

### Community 12 - "call_sites.py"
Cohesion: 0.11
Nodes (28): bindings_of(), CallSite, _CallSiteVisitor, canonical(), dotted_path(), exports_of(), find_in_repo(), find_in_source() (+20 more)

### Community 13 - "test_p2_end_to_end.py"
Cohesion: 0.14
Nodes (27): _added_import_lines(), corpus_digests(), Any, fixture, needs_docker, parametrize, Path, TempPathFactory (+19 more)

### Community 14 - "Literature Review & State of the Art"
Cohesion: 0.15
Nodes (12): 1. Problem framing: version migration vs. issue resolution, 2. Deterministic refactoring tools — the baselines, 3.1 SWE-agent — the Agent-Computer Interface (ACI), 3.2 OpenHands (formerly OpenDevin) — CodeAct and the event stream, 3.3 Agentless — the pipeline counter-argument, 3.4 Summary comparison, 3. LLM-based software-engineering systems — the SOTA, 4. Evaluation methodology in the field (+4 more)

### Community 15 - "paper.md"
Cohesion: 0.05
Nodes (37): 10. Conclusion, 1. Introduction, 2. Related Work, 3.1 The state machine, 3.2 Dependency-ordered batching, 3.3 Codemod first, model second, 3.4 The verifier and the sandbox, 3.5 Recovery and the signature-based retry cap (+29 more)

### Community 16 - "task05_signature_break — Tier-A edit-order fixture"
Cohesion: 0.06
Nodes (27): task01_datetime — Tier-A controlled task, Test-oracle rule, The `pkg` name-collision gotcha, The two states live in one commit, Import changes: deliberately empty, Running the two states, task02_datetime_aliased — Tier-A controlled task, The cross-file break (+19 more)

### Community 17 - "CLAUDE.md"
Cohesion: 0.20
Nodes (9): Coding conventions, Commit conventions, Current phase / context, Golden rules (do not violate), How to run and test, Tech stack (fixed — verified Sep 2026), What this project is, When unsure (+1 more)

### Community 18 - "README.md"
Cohesion: 0.12
Nodes (8): 1. First-time setup, 2. Keys, 3. Providers and roles — `mra.toml`, 4. Configuration variables (non-secret), 5. Privacy, 6. Security rules, 7. CI / grading environments, Configuration & Secrets

### Community 28 - "imports.py"
Cohesion: 0.09
Nodes (26): apply_patch(), main(), Path, Import accuracy (docs/05 §2.3a) for archived runs, recomputed from their…, ``git diff`` text applied to ``{path: bytes}``; a strict, in-memory ``git…, task_dir(), _changes(), import_names() (+18 more)

### Community 29 - "graph.py"
Cohesion: 0.10
Nodes (35): all_batches_done(), build_graph(), _cap(), changed_files(), finish_node(), is_green(), _key(), outcome_of() (+27 more)

### Community 30 - "cli.py"
Cohesion: 0.13
Nodes (24): main(), memory(), providers_check(), The ``mra`` command. * ``mra run --task-dir DIR`` — migrate, verify, and write…, report(), run(), _show(), skills() (+16 more)

### Community 31 - "correct_node.py"
Cohesion: 0.08
Nodes (41): is_test_path(), True for anything that is part of the test oracle (NB-4)., format_hint(), apply_source(), classify(), classify_offline(), consequence_prompt(), consequence_scope() (+33 more)

### Community 32 - "test_p4_graph.py"
Cohesion: 0.08
Nodes (48): bad_corrector(), capped03(), corpus_digests(), fake_router(), FakeDeepSeek, graph03(), graph04(), _nodes() (+40 more)

### Community 33 - "test_recovery.py"
Cohesion: 0.07
Nodes (46): bad_corrector(), corpus_digest(), gave_up(), _nodes(), oracle_tampering_corrector(), Any, fixture, needs_docker (+38 more)

### Community 34 - "test_benchmark.py"
Cohesion: 0.08
Nodes (44): ablation_a(), ablation_b(), ablation_b_task05(), corpus_digests(), matrix(), Any, fixture, parametrize (+36 more)

### Community 35 - "make_timestamp"
Cohesion: 0.08
Nodes (28): audit_record(), audit_window(), datetime, Audit trail. Imports the clock contract and also reads the clock directly., Return the ``seconds``-long window ending now. Both ends come from the same…, Stamp an audit record from the shared clock., make_timestamp(), datetime (+20 more)

### Community 36 - "verdict"
Cohesion: 0.17
Nodes (18): ``{status, reasons}`` with RED > YELLOW > GREEN; see the module docstring., verdict(), _codes(), parametrize, Already migrated: nothing found, nothing expected., Already migrated: 0/0 is undefined, not over-editing., test_green_when_nothing_is_wrong(), test_lint_is_a_multiset_and_contract_exemptions_are_honoured() (+10 more)

### Community 37 - "make_timestamp"
Cohesion: 0.08
Nodes (26): audit_record(), audit_window(), datetime, Audit trail. Imports the clock contract and also reads the clock directly., Return the ``seconds``-long window ending now. Both ends come from the same…, Stamp an audit record from the shared clock., make_timestamp(), datetime (+18 more)

### Community 38 - "baselines.py"
Cohesion: 0.15
Nodes (24): baseline_table(), _detect_with_ruff(), Any, CompletedProcess, Path, pyupgrade_baseline(), The honesty check: what the existing static tools already do (docs/05, §2.2).…, Detect with ruff, then let it fix what it can, and score the result. (+16 more)

### Community 39 - "test_consequence.py"
Cohesion: 0.12
Nodes (21): AlwaysRed, corrector_replying(), Events, fenced(), migrated(), Any, fixture, parametrize (+13 more)

### Community 41 - "recover"
Cohesion: 0.15
Nodes (20): last_rejection(), model_calls(), The reason the corrector's most recent patch was rejected, if it was., The corrector's router call log, or [] for a corrector that asks no model., Truncation retries (BUG-05) among ``calls``: each is its own step and spend., retries(), Self-correction: the loop that turns a failing migration into a passing one., Corrector (+12 more)

### Community 42 - "issue"
Cohesion: 0.15
Nodes (13): issue(), Invoicing. Stamps with its OWN clock reading, not the shared one. That detail…, Post the amount to the ledger and return the invoice record., invoice_age_seconds(), Reporting. The module the batched migration is designed to leave behind., Issue an invoice and report how old it is., Seconds since the invoice was issued. Reads its *own* clock and subtracts…, summary() (+5 more)

### Community 43 - "gold_check.py"
Cohesion: 0.22
Nodes (16): check(), defs(), hunks(), is_import(), jobs(), main(), Any, Path (+8 more)

### Community 44 - "post"
Cohesion: 0.17
Nodes (13): balance(), post(), datetime, Double-entry ledger. Half of the import cycle with :mod:`pkg.audit`. ``import…, Record an entry, stamped from the shared clock, and note it in the audit trail., Sum of every amount posted to ``account``., The ``seconds``-long window ending now. Both ends come from one reading, so…, snapshot_window() (+5 more)

### Community 45 - "task04_multimodule/gold/src/pkg/audit.py"
Cohesion: 0.20
Nodes (10): note(), Audit trail. The other half of the import cycle with :mod:`pkg.ledger`., Append a message to the trail, stamped from the shared clock., Read the ledger back — the call that closes the cycle. ``checked_at`` is never…, reconcile(), trail(), Audit trail, and the call that closes the import cycle with the ledger., Exercises audit -> ledger, the other direction of the cycle. (+2 more)

### Community 46 - "task04_multimodule/old/src/pkg/audit.py"
Cohesion: 0.20
Nodes (10): note(), Audit trail. The other half of the import cycle with :mod:`pkg.ledger`., Append a message to the trail, stamped from the shared clock., Read the ledger back — the call that closes the cycle. ``checked_at`` is never…, reconcile(), trail(), Audit trail, and the call that closes the import cycle with the ledger., Exercises audit -> ledger, the other direction of the cycle. (+2 more)

### Community 47 - "issue"
Cohesion: 0.23
Nodes (10): issue(), Post the amount to the ledger and return the invoice record., invoice_age_seconds(), Reporting. The module the batched migration is designed to leave behind., Issue an invoice and report how old it is., Seconds since the invoice was issued. Reads its *own* clock and subtracts…, summary(), The tripwire. ``invoice_age_seconds`` is the only place in the package where… (+2 more)

### Community 48 - "Product Requirements Document (PRD)"
Cohesion: 0.17
Nodes (12): 10. Risks, 1. Problem, 2. Goal, 3. Non-goals, 4. Users / personas, 5. User stories, 6. Scope (in / out), 7. Success metrics (+4 more)

### Community 49 - "Codebase-Wide Version Migration & Refactoring Agent (MRA)"
Cohesion: 0.13
Nodes (15): Acknowledgements, Architecture at a glance, Codebase-Wide Version Migration & Refactoring Agent (MRA), Documentation index, Edge-case accuracy suite, Evaluation, License, LLM providers and privacy (+7 more)

### Community 50 - "make_timestamp"
Cohesion: 0.24
Nodes (9): make_timestamp(), datetime, The shared clock. Nothing in the package imports anything to provide it. Most-…, Return the current UTC time as a naive datetime., The shared clock. No assertion here may depend on the migration (NB-10)., The semantic check. Fails against ``old/`` — that is the point., test_make_timestamp_is_non_decreasing(), test_make_timestamp_is_timezone_aware() (+1 more)

### Community 51 - "old/src/pkg/api.py"
Cohesion: 0.18
Nodes (8): handle(), The entry point. Depends on report, audit and config — the graph's deepest…, Serve one request. ``served_at`` is this module's own, self-contained reading., Static settings. No clock, no in-repo imports — the graph's other root., How long a record is kept, in seconds., retention_seconds(), The entry point, exercising the whole import DAG in one call., test_handle_serves_a_complete_response()

### Community 52 - "post"
Cohesion: 0.22
Nodes (8): Invoicing. Stamps with its OWN clock reading, not the shared one. That detail…, balance(), post(), Record an entry, stamped from the shared clock, and note it in the audit trail., Sum of every amount posted to ``account``., Ledger, including its self-contained clock reading., test_balance_sums_only_that_account(), test_post_returns_a_stamped_entry()

### Community 53 - "make_timestamp"
Cohesion: 0.28
Nodes (7): make_timestamp(), datetime, The shared clock. Nothing in the package imports anything to provide it. Most-…, Return the current UTC time as a naive datetime., The shared clock. No assertion here may depend on the migration (NB-10)., test_make_timestamp_is_non_decreasing(), test_make_timestamp_returns_a_datetime()

### Community 54 - "KeyedProvider"
Cohesion: 0.28
Nodes (4): KeyedProvider, The variable whose key serves the next call., Common state: where it lives, which env vars hold its keys, how long to wait.…, Key variable names still in play, in order: set, and not refused.

### Community 56 - "ExperienceStore"
Cohesion: 0.14
Nodes (36): ExperienceStore, One SQLite file of past fixes. ``readonly`` serves hints but learns nothing., db(), Any, CaptureFixture, fixture, MonkeyPatch, needs_docker (+28 more)

### Community 57 - "handle"
Cohesion: 0.33
Nodes (6): handle(), Serve one request. ``served_at`` is this module's own, self-contained reading., The entry point, exercising the whole import DAG in one call., Syntactic success is not success: no module may be left on a naive clock., test_every_stamp_in_one_response_is_aware(), test_handle_serves_a_complete_response()

### Community 58 - "old/src/pkg/ledger.py"
Cohesion: 0.33
Nodes (6): datetime, Double-entry ledger. Half of the import cycle with :mod:`pkg.audit`. ``import…, The ``seconds``-long window ending now. Both ends come from one reading, so…, snapshot_window(), Both ends come from one reading — safe whichever side of the migration., test_snapshot_window_is_ordered()

### Community 59 - "test_providers.py"
Cohesion: 0.16
Nodes (23): FakeProvider, Answers from ``reply(messages, model)`` (default: echo the last message).…, Any, Provider layer, router fallback, privacy mode, redaction, egress — all offline.…, _router(), test_auth_failure_moves_to_the_next_key(), test_config_rejects_a_role_naming_an_undefined_provider(), test_egress_counts_calls_and_bytes_per_remote_host() (+15 more)

### Community 60 - "gold/src/pkg/api.py"
Cohesion: 0.33
Nodes (4): The entry point. Depends on report, audit and config — the graph's deepest…, Static settings. No clock, no in-repo imports — the graph's other root., How long a record is kept, in seconds., retention_seconds()

### Community 61 - "datetime_utcnow.py"
Cohesion: 0.09
Nodes (21): FlattenSentinel, SimpleStatementLine, ConvertUtcnowCommand, _import_key(), _InsertTimezone, _place_timezone_import(), BaseExpression, Call (+13 more)

### Community 62 - "plan_batches"
Cohesion: 0.15
Nodes (20): _chunk(), cycles(), plan_batches(), plan_node(), Any, DiGraph, PLAN node: turn the dependency graph into an ordered list of edit batches…, ``MigrationState`` -> ``edit_batches`` (+ the audit note for this step). (+12 more)

### Community 63 - "Failure analysis"
Cohesion: 0.13
Nodes (15): Failure analysis, `no-recovery` on task02_datetime_aliased, `no-recovery` on task03_half_migration, `no-recovery` on task04_multimodule, `order-alphabetical-b1-norecovery` on task02_datetime_aliased, `order-alphabetical-b1-norecovery` on task03_half_migration, `order-alphabetical-b1-norecovery` on task04_multimodule, `order-alphabetical-b1-norecovery` on task05_signature_break (+7 more)

### Community 73 - "providers/__init__.py"
Cohesion: 0.15
Nodes (12): AnthropicProvider, Message, Anthropic's native Messages API, through the pinned ``anthropic`` SDK. The…, Completion, Provider, Message, Protocol, TypedDict (+4 more)

### Community 74 - "model.py"
Cohesion: 0.14
Nodes (30): build_model(), _changes(), _checks(), _edge_row(), _egress_line(), _files(), _from_state_db(), _graph() (+22 more)

### Community 75 - "snapshot"
Cohesion: 0.16
Nodes (10): The service edge: the deepest module in the import DAG., One request, its ledger entry and a metrics snapshot., serve(), Point-in-time metrics over the ledger., Entry count plus how long this reading took to assemble., snapshot(), The service edge: every module in the DAG on one call path., test_serve_returns_the_whole_response() (+2 more)

### Community 76 - "1b. Per task, per configuration"
Cohesion: 0.10
Nodes (20): 1. The whole offline matrix, 1b. Per task, per configuration, 2. Ablations, 3. Deterministic baselines — ruff (DTZ) and pyupgrade, 4. Configuration key, A. Recovery loop ON vs OFF — the headline, B. Dependency-ordered batching vs arbitrary order, batch size 1, recovery OFF (+12 more)

### Community 77 - "post"
Cohesion: 0.24
Nodes (8): age_of(), post(), Append-only ledger. Stamps entries with its own clock reading., Record one amount against an account and return the entry., Seconds since ``entry`` was posted. Hands this module's own stamp back to the…, The ledger and the call-time half of the break., test_age_of_an_entry_is_non_negative(), test_post_records_the_amount()

### Community 78 - "elapsed_since"
Cohesion: 0.33
Nodes (9): aligned(), elapsed_since(), datetime, The package clock, and the one place its contract is enforced. Every module…, The current UTC time, in whatever shape the package contract is in., Read ``stamp`` in the shape ``reference`` is in. Upgrades only, never…, Seconds between ``stamp`` and now, for a stamp this package produced. The…, utc_now() (+1 more)

### Community 79 - "post"
Cohesion: 0.24
Nodes (8): age_of(), post(), Append-only ledger. Stamps entries with its own clock reading., Record one amount against an account and return the entry., Seconds since ``entry`` was posted. Hands this module's own stamp back to the…, The ledger and the call-time half of the break., test_age_of_an_entry_is_non_negative(), test_post_records_the_amount()

### Community 80 - "elapsed_since"
Cohesion: 0.33
Nodes (9): aligned(), elapsed_since(), datetime, The package clock, and the one place its contract is enforced. Every module…, The current UTC time, in whatever shape the package contract is in., Read ``stamp`` in the shape ``reference`` is in. Upgrades only, never…, Seconds between ``stamp`` and now, for a stamp this package produced. The…, utc_now() (+1 more)

### Community 81 - "serve"
Cohesion: 0.25
Nodes (7): The service edge: the deepest module in the import DAG., One request, its ledger entry and a metrics snapshot., serve(), The service edge: every module in the DAG on one call path., Syntactic success is not success: no module may be left on a naive clock., test_every_stamp_in_one_response_is_aware(), test_serve_returns_the_whole_response()

### Community 82 - "uptime_s"
Cohesion: 0.22
Nodes (5): Start-up bookkeeping. Both of its constants are computed at *import* time. That…, Seconds since :data:`STARTED_AT`., uptime_s(), Start-up constants. Importing this module is itself the assertion., test_uptime_grows_from_the_import_stamp()

### Community 83 - "apply_codemod"
Cohesion: 0.15
Nodes (14): family(), The symbols a run for ``target`` migrates and audits., apply_codemod(), make_edit_node(), Any, Path, EDIT node: apply the migration codemod to the files the analyzer flagged. It…, Run the codemod over every file in ``call_sites``; return the ones that… (+6 more)

### Community 84 - "uptime_s"
Cohesion: 0.22
Nodes (5): Start-up bookkeeping. Both of its constants are computed at *import* time. That…, Seconds since :data:`STARTED_AT`., uptime_s(), Start-up constants. Importing this module is itself the assertion., test_uptime_grows_from_the_import_stamp()

### Community 85 - "benchmark/runner.py"
Cohesion: 0.09
Nodes (43): ``python -m mra.benchmark`` — run the matrix and write the report., _ablation_a(), _ablation_b(), _ablation_c(), _ablation_d(), _ablation_e(), _ablation_f(), _aggregate() (+35 more)

### Community 86 - "handle"
Cohesion: 0.33
Nodes (5): handle(), Request handling. Its own stamp never leaves the module, so it is self-…, Post one amount and return the handled record., test_handle_posts_the_entry(), test_handle_reports_uptime()

### Community 87 - "snapshot"
Cohesion: 0.33
Nodes (5): Point-in-time metrics over the ledger., Entry count plus how long this reading took to assemble., snapshot(), test_snapshot_counts_the_entries(), test_snapshot_reports_its_own_lag()

### Community 88 - "handle"
Cohesion: 0.33
Nodes (5): handle(), Request handling. Its own stamp never leaves the module, so it is self-…, Post one amount and return the handled record., test_handle_posts_the_entry(), test_handle_reports_uptime()

### Community 89 - "old/tests/test_timebase.py"
Cohesion: 0.29
Nodes (6): The clock contract. No assertion here may depend on the migration (NB-10).…, The safe window: a caller that has not moved yet is upgraded for free., The refusal: an aware stamp meeting a naive clock is passed through, not…, test_aligned_never_strips_a_tzinfo(), test_aligned_reads_a_naive_stamp_as_utc_when_the_clock_is_aware(), test_utc_now_returns_a_datetime()

### Community 90 - "pdf.py"
Cohesion: 0.13
Nodes (42): Canvas, Paragraph, ParagraphStyle, SimpleDocTemplate, banner(), _build(), _canvas_maker(), _changes() (+34 more)

### Community 91 - "verify_paper.py"
Cohesion: 0.15
Nodes (22): blind_test(), carries_a_figure(), cells(), check(), commit_message(), figures(), main(), pinned_defects() (+14 more)

### Community 92 - "check_invariants"
Cohesion: 0.16
Nodes (15): Counter, driver(), needs_timezone_import(), A class-form site needs ``timezone`` bound; a module-form one rides its own…, Python that imports every module and executes every site and decoy., check_invariants(), _fixture_specs(), _imports() (+7 more)

### Community 93 - "verdict.py"
Cohesion: 0.39
Nodes (8): headline(), _listing(), Any, GREEN / YELLOW / RED: one answer to "can a human merge this patch?".…, The one-line reason under the banner., _reason(), _red(), _yellow()

### Community 98 - "evidence.py"
Cohesion: 0.16
Nodes (26): apply_check(), _aware(), base_commit(), _Calls, collect(), _coverage(), edge_suite(), export_tree() (+18 more)

### Community 99 - "_Skipped"
Cohesion: 0.16
Nodes (7): Attribute, Call, CSTNode, Exports, ImportFrom, What MAP deliberately does not resolve: star imports and bare references., _Skipped

### Community 100 - "Router"
Cohesion: 0.06
Nodes (54): Role, Roles, LLM routing, providers, privacy and token accounting. Models come from mra.toml., host_of(), is_local(), privacy_mode(), PrivacyError, RuntimeError (+46 more)

### Community 101 - "test_experience.py"
Cohesion: 0.18
Nodes (21): db(), CaptureFixture, fixture, MonkeyPatch, needs_docker, Path, Feature D: the opt-in experience store. Off by default, never touched by the…, test_env_off_beats_config_on() (+13 more)

### Community 102 - "test_report_robustness.py"
Cohesion: 0.31
Nodes (14): _check(), Any, parametrize, Hunt 7 — the report under stress: a 10k-line diff, 300-character file names,…, Apply ``rename`` to every file path in a synthetic run (model inputs only)., The long-name half of the stress, at a modest file count., _rename(), _render() (+6 more)

### Community 103 - "OpenAICompatibleProvider"
Cohesion: 0.18
Nodes (8): OpenAICompatibleProvider, Message, End to end over real HTTP: request shape out, Completion shape back., Every call is recorded with who served it, the model, and the tokens., test_local_only_blocks_remote_before_any_socket_opens(), test_local_only_still_allows_a_local_server(), test_openai_compatible_provider_talks_to_a_local_server(), test_router_through_local_server_logs_provider_model_tokens()

### Community 104 - "edge.py"
Cohesion: 0.14
Nodes (29): cases(), held_out(), _json_or(), _judge(), _live_setup(), _llm_setup(), main(), Any (+21 more)

### Community 105 - "skills.py"
Cohesion: 0.12
Nodes (21): apply_rule(), _code(), derive_rule(), _extend_from_import(), _import_names(), matching(), CSTNode, Module (+13 more)

### Community 106 - "CodemodContext"
Cohesion: 0.29
Nodes (6): CodemodContext, _fake_reply(), Classify, summarise, or return the codemod's version of the file it was shown., A shadowed `datetime` the analyzer rejected must not be edited by the codemod., test_given_sites_only_those_calls_change(), test_new_timezone_import_lands_where_isort_puts_it()

### Community 107 - "1b. Per task, per configuration"
Cohesion: 0.10
Nodes (20): 1. The whole offline matrix, 1b. Per task, per configuration, 2. Ablations, 3. Deterministic baselines — ruff (DTZ) and pyupgrade, 4. Configuration key, A. Recovery loop ON vs OFF — the headline, B. Dependency-ordered batching vs arbitrary order, batch size 1, recovery OFF (+12 more)

### Community 108 - "_ImportCollector"
Cohesion: 0.25
Nodes (6): _ImportCollector, _module_name(), BaseExpression, Import, ImportFrom, Collects the dotted module names a file imports, including submodules.

### Community 109 - "test_many.py"
Cohesion: 0.20
Nodes (7): t0(), t1(), t2(), t3(), t4(), t5(), test_all()

### Community 110 - "_build.py"
Cohesion: 0.31
Nodes (7): build(), case(), locate(), one(), Generate the edge-case corpus: ``python corpus/edge/_build.py``. Every case is…, ``sites``: (file, call text, occurrence[, symbol]) — the call text's first char…, _text()

### Community 111 - "stamp"
Cohesion: 0.28
Nodes (5): datetime, stamp(), age_seconds(), test_stamp_is_recent(), test_age_is_small()

### Community 112 - "stamp"
Cohesion: 0.28
Nodes (5): datetime, stamp(), age_seconds(), test_stamp_is_recent(), test_age_is_small()

### Community 113 - "stamp"
Cohesion: 0.28
Nodes (5): datetime, stamp(), age_seconds(), test_stamp_is_recent(), test_age_is_small()

### Community 114 - "stamp"
Cohesion: 0.28
Nodes (4): stamp(), age(), test_stamp_is_recent(), test_age()

### Community 115 - "a.py"
Cohesion: 0.43
Nodes (5): a_age(), a_now(), b_age(), b_now(), test_cycle()

### Community 116 - "test_all"
Cohesion: 0.38
Nodes (4): legacy(), stamp(), ok(), test_all()

### Community 117 - "other_object_with_utcnow/old/src/pkg/core.py"
Cohesion: 0.33
Nodes (4): Clock, fake(), stamp(), test_both()

### Community 118 - "shadowed_local_name/old/src/pkg/core.py"
Cohesion: 0.38
Nodes (4): fake(), FakeClock, stamp(), test_both()

### Community 119 - "stamp"
Cohesion: 0.38
Nodes (4): datetime, stamp(), old(), test_both()

### Community 120 - "llm_server"
Cohesion: 0.29
Nodes (7): SimpleNamespace, llm_server(), _no_privacy_env(), fixture, MonkeyPatch, A tiny OpenAI-compatible server on 127.0.0.1. Records every request.…, test_anthropic_provider_lifts_the_system_prompt()

### Community 121 - "test_all"
Cohesion: 0.47
Nodes (4): ages(), stamp(), window(), test_all()

### Community 122 - "stamp"
Cohesion: 0.40
Nodes (3): datetime, stamp(), test_stamp_is_recent()

### Community 123 - "stamp"
Cohesion: 0.40
Nodes (3): datetime, stamp(), test_stamp_is_recent()

### Community 124 - "stamp"
Cohesion: 0.33
Nodes (4): Replaces datetime.utcnow() one day., Like datetime.utcnow(), but tested., stamp(), test_text_untouched()

### Community 125 - "stamp"
Cohesion: 0.50
Nodes (3): datetime, stamp(), test_stamp_is_recent()

### Community 126 - "stamp"
Cohesion: 0.50
Nodes (3): datetime, stamp(), test_close_to_now()

### Community 127 - "stamp"
Cohesion: 0.50
Nodes (3): datetime, stamp(), test_stamp_is_recent()

### Community 128 - "stamp"
Cohesion: 0.50
Nodes (3): datetime, stamp(), test_stamp_is_recent()

### Community 129 - "job"
Cohesion: 0.50
Nodes (3): job(), tagged(), test_job()

### Community 130 - "stamp"
Cohesion: 0.50
Nodes (3): datetime, stamp(), test_stamp_is_recent()

### Community 131 - "stamp"
Cohesion: 0.50
Nodes (3): datetime, stamp(), test_stamp_is_recent()

### Community 132 - "stamp"
Cohesion: 0.50
Nodes (3): datetime, stamp(), test_naive_contract()

### Community 133 - "test_both"
Cohesion: 0.50
Nodes (3): from_epoch(), stamp(), test_both()

### Community 134 - "tests/test_report.py"
Cohesion: 0.09
Nodes (36): _codemod_corrector(), green_run(), _migrate(), _pages(), Any, fixture, MonkeyPatch, needs_docker (+28 more)

### Community 147 - "test_long"
Cohesion: 0.50
Nodes (3): later(), stamp(), test_long()

### Community 239 - "1b. Per task, per configuration"
Cohesion: 0.10
Nodes (20): 1. The whole offline matrix, 1b. Per task, per configuration, 2. Ablations, 3. Deterministic baselines — ruff (DTZ) and pyupgrade, 4. Configuration key, A. Recovery loop ON vs OFF — the headline, B. Dependency-ordered batching vs arbitrary order, batch size 1, recovery OFF (+12 more)

### Community 240 - "experience.py"
Cohesion: 0.07
Nodes (31): Connection, clean_message(), configured_path(), configured_ttl(), diff_pattern(), from_config(), fully_green(), Any (+23 more)

### Community 241 - "Gold check — live and blind07 runs"
Cohesion: 0.40
Nodes (4): Gold check — live and blind07 runs, Import accuracy (docs/05 §2.3a), Notes, Planted faults (the check is not blind)

### Community 242 - "migrate_task"
Cohesion: 0.10
Nodes (30): _key(), main(), migrate_task(), Any, Collection, Path, End-to-end slice: analyse -> snapshot -> codemod -> verify -> recover -> score.…, Append-only event log, the ``mra:trajectory_event`` shape (SRS §4.1). (+22 more)

### Community 246 - "LLMCorrector"
Cohesion: 0.10
Nodes (22): Endpoint, One link of a role's chain: a provider, the model to ask it for, its policy., LLMCorrector, The CORRECT node as a corrector callable, for :func:`mra.recovery.recover`. One…, Refuse up front, not at the first call mid-run (found by corpus/edge)., A server that accepts and never answers: one retry, then ProviderError -> RED., test_local_only_refuses_an_all_remote_role_at_construction(), test_silent_endpoint_fails_fast_and_reads_red() (+14 more)

### Community 247 - "test_hostile_replies.py"
Cohesion: 0.05
Nodes (75): MarkDecorator, Popen, bug(), Bug-hunt harnesses (hypothesis, docker). Part of the default run. Hypothesis…, Mark a test that reproduces an open BUGS.md entry., _cli(), _codes(), _git() (+67 more)

### Community 248 - "test_edge.py"
Cohesion: 0.22
Nodes (8): edge_results(), Any, fixture, parametrize, TempPathFactory, The edge-case accuracy suite (corpus/edge) as tests: one per case. The suite…, test_case_gives_the_expected_verdict(), test_every_category_is_covered()

### Community 249 - "repogen.py"
Cohesion: 0.17
Nodes (14): _decoy_block(), _decoy_receiver(), expected_source(), Random multi-module repos for the T1 finder/codemod, with their ground truth. A…, (old call text, the exact text the codemod should write)., (name, call-through-name) for a decoy that reuses the binding's own name., Lines holding the site ``s`` (tagged), and the expressions that execute it., Module source, plus [(old site text, new site text)] in line order. (+6 more)

### Community 251 - "gold/src/app/clock.py"
Cohesion: 0.13
Nodes (10): now(), The scheduler's wall clock., Static configuration., due(), Job, Job records; scheduler.py imports this module back (a real cycle)., age_days(), make_job() (+2 more)

### Community 252 - "old/src/app/clock.py"
Cohesion: 0.13
Nodes (10): now(), The scheduler's wall clock., Static configuration., due(), Job, Job records; scheduler.py imports this module back (a real cycle)., age_days(), make_job() (+2 more)

### Community 253 - "load"
Cohesion: 0.17
Nodes (12): is_fresh(), Is a cached session still fresh?, The clock every cached session is stamped with., stamp(), load(), Persist the last stamp to a JSON file and read it back., save(), Hidden semantic tests: gold/ only, never shown to the agent. (+4 more)

### Community 254 - "Contributors"
Cohesion: 0.33
Nodes (5): Contributors, How we work, Origin of the code base, Team, Workstreams

### Community 255 - "summarize"
Cohesion: 0.18
Nodes (16): edit_context(), graph_slice(), offline_summary(), progress_facts(), Any, Rolling memory: what the model is told about everything that is not in front of…, The dependency neighbourhood, truncated to a constant number of names., The complete payload for one corrective-edit call (NFR-12). Everything except… (+8 more)

### Community 256 - "gold/tests/test_timebase.py"
Cohesion: 0.22
Nodes (8): The clock contract. No assertion here may depend on the migration (NB-10).…, The safe window: a caller that has not moved yet is upgraded for free., The refusal: an aware stamp meeting a naive clock is passed through, not…, The semantic check. Fails against ``old/`` — that is the point., test_aligned_never_strips_a_tzinfo(), test_aligned_reads_a_naive_stamp_as_utc_when_the_clock_is_aware(), test_utc_now_is_timezone_aware(), test_utc_now_returns_a_datetime()

### Community 257 - "stamp"
Cohesion: 0.21
Nodes (9): is_fresh(), Is a cached session still fresh?, The clock every cached session is stamped with., stamp(), load(), Persist the last stamp to a JSON file and read it back., save(), test_fresh_save_is_fresh() (+1 more)

### Community 258 - "new_state"
Cohesion: 0.21
Nodes (11): Contract, MigrationState, new_state(), TypedDict, ``MigrationState`` — the agent's working memory. A transcription of the…, What is being migrated, from the task's ``ground_truth.json``., A state with every required field present and the counters zeroed., live (+3 more)

### Community 259 - "test_metamorphic.py"
Cohesion: 0.15
Nodes (30): Files, _aliases(), _commutes(), crlf(), _files(), _full_run(), migrate(), given (+22 more)

### Community 260 - "2. Ablations"
Cohesion: 0.22
Nodes (9): 2. Ablations, A. Recovery loop ON vs OFF — the headline, B. Dependency-ordered batching vs arbitrary order, batch size 1, recovery OFF, batch size 1, recovery on, batch size 3, recovery on, C. Edit model — V4-Pro vs V4-Flash, D. Batch size 1 vs 3 vs 5 (+1 more)

### Community 261 - "test_fuzz_codemod.py"
Cohesion: 0.18
Nodes (15): AST, FUZZ, _checked(), given, settings, Hunt 1 — property-based fuzzing of MAP (finder) + EDIT (codemod). Invariants,…, All import styles that are expected to work, random contexts and decoys., ``from pkg import compat; compat.datetime.utcnow()`` mixed in. (+7 more)

### Community 262 - "test_determinism.py"
Cohesion: 0.29
Nodes (10): _first_difference(), _norm(), Any, needs_docker, parametrize, Path, Hunt 5 — determinism: each Tier-A task three times, offline (codemod…, _snapshot() (+2 more)

### Community 263 - "ImportBindings"
Cohesion: 0.22
Nodes (7): ImportBindings, _module_name(), BaseExpression, Import, ImportFrom, Dotted text of an import's module expression (``a.b.c``)., Maps each locally bound name to the fully-qualified thing it refers to. One…

### Community 264 - "._with_keys"
Cohesion: 0.29
Nodes (7): _backoff(), Any, Exception, ``call(client)`` under the retry policy above; 401/403 moves to the next key., Timeout / connection error / 5xx, by name: base.py must not import an SDK., The server's ``Retry-After`` if it sent one, else 1, 2, 4 ... s, capped., _transient()

### Community 265 - "What the Tier-A benchmark shows"
Cohesion: 0.40
Nodes (5): (a) The recovery loop is what finishes a cross-file migration, (b) The existing static tools detect the work and do none of it, (c) Dependency-ordered batching: what the data actually supports, Scope and honesty notes, What the Tier-A benchmark shows

### Community 266 - "module_specs"
Cohesion: 0.83
Nodes (4): composite, module_specs(), Any, repo_specs()

### Community 267 - "1b. Per task, per configuration"
Cohesion: 0.20
Nodes (10): 1. The whole offline matrix, 1b. Per task, per configuration, 3. Deterministic baselines — ruff (DTZ) and pyupgrade, 4. Configuration key, Benchmark results — Tier A, task01_datetime, task02_datetime_aliased, task03_half_migration (+2 more)

### Community 268 - "BUGS — v0.3.0 bug hunt (find only, nothing fixed)"
Cohesion: 0.29
Nodes (6): 8. Mutation testing — surviving mutants, Bugs (sorted by severity), BUGS — v0.3.0 bug hunt (find only, nothing fixed), Counts, Fixed, Notes on method

### Community 269 - "FakeClock"
Cohesion: 0.40
Nodes (3): FakeClock, frozen(), Test doubles. FakeClock is not a real clock: never call datetime.utcnow() here.

### Community 270 - "FakeClock"
Cohesion: 0.40
Nodes (3): FakeClock, frozen(), Test doubles. FakeClock is not a real clock: never call datetime.utcnow() here.

### Community 271 - "LegacyClock"
Cohesion: 0.40
Nodes (3): legacy_now(), LegacyClock, Legacy clock shim. Older callers used datetime.utcnow() directly; this one does…

### Community 272 - "LegacyClock"
Cohesion: 0.40
Nodes (3): legacy_now(), LegacyClock, Legacy clock shim. Older callers used datetime.utcnow() directly; this one does…

### Community 273 - "report/__init__.py"
Cohesion: 0.15
Nodes (18): Migration & Refactoring Agent., build_report(), Any, datetime, Path, RuntimeError, The run report: verdict banner, 14-page PDF, report.json, terminal summary.…, A repo name that is safe in a filename on every OS. (+10 more)

### Community 274 - "Config"
Cohesion: 0.50
Nodes (3): Config, One point in the ablation matrix (docs/05 §3: one variable at a time)., True when this row needs the live model from ``mra.toml`` and its key.

### Community 276 - "task07_cache: blind held-out result #2 (2026-10-06)"
Cohesion: 0.40
Nodes (4): Rejected attempts, task07_cache: blind held-out result #2 (2026-10-06), The guard against this task's wrong fixes (offline probe, frozen code), The model's patch (all three runs, identical; equal to `gold/`)

### Community 284 - "task06_scheduler — blind held-out fixture"
Cohesion: 0.50
Nodes (3): task06_scheduler — blind held-out fixture, Trees, What makes it hard

### Community 285 - "task07_cache — blind held-out fixture #2"
Cohesion: 0.50
Nodes (3): task07_cache — blind held-out fixture #2, Trees (verified in the sandbox before any agent run), What makes it hard

### Community 287 - "pull_request_template.md"
Cohesion: 0.50
Nodes (3): Done-gate, How it was checked, What this changes

## Knowledge Gaps
- **344 isolated node(s):** `app`, `Job`, `app`, `Job`, `svc` (+339 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **92 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SandboxRunner` connect `SandboxRunner` to `test_p4_graph.py`, `evidence.py`, `baselines.py`, `recover`, `test_p2_end_to_end.py`, `migrate_task`, `test_hostile_replies.py`, `graph.py`?**
  _High betweenness centrality (0.011) - this node is a cross-community bridge._
- **Why does `Router` connect `Router` to `test_p4_graph.py`, `test_recovery.py`, `new_state`, `OpenAICompatibleProvider`, `edge.py`, `test_consequence.py`, `benchmark/runner.py`, `LLMCorrector`, `test_hostile_replies.py`, `ExperienceStore`, `test_providers.py`, `correct_node.py`, `graph.py`, `cli.py`, `summarize`?**
  _High betweenness centrality (0.008) - this node is a cross-community bridge._
- **Why does `ImportBindings` connect `ImportBindings` to `evidence.py`, `_Skipped`, `call_sites.py`?**
  _High betweenness centrality (0.007) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `ExperienceStore` (e.g. with `Config` and `ReplayCorrector`) actually correct?**
  _`ExperienceStore` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `Router` (e.g. with `PrivacyError` and `Tokens`) actually correct?**
  _`Router` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 9 inferred relationships involving `LLMCorrector` (e.g. with `Config` and `ReplayCorrector`) actually correct?**
  _`LLMCorrector` has 9 INFERRED edges - model-reasoned connections that need verification._
- **What connects `app`, `Job`, `app` to the rest of the system?**
  _344 weakly-connected nodes found - possible documentation gaps or missing edges._