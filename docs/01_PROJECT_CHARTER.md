# Project Synopsis & Charter
### Codebase-Wide Version Migration & Refactoring Agent

| Field | Value |
|---|---|
| **Document** | Project Synopsis / Charter (Deliverable D1) |
| **Project title** | Codebase-Wide Version Migration & Refactoring Agent |
| **Internal handle** | MRA (Migration & Refactoring Agent) |
| **Author / Student** | Srinivas R C (R23EA121) |
| **Guide** | Dr Nimrita Koul |
| **Centre** | Centre for AI & ML |
| **Version** | 0.1 (Draft for guide review) |
| **Date** | 24 August 2026 |
| **Status** | Awaiting guide approval & signature |

**Revision history**

| Ver | Date | Author | Change |
|---|---|---|---|
| 0.1 | 24 Aug 2026 | Srinivas RC | Initial draft for first guide meeting |
| 0.2 | 12 Nov 2026 | Srinivas R C | Confirmed as an individual project; team listing removed |

**Approval**

| Role | Name | Signature | Date |
|---|---|---|---|
| Student | Srinivas R C | | |
| Guide | Dr Nimrita Koul | | |

---

## 1. Problem statement

When a library or language introduces breaking changes (e.g. SQLAlchemy 1.4 → 2.0, Pydantic v1 → v2), upgrading a real codebase is not a text substitution. A single changed function signature or renamed method can break callers in other files, and many breaks are **semantic, not syntactic** — the code still parses and imports, but behaves differently or fails only at test time (for example, `httpx` defaulting `follow_redirects` to `False`, or Pydantic v2 no longer treating `Optional[x]` as implicitly defaulting to `None`).

Existing automation does not close this gap. Deterministic codemod tools (`pyupgrade`, `ruff`, `2to3`, hand-written `libcst` transforms) apply only pre-programmed rules and cannot reason across files or recover from a broken test. General LLM agents can edit a file but, without a dependency model and a verification loop, they edit in unsafe order and cannot reliably detect or repair the breakage they cause.

**The core problem this project solves:** perform a correct, cross-file, self-verifying version migration across a multi-module Python codebase — mapping every affected call site before editing, ordering the edits to avoid circular regressions, running the test suite after each change, and automatically diagnosing and repairing failures until the suite passes.

## 2. Proposed solution

A **long-horizon autonomous agent, built as an explicit state machine on LangGraph 1.x**, with tools, graph-based working memory, and a verification-and-recovery loop. The agent executes five stages:

1. **MAP** — static analysis (`libcst`) builds a dependency/call graph (`networkx`) and locates every affected call site *before* any edit.
2. **PLAN** — a topological ordering over the graph produces safe, batched edits with no circular regressions.
3. **EDIT** — deterministic edits are applied as `libcst` codemods; ambiguous edits use an LLM (DeepSeek V4-Pro).
4. **TEST** — `pytest` and `ruff` run inside an isolated Docker sandbox; results are captured as structured data.
5. **CORRECT** — on failure, the stack trace is parsed, the broken contract located, a corrective patch applied, and the batch re-tested — looping until green or a retry ceiling is hit.

All state (per-file status, pending fixes, trajectory) is held in a compact `MigrationState` object and persisted by the LangGraph SQLite checkpointer, which doubles as the audit log. Every LLM and tool call is logged for the token-overhead metric; a multi-model router uses the cheaper DeepSeek V4-Flash for summaries and classification to control cost.

**Why a state machine and not a black-box agent SDK:** the self-correction loop, the edit ordering, and the memory are exactly what is being evaluated and defended in the viva. LangGraph makes them explicit, controllable, and inspectable; a higher-level "agent-as-a-library" SDK would hide them. This is a deliberate, defensible design decision.

## 3. Scope and finalized migration targets

The agent will be built and evaluated on **[3–5] migration tasks in rising difficulty** (final list to be locked with the guide). Proposed set:

| # | Migration task | Difficulty | Rationale |
|---|---|---|---|
| T1 | `datetime.utcnow()` → `datetime.now(timezone.utc)` | Easy | Clean starter; import-scope resolution already forces a real dependency graph. |
| T2 | Python 3.8 → 3.12 modernization (typing, f-strings) | Easy–Medium | Has a deterministic baseline (`pyupgrade`, `ruff UP`) to benchmark against. |
| T3 | `requests` → `httpx` | Medium | Introduces semantic (behaviour-changing) breaks that only tests catch. |
| T4 | Pydantic v1 → v2 | Hard | Extensively documented breaking changes; strong external validity. |
| T5 | SQLAlchemy 1.4 → 2.0 | Hardest | The spec's own flagship example; high impact if achieved. |

> **Open item for guide meeting:** the original problem statement reads "510 multi-file migration tasks." This is almost certainly a typo for **5–10**. To be confirmed before the corpus is built, as it materially changes scope.

