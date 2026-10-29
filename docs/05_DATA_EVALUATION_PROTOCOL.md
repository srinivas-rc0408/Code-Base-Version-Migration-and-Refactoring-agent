# Data & Evaluation Protocol
### Codebase-Wide Version Migration & Refactoring Agent (MRA)

| Field | Value |
|---|---|
| **Document** | Data & Evaluation Protocol (Deliverable D5) |
| **Author** | Srinivas RC | **Guide** | Dr Nimrita Koul |
| **Version** | 0.1 (Draft) | **Date** | 24 August 2026 |
| **Status** | For guide review |

**Revision history**

| Ver | Date | Change |
|---|---|---|
| 0.1 | 24 Aug 2026 | Corpus spec, metric formulas, sandbox setup |

> Define the evaluation **before** writing agent logic. Fixing the metrics first forces precise thinking and prevents "moving the goalposts" once results come in. This document is the scoring contract for the whole project.

---

## 1. Corpus specification

Two tiers. **Tier A is the scientific control (build first); Tier B is external validity.**

### 1.1 Tier A — controlled repos you author (gold standard)

Author 3–5 small multi-module Python packages, one per migration task, each in this exact shape:

```
corpus/tierA/task01_datetime/
├── old/                       # runs & PASSES pytest on the OLD API
│   ├── src/pkg/
│   │   ├── __init__.py
│   │   ├── core.py            # defines / contains the migrated pattern
│   │   ├── models.py          # imports core  -> dependency edge
│   │   └── utils.py           # second caller -> CROSS-FILE breakage (mandatory)
│   ├── tests/
│   │   ├── test_core.py
│   │   └── test_models.py
│   └── pyproject.toml         # pins the OLD library version
├── gold/                      # hand-written CORRECT migrated tree (mirrors old/)
│   └── ...                    # pins the NEW library version
├── ground_truth.json          # every affected call site (schema: mra:ground_truth)
└── task.yaml                  # {id, description, source_api, target_api, difficulty}
```

**Authoring rules (non-negotiable):**
1. The suite in `old/` **must pass** on the old library version, or M2 is undefined.
2. `gold/` is hand-verified correct and its suite passes on the new version.
3. `ground_truth.json` lists **every** site that must change — this is M1's denominator.
4. Every task must include **cross-file breakage** (a contract change in one file breaking a caller in another). Without it the dependency graph is untested and the project is a toy.
5. Vary **one factor at a time** across tasks (file count, call-site count, syntactic vs semantic change) so results are attributable.
6. At least one task must have a **semantic-only break** (behaviour changes, nothing raises on import) — e.g. `httpx` `follow_redirects` default flip, or Pydantic v2 `Optional` no longer defaulting to `None`. This proves M2 catches what M1 cannot.

### 1.2 Tier A git-tagging strategy
Keep `old/` and `gold/` as sibling directories (simplest to diff), **and** tag the states for reproducibility:

```bash
# inside each task's git repo
git tag task01/old   <sha-of-old-state>
git tag task01/gold  <sha-of-gold-state>
```
The agent always operates on a fresh checkout of `task01/old`; scoring diffs the agent result against `task01/gold`.

### 1.3 Tier B — real OSS repos (external validity)

**The pro move: the human migration pull-request IS the gold patch.** For a real repo that actually performed one of your migrations:

