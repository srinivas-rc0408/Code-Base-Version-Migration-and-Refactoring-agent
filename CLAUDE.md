# CLAUDE.md

Instructions for AI coding assistants (Claude Code, Cursor, etc.) working in this repository. Read this before making changes. Human contributors should read it too — it encodes the project's conventions and hard rules.

## What this project is

The **Migration & Refactoring Agent (MRA)**: an autonomous agent that performs a specified library/language version migration across a multi-module **Python** codebase and verifies the result with the repo's own test suite. It is an **academic research project**, not a product. Correctness, reproducibility, and inspectability matter more than speed or features.

The agent is a **LangGraph 1.x state machine**: `MAP → PLAN → EDIT → TEST → CORRECT`. The self-correction loop and the dependency-ordered editing are the point of the project — never shortcut them.

## Golden rules (do not violate)

1. **Never weaken or edit the test suite to make it pass.** The tests are the oracle. Changing test files to force a green run is a hard failure. If a test seems wrong, flag it — do not touch it.
2. **Never put secrets in code, docs, or commits.** API keys come from environment variables (`os.environ["DEEPSEEK_API_KEY"]`) loaded from `.env` (gitignored). See `CONFIGURATION.md`. If you see a hard-coded key, stop and remove it.
3. **All code execution happens inside the Docker sandbox**, never on the host. Do not add code that shells out on the host filesystem.
4. **Data shapes are contracts.** `MigrationState`, `ground_truth.json`, the test report, and the metrics record follow the JSON Schemas in `docs/03_SRS.md §4`. Do not change a shape without updating the schema and the doc in the same change.
5. **Deterministic edits are codemods, not LLM calls.** If an edit is a mechanical, rule-based transform, implement it as a `libcst` codemod under `src/mra/codemods/`. Reserve the LLM for genuinely ambiguous edits and for failure recovery. This is a correctness and cost (M3) requirement.
6. **Respect the functional boundaries** in `docs/03_SRS.md §5` (NB-1…NB-10). In particular: Python source only; no infra/CI changes; no business-logic rewrites unrelated to the migration; no network at agent runtime; stop at `MAX_FIX_ATTEMPTS`.
7. **Pin dependencies.** Never add an unpinned dependency. Add it to `pyproject.toml` with a version and explain why.

## Tech stack (fixed — verified Sep 2026)

- **Python 3.12**
- **LangGraph 1.x** (build v1 patterns; the 0.x API is maintenance-only)
- **libcst** — analysis + codemods (preserves formatting/comments)
- **networkx** — dependency/call graph
- **pytest** + **pytest-json-report** + **ruff** — verification
- **GitPython** — snapshot / rollback / patch
- **Docker** `python:3.12-slim` (or rootless Podman) — sandbox
- **LLM providers per role from `mra.toml`** (CONFIGURATION.md §3) — default **DeepSeek V4-Pro** (edit, recover) and **V4-Flash** (summarize, classify) over the OpenAI-compatible endpoint; any OpenAI-compatible server (incl. local Ollama/vLLM) or the pinned `anthropic` SDK. Never write a model name or base URL in code.

Do not swap frameworks or add new heavy dependencies without updating `docs/` and getting sign-off.

## Where things live

| Area | Path |
|---|---|
| State object | `src/mra/state.py` |
| Graph wiring (nodes + edges) | `src/mra/graph.py` |
| Node logic | `src/mra/nodes/*.py` |
| Static analysis (libcst visitors, graph builder) | `src/mra/analysis/` |
| Deterministic codemods (per migration task) | `src/mra/codemods/` |
| Sandbox wrappers (docker run, git) | `src/mra/sandbox/` |
| Model router + token accounting (M3) | `src/mra/models/` |
| Metric computation (M1, M2) | `src/mra/metrics/` |
| Recovery loop (CORRECT/TEST until green or capped) | `src/mra/recovery/` |
| Rolling summary + LLM context budget | `src/mra/memory/__init__.py` |
| Opt-in experience store (off by default) | `src/mra/memory/experience.py` |
| Verified skill promotion (opt-in, human-approved) | `src/mra/skills.py` |
| Corpus | `corpus/tierA/`, `corpus/tierB/` |
| Run outputs | `runs/<run_id>/` — gitignored, except the four paper-cited artefacts under `runs/benchmark/`: `results.json`, `results.md`, `failure-analysis.md`, `RESULTS_SUMMARY.md` |

