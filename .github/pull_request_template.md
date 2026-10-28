## What this changes

<!-- One or two sentences. Link the issue: Closes #NN -->

**Workstream:** <!-- A / B / C / D / E (see CONTRIBUTORS.md) -->

## How it was checked

<!-- Commands run and their result, or the benchmark rows that changed. -->

## Done-gate

- [ ] `ruff format --check .` passes
- [ ] `ruff check .` passes
- [ ] `pytest` passes offline: summary line shows 0 failed (say which tests were skipped and why)
- [ ] `pytest -m live` run if the change touches the model path (each test skips without its key)
- [ ] No test file was edited to make a test pass (CLAUDE.md golden rule 1)
- [ ] No secrets, API keys or `.env` content in the diff
- [ ] New dependencies are pinned in `pyproject.toml`
- [ ] If a data shape changed, `docs/03_SRS.md` section 4 changed with it
