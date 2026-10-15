"""DeckWellness command line.

`disk`, `orphans` and `groups` run headless (no display, no Qt import) so the
toolbox still works when the desktop session is the thing that is broken.
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
from .core.orphans import GROUP_LABELS, KILLABLE_GROUPS, OrphanTracker, group_targets
from .safely.audit import AuditLog

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_NEEDS_CONFIRM = 2

_sleep = time.sleep


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
    handler = _HANDLERS.get(ns.sub) if ns.command == "disk" else None
    if handler is None:
        sys.stderr.write(
            f"refused: comando desconhecido: {ns.command or ''} {ns.sub or ''}\n"
            f"usage: deck-wellness [disk plan|quarantine|restore|purge|list] "
            f"[orphans] [groups]\n")
        return EXIT_NEEDS_CONFIRM
    return handler(ns)