## Coding conventions

- **Type hints everywhere.** Public functions are fully annotated. Run `mypy` if configured.
- **Small, single-purpose functions.** Nodes are `state -> partial state update`; keep side effects explicit (file writes, sandbox runs).
- **Structured I/O only.** Parse `pytest`/tool output into the JSON contracts; never scrape free text with regex where a structured report exists (`pytest-json-report`).
- **Determinism.** LLM temperature 0.0–0.2 for edits; log the model ID and token counts for every call (feeds M3).
- **No `print` for logging.** Use the logger; every LLM/tool call is recorded to the trajectory.
- **Docstrings** state the node/function contract (inputs read, outputs written, side effects).

## How to run and test

```bash
# unit tests for the agent itself (offline, parallel via pytest-xdist; live and
# slow tests are deselected). Every test uses its own run ids and tmp paths.
pytest

# Docker-heavy hunt runs and the benchmark-payload checks (pre-merge)
pytest -m slow

# live-provider tests only (each skips when its key is unset)
pytest -m live

# bug hunt (tests/hunt/, part of the default run): hypothesis uses the "default"
# profile (20 examples) unless told otherwise; the full hunt is 500 examples
HYPOTHESIS_PROFILE=hunt pytest tests/hunt

# lint + format
ruff check . && ruff format .

# build the sandbox image
docker build -f Dockerfile.sandbox -t mra-sandbox:py312 .

# run a migration on a controlled task
python -m mra.run --task-dir corpus/tierA/task01_datetime

# full agent + GREEN/YELLOW/RED verdict + PDF report (src/mra/verdict.py, src/mra/report/)
mra run --task-dir corpus/tierA/task04_multimodule
```

### Gate policy

- **Inner loop (each change):** the targeted tests (the test file(s) for what you touched, plus the touched module's tests) and `ruff check .` / `ruff format --check .`. Test-first; one commit per change.
- **Before merging any branch:** the full gate, once:
  1. `pytest`: 0 failed on the summary line;
  2. `pytest -m slow`: 0 failed;
  3. `python docs/paper/verify_paper.py`: no failure beyond the known §4.5 one;
  4. the `runs/benchmark/results.json` scientific payload is unchanged (165 rows, 55 aggregates; `git diff --quiet HEAD -- runs/benchmark`);
  5. `docker ps -a` lists no container left by the run.

  If it fails, `git bisect` over the branch's per-change commits to find the culprit, fix it, and re-run the full gate.

No schema in `docs/03_SRS.md §4` changes without updating the doc. A new test must be parallel-safe: its own run ids (`tests.conftest.unique_id`) and `tmp_path`, never a shared fixed path, the cwd or a global env var. Live tests (`pytest -m live`) are optional and run only with provider keys.

## Commit conventions

Use Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`. One logical change per commit. Reference the build phase where relevant (e.g. `feat(analysis): call-site visitor for datetime.utcnow [P1]`).

## Current phase / context

Fill this in as you progress so the assistant has current context:

- **Current phase:** P0–P5 done; paper draft v1 written (`docs/paper/paper.md`)
- **Active migration task:** T1 — `datetime.utcnow()` → `datetime.now(timezone.utc)`
- **Next milestone:** P6 — Tier-B external validity, and the paper's hand-written
  sections (Abstract, §2, §10, References)

## When unsure

If a change would touch a data contract, a functional boundary, the test oracle, or a dependency version — stop and ask the human. Prefer the smallest correct change. Correctness and reproducibility beat cleverness.