1. Find the migration PR (search the repo's history/changelog for e.g. "SQLAlchemy 2.0", "pydantic v2", "migrate to httpx").
2. `git checkout` the **parent commit** of that PR → this is the reproducible "before" state; tag it `tierB/<repo>/before`.
3. The **merged PR diff** is the human gold patch; tag the merge commit `tierB/<repo>/gold`.
4. Run the agent on `before`; score its patch against the gold patch (M1 proxy) and against the repo's own suite (M2).

**Selection criteria:** good test coverage, mid-size (multi-module but not enormous), Python-only, permissive license. Candidate hunting grounds: repos already in SWE-bench's 12 source projects and any well-tested mid-size library. **Always pin to a specific old tag/SHA** so the corpus is reproducible — never "latest".

## 2. Metric definitions (hard formulas)

Let, for a task:
- $A$ = set of affected call sites in `ground_truth.json` (must-change sites).
- $X$ = set of sites the agent actually modified.
- $\mathrm{TP}$ = sites in $A$ the agent modified **and** matched gold semantics (correct + necessary edits).
- $T$ = total tests; $T_{\text{pre}}$ = tests passing before migration; $T_{\text{post}}$ = tests passing after.

### 2.1 M1 — Migration Completeness
Reported as **recall and precision** (completeness alone can be gamed by editing everything):

$$
M_{1}^{\text{recall}} = \frac{\mathrm{TP}}{|A|}\times 100
\qquad
M_{1}^{\text{precision}} = \frac{\mathrm{TP}}{|X|}\times 100
\qquad
M_{1}^{F_1} = \frac{2\,M_1^{\text{recall}} M_1^{\text{precision}}}{M_1^{\text{recall}} + M_1^{\text{precision}}}
$$

- **Recall** = did it find and fix every required site? (missing sites hurt this)
- **Precision** = of what it touched, how much was correct and necessary? (over-editing / wrong edits hurt this)
- Report both; the $F_1$ is the single headline number.

### 2.2 M2 — Post-Migration Test Pass Rate
Precondition: $T_{\text{pre}} = T$ (suite green before migration).

$$
M_{2} = \frac{T_{\text{post}}}{T}\times 100
\qquad
\text{Regressions } R = T_{\text{pre}} - T_{\text{post}}
$$

- $M_2 = 100\%$ with $R = 0$ is a fully successful migration.
- Report $R$ separately: a single regression is more informative than a percentage for small suites.

### 2.3 M3 — Token / Step Overhead
Let $t^{\text{in}}_m, t^{\text{out}}_m$ be input/output tokens for model $m$, and $p^{\text{in}}_m, p^{\text{out}}_m$ the per-token prices.

$$
\text{Tokens} = \sum_{m}\left(t^{\text{in}}_m + t^{\text{out}}_m\right)
\qquad
\text{Steps} = (\text{LLM calls}) + (\text{tool calls})
$$

$$
\text{Cost} = \sum_{m}\left(t^{\text{in}}_m\,p^{\text{in}}_m + t^{\text{out}}_m\,p^{\text{out}}_m\right)
$$

Normalized overhead (for fair cross-task comparison, since larger tasks legitimately cost more):

$$
\text{Tokens per site} = \frac{\text{Tokens}}{|A|}
\qquad
\text{Steps per site} = \frac{\text{Steps}}{|A|}
$$

Use current DeepSeek rates for Cost (verify at run time): V4-Pro and V4-Flash, off-peak/peak, with prompt-cache hits billed far lower — cache the stable repo/system prefix to reduce effective input cost.

### 2.3a Import accuracy (separate from M1)
M1 scores call sites, and an import line is never a site, so M1 cannot see a redundant
or a missing import. Import accuracy scores the import edits on their own, against
`ground_truth.json` `expected_import_changes` (SRS §4.2). Per non-test source file, a
*change* is one name the file starts importing (add) or stops importing (remove),
comparing the bound names of every import statement before and after the migration
(`as` aliases win). Let $E$ = expected changes and $G$ = the changes the run made:

$$
\text{Imports} = \frac{|E \cap G|}{|E \cup G|}\times 100 \qquad (100 \text{ when } E \cup G = \varnothing)
$$

- **Spurious** = $G \setminus E$: an import gold does not add (e.g. a redundant
  `from datetime import timezone` beside an existing `import datetime as dt`).
- **Missing** = $E \setminus G$: a required import the run did not add.
- Undefined (`null`) when the task has no `expected_import_changes`. It never changes M1,
  and it is not a verdict condition; the report lists it under Verification.

### 2.4 Reference computation (already stubbed in the resource pack)

```python
def m1(agent_sites: set, correct_sites: set, ground_truth_sites: set):
    tp = len(correct_sites & ground_truth_sites)
    recall = 100 * tp / max(len(ground_truth_sites), 1)
    precision = 100 * tp / max(len(agent_sites), 1)
    f1 = 0 if (recall + precision) == 0 else 2 * recall * precision / (recall + precision)
    return {"recall": recall, "precision": precision, "f1": f1}


def m2(t_total: int, t_post_pass: int):
    return {"pass_rate": 100 * t_post_pass / max(t_total, 1), "regressions": t_total - t_post_pass}
```

## 3. Experimental protocol

- **One variable at a time.** Baseline run, then change exactly one factor and re-run.
- **Ablations (the paper's headline):**

| Ablation | Question it answers |
|---|---|
| With vs **without** the CORRECT loop | How much does self-correction contribute? (expected: large drop in M2 without it) |
| With vs **without** dependency-graph ordering | Does principled edit order prevent regressions? |
| Edit model: **V4-Pro vs V4-Flash** | Capability vs cost trade-off on M1/M3. |
| Batch size **1 vs 3 vs 5** | Effect on M2 (failure localization) and M3 (token overhead). |

- **Repetition:** run each configuration ≥ 3 times (LLM non-determinism); report mean ± spread.
- **Report failures honestly.** The failure analysis (which tasks failed, which failure class dominated, where the planner mis-ordered) is what makes the paper publishable and the viva strong.
- **Every run** writes `runs/<run_id>/` = `{patch, trajectory.json, metrics.json, config.yaml}`.

## 4. Sandbox environment setup (Docker, reproducible on CachyOS/Arch)

### 4.1 Sandbox image

```dockerfile
# Dockerfile.sandbox
FROM python:3.12-slim

# git is needed for snapshot/rollback/diff inside the sandbox
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

# verifier toolchain; pin versions for reproducibility (fill exact pins at build time)
RUN pip install --no-cache-dir \
    pytest pytest-json-report ruff

# task dependencies (old/new library versions) are installed per-task at run time
WORKDIR /work
```

Build once:

```bash
docker build -f Dockerfile.sandbox -t mra-sandbox:py312 .
```

### 4.2 Volume mounts and the run command

```bash
RUN_ID=$(uuidgen)
mkdir -p runs/$RUN_ID

docker run --rm \
  --name mra-$RUN_ID \
  --network none \                       # NB-5: no runtime network in the sandbox
  --user "$(id -u)":"$(id -g)" \         # CRITICAL on Arch: avoids root-owned output files
  -v "$PWD/corpus/tierA/task01_datetime/old":/work/repo:ro \   # input, read-only
  -v "$PWD/runs/$RUN_ID":/work/out:rw \                        # output, writable
  mra-sandbox:py312 \
  bash -lc '
     cp -r /work/repo /work/repo_rw && cd /work/repo_rw &&
     git init -q && git add -A && git commit -qm snapshot &&
     pip install -q -e . &&
     pytest --json-report --json-report-file=/work/out/pre.json ; true
  '
```

Notes on the flags (these are the "minute details" that bite people):
- `--user $(id -u):$(id -g)` makes files the container writes to `runs/<id>/` owned by **you**, not root. Without it, on Arch you get root-owned artifacts you then have to `sudo chown` — a classic bind-mount permission trap.
- Input repo mounted **read-only** (`:ro`); the container copies it to a writable path before editing (NB-6 isolation + clean rollback).
- `--network none` enforces NB-5 (no runtime installs/fetches); pre-bake all deps in the image or install from a pinned local wheel cache before cutting the network if a task needs a specific library version.
- `--rm` and a per-invocation container name keep runs isolated and self-cleaning. `SandboxRunner` names each container `mra-<run_id>-<6 hex>`, so two runs with one id (different runs dirs, parallel test workers) never collide on the name.

### 4.3 Podman alternative (recommended on Arch/CachyOS)
Arch ships rootless **Podman** cleanly, and rootless containers avoid root-owned bind-mount files by design (your UID maps to the container root). The commands are drop-in — replace `docker` with `podman`. If you prefer Docker, keep the `--user` flag above. Either is acceptable; document which you used for reproducibility.

### 4.4 Reproducibility checklist
- Pin every dependency version in `Dockerfile.sandbox` and each task's `pyproject.toml`.
- Record the image digest (`docker images --digests`) in `config.yaml` per run.
- Fix LLM `temperature` (0.0–0.2) and log the model IDs used.
- Store the sandbox image build args and the exact `docker run` command in `runs/<run_id>/config.yaml`.
- Never rely on host Python; all execution is inside the image.

## 5. Traceability to other documents
- Corpus shapes conform to `mra:ground_truth` and `mra:call_site` (SRS §4).
- Metric records conform to `mra:metrics` (SRS §4.4).
- Sandbox satisfies NFR-8/NFR-9 and boundary NB-5/NB-6 (SRS §5–6).
- Ablations feed the benchmarking report (Charter A4) and the paper (A5).

---
*This protocol is the scoring contract. Metrics and corpus rules are frozen once the guide approves; changing them after results exist requires a documented revision and re-run.*
