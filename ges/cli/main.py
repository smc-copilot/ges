from __future__ import annotations

import argparse
import sys

from ges import __distribution_version__, __product_version__, __version__
from ges.cli import analyze, apply, artifact, capability, check, diff, doctor, evidence, gate, governance, init, legacy, remove, trace, work
from ges.errors import GesError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ges", description="GES 6 Composer")
    parser.add_argument(
        "--version",
        action="version",
        version=f"{__product_version__} (distribution {__distribution_version__})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="analyze, resolve, confirm, apply, check")
    _repo(init_p)
    _select(init_p)
    init_p.set_defaults(func=init.run)

    analyze_p = sub.add_parser("analyze", help="deterministic repo profile")
    _repo(analyze_p)
    analyze_p.set_defaults(func=analyze.run)

    diff_p = sub.add_parser("diff", help="show desired vs current plan")
    _repo(diff_p)
    _select(diff_p)
    diff_p.add_argument("--json", action="store_true")
    diff_p.set_defaults(func=diff.run)

    apply_p = sub.add_parser("apply", help="reconcile desired state")
    _repo(apply_p)
    _select(apply_p)
    apply_p.set_defaults(func=apply.run)

    check_p = sub.add_parser("check", help="validate composed project state")
    _repo(check_p)
    check_p.set_defaults(func=check.run)

    cap_p = sub.add_parser("capability", help="parallel provider overlay")
    cap_sub = cap_p.add_subparsers(dest="capability_command", required=True)
    cap_list = cap_sub.add_parser("list")
    _repo(cap_list)
    cap_list.add_argument("--json", action="store_true")
    cap_list.set_defaults(func=capability.run_list)
    cap_add = cap_sub.add_parser("add")
    cap_add.add_argument("id")
    _repo(cap_add)
    cap_add.set_defaults(func=capability.run_add)
    cap_rm = cap_sub.add_parser("remove")
    cap_rm.add_argument("id")
    _repo(cap_rm)
    cap_rm.set_defaults(func=capability.run_remove)
    cap_doc = cap_sub.add_parser("doctor")
    cap_doc.add_argument("id")
    _repo(cap_doc)
    cap_doc.set_defaults(func=capability.run_doctor)

    doctor_p = sub.add_parser("doctor", help="runtime readiness observation")
    _repo(doctor_p)
    doctor_p.add_argument("--preflight", action="store_true")
    doctor_p.set_defaults(func=doctor.run)

    remove_p = sub.add_parser("remove", help="remove GES-owned projection")
    _repo(remove_p)
    remove_p.set_defaults(func=remove.run)

    legacy_p = sub.add_parser("legacy", help="inspect or remove GES v5 leftovers")
    legacy_sub = legacy_p.add_subparsers(dest="legacy_command", required=True)
    inspect_p = legacy_sub.add_parser("inspect")
    _repo(inspect_p)
    inspect_p.set_defaults(func=legacy.run_inspect)
    lremove = legacy_sub.add_parser("remove")
    _repo(lremove)
    lremove.add_argument("--dry-run", action="store_true", default=True)
    lremove.add_argument("--apply", action="store_true")
    lremove.add_argument("--force", action="store_true")
    lremove.set_defaults(func=legacy.run_remove)

    gov_p = sub.add_parser("governance", help="initialize governance backplane")
    gov_sub = gov_p.add_subparsers(dest="governance_command", required=True)
    gov_init = gov_sub.add_parser("init")
    _repo(gov_init)
    gov_init.set_defaults(func=governance.run_init)

    work_p = sub.add_parser("work", help="work registry")
    work_sub = work_p.add_subparsers(dest="work_command", required=True)
    work_create = work_sub.add_parser("create")
    _repo(work_create)
    work_create.add_argument("--id", required=True)
    work_create.add_argument("--title", required=True)
    work_create.add_argument("--owner", required=True)
    work_create.add_argument("--risk", required=True, choices=["LOW", "MEDIUM", "HIGH"])
    work_create.add_argument("--host", required=True, choices=["cursor", "codex", "hermes"])
    work_create.set_defaults(func=work.run_create)
    work_show = work_sub.add_parser("show")
    _repo(work_show)
    work_show.add_argument("--id", required=True)
    work_show.set_defaults(func=work.run_show)
    work_update = work_sub.add_parser("update")
    _repo(work_update)
    work_update.add_argument("--id", required=True)
    work_update.add_argument("--title")
    work_update.add_argument("--owner")
    work_update.add_argument("--risk", choices=["LOW", "MEDIUM", "HIGH"])
    work_update.add_argument("--policy")
    work_update.set_defaults(func=work.run_update)
    work_close = work_sub.add_parser("close")
    _repo(work_close)
    work_close.add_argument("--id", required=True)
    work_close.set_defaults(func=work.run_close)
    work_migrate = work_sub.add_parser("migrate")
    _repo(work_migrate)
    work_migrate.add_argument("--id", required=True)
    work_migrate.add_argument("--host", required=True, choices=["cursor", "codex", "hermes"])
    work_migrate.set_defaults(func=work.run_migrate)
    work_cap = work_sub.add_parser("capability")
    work_cap_sub = work_cap.add_subparsers(dest="work_capability_command", required=True)
    work_cap_add = work_cap_sub.add_parser("add")
    work_cap_add.add_argument("--id", required=True)
    work_cap_add.add_argument("capability_id")
    _repo(work_cap_add)
    work_cap_add.set_defaults(func=work.run_capability_add)
    work_cap_rm = work_cap_sub.add_parser("remove")
    work_cap_rm.add_argument("--id", required=True)
    work_cap_rm.add_argument("capability_id")
    _repo(work_cap_rm)
    work_cap_rm.set_defaults(func=work.run_capability_remove)

    art_p = sub.add_parser("artifact", help="link SPEC/PLAN pointers")
    art_sub = art_p.add_subparsers(dest="artifact_command", required=True)
    art_link = art_sub.add_parser("link")
    _repo(art_link)
    art_link.add_argument("work_id")
    art_link.add_argument("--type", required=True, choices=["SPEC", "PLAN"])
    art_link.add_argument("--path", required=True)
    art_link.add_argument("--replace", action="store_true")
    art_link.set_defaults(func=artifact.run_link)

    evid_p = sub.add_parser("evidence", help="observe provider-backed evidence")
    evid_sub = evid_p.add_subparsers(dest="evidence_command", required=True)
    evid_collect = evid_sub.add_parser("collect")
    _repo(evid_collect)
    evid_collect.add_argument("work_id")
    evid_collect.add_argument("--pr", required=True, type=int)
    evid_collect.add_argument("--json", action="store_true")
    evid_collect.set_defaults(func=evidence.run_collect)
    evid_add = evid_sub.add_parser("add")
    evid_add.set_defaults(func=evidence.run_add)

    trace_p = sub.add_parser("trace", help="traceability graph")
    trace_sub = trace_p.add_subparsers(dest="trace_command", required=True)
    trace_show = trace_sub.add_parser("show")
    _repo(trace_show)
    trace_show.add_argument("work_id")
    trace_show.add_argument("--pr", required=True, type=int)
    trace_show.add_argument("--json", action="store_true")
    trace_show.set_defaults(func=trace.run_show)

    gate_p = sub.add_parser("gate", help="WORK_READY, EXECUTION_READY, MERGE_READY")
    gate_sub = gate_p.add_subparsers(dest="gate_command", required=True)
    gate_intake = gate_sub.add_parser("intake")
    _repo(gate_intake)
    gate_intake.add_argument("work_id")
    gate_intake.add_argument("--json", action="store_true")
    gate_intake.set_defaults(func=gate.run_intake)
    gate_exec = gate_sub.add_parser("execution")
    _repo(gate_exec)
    gate_exec.add_argument("work_id")
    gate_exec.add_argument("--json", action="store_true")
    gate_exec.set_defaults(func=gate.run_execution)
    gate_merge = gate_sub.add_parser("merge")
    _repo(gate_merge)
    gate_merge.add_argument("work_id")
    gate_merge.add_argument("--pr", required=True, type=int)
    gate_merge.add_argument("--json", action="store_true")
    gate_merge.set_defaults(func=gate.run_merge)
    gate_explain = gate_sub.add_parser("explain")
    _repo(gate_explain)
    gate_explain.add_argument("work_id")
    gate_explain.add_argument("--gate", required=True, choices=["intake", "merge", "execution"])
    gate_explain.add_argument("--pr", type=int)
    gate_explain.set_defaults(func=gate.run_explain)
    return parser


def _repo(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("repo", nargs="?", default=".")


def _select(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--exclude", action="append", default=[], dest="exclude")
    parser.add_argument("--enable", "--extra", action="append", default=[], dest="enable")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except GesError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        if exc.code == "GES_RECONCILE_NOOP":
            print(exc.code)
            return 0
        if exc.code == "GOVERNANCE_ALREADY_INITIALIZED":
            print(exc.code)
            return 0
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
