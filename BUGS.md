# BUGS — v0.3.0 bug hunt (find only, nothing fixed)

Hunted on 2026-10-06 against the v0.3.0 working tree (`src/mra/` as checked out, including the
uncommitted consequence-repair changes; `src/mra/` was not modified by the hunt).

Every bug below is reproduced by a test under `tests/hunt/`, marked
`xfail(strict=True, reason="BUG-NN: …")`. The hunt runs in the default `pytest` run with a small
hypothesis profile; `HYPOTHESIS_PROFILE=hunt` runs the full 500-example hunt:

```bash
uv pip install --python .venv/bin/python -e '.[dev]'                   # pins hypothesis + mutmut
HYPOTHESIS_PROFILE=hunt .venv/bin/python -m pytest tests/hunt -q      # all xfail = all bugs still open
.venv/bin/python -m pytest tests/hunt/<file>::<test> --runxfail        # see one bug fail
tests/hunt/mutation/run.sh                                             # mutation testing (section 8)
```

When a fix lands, its strict xfail turns into a failure: remove the marker and keep the test.

## Counts

| Severity | Count | | Category | Count |
|---|---|---|---|---|
| critical | 2 | | security | 4 |
| high | 6 | | hostile-reply | 4 |
| medium | 5 | | codemod | 2 |
| low | 4 | | env-fault | 4 |
| **total** | **17** | | path-handling | 1 |
| | | | report | 2 |
| | | | determinism | 0 |

Hunts that found **nothing** (all invariants held): core fuzzing — 500 random multi-module repos
over 11 import styles, 14 call-site contexts, 11 decoy kinds (finder count exact, zero decoys
matched, output parses, idempotent, no collateral AST edits, imports only when needed, migrated
tree runs with `-W error::DeprecationWarning`); metamorphic rename / reorder / CRLF / tabs
(125 examples each), paths with spaces + non-ASCII, a colon, a symlinked repo path (offline and
full docker run); determinism — 5 Tier-A tasks × 3 runs, patches byte-identical and every other
artifact identical after normalising timestamps / run ids / SHAs; transport faults (HTTP 500,
malformed JSON, reply slower than the timeout) all end in `ProviderError` within the time bound
with the tree untouched; Ctrl+C mid-batch (report written, RED, no container left, no
half-migrated file, corpus untouched); distinct run ids in parallel; missing repo path; repo
with no tests; `.env` contents never reached a prompt or an artifact.

## Bugs (sorted by severity)

