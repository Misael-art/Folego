"""DeckWellness command line.

`disk`, `orphans`, `groups` and `tune` run headless (no display, no Qt import) so
the toolbox still works when the desktop session is the thing that is broken.
`tune` never writes in this process: each mutation is handed to a child that can
be killed if the disk stalls.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from .actions.disk import planner, tmpclean
from .actions.disk.measure import measure_tree
from .actions.disk.quarantine import Quarantine
from .actions.orphans import scan
from .actions.tmpfs import inventory, plan as tmpfs_plan, policy as tmpfs_policy_mod
from .actions.tunings.registry import TUNINGS
from .core.orphans import GROUP_LABELS, KILLABLE_GROUPS, OrphanTracker, group_targets
from .core.tmpfs import WATCHED, watched_volumes
from .process.runner import run_isolated
from .safely.audit import AuditLog

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_NEEDS_CONFIRM = 2

WORKER_MODULE = "deck_wellness.actions.tunings.worker"
TUNE_TIMEOUT_S = 15.0

_sleep = time.sleep

_tmpfs_volumes = watched_volumes
_tmpfs_now = time.time


def run_gui(argv=None) -> int:
    from .app import main as gui_main
    return gui_main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deck-wellness",
        description="Bem-estar do Steam Deck: diagnóstico e higiene com confirmação.")
    commands = parser.add_subparsers(dest="command")

    disk = commands.add_parser("disk", help="higiene de disco (dry-run primeiro)")
    disk_sub = disk.add_subparsers(dest="sub", required=True)

    plan = disk_sub.add_parser("plan", help="dry-run: o que poderia ser liberado (nada muda)")
    plan.add_argument("--json", action="store_true", help="saída para máquinas")
    plan.add_argument("--prazo", type=float, default=30.0,
                      help="segundos máximos de leitura por diretório")

    for name, help_text in (
        ("quarantine", "mover um diretório para quarentena reversível"),
        ("restore", "devolver um item quarentenado ao lugar original"),
        ("purge", "apagar de vez um item já quarentenado"),
    ):
        sub = disk_sub.add_parser(name, help=help_text)
        sub.add_argument("target", help="caminho (quarantine) ou id de quarentena")
        sub.add_argument("--confirmar", action="store_true", help="aceita esta mutação")
        if name == "purge":
            sub.add_argument("--irreversivel", action="store_true",
                             help="aceita que o conteúdo não voltará nunca mais")

    disk_sub.add_parser("list", help="itens em quarentena")

    tmp = disk_sub.add_parser("tmp", help="itens vencidos em /tmp (ocupa RAM e causa ENOSPC)")
    tmp.add_argument("--dias", type=float, default=3.0, help="idade mínima em dias")
    tmp.add_argument("--raiz", default="/tmp", help="diretório temporário a analisar")
    tmp.add_argument("--confirmar", action="store_true", help="apaga em vez de só listar")
    tmp.add_argument("--irreversivel", action="store_true",
                     help="aceita que itens de /tmp não têm volta")

    orphans = commands.add_parser(
        "orphans", help="processos abandonados pelo PID 1, parados há um tempo")
    orphans.add_argument("--janela", type=float, default=10.0,
                         help="segundos observados para provar a ociosidade")
    orphans.add_argument("--amostras", type=int, default=2,
                         help="número de leituras dentro da janela")
    orphans.add_argument("--ocioso", type=float, default=None,
                         help="ociosidade mínima exigida (padrão: a própria janela)")
    orphans.add_argument("--confirmar", action="store_true",
                         help="envia SIGTERM aos listados")
    orphans.add_argument("--forcar", action="store_true",
                         help="SIGKILL em vez de SIGTERM (com --confirmar)")

    groups = commands.add_parser(
        "groups", help="família inteira de navegador, para rendimento alto")
    groups.add_argument("--grupo", choices=KILLABLE_GROUPS, default=None,
                        help="restringe a edge ou chrome (padrão: ambos)")
    groups.add_argument("--confirmar", action="store_true",
                        help="envia SIGTERM à família listada")

    tune = commands.add_parser(
        "tune", help="ajustes de economia na config do navegador (dry-run primeiro)")
    tune_sub = tune.add_subparsers(dest="sub", required=True)
    status = tune_sub.add_parser("status", help="estado atual de cada ajuste (não escreve)")
    status.add_argument("--json", action="store_true", help="saída para máquinas")
    for name, help_text in (
        ("apply", "aplica um ajuste, com backup reversível"),
        ("revert", "devolve o arquivo ao último backup"),
    ):
        sub = tune_sub.add_parser(name, help=help_text)
        sub.add_argument("tuning", help="id do ajuste, ex. edge.startup_boost")
        sub.add_argument("--confirmar", action="store_true", help="aceita esta mutação")

    tmpfs = commands.add_parser(
        "tmpfs", help="espaços em RAM (/tmp, /run/user, /dev/shm): ver e liberar com confirmação")
    tmpfs_sub = tmpfs.add_subparsers(dest="sub")

    status = tmpfs_sub.add_parser("status", help="capacidade e pressão dos volumes (não escreve)")
    status.add_argument("--json", action="store_true", help="saída para máquinas")
    status.add_argument("--raiz", action="append", default=None,
                        help="restringe a um volume da watch-list (repetível)")

    plan = tmpfs_sub.add_parser("plan", help="dry-run: elegíveis e protegidos (nada muda)")
    plan.add_argument("--json", action="store_true", help="saída para máquinas")
    plan.add_argument("--raiz", action="append", default=None,
                      help="restringe a um volume da watch-list (repetível)")
    plan.add_argument("--dias", type=float, default=None,
                      help=f"idade mínima em dias (padrão {tmpfs_policy_mod.MIN_AGE_DAYS:g})")
    plan.add_argument("--permitir", action="append", default=[], dest="permitir",
                      help="padrão extra de allow-list, item por item")
    plan.add_argument("--prazo", type=float, default=10.0,
                      help="segundos máximos de varredura por volume")
    return parser


def _quarantine(fake_home=None) -> Quarantine:
    home = Path(fake_home) if fake_home else Path.home()
    return Quarantine(allowed_roots=planner.default_allowed_roots(home),
                      audit=AuditLog())


def _cmd_plan(args) -> int:
    home = Path.home()
    plan = planner.build_plan(planner.default_targets(), home=home,
                              deadline_s=args.prazo)
    if args.json:
        payload = json.loads(plan.to_json())
        payload["volumes"] = [v.to_dict() for v in planner.volume_report(home=home)]
        print(json.dumps(payload, ensure_ascii=False))
        return EXIT_OK
    volumes = planner.volume_report(home=home)
    print("Volume:")
    print(planner.format_volumes(volumes))
    print("")
    print("Candidatos a liberação (dry-run, nada foi alterado):")
    print(planner.format_report(plan))
    print("")
    print("Para liberar de forma reversível: deck-wellness disk quarantine <caminho> --confirmar")
    return EXIT_OK


def _cmd_quarantine(args) -> int:
    if not args.confirmar:
        sys.stderr.write("refused: mutação exige --confirmar (nada foi alterado)\n")
        return EXIT_NEEDS_CONFIRM
    try:
        entry = _quarantine().move_in(args.target)
    except (PermissionError, OSError) as err:
        sys.stderr.write(f"refused: {err}\n")
        return EXIT_REFUSED
    print(f"quarentena: {entry.entry_id}")
    print(f"   de:   {entry.original}")
    print(f"   para: {entry.stored}")
    print(f"   {planner.fmt_bytes(entry.bytes)} recuperáveis · reverta com "
          f"deck-wellness disk restore {entry.entry_id} --confirmar")
    return EXIT_OK


def _cmd_restore(args) -> int:
    if not args.confirmar:
        sys.stderr.write("refused: mutação exige --confirmar (nada foi alterado)\n")
        return EXIT_NEEDS_CONFIRM
    result = _quarantine().restore(args.target)
    if not result.ok:
        sys.stderr.write(f"refused: {result.reason}\n")
        return EXIT_REFUSED
    print(f"restaurado: {args.target}")
    return EXIT_OK


def _cmd_purge(args) -> int:
    if not args.confirmar:
        sys.stderr.write("refused: mutação exige --confirmar (nada foi alterado)\n")
        return EXIT_NEEDS_CONFIRM
    if not args.irreversivel:
        sys.stderr.write("refused: purga é irreversível, exige --irreversivel "
                         "(nada foi alterado)\n")
        return EXIT_NEEDS_CONFIRM
    result = _quarantine().purge(args.target)
    if not result.ok:
        sys.stderr.write(f"refused: {result.reason}\n")
        return EXIT_REFUSED
    print(f"purgado: {args.target}")
    return EXIT_OK


def _cmd_list(args) -> int:
    q = _quarantine()
    q.reconcile()
    entries = sorted(q.entries().values(), key=lambda e: -e.bytes)
    if not entries:
        print("quarentena vazia")
        return EXIT_OK
    for entry in entries:
        stat = measure_tree(entry.stored) if entry.state == "stored" else None
        size = stat.bytes if stat else 0
        print(f"{entry.entry_id} · {Path(entry.original).name} · "
              f"{planner.fmt_bytes(size)} · {entry.state} · {entry.original}")
    print(f"\nem quarentena: {planner.fmt_bytes(q.reclaimable_bytes())}")
    return EXIT_OK


def _cmd_tmp(args) -> int:
    root = Path(args.raiz)
    if str(root.resolve()).startswith("/mnt"):
        sys.stderr.write("refused: /mnt (cartão SD) pode travar em EIO/D-state; "
                         "limpe-o por fora\n")
        return EXIT_REFUSED
    plan = tmpclean.plan_tmp(root, min_age_days=args.dias)
    if not plan.items:
        print(f"{root}: nada com mais de {args.dias:g} dia(s) pertencente a você")
        return EXIT_OK
    print(f"{root} · {len(plan.items)} item(ns) vencidos · "
          f"{planner.fmt_bytes(plan.total_bytes)} · {len(plan.kept)} mantido(s)")
    for item in sorted(plan.items, key=lambda i: -i.bytes):
        print(f"  · {Path(item.path).name} · {planner.fmt_bytes(item.bytes)} · "
              f"{item.age_days:.0f} d · {item.path}")
    if not args.confirmar and not args.irreversivel:
        sys.stderr.write("\ndry-run: nada alterado. Para apagar use "
                         "--confirmar --irreversivel\n")
        return EXIT_OK
    if not (args.confirmar and args.irreversivel):
        missing = [flag for flag, given in (("--confirmar", args.confirmar),
                                           ("--irreversivel", args.irreversivel)) if not given]
        sys.stderr.write("refused: apagar exige " + " e ".join(missing) +
                         " (nada foi alterado)\n")
        return EXIT_NEEDS_CONFIRM
    result = tmpclean.expire_tmp(root, min_age_days=args.dias, audit=AuditLog())
    print(f"\nremovidos: {len(result.removed)} · liberado: "
          f"{planner.fmt_bytes(result.freed_bytes)}")
    for line in result.errors:
        print(f"aviso: {line}")
    return EXIT_OK


_HANDLERS = {
    "plan": _cmd_plan,
    "quarantine": _cmd_quarantine,
    "restore": _cmd_restore,
    "purge": _cmd_purge,
    "list": _cmd_list,
    "tmp": _cmd_tmp,
}


def _reaper():
    from .actions.orphans.reaper import Reaper
    return Reaper(audit=AuditLog())


def _rss(rss_kb: int) -> str:
    return planner.fmt_bytes(rss_kb * 1024)


def _cmd_orphans(args) -> int:
    if args.forcar and not args.confirmar:
        sys.stderr.write("refused: SIGKILL é mais disruptivo que SIGTERM; use "
                         "--confirmar --forcar\n")
        return EXIT_NEEDS_CONFIRM
    min_idle = args.janela if args.ocioso is None else args.ocioso
    found = scan.scan_orphans(
        scan.collector_for(), tracker=OrphanTracker(min_idle_s=min_idle),
        samples=max(2, args.amostras), window_s=args.janela, sleep=_sleep)
    if not found:
        print(f"sem órfão comprovado (janela de {args.janela:g} s, "
              f"{args.amostras} amostras)")
        print("órfão comprovado: adotado por PID 1 ou pelo supervisor da sessão, "
              "sem filhos vivos, fora da lista protegida e sem consumir CPU há "
              f"{min_idle:g} s")
        return EXIT_OK
    print(f"{len(found)} órfão(s) comprovado(s) · {_rss(sum(c.rss_kb for c in found))} "
          f"· ocioso ≥ {min_idle:g} s")
    for c in found:
        command = " ".join(c.cmdline)[:120] or "—"
        print(f"  · pid {c.pid} · {c.comm} · {_rss(c.rss_kb)} · "
              f"{c.idle_s:.0f} s sem CPU · estado {c.state} · pai {c.ppid}")
        print(f"      comando: {command}")
    if not args.confirmar:
        sys.stderr.write("\ndry-run: nenhum processo foi encerrado. Para encerrar use "
                         "--confirmar (SIGTERM) ou --confirmar --forcar (SIGKILL)\n")
        return EXIT_OK
    reaper = _reaper()
    refused = 0
    for c in found:
        result = (reaper.force(c, confirm=True) if args.forcar
                  else reaper.terminate(c))
        if result.ok:
            note = f" · {result.reason}" if result.reason else ""
            print(f"encerrado: pid {result.pid} · {result.comm}{note}")
        else:
            refused += 1
            sys.stderr.write(f"refused: pid {result.pid} · {result.reason}\n")
    return EXIT_REFUSED if refused else EXIT_OK


def _cmd_groups(args) -> int:
    groups = (args.grupo,) if args.grupo else KILLABLE_GROUPS
    targets = group_targets(scan.collector_for().collect().procs, groups=groups)
    if not targets:
        print("nenhum grupo aberto (" + ", ".join(GROUP_LABELS[g] for g in groups) + ")")
        return EXIT_OK
    for target in targets:
        print(f"{target.label}: {len(target.members)} processo(s) · "
              f"{_rss(target.total_rss_kb)}")
        for member in target.members:
            print(f"  · pid {member.pid} · {member.comm} · {_rss(member.rss_kb)}")
    if not args.confirmar:
        sys.stderr.write("\ndry-run: nenhum processo foi encerrado. Para encerrar use "
                         "deck-wellness groups --grupo edge --confirmar\n")
        return EXIT_OK
    reaper = _reaper()
    refused = 0
    for target in targets:
        for result in reaper.terminate_group(target):
            if result.ok:
                print(f"encerrado: pid {result.pid} · {result.comm}")
            else:
                refused += 1
                sys.stderr.write(f"refused: pid {result.pid} · {result.reason}\n")
    return EXIT_REFUSED if refused else EXIT_OK


def _worker(acao: str, tuning_id: str, *, confirmar: bool = False):
    """One tuning action, in a child the terminal can outlive."""
    argv = [sys.executable, "-m", WORKER_MODULE, acao, tuning_id]
    if confirmar:
        argv.append("--confirmar")
    return run_isolated(argv, timeout=TUNE_TIMEOUT_S)


def _worker_answer(res) -> dict | None:
    """The child's JSON line, or None when it never gave one."""
    if res.refused or res.timed_out or not res.stdout.strip():
        return None
    try:
        return json.loads(res.stdout.strip().splitlines()[-1])
    except ValueError:
        return None


