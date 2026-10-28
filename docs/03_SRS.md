# Software Requirements Specification (SRS)
### Codebase-Wide Version Migration & Refactoring Agent (MRA)

| Field | Value |
|---|---|
| **Document** | SRS (Deliverable D3) |
| **Author** | Srinivas RC | **Guide** | Dr Nimrita Koul |
| **Version** | 0.1 (Draft) | **Date** | 24 August 2026 |
| **Standard** | Adapted from IEEE 830 / ISO-IEC-IEEE 29148, tuned for an LLM-agent system |
| **Status** | For guide review |

**Revision history**

| Ver | Date | Change |
|---|---|---|
| 0.1 | 24 Aug 2026 | Initial draft; contracts, boundaries, and NFRs defined |
| 0.2 | 1 Oct 2026 | §4.1 `contract.expected_lint`: ruff rules the target API itself triggers, exempted (and listed) by the run report |
| 0.3 | 6 Oct 2026 | §4.1 `contract.forbidden_patterns`: regexes a corrective patch may not add (anti-reversal guard, v0.3.0 consequence repair) |

> This SRS deliberately departs from a prose-heavy template. For an LLM-agent system the highest-risk ambiguity is **data-shape ambiguity**: agents cannot reliably infer types from prose. Section 4 therefore fixes the exact JSON contracts, Section 5 fixes the functional boundaries (what the agent must *not* do), and Section 6 fixes the non-functional constraints (budgets, retries, timeouts). These three sections are the load-bearing part of the document.

---

## 1. Introduction

### 1.1 Purpose
Specify the functional and non-functional requirements of the MRA: an autonomous agent that performs a specified library/language version migration across a multi-module Python codebase and verifies the result with the repository's test suite.

### 1.2 Definitions
- **Migration contract** — the source→target API change to apply (e.g. `datetime.utcnow()` → `datetime.now(timezone.utc)`), plus the relevant excerpt of the library's migration guide.
- **Call site** — a location in the code where the migrated pattern appears (file, line, column, symbol).
- **Batch** — an ordered group of files edited together in one EDIT step.
- **Trajectory** — the append-only log of every node transition, edit, test result, and correction.
- **Node** — a stage in the LangGraph state machine: MAP, PLAN, EDIT, TEST, CORRECT.
- **Signature** (of a failure) — a stable hash identifying a recurring test failure, used to cap retries.

### 1.3 Actors
- **Operator** (the student) — supplies the target repo and migration contract, starts a run, reads the report.
- **The Agent (MRA)** — performs the migration autonomously.
- **The Guide** — evaluates deliverables against success criteria.

## 2. Overall description

The MRA runs as a Python application orchestrated by a LangGraph 1.x state machine, calling deterministic tools (`libcst`, `networkx`, `pytest`, `ruff`, `git`) and two LLMs (DeepSeek V4-Pro/Flash) via an OpenAI-compatible API. All file execution occurs inside a Docker `python:3.12-slim` sandbox. State persists in a SQLite checkpointer. Input is a repository plus a migration contract; output is a migrated repository, a unified `.patch`, a trajectory log, and a metrics record.

## 3. Functional requirements

Each requirement is testable. **FR-x** = functional requirement.

| ID | Requirement | Acceptance test |
|---|---|---|
| FR-1 | Given a repo and a target pattern, the analyzer shall enumerate **every** call site (file, line, col, symbol), resolving import scope and aliases. | On Tier-A task, output set equals `ground_truth.json` call-site set. |
| FR-2 | The analyzer shall build a directed import/call dependency graph over the repo's modules. | Graph nodes = modules; edges = imports; verified against a known fixture. |
| FR-3 | The planner shall produce an ordered list of edit batches via topological sort such that a contract change and its dependents are testable without circular regression. | No batch edits a file whose unresolved dependency is edited in a later batch (checked programmatically). |
| FR-4 | The editor shall apply deterministic edits as `libcst` codemods and reserve the LLM for ambiguous edits. | Mechanical renames produce byte-identical results across runs (determinism check). |
| FR-5 | The editor shall preserve formatting, comments, and unrelated code. | `git diff` touches only intended regions (no whitespace-only churn). |
| FR-6 | The verifier shall run `pytest` and `ruff` in the sandbox and emit a **structured** report (§4.3), not scraped text. | Report validates against the test-report JSON schema. |
| FR-7 | On any post-edit test failure, the recovery loop shall parse the trace, locate the broken contract, apply a corrective patch, and re-test. | Injected break is repaired and suite returns to green in ≤ `MAX_FIX_ATTEMPTS`. |
| FR-8 | The system shall maintain `MigrationState` (§4.1) and persist every transition to the checkpointer. | Trajectory reconstructable from `state.db` alone. |
| FR-9 | The system shall stop on success (all batches done, suite green) or give up after a failure repeats `MAX_FIX_ATTEMPTS` times, logging and flagging for human review. | Both stop conditions exercised by tests. |
| FR-10 | The system shall generate a unified `.patch` (git diff) for the completed migration. | `git apply --check` succeeds on a clean checkout. |
| FR-11 | The system shall record per-call token counts and tool-call counts for the M3 metric. | Metrics record validates against schema; totals are non-zero and monotonic. |
| FR-12 | The model router shall dispatch edits/trace-reasoning to V4-Pro and summaries/classification to V4-Flash. | Router log shows correct model per call type. |

