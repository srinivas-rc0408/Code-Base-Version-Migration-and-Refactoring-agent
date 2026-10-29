"""The ``mra`` command.

* ``mra run --task-dir DIR`` — migrate, verify, and write the run report.
* ``mra report RUN_ID`` — rebuild a run's report from its artifacts.
* ``mra memory stats|export|purge`` — inspect or wipe the opt-in experience
  store (``[experience]`` in mra.toml; off by default). Purge removes its
  promoted skills too.
* ``mra skills review|approve ID|revoke ID`` — verified skill promotion
  (:mod:`mra.skills`). Nothing is promoted without ``approve``, and approve
  runs the full validation gate first.
* ``mra providers check`` — ping every configured provider. Unreachable is a
  warning, not a failure: the deterministic path never needs a provider.

``run`` and ``report`` exit 0 for GREEN, 1 for YELLOW, 2 for RED.
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path

from mra import __version__
from mra.codemods.datetime_utcnow import TARGET
from mra.models.privacy import host_of, privacy_mode
from mra.models.router import config_path, endpoints, load_config

EXIT = {"GREEN": 0, "YELLOW": 1, "RED": 2}


def providers_check(path: str | None) -> int:
    path = path or str(config_path())
    built = endpoints(load_config(path))
    if not built:
        print(f"no [providers.*] entries in {path}; copy mra.example.toml to start")
        return 0
    local_only = privacy_mode() == "local-only"
    for name, endpoint in built.items():
        where = f"{name:<16} {endpoint.model:<22} {host_of(endpoint.provider.base_url)}"
        if local_only and not endpoint.local:
            print(f"BLOCKED      {where}  (MRA_PRIVACY=local-only)")
            continue
        if not endpoint.provider.available:
            print(f"WARN no key  {where}  (${' / $'.join(endpoint.provider.api_key_envs)} unset)")
            continue
        try:
            result = endpoint.provider.complete(
                [{"role": "user", "content": "Reply with: ok"}], endpoint.model, 0.0, 5
            )
        except Exception as exc:  # any failure here is the answer, not a crash
            reason = str(exc).splitlines()[0][:80] if str(exc) else type(exc).__name__
            print(f"WARN unreach {where}  ({reason})")
        else:
            key = f"  key ${result['key_env']}" if result.get("key_env") else ""
            print(f"reachable    {where}  {result['latency_s']:.2f}s{key}")
    return 0


def run(task_dir: str, run_id: str | None, runs_dir: str, llm: bool) -> int:
    from mra.benchmark.runner import codemod_corrector
    from mra.memory.experience import from_config
    from mra.report import RunBusy, run_with_report, terminal_summary
    from mra.skills import from_config as promoted_rules

    run_id = run_id or uuid.uuid4().hex[:12]
    experience = from_config(forbidden=(Path(task_dir),))
    router, corrector = None, codemod_corrector
    run_kwargs = {"experience": experience, "rules": promoted_rules()}
    if llm:
        from mra.models import Router
        from mra.nodes.correct_node import LLMCorrector
        from mra.state import new_state

        truth = json.loads((Path(task_dir) / "ground_truth.json").read_text())
        contract = {
            "task_id": Path(task_dir).name,
            "source_api": truth["source_api"],
            "target_api": truth["target_api"],
        }
        state = new_state(run_id, "", contract)
        router = Router(state["tokens"])
        if not router.available:
            print("--llm: no usable provider in mra.toml; see `mra providers check`")
            return 2
        corrector = LLMCorrector(router, TARGET, contract, experience)
        run_kwargs["state"] = state
    try:
        result = run_with_report(
            task_dir,
            run_id=run_id,
            runs_dir=runs_dir,
            router=router,
            corrector=corrector,
            **run_kwargs,
        )
    except RunBusy as exc:
        print(exc)
        return 2
    print(terminal_summary(result["model"], result["pdf"]))
    return EXIT[result["model"]["verdict"]["status"]]


def report(run_id: str, runs_dir: str) -> int:
    from mra.report import build_report, terminal_summary

    out_dir = Path(runs_dir) / run_id
    if not out_dir.is_dir():
        print(f"no run directory {out_dir}")
        return 2
    pdf, model = build_report(out_dir)
    print(terminal_summary(model, pdf))
    return EXIT[model["verdict"]["status"]]


def memory(action: str) -> int:
    from mra.memory.experience import ExperienceStore, configured_path, export_json

    store = ExperienceStore(configured_path())
    if action == "purge":
        print(f"purged {store.purge()} fix(es) from {store.path}")
    elif action == "export":
        print(export_json(store))
    else:
        print(json.dumps(store.stats(), indent=2))
    return 0


def _show(skill: dict, heading: str) -> None:
    print(
        f"{heading} {skill['id']}  [{skill['failure_class']}]  {skill['source_api']} -> "
        f"{skill['target_api']}"
    )
    print(
        f"  evidence: {skill['tasks']} independent GREEN task(s), runs {', '.join(skill['runs'])}"
    )
    print("  rule:")
    for old, new in skill["rule"]["replace"]:
        print(f"    - {old}\n    + {new}")
    for module, name in skill["rule"]["imports"]:
        print(f"    + from {module} import {name}")
    print("  learnt from:")
    for line in skill["patterns"][0].splitlines():
        print(f"    {line}")


def skills(action: str, ident: str | None) -> int:
    from mra.memory.experience import ExperienceStore, configured_path
    from mra.skills import validate

    store = ExperienceStore(configured_path())
    if action == "review":
        candidates = store.candidates()
        if not candidates:
            print(f"no candidates in {store.path}")
        for candidate in candidates:
            _show(candidate, "candidate")
        for skill in store.skills():
            print(
                f"{skill['status']:<9} {skill['id']}  [{skill['failure_class']}]  "
                f"validation: edge {skill['validation'].get('edge', '?')}"
            )
        return 0
    if action == "revoke":
        if not store.revoke(ident):
            print(f"no skill or candidate {ident}")
            return 2
        print(f"revoked {ident}: it will not fire and will not be offered again")
        return 0
    candidate = next((c for c in store.candidates() if c["id"] == ident), None)
    if candidate is None:
        print(f"no candidate {ident} (see `mra skills review`)")
        return 2
    _show(candidate, "validating")
    print("  running the edge suite and the Tier-A matrix with this rule on ...")
    result = validate(candidate)
    if not result["ok"]:
        print(f"NOT promoted: edge {result['edge']}; {len(result['problems'])} change(s):")
        for problem in result["problems"][:20]:
            print(f"  - {problem}")
        return 1
    store.promote(candidate, result)
    print(f"promoted {ident}: edge {result['edge']}, {result['matrix_runs']} matrix runs unchanged")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mra")
    parser.add_argument("--version", action="version", version=f"mra {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    run_cmd = commands.add_parser("run", help="migrate a task, verify it, write the report")
    run_cmd.add_argument("--task-dir", required=True)
    run_cmd.add_argument("--run-id")
    run_cmd.add_argument("--runs-dir", default="runs")
    run_cmd.add_argument(
        "--llm",
        action="store_true",
        help="recover with the LLM corrector (mra.toml) instead of the codemod",
    )
    report_cmd = commands.add_parser("report", help="rebuild a run's report from its artifacts")
    report_cmd.add_argument("run_id")
    report_cmd.add_argument("--runs-dir", default="runs")
    providers = commands.add_parser("providers", help="LLM provider tools")
    actions = providers.add_subparsers(dest="action", required=True)
    check = actions.add_parser("check", help="ping each configured provider")
    check.add_argument("--config", help="path to mra.toml (default: $MRA_CONFIG or ./mra.toml)")
    memory_cmd = commands.add_parser("memory", help="the opt-in local experience store")
    memory_cmd.add_argument("action", choices=("stats", "export", "purge"))
    skills_cmd = commands.add_parser("skills", help="verified skill promotion (opt-in)")
    skill_actions = skills_cmd.add_subparsers(dest="action", required=True)
    skill_actions.add_parser("review", help="list candidates with their evidence and rule")
    for name, text in (("approve", "validate, then promote one"), ("revoke", "revoke one")):
        skill_actions.add_parser(name, help=text).add_argument("id")
    args = parser.parse_args(argv)
    if args.command == "memory":
        return memory(args.action)
    if args.command == "skills":
        return skills(args.action, getattr(args, "id", None))
    if args.command == "run":
        return run(args.task_dir, args.run_id, args.runs_dir, args.llm)
    if args.command == "report":
        return report(args.run_id, args.runs_dir)
    return providers_check(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