def _child_failure(res) -> str:
    if res.refused:
        return res.refused
    if res.timed_out:
        return (f"o processo de leitura não respondeu em {TUNE_TIMEOUT_S:g} s e foi "
                f"encerrado (disco travado?)")
    if res.stderr.strip():
        return res.stderr.strip()
    return f"o processo filho terminou sem resposta (código {res.exit_code})"


def _tune_label(tuning_id: str) -> str:
    tuning = next((t for t in TUNINGS if t.id == tuning_id), None)
    return tuning.label if tuning else tuning_id


def _tune_state(payload) -> str:
    if payload is None:
        return "não respondeu"
    if payload.get("error"):
        if not payload.get("exists"):
            return "arquivo não existe"
        return payload["error"]
    if not payload.get("present"):
        return "padrão do navegador (chave ausente)"
    return "ligado" if payload.get("current") else "desligado"


def _cmd_tune_status(args) -> int:
    rows, failures = [], 0
    for tuning in TUNINGS:
        res = _worker("detect", tuning.id)
        payload = _worker_answer(res)
        if payload is None:
            failures += 1
        row = {"id": tuning.id, "label": tuning.label, "key": tuning.key,
               "state": _tune_state(payload)}
        if payload is not None:
            row.update(file=payload.get("file"), present=payload.get("present"),
                       current=payload.get("current"), desired=payload.get("desired"),
                       change_needed=payload.get("change_needed"),
                       error=payload.get("error"))
        else:
            row.update(file=None, present=None, current=None, desired=tuning.desired,
                       change_needed=None, error=_child_failure(res))
        rows.append(row)

    if args.json:
        print(json.dumps({"tunings": rows}, ensure_ascii=False))
        return EXIT_REFUSED if failures else EXIT_OK

    print("Ajustes de economia (dry-run: nada foi escrito):")
    for row in rows:
        print(f"{row['id']} · {row['label']}")
        print(f"   chave:   {row['key']}")
        print(f"   arquivo: {row['file'] or '—'}")
        note = ""
        if row["present"] and not row["change_needed"]:
            note = " (já econômico)"
        print(f"   estado: {row['state']}{note}")
        if row["error"]:
            print(f"   aviso:  {row['error']}")
    if failures:
        print(f"\n{failures} ajuste(s) sem leitura confiável — o arquivo pode estar "
              "em um disco travado")
    print("\nPara aplicar: deck-wellness tune apply <id> --confirmar "
          "(o Edge precisa estar fechado)")
    return EXIT_REFUSED if failures else EXIT_OK


