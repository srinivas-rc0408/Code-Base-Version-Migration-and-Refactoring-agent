## What this changes

<!-- One or two sentences. Link the issue: Closes #NN -->

**Workstream:** <!-- A / B / C / D / E (see CONTRIBUTORS.md) -->

## How it was checked

<!-- Commands run and their result, or the benchmark rows that changed. -->

## Done-gate

- [ ] `ruff format --check .` passes
- [ ] `ruff check .` passes
- [ ] Inner loop on each change: targeted tests for what changed, `ruff check`, `ruff format --check`
- [ ] Pre-merge gate, once on the final commit (CLAUDE.md "Gate policy"):
  - [ ] `pytest`: 0 failed (say which tests were skipped and why)
  - [ ] `pytest -m slow`: 0 failed
  - [ ] `python docs/paper/verify_paper.py`: no failure beyond the known §4.5 one
  - [ ] `runs/benchmark/results.json` scientific payload unchanged (165 rows, 55 aggregates)
  - [ ] `docker ps -a` shows no leftover container
- [ ] New tests are parallel-safe: own run ids (`tests.conftest.unique_id`) and `tmp_path`
- [ ] `pytest -m live` run if the change touches the model path (each test skips without its key)
- [ ] No test file was edited to make a test pass (CLAUDE.md golden rule 1)
- [ ] No secrets, API keys or `.env` content in the diff
- [ ] New dependencies are pinned in `pyproject.toml`
- [ ] If a data shape changed, `docs/03_SRS.md` section 4 changed with it
