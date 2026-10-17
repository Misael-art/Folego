"""Child-process entry point for one tuning action.

    python -m folego.actions.tunings.worker apply edge.startup_boost --confirmar

Answers with a single JSON line so the parent (tray or CLI) never has to parse
prose, and exits 0 applied / 1 refused / 2 needs confirmation. Running here, in
a process the parent can kill, is what keeps a stuck write from freezing the UI:
see ``folego.process.runner``.
"""
import argparse
import json
import sys

from .engine import NEEDS_CONFIRM, TuningEngine
from .registry import TUNINGS, tuning_by_id

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_NEEDS_CONFIRM = 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="folego-tune", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("acao", choices=("detect", "apply", "revert"))
    parser.add_argument("tuning", help="id do ajuste, ex. edge.startup_boost")
    parser.add_argument("--confirmar", action="store_true",
                        help="aceita esta mutação; sem ela nada é escrito")
    args = parser.parse_args(argv)
    payload = run(args.acao, args.tuning, confirm=args.confirmar)
    print(json.dumps(payload, ensure_ascii=False))
    return payload["exit"]


def run(acao: str, tuning_id: str, *, confirm: bool = False) -> dict:
    try:
        tuning = tuning_by_id(tuning_id)
    except KeyError:
        return _finish(acao, ok=False, exit=EXIT_REFUSED,
                       reason=f"tuning desconhecido: {tuning_id}",
                       conhecidos=[t.id for t in TUNINGS])

    engine = TuningEngine()
    det = engine.detect(tuning)
    if acao == "detect":
        return _finish(acao, ok=True, exit=EXIT_OK, **_detect_fields(det))

    if acao == "revert":
        result = engine.revert(tuning)
        return _finish(acao, ok=result.ok,
                       exit=EXIT_OK if result.ok else EXIT_REFUSED,
                       reason=result.reason, sha=result.sha, backup_id=result.backup_id,
                       file=str(result.target))

    plan = engine.plan(det)
    if plan is None:
        return _finish(acao, ok=True, exit=EXIT_OK, changed=False,
                       reason="já está no valor desejado; nada foi escrito",
                       file=str(det.target), **_detect_fields(det))
    result = engine.apply(plan, confirm=confirm)
    exit_code = EXIT_OK if result.ok else (
        EXIT_NEEDS_CONFIRM if result.reason == NEEDS_CONFIRM else EXIT_REFUSED)
    return _finish(acao, ok=result.ok, exit=exit_code, changed=result.ok,
                   reason=result.reason, sha=result.sha, backup_id=result.backup_id,
                   file=str(result.target), plan=_plan_fields(plan))


def _detect_fields(det) -> dict:
    return {"exists": det.exists, "present": det.present, "current": det.current,
            "desired": det.tuning.desired, "change_needed": det.change_needed,
            "error": det.error, "file": str(det.target), "key": det.tuning.key,
            "label": det.tuning.label, "why": det.tuning.why}


def _plan_fields(plan) -> dict:
    return {"before_sha": plan.before_sha, "after_sha": plan.after_sha,
            "blocked": plan.blocked}


def _finish(acao: str, **fields) -> dict:
    payload = {"acao": acao}
    payload.update(fields)
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