def _report_mutation(res, acao: str, tuning_id: str) -> int:
    label = _tune_label(tuning_id)
    payload = _worker_answer(res)
    if payload is None:
        sys.stderr.write(f"refused: {_child_failure(res)}\n")
        return EXIT_REFUSED
    if payload.get("conhecidos") is not None:
        sys.stderr.write(f"refused: {payload['reason']}\n")
        sys.stderr.write("existem: " + ", ".join(payload["conhecidos"]) + "\n")
        return EXIT_REFUSED

    ok = bool(payload.get("ok"))
    exit_code = payload.get("exit", EXIT_OK if ok else EXIT_REFUSED)
    if ok:
        if acao == "apply" and not payload.get("changed"):
            print(f"nada a fazer: {payload.get('reason') or 'já está no valor desejado'}")
            return EXIT_OK
        print(f"{'aplicado' if acao == 'apply' else 'restaurado'}: {label}")
        print(f"   arquivo: {payload.get('file')}")
        print(f"   sha256:  {payload.get('sha')}")
        if payload.get("backup_id"):
            print(f"   backup:  {payload['backup_id']}")
        if acao == "apply":
            print(f"   reverta: deck-wellness tune revert {tuning_id} --confirmar")
        return EXIT_OK

    if exit_code == EXIT_NEEDS_CONFIRM:
        sys.stderr.write(f"dry-run: nada foi escrito ({payload.get('reason')}).\n")
        sys.stderr.write(f"        para aplicar: deck-wellness tune apply "
                         f"{tuning_id} --confirmar\n")
        return EXIT_NEEDS_CONFIRM
    sys.stderr.write(f"refused: {payload.get('reason')}\n")
    return exit_code


