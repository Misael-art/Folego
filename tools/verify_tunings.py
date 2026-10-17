"""Re-runnable live check for M2: what each tuning is on this machine, byte-proof.

    .venv/bin/python tools/verify_tunings.py            # read-only census
    .venv/bin/python tools/verify_tunings.py --guard    # plus the un-confirmed dry-run

Run it through ``tee`` for a stable transcript:
``... | tee /dev/shm/dw-verify-tunings.log``.

Everything here goes through the real child process, the same way the tray and
the CLI do, so what is proved is the deployed path. The census only reads: it
pins the sha256 of the browser's own files before and after and fails loudly if
a byte moved, and it fails if the audit trail grew by anything other than the
refusal the --guard step deliberately asks for.

Applying for real needs the user's explicit confirmation (and Edge closed) and
is deliberately not part of this script.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from folego import paths  # noqa: E402
from folego.actions.tunings.registry import TUNINGS  # noqa: E402
from folego.core import browser  # noqa: E402
from folego.process.runner import run_isolated  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
MODULE = "folego.actions.tunings.worker"
TIMEOUT_S = 15.0


def fingerprint(path: Path) -> str:
    if not path.is_file():
        return "ausente"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_lines() -> list[dict]:
    log = paths.audit_log_path()
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def child(*argv) -> tuple[dict | None, object]:
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    res = run_isolated([sys.executable, "-m", MODULE, *argv], timeout=TIMEOUT_S, env=env)
    if res.timed_out or res.refused or not res.stdout.strip():
        return None, res
    try:
        return json.loads(res.stdout.strip().splitlines()[-1]), res
    except ValueError:
        return None, res


def why_silent(res) -> str:
    if res.refused:
        return res.refused
    if res.timed_out:
        return f"não respondeu em {TIMEOUT_S:g} s"
    return res.stderr.strip() or f"código {res.exit_code}"


def census() -> int:
    problems = []
    targets = {tuning.id: fingerprint(tuning.target()) for tuning in TUNINGS}
    audit_before = len(audit_lines())
    who = browser.edge_running()
    print(f"edge_aberto={who or 'não'}")

    for tuning in TUNINGS:
        payload, res = child("detect", tuning.id)
        if payload is None:
            problems.append(f"{tuning.id}: o filho não respondeu ({why_silent(res)})")
            continue
        state = ("arquivo não existe" if not payload["exists"] else
                 payload.get("error") or
                 ("padrão do navegador (chave ausente)" if not payload["present"] else
                  f"atual={payload['current']!r} desejado={payload['desired']!r}"))
        print(f"{tuning.id:<22} chave={tuning.key:<28} {state}")
        print(f"{'':<22} arquivo={payload['file']} exit={res.exit_code}")
        if payload.get("error"):
            problems.append(f"{tuning.id}: leitura com erro — {payload['error']}")

    unknown, _ = child("detect", "edge.nada_disso")
    known = [t.id for t in TUNINGS]
    if unknown is None or unknown.get("conhecidos") != known:
        problems.append(f"tuning desconhecido não foi devolvido com a lista: {unknown}")

    after = {tuning.id: fingerprint(tuning.target()) for tuning in TUNINGS}
    moved = [tid for tid in targets if targets[tid] != after[tid]]
    if moved:
        problems.append(f"bytes mexidos durante a leitura: {moved}")
    grew = len(audit_lines()) - audit_before
    if grew:
        problems.append(f"a leitura criou {grew} linha(s) na auditoria")

    print(f"ajustes={len(TUNINGS)} arquivos_inalterados={not moved} "
          f"audit_linhas_antes={audit_before} audit_linhas_depois={audit_before + grew}")
    return report(problems)


def guard() -> int:
    """Ask the child to apply WITHOUT confirming: it must refuse, write nothing,
    and record the refusal."""
    problems = []
    tuning = TUNINGS[0]
    before = fingerprint(tuning.target())
    audit_before = audit_lines()

    payload, res = child("apply", tuning.id)
    if payload is None:
        problems.append(f"o filho não respondeu ao dry-run ({why_silent(res)})")
    else:
        blocked = (payload.get("plan") or {}).get("blocked")
        if payload.get("ok"):
            problems.append("o dry-run aplicou sem --confirmar")
        elif payload.get("exit") != 2 or "confirma" not in str(payload.get("reason")):
            problems.append("o dry-run parou antes do portão de confirmação "
                            f"(exit={payload.get('exit')}): "
                            f"{blocked or payload.get('reason')}")
        else:
            print(f"recusa_prova={payload['reason'][:70]}")

    if fingerprint(tuning.target()) != before:
        problems.append("o dry-run escreveu no arquivo do navegador")
    tail = audit_lines()[len(audit_before):]
    if len(tail) != 1 or tail[0]["outcome"] != "refused":
        problems.append(f"esperava 1 recusa na auditoria, veio {tail}")
    else:
        print(f"audit_recusa={tail[0]['action_id']} risco={tail[0]['risk']}")

    print(f"dry_run_inalterado={fingerprint(tuning.target()) == before} "
          f"audit_linhas={len(audit_lines())}")
    return report(problems)


def report(problems: list[str]) -> int:
    for line in problems:
        print(f"FALHA: {line}")
    print(f"veredicto={'FALHOU' if problems else 'OK'} problemas={len(problems)}")
    return 1 if problems else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--guard", action="store_true",
                        help="inclui o dry-run sem --confirmar (ainda não escreve)")
    args = parser.parse_args(argv)
    code = census()
    if args.guard and code == 0:
        code = guard()
    return code


if __name__ == "__main__":
    out = main()
    sys.exit(out)