## 4. Input / Output contracts (JSON schemas) — CRITICAL

All schemas are JSON Schema draft 2020-12. These are the authoritative data shapes; code and prompts must conform.

### 4.1 `MigrationState` (the agent's working memory)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "mra:migration_state",
  "title": "MigrationState",
  "type": "object",
  "additionalProperties": false,
  "required": ["run_id", "repo_path", "contract", "file_status", "current_batch", "done"],
  "properties": {
    "run_id":        { "type": "string", "description": "UUID for this run" },
    "repo_path":     { "type": "string", "description": "Path to the repo copy inside the sandbox" },
    "contract": {
      "type": "object",
      "additionalProperties": false,
      "required": ["task_id", "source_api", "target_api"],
      "properties": {
        "task_id":    { "type": "string" },
        "source_api": { "type": "string", "description": "e.g. datetime.utcnow" },
        "target_api": { "type": "string", "description": "e.g. datetime.now(timezone.utc)" },
        "guide_excerpt": { "type": "string", "description": "Relevant migration-guide text" },
        "expected_lint": { "type": "array", "items": { "type": "string" },
                           "description": "Ruff rule codes the target API itself triggers (e.g. UP017 for timezone.utc); the run report lists them as exempted, never silently" },
        "forbidden_patterns": { "type": "array", "items": { "type": "string" },
                           "description": "Regexes a corrective patch may not add: patterns that reverse the migration by another route (for datetime: tzinfo=None, rebuilding from timetuple()). A patch that adds one, or reintroduces source_api, is rejected and still counts as an attempt" }
      }
    },
    "call_sites": {
      "type": "object",
      "description": "Map of file path -> list of call sites in that file",
      "additionalProperties": {
        "type": "array",
        "items": { "$ref": "mra:call_site" }
      }
    },
    "dep_graph": {
      "type": "object",
      "description": "Adjacency list: file -> list of files that import it",
      "additionalProperties": { "type": "array", "items": { "type": "string" } }
    },
    "edit_batches": {
      "type": "array",
      "description": "Ordered batches; each batch is a list of file paths",
      "items": { "type": "array", "items": { "type": "string" } }
    },
    "file_status": {
      "type": "object",
      "additionalProperties": {
        "enum": ["pending", "in_progress", "migrated", "partial", "verified", "failed"]
      }
    },
    "current_batch": { "type": "integer", "minimum": 0 },
    "last_test_report": { "$ref": "mra:test_report" },
    "fix_attempts": {
      "type": "object",
      "description": "failure signature -> attempt count",
      "additionalProperties": { "type": "integer", "minimum": 0 }
    },
    "trajectory": {
      "type": "array",
      "description": "Append-only audit log of events, reconstructed from the checkpointer at end of run",
      "items": { "$ref": "mra:trajectory_event" }
    },
    "summary": {
      "type": "string",
      "description": "Rolling progress note carried into the next LLM prompt; length-bounded so context does not grow with repo size (NFR-12)"
    },
    "note": {
      "type": "object",
      "description": "The step just taken, as {action, detail}. A single slot, not a list: the checkpointer stores one state snapshot per step, so the checkpoint history IS the audit log and trajectory events are reconstructed from it",
      "additionalProperties": false,
      "properties": {
        "action": { "type": "string" },
        "detail": { "type": "object" }
      }
    },
    "tokens": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "pro_in":  { "type": "integer", "minimum": 0 },
        "pro_out": { "type": "integer", "minimum": 0 },
        "flash_in":{ "type": "integer", "minimum": 0 },
        "flash_out":{ "type": "integer", "minimum": 0 },
        "tool_calls": { "type": "integer", "minimum": 0 }
      }
    },
    "done": { "type": "boolean" }
  }
}
```

**`call_site` sub-schema** (`$id: mra:call_site`):

```json
{
  "$id": "mra:call_site",
  "type": "object",
  "additionalProperties": false,
  "required": ["file", "line", "col", "symbol"],
  "properties": {
    "file":   { "type": "string" },
    "line":   { "type": "integer", "minimum": 1 },
    "col":    { "type": "integer", "minimum": 0 },
    "symbol": { "type": "string", "description": "Fully-qualified matched symbol, e.g. datetime.datetime.utcnow" },
    "kind":   { "enum": ["call", "import", "attribute", "decorator"], "default": "call" }
  }
}
```

**`trajectory_event` sub-schema** (`$id: mra:trajectory_event`):

```json
{
  "$id": "mra:trajectory_event",
  "type": "object",
  "additionalProperties": false,
  "required": ["seq", "ts", "node", "action"],
  "properties": {
    "seq":    { "type": "integer", "minimum": 0 },
    "ts":     { "type": "string", "format": "date-time" },
    "node":   { "enum": ["MAP", "PLAN", "EDIT", "TEST", "CORRECT", "FINISH"] },
    "action": { "type": "string", "description": "Human-readable summary of what happened" },
    "detail": { "type": "object", "description": "Node-specific payload (files, diff, model, tokens)" }
  }
}
```

### 4.2 `ground_truth.json` (Tier-A scoring key)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "mra:ground_truth",
  "type": "object",
  "additionalProperties": false,
  "required": ["task_id", "source_api", "target_api", "call_sites", "gold_commit"],
  "properties": {
    "task_id":    { "type": "string" },
    "difficulty": { "enum": ["easy", "medium", "hard"] },
    "source_api": { "type": "string" },
    "target_api": { "type": "string" },
    "call_sites": {
      "type": "array",
      "description": "Every site that MUST change for a correct migration",
      "items": { "$ref": "mra:call_site" }
    },
    "expected_import_changes": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["file", "add"],
        "properties": {
          "file":   { "type": "string" },
          "add":    { "type": "array", "items": { "type": "string" } },
          "remove": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "semantic_checks": {
      "type": "array",
      "description": "Behaviour that must hold post-migration but is not syntactic (e.g. timezone-aware datetime)",
      "items": { "type": "string" }
    },
    "gold_commit": { "type": "string", "description": "Git SHA of the hand-verified correct migrated tree" }
  }
}
```