def _cmd_tune_apply(args) -> int:
    return _report_mutation(_worker("apply", args.tuning, confirmar=args.confirmar),
                            "apply", args.tuning)


def _cmd_tune_revert(args) -> int:
    if not args.confirmar:
        sys.stderr.write("refused: restaurar regrava o arquivo do navegador e exige "
                         "--confirmar (nada foi alterado)\n")
        return EXIT_NEEDS_CONFIRM
    return _report_mutation(_worker("revert", args.tuning, confirmar=True),
                            "revert", args.tuning)


def _tmpfs_roots(raiz=None) -> list:
    """`--raiz` só aceita o que a watch-list conhece: /run e /run/credentials não."""
    wanted = list(raiz or WATCHED)
    outside = [w for w in wanted if w not in WATCHED]
    if outside:
        sys.stderr.write("refused: fora da watch-list: " + ", ".join(outside) +
                         " (o que não medimos não mutamos)\n")
    return [w for w in wanted if w in WATCHED]


def tmpfs_policy(permitir=(), dias=None, volumes=None) -> tmpfs_policy_mod.Policy:
    """O escopo de volume segue o que foi medido: em produção `_tmpfs_roots` já
    garantiu que é watch-list, e num teste o chão falso é o próprio volume."""
    allow = tuple(tmpfs_policy_mod.DEFAULT_ALLOW_PATTERNS) + tuple(permitir or ())
    return tmpfs_policy_mod.Policy(
        allow_patterns=allow,
        min_age_days=tmpfs_policy_mod.MIN_AGE_DAYS if dias is None else dias,
        volumes=tuple(volumes) if volumes else tmpfs_policy_mod.WATCHED)


