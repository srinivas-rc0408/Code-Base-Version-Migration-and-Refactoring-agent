# Notes for the author — Abstract, §1, §2, §10 after v0.4.0

These sections are yours to rewrite; the v0.4.0 pass did not touch them. Below
is every sentence in them that is now inaccurate or out of date. Each entry
gives the sentence as it stands, the correct fact, and the source for it.

## Abstract

1. > "The repair is scoped: every correction measured here repaired residual
   > call sites of the deprecated API."

   **Now false.** On `task07_cache`, every run's single correction rewrote
   `src/svc/store.py`, which holds no call site (the only site is in
   `src/svc/stamp.py`). That was a consequence repair, added in v0.3.0.
   *Source:* `corpus/blind/task07_cache/results.json` (`corrections[].changed` =
   `["src/svc/store.py"]` in r1–r3); `corpus/blind/task07_cache/ground_truth.json`
   (`call_sites`: `stamp.py` only); paper §3.5, §7.10.

2. > "On a blind held-out task whose break lies outside any call site, the agent
   > stops with a RED verdict and edits nothing it should not;"

   **Out of date.** This holds for v0.2.0 on `task06_scheduler` only (3/3 RED).
   On the second blind task, `task07_cache`, which also breaks off the call
   sites, v0.3.0 is GREEN on 3 of 3 runs and meets 9 of 9 criteria.
   *Source:* `corpus/blind/task06_scheduler/results.json`;
   `corpus/blind/task07_cache/results.json` and `results/RESULTS.md`; paper
   §7.9, §7.10.

3. > "recovery from such breaks is not supported in this version."

   **Now false.** Consequence repair has been supported since v0.3.0 (commit
   `06da274`), and the current version is 0.4.0. Its only measurement is
   `task07` (3/3 GREEN). `task06` has not been re-run since then.
   *Source:* commit `06da274`; `pyproject.toml` `version = "0.4.0"`; paper
   §3.5, §7.10, §9 item 7.

## §1 Introduction

4. > "In our benchmarks Ruff reached full detection parity with our analyzer yet
   > fixed none of the sites,"

   **Inaccurate, and older than v0.4.0.** Ruff's recall is 100 % on every task,
   but on `task05` it reports 7 hits for 6 sites, so its precision there is
   86 %. The analyzer's precision is 100 %. "Full detection parity" holds for
   recall only.
   *Source:* `runs/benchmark/results.md` §3 (`task05_signature_break`, ruff
   (DTZ): detected 7, recall 100 %, precision 86 %); paper §7.3.

5. > "What the loop repairs is residual call sites: a break the migration causes
   > in code that holds no deprecated call, such as a naive constant that the
   > newly aware clock is subtracted from, never reaches the model."

   **Out of date.** This was true through v0.2.0. Since v0.3.0, when no
   residual site is left, CORRECT scopes a consequence repair to the traced
   files and their migrated neighbours, and the model is asked for the patch.
   *Source:* `src/mra/nodes/correct_node.py` `consequence_scope()`; commit
   `06da274`; paper §3.5.

6. > "On a blind held-out task built that way, the agent fails safely (§8.2)."

   **Out of date.** That is v0.2.0 on `task06`. A second blind task of the same
   kind (`task07`) now passes on v0.3.0 (3/3 GREEN, §7.10), and §8.2 now
   describes v0.2.0 explicitly.
   *Source:* as for item 2.

## §2 Related Work (stub)

7. > "This is the row we beat in §7.2."

   **Wrong cross-reference, older than v0.4.0.** The static-tool baseline
   (ruff, pyupgrade) is claim (b) in **§7.3**. §7.2 is the recovery-loop
   ablation.
   *Source:* paper headings `## 7.2 Claim (a)` and `## 7.3 Claim (b) — the
   existing static tools detect the work and do none of it`.

## §10 Conclusion (stub)

8. > "Future work, one clause each: Tier-B external validity; a second migration
   > family to exercise the rest of the failure taxonomy; the live-model arms;
   > an editor expressive enough to represent arity changes."

   **Out of date in one clause.** The live model
   (`nvidia/nemotron-3-super-120b-a12b`) is no longer served to this account,
   so "the live-model arms" can only be done on a different model, and no live
   result in the paper can be repeated on the same one. The list also leaves
   out three items that are now open: consequence repair measured on more than
   one task; re-running `task06` with consequence repair; and the 5 medium + 4
   low open bugs.
   *Source:* `runs/benchmark/live/evidence/GOLD_CHECK.md` "Model availability
   (2026-10-29)" (provider 404 "Not found for account"); paper §9 items 4, 7
   and 8; `BUGS.md`.

## Mechanics to keep in mind when rewriting

- `verify_paper.py` requires the phrase **"residual call sites"** in the
  Abstract and §1 ("recovery claim scoped to residual call sites"). If the
  rewrite drops it, for example by describing consequence repair instead,
  update that check in the same change.
- The Abstract is checked with `states_a_count`, so number words ("three of the
  five") also need a `<!-- SOURCE: -->` pointer. The Abstract's existing
  pointer `(scope; blind held-out task RED)` cites only `task06`. Add
  `corpus/blind/task07_cache/results.json` if `task07` is mentioned.
- Abstract and §1 are also checked for intensifier padding ("completely",
  "absolutely", "merely", "significantly").