**Note on versions (verified 24 Aug 2026):** Core Pydantic remains on the v2 line (v3 not yet released — a "Pydantic v3" claim in circulation refers to the separate *Pydantic AI* product), so T4 is valid. LangGraph is on the 1.x line; the 0.x branch is in maintenance until Dec 2026.

## 4. Deliverables

| ID | Deliverable | Description |
|---|---|---|
| A1 | **Agent framework** | Static analyzer + planner + editor + verifier + recovery loop on LangGraph 1.x, runnable in Docker. |
| A2 | **Migration patch(es)** | One unified `.patch` (git diff) per task applying the full upgrade across the target repo. |
| A3 | **Trajectory / audit logs** | Structured JSON of every decision: call-graph map, edit order, failures, corrective actions. |
| A4 | **Benchmarking report** | The three metrics (§5) across all tasks, with ablations and failure analysis. |
| A5 | **Research paper** | Journal/conference manuscript on the method and results (venue & deadline per guide). |
| A6 | **Corpus** | Tier A controlled repos (with ground truth) + Tier B real OSS repo(s). |
| A7 | **Project documents** | This charter, literature review, SRS, HLD/LLD, data & evaluation protocol. |

## 5. Success criteria (metrics)

Success is measured on three metrics, defined formally in the Data & Evaluation Protocol (Deliverable D5):

- **M1 — Migration Completeness (%):** fraction of affected call sites correctly updated (reported as recall *and* precision to penalise over-editing).
- **M2 — Post-Migration Test Pass Rate (%):** fraction of the target test suite passing after migration (precondition: the suite passes on the pre-migration code).
- **M3 — Token / Step Overhead:** total tokens, tool/LLM calls, and cost per completed task.

A quantitative pass threshold (e.g. M1 ≥ X%, M2 = 100% on Tier A) will be agreed with the guide (§ open item 6, meeting agenda).

## 6. Technology stack (summary)

LangGraph 1.x (orchestration) · `langgraph-checkpoint-sqlite` (state/audit) · `libcst` (analysis + codemods) · `networkx` (dependency graph) · `pytest` + `pytest-json-report` + `ruff` (verification) · `GitPython` (snapshot / patch) · Docker `python:3.12-slim` (sandbox) · DeepSeek V4-Pro (edits) + V4-Flash (summaries) via OpenAI-compatible API. Development on CachyOS (Arch Linux). Full detail in the SRS and HLD.

## 7. Timeline (indicative, aligned to the build phases)

| Phase | Weeks | Milestone |
|---|---|---|
| P0 Skeleton | 1 | Dockerized skeleton wraps `pytest` + `git` as tools; can run a suite and read results. |
| P1 Static analyzer | 2–3 | Given a repo + pattern, output all call sites + dependency graph (deterministic). |
| P2 Single-file edit + verify | 4 | Migrate one file, run tests, report pass/fail. End-to-end tiny agent working. |
| P3 Recovery loop | 5–6 | Self-correction: parse trace → patch → re-test. The graded core. |
| P4 Multi-file + memory | 7–8 | Scale to a full repo; add state tracker + context summarization. |
| P5 Benchmark + paper | 9+ | Run all tasks, log trajectories, compute metrics, write report + paper. |

## 8. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Recovery loop under-built | Project becomes a "fancy find-replace" (loses ~80% of value) | Phase 3 is time-boxed and prioritized; ablation proves its contribution. |
| Context/token blow-up on long horizons | Cost + failure | Build state summarization in P4; log tokens from P0; route cheap model for summaries. |
| Semantic breaks pass unit tests silently | Wrong "success" | Corpus deliberately includes behaviour-changing tasks (httpx, Pydantic Optional). |
| Corpus lacks ground truth | Metrics unscoreable | Tier A hand-authored `gold/` + `ground_truth.json`; Tier B uses real migration PRs as gold. |
| Scope creep (real repos too large) | Time overrun | Ship Tier A end-to-end first; Tier B is validation, not the foundation. |

## 9. Constraints and assumptions

- Target language is **Python** only; migrations are library/language version upgrades (not business-logic rewrites).
- Every target repo has a `pytest` suite that **passes on the pre-migration code** (required for M2 to be meaningful).
- All code execution occurs inside a Docker sandbox; the host machine is never edited directly.
- Compute: student machine + Docker + free/low-cost DeepSeek API (5M free tokens on signup); to be confirmed with guide.

## 10. Open items for first guide meeting

1. Confirm task count is **5–10**, not 510.
2. Lock the final migration target list from the menu in §3.
3. Is the **research paper** a hard deliverable? Which venue and deadline?
4. Team size: resolved, individual project (revision 0.2).
5. Compute/budget limits.
6. Numeric success thresholds for M1/M2.
7. Is Tier B (real OSS repo) required for the grade, or is Tier A sufficient?

---
*This charter is the reference contract for the project. Changes to scope, deliverables, or targets after approval require a new revision and guide sign-off.*