### 4.3 Test-report contract (normalized verifier output)

Produced by wrapping `pytest-json-report`; the agent consumes only this normalized shape.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "mra:test_report",
  "type": "object",
  "additionalProperties": false,
  "required": ["task_id", "phase", "total", "passed", "failed", "errors", "skipped", "failures", "duration_s"],
  "properties": {
    "task_id":  { "type": "string" },
    "phase":    { "enum": ["pre", "post", "recovery"] },
    "total":    { "type": "integer", "minimum": 0 },
    "passed":   { "type": "integer", "minimum": 0 },
    "failed":   { "type": "integer", "minimum": 0 },
    "errors":   { "type": "integer", "minimum": 0 },
    "skipped":  { "type": "integer", "minimum": 0 },
    "failures": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["nodeid", "signature", "exc_type", "message"],
        "properties": {
          "nodeid":    { "type": "string", "description": "pytest node id, e.g. tests/test_core.py::test_utc" },
          "signature": { "type": "string", "description": "stable hash of (nodeid + exc_type + normalized message)" },
          "exc_type":  { "type": "string" },
          "message":   { "type": "string" },
          "trace":     { "type": "string", "description": "truncated stack trace fed to the recovery model" },
          "file":      { "type": "string" },
          "line":      { "type": "integer" }
        }
      }
    },
    "lint": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "errors":   { "type": "integer", "minimum": 0 },
        "warnings": { "type": "integer", "minimum": 0 }
      }
    },
    "duration_s": { "type": "number", "minimum": 0 }
  }
}
```

### 4.4 Metrics record (per completed task)

```json
{
  "$id": "mra:metrics",
  "type": "object",
  "additionalProperties": false,
  "required": ["task_id", "m1_recall", "m1_precision", "m2_pass_rate", "m3_tokens", "m3_steps"],
  "properties": {
    "task_id":     { "type": "string" },
    "m1_recall":   { "type": "number", "minimum": 0, "maximum": 100 },
    "m1_precision":{ "type": "number", "minimum": 0, "maximum": 100 },
    "m2_pass_rate":{ "type": "number", "minimum": 0, "maximum": 100 },
    "m2_regressions": { "type": "integer", "minimum": 0 },
    "m3_tokens":   { "type": "integer", "minimum": 0 },
    "m3_steps":    { "type": "integer", "minimum": 0 },
    "m3_cost_usd": { "type": "number", "minimum": 0 },
    "recovery_used": { "type": "boolean" },
    "outcome":     { "enum": ["success", "gave_up", "error"] },
    "imports": {
      "description": "Import accuracy vs expected_import_changes (docs/05 §2.3a); null without them",
      "type": ["object", "null"],
      "additionalProperties": false,
      "required": ["accuracy", "expected", "spurious", "missing"],
      "properties": {
        "accuracy": { "type": "number", "minimum": 0, "maximum": 100 },
        "expected": { "type": "integer", "minimum": 0 },
        "spurious": { "type": "array", "items": { "type": "string" } },
        "missing":  { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

### 4.5 Run metadata (`run_meta.json`, written by every `mra run`)

Written in `run_with_report`'s `finally`, so a crashed or refused run has one too. The
verdict reads it: `expected_sites` (from `ground_truth.json`, `null` without one) is what
makes a run that finds no call site where some are expected YELLOW `nothing_to_migrate`.

```json
{
  "$id": "mra:run_meta",
  "type": "object",
  "additionalProperties": false,
  "required": ["run_id", "task_id", "repo_name", "agent_version", "target", "source_api",
               "target_api", "has_ground_truth", "expected_sites", "started_at", "wall_clock_s",
               "completed_at", "completed_tz", "token_budget", "run_timeout_s", "crash",
               "crash_summary", "refused", "llm"],
  "properties": {
    "run_id":           { "type": "string" },
    "task_id":          { "type": "string" },
    "repo_name":        { "type": "string" },
    "agent_version":    { "type": "string" },
    "target":           { "type": "string", "description": "Codemod target, e.g. datetime.utcnow" },
    "source_api":       { "type": ["string", "null"] },
    "target_api":       { "type": ["string", "null"] },
    "has_ground_truth": { "type": "boolean" },
    "expected_sites":   { "type": ["integer", "null"], "minimum": 0,
                          "description": "len(ground_truth.call_sites); null without ground truth" },
    "started_at":       { "type": "string", "description": "ISO 8601, seconds" },
    "wall_clock_s":     { "type": "number", "minimum": 0 },
    "completed_at":     { "type": "string", "description": "ISO 8601 local time with offset" },
    "completed_tz":     { "type": ["string", "null"] },
    "token_budget":     { "type": "integer", "minimum": 0 },
    "run_timeout_s":    { "type": "integer", "minimum": 0 },
    "crash":            { "type": ["string", "null"], "description": "Full traceback" },
    "crash_summary":    { "type": ["string", "null"], "description": "ExcType: message" },
    "refused":          { "type": ["string", "null"], "description": "PreconditionError / PrivacyError" },
    "llm": {
      "type": "object",
      "additionalProperties": false,
      "required": ["calls", "egress", "privacy"],
      "properties": {
        "calls":   { "type": "array", "items": { "type": "object" } },
        "egress":  { "type": "object" },
        "privacy": { "type": "string" }
      }
    }
  }
}
```

## 5. Functional boundaries — what the agent will NOT do

Explicit non-goals. These bound the LLM's authority and prevent scope creep and unsafe behaviour.

- **NB-1** The agent will **not** modify anything outside Python source files (no CI config, no infrastructure, no Dockerfiles, no environment provisioning, no OS packages).
- **NB-2** The agent will **not** rewrite business logic unrelated to the specified migration. Only code affected by the migration contract may change; incidental refactors are out of scope.
- **NB-3** The agent will **not** change the public API of the target repo (no renaming its functions/classes) except where the migration contract requires it.
- **NB-4** The agent will **not** add, delete, or weaken tests to make the suite pass. The test suite is the oracle; tampering with it is a hard failure. (The verifier snapshots test files and rejects any run where they changed.)
- **NB-5** The agent will **not** perform network installs or fetch external code at runtime beyond the pinned dependency set baked into the sandbox image.
- **NB-6** The agent will **not** operate outside the Docker sandbox; it has no access to the host filesystem, host git, or host credentials.
- **NB-7** The agent will **not** attempt migrations not on the finalized target list (§Charter 3) without a new contract.
- **NB-8** The agent will **not** proceed past the retry ceiling; unresolved failures are logged and flagged for human review, never silently accepted.
- **NB-9** The agent handles **single-language (Python)** repositories only; polyglot repos are out of scope for this project.
- **NB-10** The agent assumes the pre-migration suite is green; repairing a repo that fails *before* migration is out of scope (M2 would be undefined).

## 6. Non-functional requirements (constraints)

**NFR-x** = non-functional requirement. Concrete, tunable, and logged.

| ID | Constraint | Default | Rationale |
|---|---|---|---|
| NFR-1 | `MAX_FIX_ATTEMPTS` per failure signature | 3 | Caps the recovery loop; prevents infinite self-correction. |
| NFR-2 | Per-task token budget (hard ceiling) | 2,000,000 tokens | Bounds cost; run aborts and is flagged if exceeded. M3 is graded. |
| NFR-3 | Per-run wall-clock timeout | 30 min | Bounds long-horizon runs; abort + flag on breach. |
| NFR-4 | Per-`pytest` invocation timeout (in sandbox) | 120 s | Catches hangs/infinite loops introduced by a bad edit. |
| NFR-5 | Edit batch size | 1–5 files | Small batches localise failures and keep test feedback informative. Ablation variable. |
| NFR-6 | LLM temperature for edits | 0.0–0.2 | Determinism/reproducibility; deterministic codemods use no LLM. |
| NFR-7 | Reproducibility | Fixed seeds + pinned deps + snapshotted image | Runs must be re-executable for the paper. |
| NFR-8 | Isolation | One Docker container per run; no host mounts except the repo copy + output dir | Safety (NB-6). |
| NFR-9 | Rollback | `git` snapshot before each batch; revertible on failure | Prevents a bad batch from corrupting later state. |
| NFR-10 | Observability | Every LLM + tool call logged with tokens, model, latency | Feeds M3 and the trajectory deliverable. |
| NFR-11 | Model routing | V4-Pro for edits/trace reasoning; V4-Flash for summaries/classification | Controls token overhead (graded). |
| NFR-12 | Context budget per LLM edit call | Only the target file + graph slice + rolling summary | Never send full state; long horizons blow context. |
| NFR-13 | Data retention | Trajectories + metrics stored per run under `runs/<run_id>/` | Auditability and paper reproducibility. |
| NFR-14 | Portability | Runs on CachyOS/Arch host with Docker; no distro-specific host deps | Matches operator environment. |

## 7. External interfaces

- **LLM API:** OpenAI-compatible endpoint, `base_url=https://api.deepseek.com`, models `deepseek-v4-pro` / `deepseek-v4-flash`. Auth via `DEEPSEEK_API_KEY` env var (never hard-coded). Prompt caching relied upon for the stable repo/system prefix (lowers M3).
- **Docker:** local daemon; image built from `Dockerfile.sandbox` (see Data & Evaluation Protocol D5).
- **Filesystem:** input repo (read-only mount → copied writable inside sandbox); `runs/<run_id>/` output (trajectory, patch, metrics).
- **Git:** repository-local operations inside the sandbox (snapshot, diff, apply).

## 8. Traceability

Every FR maps to at least one acceptance test in the test plan; every metric (M1–M3) maps to a schema in §4.4 and a formula in the Data & Evaluation Protocol (D5). The functional boundaries (§5) map to guard checks in the verifier (NB-4 test-tamper check) and the sandbox (NB-6 isolation).

---
*This SRS is the source of truth for data shapes and constraints. Code, prompts, and tests must conform to the schemas in §4; any change to a contract requires a document revision.*