def _scan_tmpfs(raiz=None, prazo: float = 10.0):
    volumes = [v for v in _tmpfs_volumes() if v.path in _tmpfs_roots(raiz)]
    entries = []
    for volume in volumes:
        _, _, found = inventory.scan_volume(volume, now=_tmpfs_now(),
                                            deadline_s=prazo)
        entries.extend(found)
    return volumes, entries


def _build_tmpfs_plan(raiz=None, permitir=(), dias=None, prazo: float = 10.0):
    """A única porta para um plano: leitura + política, sem mutação nenhuma."""
    volumes, entries = _scan_tmpfs(raiz, prazo)
    plan = tmpfs_plan.build_plan(volumes, entries,
                                 tmpfs_policy(permitir, dias, [v.path for v in volumes]),
                                 now=_tmpfs_now())
    return plan


def _cmd_tmpfs_status(args) -> int:
    volumes = [v for v in _tmpfs_volumes() if v.path in _tmpfs_roots(args.raiz)]
    if not volumes:
        sys.stderr.write("refused: nenhum volume da watch-list montado "
                         "(nem /tmp, nem /run/user/1000, nem /dev/shm)\n")
        return EXIT_REFUSED
    if args.json:
        print(json.dumps({"volumes": [v.to_dict() for v in volumes],
                          "worst": max(volumes, key=lambda v: v.used_frac).to_dict()},
                         ensure_ascii=False))
        return EXIT_OK
    print("Espaços temporários (são RAM; seco aqui = ENOSPC no agente):")
    for volume in sorted(volumes, key=lambda v: v.used_frac, reverse=True):
        print(f"{volume.path} · {volume.fs_type} · {planner.fmt_bytes(volume.total_bytes)} · "
              f"usado {planner.fmt_bytes(volume.used_bytes)} · "
              f"livre {planner.fmt_bytes(volume.avail_bytes)} · "
              f"{round(volume.used_frac * 100)}%")
    worst = max(volumes, key=lambda v: v.used_frac)
    print(f"\npior volume: {worst.path} a {round(worst.used_frac * 100)}%")
    print("Para ver o plano: deck-wellness tmpfs plan (dry-run, nada muda)")
    return EXIT_OK