| ID | Category | Severity | Reproduction | Expected vs actual |
|---|---|---|---|---|
| BUG-07 | path-handling | critical | `test_metamorphic.py::test_full_run_location_invariance[build]`, `::test_location_does_not_change_the_answer[*-build_component\|dist_component\|venv_component]`. Put a task (or `--runs-dir`) under any directory named `build`, `dist`, `venv`, `.venv`, `.git`, `__pycache__`… e.g. `~/build/task01_datetime`. | **Expected** the same sites, patch and verdict as anywhere else. **Actual** `python_files()` (`analysis/dep_graph.py`) tests `SKIP_DIRS` against every part of the *absolute* path, so every file is skipped: MAP finds 0 sites, nothing is edited, the residual scan also sees nothing, and the run reports **GREEN with an empty migration.patch**. A silent false GREEN. |
| BUG-11 | security | critical | `test_security.py::test_symlink_outside_repo_is_not_followed[file\|dir]`: `old/src/pkg/shared.py -> /elsewhere/shared.py` (or a symlinked directory). | **Expected** a link leaving the repo is not followed (or the run refuses). **Actual** `shutil.copytree` in `run_migration` dereferences links, so the outside file — or a whole outside directory tree — is copied into `runs/<id>/repo`, migrated, committed, written into `migration.patch`, `report.json` and the PDF; with `--llm` its content is eligible for a prompt to a remote provider. A link to `$HOME` would copy the home directory. |
| BUG-04 | hostile-reply | high | `test_hostile_replies.py::test_hostile_reply_is_rejected_and_counted[{empty,whitespace,reasoning_only,reasoning_cut_off,test_file,path_traversal,absolute_path,outside_scope}-residual]` | **Expected** a reply that is not a plausible rewrite of the located file is rejected unapplied. **Actual** residual mode (`extract_source`) takes any text that parses as the whole new file: an empty reply, `<think>…</think>` with no answer, or a snippet meant for another file (`FILE: tests/…`, `FILE: ../../outside.py`) **overwrites the located module** (e.g. `report.py` becomes empty or `X = 1`). The attempt is counted, but the module's content is gone from the run's tree and the patch. Consequence mode rejects all of these. |
| BUG-05 | hostile-reply | high | `test_hostile_replies.py::test_finish_reason_length_is_rejected` (real OpenAI SDK, local server returning `finish_reason="length"`); `::…[truncated_parseable_no_fence-residual]` | **Expected** a reply cut off by `max_tokens` is rejected. **Actual** `finish_reason` is never read (`providers/openai_compatible.py` keeps only `message.content`); a truncation that happens to end on a statement boundary parses and is applied, **deleting the tail of the file** (here `stamp_age_seconds`). |
| BUG-09 | env-fault | high | `test_env_faults.py::test_repo_that_already_is_a_git_repo`: `old/` is its own git repo (as any real checkout is) whose root commit differs from the working tree. | **Expected** GREEN with the same patch as the plain tree. **Actual** `copytree` copies `.git`, so snapshots are committed on top of the user's history and `evidence.base_commit()` (`rev-list --max-parents=0 HEAD`) picks the **user's root commit** as the "pre-migration" tree: `apply_check` fails → **RED** for a correct migration, and lint/semantic baselines are computed against the wrong tree. |
| BUG-10 | env-fault | high | `test_env_faults.py::test_two_runs_with_the_same_id_at_once`: two `mra run --run-id same` (task01 and task04) 3 s apart. | **Expected** the second run refuses the busy id (or they cannot collide). **Actual** the second `run_with_report` `rmtree`s the first run's directory mid-run; both processes exit 0 (GREEN) while `runs/same/` holds only task04's artifacts — one run's GREEN is reported for a directory that no longer contains it. (Docker `--name mra-<run_id>` would also collide if their TEST phases overlap.) |
| BUG-12 | security | high | `test_security.py::test_fake_key_never_reaches_a_remote_prompt[{bearer_header,dict_api_key,stripe_live,huggingface,url_password}]` | **Expected** secrets in the located file / failure message are redacted before a remote call. **Actual** `privacy.SECRET_PATTERNS` + `ASSIGNMENT` miss common shapes, which reach the remote prompt verbatim: `"Authorization": "Bearer nvapi-…"` (the NVIDIA key format this project itself uses), `{"api_key": "…"}` (dict key, quote before the colon), `sk_live_…` (Stripe), `hf_…` (Hugging Face), `postgres://user:password@host`. Caught correctly: `sk-…`, `sk-ant-…`, `NVIDIA_API_KEY = "…"`, `aws_secret_access_key = "…"`. |
| BUG-17 | report | high | `test_report_robustness.py::test_500_files`, `::test_300_character_file_names_500_files` | **Expected** a 500-file run fits in ≤ 14 pages by truncating. **Actual** `render()` raises `RuntimeError: report exceeds 14 pages even at the last truncation level` (pages at the last ladder level: 200 files → 9, 300 → 11, 400 → 14, 500 → 16). The per-file **Changes table** (`pdf.py` `_changes`) has no limit in `LADDER`. Because `build_report` runs in `run_with_report`'s `finally`, a large repo gets **no report at all** and the CLI dies with a traceback. |
| BUG-03 | hostile-reply | medium | `test_hostile_replies.py::test_hostile_reply_is_rejected_and_counted[{no_code_block,syntax_error,truncated_fence}-residual]` | **Expected** an unparseable reply is rejected and costs one attempt, like consequence mode does. **Actual** in residual mode `corrective_patch` lets `libcst.ParserSyntaxError` escape `LLMCorrector.__call__`, which escapes `recover()` / the CORRECT node: one prose or broken reply **ends the whole run** (RED "crashed") with the remaining attempts unspent. |
| BUG-06 | hostile-reply | medium | `test_hostile_replies.py::test_net_zero_reintroduction_is_rejected`, `::…[reintroduce_deprecated-residual]` | **Expected** a patch that adds a new `datetime.utcnow()` is rejected (anti-reversal). **Actual** `reversal()` compares the *count* of residual sites before/after; a patch that migrates the located site and plants `utcnow()` elsewhere is net zero and is applied. |
| BUG-01 | codemod | medium | `test_fuzz_codemod.py::test_fuzz_with_module_attribute_reexport`; saved shrunk example `tests/hunt/fixtures/fuzz_with_module_attribute_reexport/` (`from pkg import compat` + `compat.datetime.utcnow()`, where `pkg/compat.py` does `from datetime import datetime`). | **Expected** `compat.datetime.now(timezone.utc)` + `from datetime import timezone`. **Actual** with analyzer sites, `_form` picks the binding form from the attribute *count* (2 → "module") and writes `compat.datetime.now(compat.timezone.utc)` → `AttributeError: module 'pkg.compat' has no attribute 'timezone'` at runtime. The finder resolved it correctly as a class site; the codemod re-derived the form wrongly. (The semantic check flags it as YELLOW "tz not imported", so it is not silent.) |
| BUG-08 | env-fault | medium | `test_env_faults.py::test_docker_daemon_stopped_is_named_as_such` (stub `docker` that prints "Cannot connect to the Docker daemon…" and exits 125). | **Expected** RED naming the sandbox / docker daemon. **Actual** RED `precondition`: "The pre-migration suite was not green… Make the original suite pass" — it blames the user's tests; the daemon message is only in `test_report_pre.json`. (A missing runtime binary is reported as `crashed: FileNotFoundError`, which is at least accurate.) |
| BUG-13 | security | medium | `test_security.py::test_fake_key_never_reaches_a_report`: a key on the line above an edited call. | **Expected** secrets never appear in a log / trajectory / report. **Actual** diff excerpts are copied unredacted into `report.json` and the PDF (the key is diff context). `migration.patch` itself is excluded from this check as the deliverable. `.env` content did not leak. |
| BUG-14 | env-fault | low | `test_env_faults.py::test_read_only_output_dir_fails_cleanly` | **Expected** a one-line error and a non-zero exit. **Actual** `PermissionError` traceback from `out_dir.mkdir` inside `run_with_report`'s `finally` (exit 1). |
| BUG-02 | codemod | low | `test_fuzz_codemod.py::test_fuzz_alias_named_timezone`; fixture `tests/hunt/fixtures/fuzz_alias_named_timezone/` (`from datetime import datetime as timezone; timezone.utcnow()`). | **Expected** a working rewrite (e.g. `timezone.now(datetime.timezone.utc)` via a fresh import name). **Actual** `timezone.now(timezone.utc)` + `from datetime import timezone`, which rebinds the alias → `AttributeError: type object 'datetime.timezone' has no attribute 'now'`. |
| BUG-15 | security | low | `test_security.py::test_codemod_on_a_symlinked_file_does_not_write_outside` | **Expected** `find_in_repo` / `apply_codemod` do not follow a symlinked file out of the repo. **Actual** they read and **write through** the link, modifying the outside file. Not reachable from `mra run` today (the run copy is dereferenced, see BUG-11), but `locate`/`reversal` and any direct caller share these functions. |
| BUG-16 | report | low | `test_report_robustness.py::test_non_ascii_paths_are_legible[src/пакет/модуль.py\|src/包/模块_时间.py]` | **Expected** non-ASCII paths legible in the PDF. **Actual** Latin-1 paths render (`módulo_ñandú` passes), but Cyrillic and CJK characters are not in Helvetica/WinAnsi and disappear from the text (`модуль`, `模块_时间` absent). report.json is correct. |

## 8. Mutation testing — surviving mutants

MUTATION_RESULTS

## Notes on method

* Each harness has a control that must pass (a correct patch lands, a plain path is GREEN, Latin
  paths render, a 100-file run fits) so a failure means the product, not the harness.
* `xfail(strict=True)` marks are the source of truth for open bugs; this file mirrors them.
* Severity: critical = silent wrong verdict or data leaving the repo boundary; high = data loss
  in the run, secrets to a remote host, wrong verdict, or no report; medium = crash/misleading
  output with a correct overall RED or a YELLOW that catches it; low = rare input or not reachable
  from `mra run`.