def _cmd_tmpfs_plan(args) -> int:
    result = _build_tmpfs_plan(args.raiz, args.permitir, args.dias, args.prazo)
    if not result.volumes:
        sys.stderr.write("refused: nenhum volume da watch-list montado\n")
        return EXIT_REFUSED
    if args.json:
        print(result.to_json())
        return EXIT_OK
    print("Plano de liberação (dry-run: nada foi movido):")
    print(f"volumes: {', '.join(v.path for v in result.volumes)}")
    print(f"recuperáveis {planner.fmt_bytes(result.total_bytes)} em "
          f"{len(result.reclaimable)} item(ns); protegidos {len(result.protected)}")
    for item in result.reclaimable:
        print(f"  · {item.path} · {planner.fmt_bytes(item.bytes)} · "
              f"{item.age_days:.0f} d · padrão {item.matched}")
    for item in result.protected:
        print(f"  protegido: {item.path} · {item.reason}")
    print(f"\nscanned {result.scanned_entries} item(ns) · "
          f"{planner.fmt_bytes(result.scanned_bytes)} lidos · "
          f"impressão: {result.digest[:16]}")
    if result.scanned_entries != len(result.reclaimable) + len(result.protected):
        sys.stderr.write("aviso: a contagem não fechou — o plano é incompleto\n")
        return EXIT_REFUSED
    print("\nDry-run comprovado: nenhum byte saiu do volume.")
    return EXIT_OK


_TMPFS_HANDLERS = {
    "status": _cmd_tmpfs_status,
    "plan": _cmd_tmpfs_plan,
}


_TUNE_HANDLERS = {
    "status": _cmd_tune_status,
    "apply": _cmd_tune_apply,
    "revert": _cmd_tune_revert,
}


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        ns = parser.parse_args(args)
    except SystemExit as exit_request:
        return int(exit_request.code or EXIT_NEEDS_CONFIRM)
    if ns.command is None:
        return run_gui(args)
    if ns.command == "orphans":
        return _cmd_orphans(ns)
    if ns.command == "groups":
        return _cmd_groups(ns)
    if ns.command == "tune":
        handler = _TUNE_HANDLERS.get(ns.sub)
        if handler is None:
            sys.stderr.write(f"refused: subcomando desconhecido: {ns.sub}\n")
            return EXIT_NEEDS_CONFIRM
        return handler(ns)
    if ns.command == "tmpfs":
        handler = _TMPFS_HANDLERS.get(ns.sub)
        if handler is None:
            sys.stderr.write(f"refused: subcomando desconhecido: "
                             f"{ns.sub or '(nenhum)'}\n")
            return EXIT_NEEDS_CONFIRM
        return handler(ns)
    handler = _HANDLERS.get(ns.sub) if ns.command == "disk" else None
    if handler is None:
        sys.stderr.write(
            f"refused: comando desconhecido: {ns.command or ''} {ns.sub or ''}\n"
            f"usage: deck-wellness [disk plan|quarantine|restore|purge|list|tmp] "
            f"[orphans] [groups] [tune status|apply|revert] [tmpfs status|plan]\n")
        return EXIT_NEEDS_CONFIRM
    return handler(ns)
