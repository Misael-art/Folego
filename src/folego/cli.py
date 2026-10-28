"""Fôlego command line.

`disk`, `orphans`, `groups` and `tune` run headless (no display, no Qt import) so
the toolbox still works when the desktop session is the thing that is broken.
`tune` never writes in this process: each mutation is handed to a child that can
be killed if the disk stalls.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

from . import doctor as doctor_mod
from . import paths
from .actions.disk import coordinated as disk_coordinated
from .actions.disk import planner, tmpclean
from .actions.disk.measure import measure_tree
from .actions.disk.quarantine import Quarantine
from .actions.orphans import scan
from .actions.tmpfs import coordinated as tmpfs_coordinated
from .actions.tmpfs import inventory, plan as tmpfs_plan, policy as tmpfs_policy_mod
from .actions.tmpfs import release as tmpfs_release
from .actions.tmpfs.ledger import MAX_RETAINED_BYTES, RETENTION_DAYS, Ledger
from .actions.tunings.registry import TUNINGS
from .adapters.inventory import EcosystemInventory, default_adapters
from .core.exclusions import KINDS as EXCLUSION_KINDS
from .core.exclusions import ExclusionError, ExclusionList
from .core.migrate import MigrationError, apply_plan, build_plan
from .core.orphans import GROUP_LABELS, KILLABLE_GROUPS, OrphanTracker, group_targets
from .core.sessions import SessionError, SessionRegistry
from .core.tmpfs import WATCHED, watched_volumes
from .core import runtime_size
from .actions.tmpfs import diagnosis as tmpfs_diagnosis
from .orchestration import Coordinator, Outcome
from .orchestration.automation import FIRST_AUTOMATION_ACTIONS, MODES, PRESETS
from .orchestration.decisions import DecisionLog
from .orchestration.config import ConfigError, ConfigStore
from .orchestration.grants import GrantError, GrantStore
from .process.runner import run_isolated
from .safely.audit import AuditLog

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_NEEDS_CONFIRM = 2
EXIT_PARTIAL = 3
EXIT_FAILED = 4
EXIT_UNKNOWN = 5
# reservado: nenhuma rota da CLI cancela uma operação hoje. Ctrl-C vira
# `desconhecido` (5), porque interromper não prova ausência de efeitos.
EXIT_CANCELLED = 6

# O protocolo de saída (F2/entrega 7): um código por desfecho estruturado, o
# mesmo que o `outcome` do diário; com --json, o código e o desfecho viajam no
# objeto do stdout. `EXIT_NEEDS_CONFIRM` coincide com o 2 do argparse para
# invocação inválida — nos dois casos nada mutou.
EXIT_BY_OUTCOME = {
    Outcome.OK: EXIT_OK,
    Outcome.REFUSED: EXIT_REFUSED,
    Outcome.PARTIAL: EXIT_PARTIAL,
    Outcome.FAILED: EXIT_FAILED,
    Outcome.UNKNOWN: EXIT_UNKNOWN,
    Outcome.CANCELLED: EXIT_CANCELLED,
}

WORKER_MODULE = "folego.actions.tunings.worker"
TUNE_TIMEOUT_S = 15.0

_sleep = time.sleep

_tmpfs_volumes = watched_volumes
_tmpfs_now = time.time


def _tmpfs_ledger() -> Ledger:
    return Ledger()


def _tmpfs_audit() -> AuditLog:
    return AuditLog()


def _tmpfs_dest() -> Path:
    return paths.tmp_quarantine_dir()


def _tmpfs_guard_roots() -> list:
    return tmpfs_release.default_allowed_roots()


def _tmpfs_coordinator() -> Coordinator:
    """O único portão de mutação: trava entre processos + diário de intenção.

    `wait=None` de propósito: duas mutações concorrentes **serializam** (a segunda
    espera a primeira), que é o que "uma por vez" quer dizer no terminal; recusar
    por trava ocupada fica para quem tem fila limitada (a GUI, se precisar).
    """
    return Coordinator()


def run_gui(argv=None) -> int:
    from .app import main as gui_main
    return gui_main()


# ------------------------------------------------------- protocolo de desfecho


def _outcome_of(run) -> Outcome | None:
    """O desfecho do veredito, quando a operação foi coordenada; senão None."""
    return run.verdict.outcome if run.verdict is not None else None


# prefixo do stderr por desfecho; recusa mantém o "refused: " histórico
_STDERR_PREFIX = {Outcome.PARTIAL: "parcial: ", Outcome.FAILED: "falha: ",
                  Outcome.UNKNOWN: "desconhecido: ",
                  Outcome.CANCELLED: "cancelado: "}


def _door_refused(run) -> int:
    """Porta fechada antes do ato: stderr como sempre, código do desfecho real.

    Recusa (trava ocupada, diário corrompido, plano expirado) continua
    `refused:` + 1; falha/desconhecido vindos da porta falam a própria voz e
    devolvem o próprio código — a mesma verdade que o objeto --json carrega.
    """
    outcome = run.verdict.outcome
    sys.stderr.write(f"{_STDERR_PREFIX.get(outcome, 'refused: ')}"
                     f"{run.verdict.reason}\n")
    return EXIT_BY_OUTCOME.get(outcome, EXIT_REFUSED)


def _emit_gate_refusal(args, acao: str, reason: str,
                       code: int = EXIT_REFUSED) -> int:
    """Recusa antes de plano/porta (alvo fora do plano, nenhum volume).

    O stderr continua sendo a voz humana de sempre; com --json, o mesmo motivo
    sai como objeto único no stdout — o consumidor de máquina não depende do
    stderr nem de inferir pelo código.
    """
    sys.stderr.write(f"{reason}\n")
    if getattr(args, "json", False):
        print(json.dumps({"acao": acao, "ok": False, "exit": code,
                          "outcome": str(Outcome.REFUSED), "reason": reason},
                         ensure_ascii=False))
    return code


def _emit_failure(args, acao: str, run, code: int) -> None:
    """Com --json, todo desfecho não-sucesso vira um objeto no stdout.

    O consumidor recebe `outcome` (o vocabulário do diário), o `exit` do processo
    e o motivo no mesmo lugar; campos do domínio (resultados com ``to_dict``) e
    os ``effects``/``errors`` do veredito viajam junto — a falha não esconde o
    que foi observado. Sem veredito (dry-run/flag sem confirmação), o desfecho é
    a recusa do próprio domínio e `ok` fica False mesmo quando o resultado do
    domínio se diz ok: parcial não é sucesso pleno.
    """
    if not getattr(args, "json", False):
        return
    result, verdict = run.result, run.verdict
    payload: dict = {"acao": acao, "ok": False, "exit": code,
                     "outcome": str(verdict.outcome) if verdict is not None
                     else str(Outcome.REFUSED)}
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        payload.update(to_dict())
    reason = (verdict.reason if verdict is not None else None) or payload.get("reason") or getattr(result, "reason", "")
    payload["reason"] = reason
    payload["ok"] = False
    if verdict is not None:
        payload["operation_id"] = verdict.operation_id
        if verdict.effects:
            payload["effects"] = dict(verdict.effects)
        if verdict.errors:
            payload["errors"] = list(verdict.errors)
    print(json.dumps(payload, ensure_ascii=False))


def _emit_uncertain(args, action, run):
    if run.verdict is None or run.verdict.outcome not in (Outcome.UNKNOWN, Outcome.FAILED):
        return None
    code = EXIT_BY_OUTCOME[run.verdict.outcome]
    sys.stderr.write(f"{run.verdict.reason}\n")
    _emit_failure(args, action, run, code)
    return code


def _emit_success(args, acao: str, payload: dict) -> bool:
    """Com --json, o sucesso sai no mesmo envelope dos outros desfechos."""
    if not getattr(args, "json", False):
        return False
    print(json.dumps({"acao": acao, "ok": True, "exit": EXIT_OK,
                      "outcome": str(Outcome.OK), **payload}, ensure_ascii=False))
    return True


def _failed(ns, exc: Exception) -> int:
    """Erro inesperado vira desfecho de protocolo, nunca traceback cru sem código."""
    detail = f"{type(exc).__name__}: {exc}"
    sys.stderr.write(f"falha: {detail}\n")
    if os.environ.get("FOLEGO_TRACEBACK"):
        traceback.print_exc()
    else:
        sys.stderr.write("       (FOLEGO_TRACEBACK=1 mostra o traceback)\n")
    if getattr(ns, "json", False):
        print(json.dumps({"acao": getattr(ns, "sub", None) or ns.command or "",
                          "ok": False, "exit": EXIT_FAILED,
                          "outcome": str(Outcome.FAILED), "reason": detail},
                         ensure_ascii=False))
    return EXIT_FAILED


def _interrupted(ns) -> int:
    """Ctrl-C não prova ausência de efeitos: desconhecido, não cancelamento."""
    sys.stderr.write("desconhecido: interrompido no meio; o diário mostra o que "
                     "tinha começado — consulte antes de repetir\n")
    if getattr(ns, "json", False):
        print(json.dumps({"acao": getattr(ns, "sub", None) or ns.command or "",
                          "ok": False, "exit": EXIT_UNKNOWN,
                          "outcome": str(Outcome.UNKNOWN),
                          "reason": "interrompido pelo usuário; efeitos não "
                                    "verificados"},
                         ensure_ascii=False))
    return EXIT_UNKNOWN


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="folego",
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
        sub.add_argument("--json", action="store_true", help="saída para máquinas")
        if name == "purge":
            sub.add_argument("--irreversivel", action="store_true",
                             help="aceita que o conteúdo não voltará nunca mais")
        if name == "quarantine":
            sub.add_argument("--reviewed-plan", help="ActionPlan JSON apresentado na revisão")

    list_q = disk_sub.add_parser("list", help="itens em quarentena")
    list_q.add_argument("--json", action="store_true",
                        help="uma linha de saída para máquinas")

    tmp = disk_sub.add_parser(
        "tmp", help="itens vencidos em /tmp (lista; mutação desativada — use "
                    "tmpfs plan/release)")
    tmp.add_argument("--dias", type=float, default=3.0, help="idade mínima em dias")
    tmp.add_argument("--raiz", default="/tmp",
                     help="diretório temporário a analisar (só raízes suportadas)")
    tmp.add_argument("--confirmar", action="store_true",
                     help="(desativado) apontava para a rota legada de exclusão")
    tmp.add_argument("--irreversivel", action="store_true",
                     help="(desativado) aceitava a exclusão sem retenção")

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
    groups.add_argument("--forcar", action="store_true",
                        help="SIGKILL em vez de SIGTERM (com --confirmar)"),

    process = commands.add_parser("process", help="executa um plano manual de sinais por identidade")
    process.add_argument("--plan", required=True, help="ActionPlan JSON")
    process.add_argument("--confirmar", action="store_true")
    process.add_argument("--forcar", action="store_true", help="confirma SIGKILL separadamente")
    process.add_argument("--json", action="store_true")

    session = commands.add_parser(
        "session", help="sessões opt-in: UUID, heartbeat, artefatos e manter ativo")
    session_sub = session.add_subparsers(dest="sub", required=True)
    start = session_sub.add_parser(
        "start", help="registra um processo vivo como sessão (cria o registro)")
    start.add_argument("--pid", type=int, required=True,
                       help="processo que a sessão representa")
    start.add_argument("--project", default="", help="projeto dono da sessão")
    start.add_argument("--label", default="", help="rótulo humano")
    start.add_argument("--manter-ativo", action="store_true", dest="keep_active",
                       help="protege o processo de qualquer encerramento heurístico")
    start.add_argument("--json", action="store_true", help="saída para máquinas")
    run = session_sub.add_parser(
        "run", help="inicia um comando sob uma sessão (launcher local)")
    run.add_argument("--project", default="", help="projeto dono da sessão")
    run.add_argument("--label", default="", help="rótulo humano")
    run.add_argument("--manter-ativo", action="store_true", dest="keep_active",
                     help="protege o comando de encerramento heurístico")
    run.add_argument("--heartbeat", type=float, default=None,
                     help="intervalo de sinal de vida em segundos (padrão: política)")
    run.add_argument("argv", nargs=argparse.REMAINDER,
                     help="comando e argumentos, após --")
    for name, help_text in (
        ("heartbeat", "renova o sinal de vida de uma sessão"),
        ("disconnect", "marca que o cliente saiu, sem encerrar o processo"),
        ("end", "encerra explicitamente a sessão (o processo não é sinalizado)"),
    ):
        sub = session_sub.add_parser(name, help=help_text)
        sub.add_argument("session_id", help="UUID devolvido por session start")
        sub.add_argument("--json", action="store_true", help="saída para máquinas")
    listing = session_sub.add_parser("list", help="sessões, estados e artefatos")
    listing.add_argument("--json", action="store_true", help="saída para máquinas")
    listing.add_argument("--todas", action="store_true",
                         help="inclui encerradas (padrão: todas, por transparência)")
    artifact = session_sub.add_parser("artifact", help="registra um artefato da sessão")
    artifact.add_argument("session_id")
    artifact.add_argument("path", help="caminho absoluto do artefato")
    artifact.add_argument("--kind", default="file", help="tipo lógico do artefato")
    artifact.add_argument("--bytes", type=int, default=None, dest="size_bytes",
                          help="tamanho observado, se já conhecido")
    artifact.add_argument("--dias", type=float, default=None,
                          help="vida útil em dias (padrão da política)")
    artifact.add_argument("--json", action="store_true", help="saída para máquinas")
    expired = session_sub.add_parser(
        "expired", help="artefatos vencidos (só lista; nunca apaga)")
    expired.add_argument("--json", action="store_true", help="saída para máquinas")

    exclusions = commands.add_parser(
        "exclusions", help="exclusões por app/projeto/comando e manter ativo")
    exclusions_sub = exclusions.add_subparsers(dest="sub", required=True)
    ex_list = exclusions_sub.add_parser("list", help="exclusões registradas")
    ex_list.add_argument("--json", action="store_true", help="saída para máquinas")
    ex_add = exclusions_sub.add_parser("add", help="adiciona uma exclusão")
    ex_add.add_argument("kind", choices=EXCLUSION_KINDS)
    ex_add.add_argument("value")
    ex_add.add_argument("--manter-ativo", action="store_true", dest="keep_active",
                        help="também protege no ato, não só filtra a lista")
    ex_add.add_argument("--json", action="store_true", help="saída para máquinas")
    ex_remove = exclusions_sub.add_parser("remove", help="remove pelo id")
    ex_remove.add_argument("exclusion_id")
    ex_remove.add_argument("--json", action="store_true", help="saída para máquinas")

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

    diagnose = tmpfs_sub.add_parser(
        "diagnose", help="por que encheu: maiores itens, quem os segura e o comando oficial (não escreve)")
    diagnose.add_argument("--json", action="store_true", help="saída para máquinas")
    diagnose.add_argument("--raiz", action="append", default=None,
                          help="volume a diagnosticar (padrão: o mais cheio)")
    diagnose.add_argument("--prazo", type=float, default=10.0,
                          help="segundos máximos de varredura por volume")

    rsize = tmpfs_sub.add_parser(
        "runtime-size", help="opções de tamanho do runtime (/run/user/<uid>); aplicar pede senha")
    rsize.add_argument("--vezes", type=int, choices=runtime_size.MULTIPLIERS,
                       help="múltiplo do tamanho atual a aplicar")
    rsize.add_argument("--confirmar", action="store_true",
                       help="executa via pkexec: drop-in do logind + remount imediato")
    rsize.add_argument("--json", action="store_true", help="saída para máquinas")

    release = tmpfs_sub.add_parser(
        "release", help="liberar um item para a SSD: copy → verify → unlink, com ledger")
    release.add_argument("target", help="caminho do item, tal como o plano o mostrou")
    release.add_argument("--confirmar", action="store_true", help="aceita esta mutação")
    release.add_argument("--prazo", type=float, default=10.0,
                         help="segundos máximos de varredura por volume")
    release.add_argument("--json", action="store_true",
                         help="uma linha de saída para máquinas (a recusa segue no stderr)")

    restore = tmpfs_sub.add_parser("restore",
                                   help="devolver um item do ledger ao lugar original")
    restore.add_argument("target", help="id do ledger (sai na saída do release)")
    restore.add_argument("--confirmar", action="store_true", help="aceita esta mutação")
    restore.add_argument("--json", action="store_true",
                         help="uma linha de saída para máquinas (a recusa segue no stderr)")

    ledger = tmpfs_sub.add_parser("ledger", help="o que está retido e o orçamento")
    ledger.add_argument("--json", action="store_true", help="saída para máquinas")

    expire = tmpfs_sub.add_parser("expire", help="seca a retenção que estourou o orçamento")
    expire.add_argument("--dias", type=float, default=RETENTION_DAYS,
                        help="idade acima da qual a retenção vence")
    expire.add_argument("--max-bytes", type=int, default=MAX_RETAINED_BYTES,
                        help="teto de bytes retidos na SSD")
    expire.add_argument("--confirmar", action="store_true", help="apaga em vez de listar")
    expire.add_argument("--irreversivel", action="store_true",
                        help="aceita que o conteúdo retido não voltará")
    expire.add_argument("--json", action="store_true",
                        help="uma linha de saída para máquinas (a recusa segue no stderr)")

    recover = tmpfs_sub.add_parser(
        "recover", help="fecha liberações inacabadas (staging) e devolve o caminho")
    recover.add_argument("--confirmar", action="store_true",
                         help="descarta os clones inacabados em vez de listar")
    recover.add_argument("--json", action="store_true",
                         help="uma linha de saída para máquinas (a recusa segue no stderr)")

    grant = commands.add_parser(
        "grant", help="autorizações persistidas e revogáveis da automação")
    grant_sub = grant.add_subparsers(dest="sub", required=True)
    operation = commands.add_parser("operation", help="consulta uma operação pelo ID, sem reaplicar")
    operation.add_argument("operation_id")
    operation.add_argument("--json", action="store_true")
    g_list = grant_sub.add_parser("list", help="grants registrados (inclusive revogados)")
    g_list.add_argument("--json", action="store_true", help="saída para máquinas")
    g_add = grant_sub.add_parser("add", help="cria um grant limitado para uma ação")
    g_add.add_argument("action", help="ação coberta, ex. tmpfs.release")
    g_add.add_argument("--limit", action="append", default=[],
                       metavar="CHAVE=JSON",
                       help="teto/igualdade por parâmetro do plano (repetível)")
    g_add.add_argument("--ttl", type=float, default=3600,
                       help="validade em segundos (padrão: 3600)")
    g_add.add_argument("--resource", action="append", default=[], metavar="JSON",
                       help="identidade ResourceIdentity serializada (repetível)")
    g_add.add_argument("--json", action="store_true", help="saída para máquinas")
    g_revoke = grant_sub.add_parser("revoke", help="revoga sem apagar o registro")
    g_revoke.add_argument("grant_id")
    g_revoke.add_argument("--json", action="store_true", help="saída para máquinas")

    automation = commands.add_parser(
        "automation", help="modo, preset e pausa da automação (sem executar nada)")
    automation_sub = automation.add_subparsers(dest="sub", required=True)
    a_status = automation_sub.add_parser("status", help="estado atual (não escreve)")
    a_status.add_argument("--json", action="store_true", help="saída para máquinas")
    a_mode = automation_sub.add_parser("mode", help="troca o modo; automático exige grant")
    a_mode.add_argument("mode", choices=MODES)
    a_mode.add_argument("--confirmar", action="store_true",
                        help="necessário para entrar no modo automático")
    a_mode.add_argument("--json", action="store_true", help="saída para máquinas")
    a_preset = automation_sub.add_parser("preset", help="troca só a paciência, nunca o grant")
    a_preset.add_argument("preset", choices=tuple(PRESETS))
    a_preset.add_argument("--json", action="store_true", help="saída para máquinas")
    a_pause = automation_sub.add_parser("pause", help="pausa sem sair nem revogar")
    a_pause.add_argument("--json", action="store_true", help="saída para máquinas")
    a_resume = automation_sub.add_parser("resume", help="retoma no mesmo modo/grant")
    a_resume.add_argument("--json", action="store_true", help="saída para máquinas")
    a_decisions = automation_sub.add_parser(
        "decisions", help="simulações registradas para revisão humana (sem efeito)")
    a_decisions.add_argument("--limit", type=int, default=20,
                              help="máximo de registros recentes (1–500)")
    a_decisions.add_argument("--json", action="store_true", help="saída para máquinas")

    ecosystem = commands.add_parser(
        "ecosystem", help="inventário somente leitura de projetos, caches, "
                          "containers, VMs e montagens (F7)")
    ecosystem.add_argument("--adapter", action="append", default=None,
                           choices=("projects", "caches", "docker", "podman",
                                    "libvirt", "mounts", "pytest-fixtures"),
                           help="restringe o inventário (repetível)")
    ecosystem.add_argument("--json", action="store_true", help="saída para máquinas")

    doctor = commands.add_parser(
        "doctor", help="diagnóstico somente leitura: capacidades, schema e ferramentas")
    doctor.add_argument("--json", action="store_true", help="saída para máquinas")

    migrate = commands.add_parser(
        "migrate", help="copia estado legado DeckWellness sem apagar nem sobrescrever")
    migrate.add_argument("--confirmar", action="store_true",
                         help="executa a cópia (sem isso é dry-run)")
    migrate.add_argument("--json", action="store_true", help="saída para máquinas")

    logs = commands.add_parser(
        "logs", help="orçamento e rotação do diário de auditoria (nunca apaga)")
    logs_sub = logs.add_subparsers(dest="sub", required=True)
    l_status = logs_sub.add_parser("status", help="tamanho ativo/arquivado e orçamento")
    l_status.add_argument("--json", action="store_true", help="saída para máquinas")
    l_rotate = logs_sub.add_parser(
        "rotate", help="compacta o ativo em .jsonl.gz e começa outro")
    l_rotate.add_argument("--confirmar", action="store_true",
                          help="executa a rotação (sem isso só mostra)")
    l_rotate.add_argument("--json", action="store_true", help="saída para máquinas")
    l_archives = logs_sub.add_parser("archives", help="lista arquivos preservados")
    l_archives.add_argument("--json", action="store_true", help="saída para máquinas")
    return parser


def _quarantine(fake_home=None) -> Quarantine:
    home = Path(fake_home) if fake_home else Path.home()
    return Quarantine(allowed_roots=planner.default_allowed_roots(home),
                      audit=AuditLog())


def _disk_coordinator() -> Coordinator:
    """A mesma porta do `_tmpfs_coordinator`: uma trava e um diário por usuário.

    O estado é compartilhado entre os domínios de propósito — trocar de
    subsistema não pode afrouxar a serialização entre processos.
    """
    return Coordinator()


def _cmd_plan(args) -> int:
    home = Path.home()
    plan = planner.build_plan(planner.default_targets(), home=home,
                              deadline_s=args.prazo)
    payload = json.loads(plan.to_json())
    from .actions.disk.review import plan_quarantine
    book = _quarantine()
    for item in payload["items"]:
        if item["reclaimable"]:
            try:
                item["action_plan"] = plan_quarantine(item["path"], book).to_dict()
            except (OSError, ValueError) as exc:
                item["review_error"] = str(exc)
                item["reclaimable"] = False
                item["reason"] = f"refused: revisão incompleta/protegida: {exc}"
    payload["total_bytes"] = sum(item["bytes"] for item in payload["items"] if item["reclaimable"])
    if args.json:
        payload["volumes"] = [v.to_dict() for v in planner.volume_report(home=home)]
        print(json.dumps(payload, ensure_ascii=False))
        return EXIT_OK
    from dataclasses import replace
    plan = replace(plan, items=tuple(replace(original, reclaimable=row["reclaimable"],
                                            reason=row["reason"])
                                     for original, row in zip(plan.items, payload["items"])),
                   total_bytes=payload["total_bytes"])
    volumes = planner.volume_report(home=home)
    print("Volume:")
    print(planner.format_volumes(volumes))
    print("")
    print("Candidatos a liberação (dry-run, nada foi alterado):")
    print(planner.format_report(plan))
    print("")
    print("Para liberar de forma reversível: folego disk quarantine <caminho> --confirmar")
    return EXIT_OK


def _cmd_quarantine(args) -> int:
    # toda mutação confirmada passa pelo coordenador (intenção antes do
    # rename); a recusa de flag mora na ponte, uma porta só para CLI e GUI
    reviewed_plan = None
    if getattr(args, "reviewed_plan", None):
        from .orchestration.models import ActionPlan, ValidationError
        try:
            reviewed_plan = ActionPlan.from_dict(json.loads(args.reviewed_plan))
        except (ValueError, TypeError, ValidationError) as exc:
            return _emit_gate_refusal(args, "quarantine", f"plano revisado inválido: {exc}")
    run = disk_coordinated.quarantine(
        coordinator=_disk_coordinator(), confirm=args.confirmar,
        book=_quarantine(), path=args.target, reviewed_plan=reviewed_plan)
    if run.result is None:
        if run.verdict is not None and run.verdict.ok:
            if not _emit_success(args, "quarantine", {
                    **dict(run.verdict.effects), "operation_id": run.verdict.operation_id,
                    "queried": True}):
                print(f"resultado já registrado: {run.verdict.operation_id}")
            return EXIT_OK
        # porta fechada (trava entre processos, diário corrompido): nada rodou
        # e o diário não ganhou operação
        code = _door_refused(run)
        _emit_failure(args, "quarantine", run, code)
        return code
    uncertain = _emit_uncertain(args, 'quarantine', run)
    if uncertain is not None:
        return uncertain
    result = run.result
    if not result.ok:
        code = EXIT_NEEDS_CONFIRM if not args.confirmar else \
            EXIT_BY_OUTCOME.get(_outcome_of(run) or Outcome.REFUSED, EXIT_REFUSED)
        sys.stderr.write(f"{result.reason}\n")
        _emit_failure(args, "quarantine", run, code)
        return code
    entry = result.entry
    if _emit_success(args, "quarantine", {"entry_id": entry.entry_id,
                                          "operation_id": run.verdict.operation_id,
                                          "bytes": entry.bytes,
                                          "original": entry.original,
                                          "stored": entry.stored}):
        return EXIT_OK
    print(f"quarentena: {entry.entry_id}")
    print(f"   de:   {entry.original}")
    print(f"   para: {entry.stored}")
    print(f"   {planner.fmt_bytes(entry.bytes)} recuperáveis · reverta com "
          f"folego disk restore {entry.entry_id} --confirmar")
    return EXIT_OK


def _cmd_restore(args) -> int:
    run = disk_coordinated.restore(
        coordinator=_disk_coordinator(), confirm=args.confirmar,
        book=_quarantine(), entry_id=args.target)
    if run.result is None:
        code = _door_refused(run)
        _emit_failure(args, "restore", run, code)
        return code
    uncertain = _emit_uncertain(args, 'restore', run)
    if uncertain is not None:
        return uncertain
    result = run.result
    if not result.ok:
        code = EXIT_NEEDS_CONFIRM if not args.confirmar else \
            EXIT_BY_OUTCOME.get(_outcome_of(run) or Outcome.REFUSED, EXIT_REFUSED)
        sys.stderr.write(f"{result.reason}\n")
        _emit_failure(args, "restore", run, code)
        return code
    entry = result.entry
    if _emit_success(args, "restore", {
            "entry_id": str(args.target),
            "bytes": entry.bytes if entry is not None else 0,
            "restored_to": entry.original if entry is not None else ""}):
        return EXIT_OK
    print(f"restaurado: {args.target}")
    return EXIT_OK


def _cmd_purge(args) -> int:
    run = disk_coordinated.purge(
        coordinator=_disk_coordinator(), confirm=args.confirmar,
        irreversible=args.irreversivel, book=_quarantine(), entry_id=args.target)
    if run.result is None:
        code = _door_refused(run)
        _emit_failure(args, "purge", run, code)
        return code
    uncertain = _emit_uncertain(args, 'purge', run)
    if uncertain is not None:
        return uncertain
    result = run.result
    if not result.ok:
        code = (EXIT_NEEDS_CONFIRM if not (args.confirmar and args.irreversivel)
                else EXIT_BY_OUTCOME.get(_outcome_of(run) or Outcome.REFUSED,
                                         EXIT_REFUSED))
        sys.stderr.write(f"{result.reason}\n")
        _emit_failure(args, "purge", run, code)
        return code
    entry = result.entry
    if _emit_success(args, "purge", {
            "entry_id": str(args.target),
            "bytes": entry.bytes if entry is not None else 0,
            "purged": entry.stored if entry is not None else ""}):
        return EXIT_OK
    print(f"purgado: {args.target}")
    return EXIT_OK


def _cmd_list(args) -> int:
    q = _quarantine()
    # o reparo de uma queda passa pela porta única (intenção no diário quando há
    # o que reparar); sem reparo pendente, listar é só leitura
    run = disk_coordinated.reconcile(coordinator=_disk_coordinator(), book=q)
    uncertain = _emit_uncertain(args, "disk.list", run)
    if uncertain is not None:
        return uncertain
    report = run.result
    if report is not None and report.problems:
        # manifesto ilegível/inconsistente: não se finge vazio nem se lista o que
        # não é confiável — a mutação fica bloqueada até o reparo humano
        reason = ("manifesto da quarentena inconsistente; mutações bloqueadas e "
                  "listagem não confiável: " + "; ".join(report.problems))
        sys.stderr.write("refused: " + reason + "\n")
        if getattr(args, "json", False):
            _emit_machine({"acao": "disk.list", "ok": False, "exit": EXIT_REFUSED,
                           "outcome": "recusa", "reason": reason})
        return EXIT_REFUSED
    if run.result is None:
        # porta fechada (trava/diário): o reparo não rodou, mas a leitura continua
        sys.stderr.write(f"aviso: reparo bloqueado: {run.verdict.reason}\n")
    elif report.manual:
        sys.stderr.write(f"aviso: {len(report.manual)} entrada(s) de quarentena "
                         f"ambígua(s), decisão manual: {', '.join(report.manual)}\n")
    entries = sorted(q.entries().values(), key=lambda e: -e.bytes)
    rows = []
    for entry in entries:
        stat = measure_tree(entry.stored) if entry.state == "stored" else None
        size = stat.bytes if stat else 0
        row = {**entry.to_dict(), "observed_bytes": size}
        rows.append(row)
        if not getattr(args, "json", False):
            print(f"{entry.entry_id} · {Path(entry.original).name} · "
                  f"{planner.fmt_bytes(size)} · {entry.state} · {entry.original}")
    if getattr(args, "json", False):
        _emit_machine({"acao": "disk.list", "ok": True, "exit": EXIT_OK,
                       "outcome": "sucesso", "entries": rows,
                       "reclaimable_bytes": q.reclaimable_bytes()})
        return EXIT_OK
    if not entries:
        print("quarentena vazia")
        return EXIT_OK
    print(f"\nem quarentena: {planner.fmt_bytes(q.reclaimable_bytes())}")
    return EXIT_OK


def _tmp_legacy_roots() -> tuple:
    """Raízes que a rota legada aceita. O default é o /tmp; o teste troca a costura."""
    return ("/tmp",)


def _tmp_legacy_mounts():
    from .core.tmpfs import read_mounts
    return read_mounts()


def _tmp_legacy_holders(root: Path):
    from .actions.tmpfs.holders import holder_index
    return holder_index(prefixes=(str(root),))


def _cmd_tmp(args) -> int:
    """Lista o que a rota legada considerava vencido — e não muta mais.

    R01/F1.1: a seleção antiga olhava só o filho direto e o `rmtree` não consultava
    holders nem montes. Até a unificação no planejador conservador (F2), esta rota
    fica somente leitura e aponta para `folego tmpfs plan/release`, que copia,
    verifica e retém em vez de apagar direto.
    """
    root = Path(args.raiz)
    try:
        resolved = root.resolve()
    except OSError:
        resolved = root
    supported = [Path(r).resolve() for r in _tmp_legacy_roots()]
    if resolved not in supported:
        sys.stderr.write(
            f"refused: {root} não é uma raiz suportada pela rota legada "
            f"({', '.join(str(s) for s in supported)}); a rota legada só lista, e a "
            "liberação real é `folego tmpfs plan` → `folego tmpfs release`\n")
        return EXIT_REFUSED
    mounts = _tmp_legacy_mounts()
    inner = [m for m, _ in mounts if m != str(resolved) and m.startswith(str(resolved) + os.sep)]
    if inner:
        sys.stderr.write(
            f"refused: há um monte dentro de {root} ({', '.join(inner)}); a rota legada "
            "não atravessa montagem — libere item por item com `folego tmpfs release`\n")
        return EXIT_REFUSED

    plan = tmpclean.plan_tmp(resolved, min_age_days=args.dias)
    holders = _tmp_legacy_holders(resolved)
    in_use = {p.path for p in plan.items
              if holders.pids_holding(p.path)}
    if not plan.items:
        print(f"{root}: nada com mais de {args.dias:g} dia(s) pertencente a você")
    else:
        print(f"{root} · {len(plan.items)} item(ns) vencidos · "
              f"{planner.fmt_bytes(plan.total_bytes)} · {len(plan.kept)} mantido(s)")
        for item in sorted(plan.items, key=lambda i: -i.bytes):
            note = ""
            if item.path in in_use:
                pids = ", ".join(str(p) for p in holders.pids_holding(item.path))
                note = f" · em uso por pid {pids}"
            print(f"  · {Path(item.path).name} · {planner.fmt_bytes(item.bytes)} · "
                  f"{item.age_days:.0f} d · {item.path}{note}")
    if holders.state != "complete":
        sys.stderr.write(
            "aviso: o índice de holders está incompleto; ausência de 'em uso' aqui "
            "não prova que o item está livre\n")

    if args.confirmar or args.irreversivel:
        sys.stderr.write(
            "refused: a exclusão direta desta rota foi desativada (F1.1): ela não "
            "consultava holders nem montes e apagava sem retenção. Nada foi alterado. "
            "Para liberar com cópia verificada e retorno pelo ledger, use "
            "`folego tmpfs plan` e `folego tmpfs release <caminho> --confirmar`\n")
        return EXIT_REFUSED
    sys.stderr.write("\ndry-run: nada alterado. Esta rota não apaga mais; use "
                     "`folego tmpfs plan` → `folego tmpfs release`\n")
    return EXIT_OK


_HANDLERS = {
    "plan": _cmd_plan,
    "quarantine": _cmd_quarantine,
    "restore": _cmd_restore,
    "purge": _cmd_purge,
    "list": _cmd_list,
    "tmp": _cmd_tmp,
}


def _emit_machine(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _protection_checker():
    """Uma leitura de sessões/exclusões por varredura; falha fechado."""
    try:
        sessions = SessionRegistry().snapshot()
        exclusions = ExclusionList().list()
    except (SessionError, ExclusionError) as exc:
        reason = f"proteção ilegível: {exc}"
        return lambda proc: reason
    by_key = {(item.pid, item.starttime): item
              for item in sessions if not item.ended}

    def check(proc):
        session = by_key.get((proc.pid, proc.starttime))
        if session is not None and session.keep_active:
            return (f"sessão {session.session_id} marcada como manter ativo "
                    f"({session.state})")
        project = session.project if session is not None else ""
        session_id = session.session_id if session is not None else ""
        for item in exclusions:
            if ExclusionList._match(item, proc, project, session_id):
                suffix = " (manter ativo)" if item.keep_active else ""
                return f"exclusão {item.kind}:{item.value}{suffix}"
        return None

    return check


def _reaper(protected_fn=None):
    from .actions.orphans.reaper import Reaper
    if protected_fn is None:
        from .core.process_protection import ProcessProtection
        protected_fn = ProcessProtection()
    return Reaper(audit=AuditLog(), protected_fn=protected_fn)


def _session_error(args, action: str, exc: Exception,
                   code: int = EXIT_REFUSED) -> int:
    message = str(exc)
    sys.stderr.write(f"refused: {message}\n")
    if getattr(args, "json", False):
        _emit_machine({"acao": action, "ok": False, "exit": code,
                       "reason": message})
    return code


def _session_ok(args, action: str, payload: dict, human: str) -> int:
    if getattr(args, "json", False):
        _emit_machine({"acao": action, "ok": True, "exit": EXIT_OK,
                       **payload})
    else:
        print(human)
    return EXIT_OK


def _rss(rss_kb: int) -> str:
    return planner.fmt_bytes(rss_kb * 1024)


def _session_run(args) -> int:
    """Launch a command under a session; the child survives a lost launcher.

    `start_new_session=True` gives the child its own session, so Ctrl-C/SIGHUP
    that reaches this launcher does not take a useful build with it. The session
    heartbeat is renewed while the launcher lives; if it disappears, the record
    becomes `heartbeat_lost` and an explicit keep-active promise still protects
    the child. No signal is sent to the child by the launcher.
    """
    argv = list(args.argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        return _session_error(
            args, "session.run",
            SessionError("informe o comando após --"), EXIT_NEEDS_CONFIRM)
    try:
        from .safely.jobtemp import prepare_job_environment
        child = subprocess.Popen(argv, start_new_session=True,
                                 env=prepare_job_environment())
    except OSError as exc:
        return _session_error(args, "session.run",
                              SessionError(f"não foi possível iniciar: {exc}"),
                              EXIT_FAILED)
    store = SessionRegistry()
    try:
        session = store.register(child.pid, project=args.project,
                                 label=args.label, keep_active=args.keep_active)
    except SessionError as exc:
        # O filho já existe; não deixamos um processo sem registro protetor.
        # SIGTERM e espera curta, sem escalada automática.
        try:
            child.terminate()
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"aviso: pid {child.pid} continua ativo; "
                             f"escalada não é automática\n")
        return _session_error(args, "session.run", exc)

    protect = "sim" if session.keep_active else "não"
    sys.stderr.write(
        f"sessão {session.session_id} · pid {child.pid} · estado {session.state} "
        f"· manter ativo: {protect}\n")
    interval = args.heartbeat
    if interval is None:
        interval = max(1.0, min(30.0, store.policy.heartbeat_ttl_s / 3.0))
    interval = max(0.05, float(interval))
    last_beat = time.monotonic()
    beat_errors = False
    try:
        while True:
            code = child.poll()
            if code is not None:
                break
            now = time.monotonic()
            if now - last_beat >= interval:
                try:
                    store.heartbeat(session.session_id)
                    beat_errors = False
                except SessionError as exc:
                    if not beat_errors:
                        sys.stderr.write(f"aviso: heartbeat falhou: {exc}\n")
                        beat_errors = True
                last_beat = now
            time.sleep(0.1)
    except KeyboardInterrupt:
        try:
            store.disconnect(session.session_id)
        except SessionError:
            pass
        sys.stderr.write(
            f"launcher interrompido: a sessão {session.session_id} foi marcada "
            f"como desconectada; pid {child.pid} continua ativo\n")
        return EXIT_UNKNOWN

    reason = (f"processo filho saiu com código {code}" if code >= 0
              else f"processo filho terminou pelo sinal {-code}")
    try:
        store.end(session.session_id, reason=reason)
    except SessionError as exc:
        sys.stderr.write(f"aviso: não foi possível encerrar a sessão: {exc}\n")
    return 0 if code == 0 else (code if code > 0 else 128 + (-code))


def _cmd_session(args) -> int:
    action = f"session.{args.sub}"
    try:
        if args.sub == "run":
            return _session_run(args)
        if args.sub == "start":
            item = SessionRegistry().register(
                args.pid, project=args.project, label=args.label,
                keep_active=args.keep_active)
            protect = "sim" if item.keep_active else "não"
            return _session_ok(
                args, action, {"session": item.to_dict()},
                f"sessão {item.session_id} · pid {item.pid} · estado {item.state} "
                f"· manter ativo: {protect}")
        if args.sub == "list":
            items = SessionRegistry().snapshot()
            if args.json:
                return _session_ok(args, action,
                                   {"sessions": [item.to_dict() for item in items]},
                                   "")
            if not items:
                print("nenhuma sessão registrada (registro opt-in: nada observado "
                      "foi inferido como sessão)")
                return EXIT_OK
            for item in items:
                protect = " · manter ativo" if item.keep_active else ""
                project = f" · {item.project}" if item.project else ""
                label = item.label or "(sem rótulo)"
                print(f"{item.session_id} · pid {item.pid} · {item.state} · "
                      f"{label}{project}{protect}")
            return EXIT_OK
        if args.sub == "heartbeat":
            item = SessionRegistry().heartbeat(args.session_id)
            return _session_ok(args, action, {"session": item.to_dict()},
                               f"sessão {item.session_id} · estado {item.state}")
        if args.sub == "disconnect":
            item = SessionRegistry().disconnect(args.session_id)
            return _session_ok(args, action, {"session": item.to_dict()},
                               f"sessão {item.session_id} · estado {item.state} "
                               f"(processo não foi sinalizado)")
        if args.sub == "end":
            item = SessionRegistry().end(args.session_id)
            return _session_ok(args, action, {"session": item.to_dict()},
                               f"sessão {item.session_id} · estado {item.state} "
                               f"(processo não foi sinalizado)")
        if args.sub == "artifact":
            artifact = SessionRegistry().add_artifact(
                args.session_id, args.path, kind=args.kind,
                size_bytes=args.size_bytes, ttl_days=args.dias)
            return _session_ok(args, action, {"artifact": artifact.to_dict()},
                               f"artefato {artifact.path} · expira em "
                               f"{artifact.expires_at or 'nunca'}")
        if args.sub == "expired":
            artifacts = SessionRegistry().expired_artifacts()
            if args.json:
                return _session_ok(
                    args, action,
                    {"artifacts": [item.to_dict() for item in artifacts]}, "")
            if not artifacts:
                print("nenhum artefato vencido (nada foi apagado)")
            for item in artifacts:
                print(f"{item.path} · {item.kind} · vencido em {item.expires_at}")
            return EXIT_OK
    except SessionError as exc:
        code = EXIT_UNKNOWN if "ilegível" in str(exc) else EXIT_REFUSED
        return _session_error(args, action, exc, code)
    return _session_error(args, action, SessionError("subcomando desconhecido"))


def _cmd_exclusions(args) -> int:
    action = f"exclusions.{args.sub}"
    try:
        ledger = ExclusionList()
        if args.sub == "list":
            items = ledger.list()
            if args.json:
                return _session_ok(
                    args, action, {"exclusions": [item.to_dict() for item in items]},
                    "")
            if not items:
                print("nenhuma exclusão registrada")
            for item in items:
                protect = " · manter ativo" if item.keep_active else ""
                print(f"{item.exclusion_id} · {item.kind}:{item.value}{protect}")
            return EXIT_OK
        if args.sub == "add":
            item = ledger.add(args.kind, args.value,
                              keep_active=args.keep_active)
            protect = " · manter ativo" if item.keep_active else ""
            return _session_ok(
                args, action, {"exclusion": item.to_dict()},
                f"exclusão {item.exclusion_id} · {item.kind}:{item.value}{protect}")
        if args.sub == "remove":
            removed = ledger.remove(args.exclusion_id)
            if not removed:
                return _session_error(
                    args, action,
                    ExclusionError(f"exclusão {args.exclusion_id} não encontrada"))
            return _session_ok(args, action,
                               {"removed": args.exclusion_id, "exclusion_id":
                                args.exclusion_id},
                               f"exclusão {args.exclusion_id} removida")
    except ExclusionError as exc:
        code = EXIT_UNKNOWN if "ilegível" in str(exc) else EXIT_REFUSED
        return _session_error(args, action, exc, code)
    return _session_error(args, action,
                          ExclusionError("subcomando desconhecido"))


def _parse_limit_rows(rows) -> dict:
    limits = {}
    for row in rows:
        key, separator, raw = row.partition("=")
        if not separator or not key:
            raise GrantError(f"limite inválido: {row!r} (use CHAVE=JSON)")
        try:
            limits[key] = json.loads(raw)
        except ValueError as exc:
            raise GrantError(f"limite {key!r} não é JSON: {raw!r}") from exc
    return limits


def _automation_payload(config, grants, now=None) -> dict:
    now = time.time() if now is None else now
    active = [grant for grant in grants if grant.active(now)]
    return {
        "mode": config.mode,
        "preset": config.preset,
        "paused": config.paused,
        "updated_at": config.updated_at,
        "grants_total": len(grants),
        "grants_active": len(active),
        "automation_actions": list(FIRST_AUTOMATION_ACTIONS),
        "active_grants": [grant.to_dict() for grant in active],
    }


def _cmd_operation(args) -> int:
    from .orchestration.journal import Journal, CorruptJournal
    state = None
    try:
        state = Journal().state_of(args.operation_id)
        result = state.result if state is not None else None
        outcome = result.outcome if result is not None else Outcome.UNKNOWN
        reason = (result.reason if result is not None else
                  "intenção sem resultado; reconciliação pendente; não repetir" if state is not None
                  else "ID não encontrado; ausência de efeito não comprovada")
    except (OSError, CorruptJournal) as exc:
        outcome, reason = Outcome.UNKNOWN, f"histórico não comprovado: {exc}"
    code = EXIT_BY_OUTCOME[outcome]
    payload = {"acao": "operation.query", "operation_id": args.operation_id,
               "ok": outcome is Outcome.OK, "exit": code, "outcome": str(outcome),
               "reason": reason, "state": state.to_dict() if state is not None else None}
    if args.json:
        _emit_machine(payload)
    else:
        print(f"{args.operation_id} · {outcome} · {reason or 'resultado registrado'}")
    return code


def _cmd_grant(args) -> int:
    action = f"grant.{args.sub}"
    try:
        store = GrantStore()
        if args.sub == "list":
            items = store.list()
            if getattr(args, "json", False):
                _emit_machine({"acao": action, "ok": True, "exit": EXIT_OK,
                               "outcome": "sucesso",
                               "grants": [item.to_dict() for item in items]})
            elif not items:
                print("nenhum grant registrado (automação desligada)")
            else:
                now = time.time()
                for item in items:
                    state = "ativo" if item.active(now) else "inativo/revogado"
                    print(f"{item.grant_id} · {item.action} · {state} · "
                          f"limites {dict(item.limits)}")
            return EXIT_OK
        if args.sub == "add":
            from .orchestration.models import ResourceIdentity, ValidationError
            try:
                resources = tuple(ResourceIdentity.from_dict(json.loads(raw)) for raw in args.resource)
            except (ValueError, TypeError, ValidationError) as exc:
                raise GrantError(f"identidade de recurso inválida: {exc}") from exc
            grant = store.add(args.action, _parse_limit_rows(args.limit),
                              ttl_s=args.ttl, resources=resources)
            return _session_ok(
                args, action, {"outcome": "sucesso", "grant": grant.to_dict()},
                f"grant {grant.grant_id} criado para {grant.action} · "
                f"limites {dict(grant.limits)}")
        if args.sub == "revoke":
            grant = store.revoke(args.grant_id)
            return _session_ok(
                args, action, {"outcome": "sucesso", "grant": grant.to_dict()},
                f"grant {grant.grant_id} revogado; o registro permanece")
    except GrantError as exc:
        code = EXIT_UNKNOWN if "ilegível" in str(exc) else EXIT_REFUSED
        return _session_error(args, action, exc, code)
    return _session_error(args, action, GrantError("subcomando desconhecido"),
                          EXIT_NEEDS_CONFIRM)


def _cmd_automation(args) -> int:
    action = f"automation.{args.sub}"
    if args.sub == "decisions":
        # Revisar simulações não depende de config válida: o registro é evidência
        # histórica e continua legível mesmo quando o modo atual está corrompido.
        limit = min(max(0, args.limit), 500)
        records = DecisionLog().recent(limit)
        return _session_ok(
            args, action,
            {"outcome": "sucesso", "count": len(records), "decisions": records},
            "\n".join(
                f"{row['ts']} · {row['actor']} · {row['mode']}/{row['preset']} · "
                f"{row['action']} · {row['target'].get('key', '?')} · "
                f"executaria={row['would_execute']} · executado={row['executed']} · "
                f"plano {row['plan_digest'][:16]}"
                for row in records) or
            "nenhuma simulação registrada (nada foi executado)")
    try:
        store = ConfigStore()
        config = store.read()
        if args.sub == "status":
            grants = GrantStore().list()
            payload = _automation_payload(config, grants)
            return _session_ok(
                args, action, {"outcome": "sucesso", **payload},
                f"modo {config.mode} · preset {config.preset} · "
                f"{'pausado' if config.paused else 'ativo'} · "
                f"{payload['grants_active']} grant(s) ativo(s)")
        if args.sub == "mode":
            if args.mode == "automatico" and not args.confirmar:
                return _session_error(
                    args, action,
                    ConfigError("entrar no modo automático exige --confirmar"),
                    EXIT_NEEDS_CONFIRM)
            config = store.set_mode(args.mode)
            return _session_ok(
                args, action,
                {"outcome": "sucesso", **_automation_payload(
                    config, GrantStore().list())},
                f"modo {config.mode} · preset {config.preset} · "
                f"{'pausado' if config.paused else 'ativo'}")
        if args.sub == "preset":
            config = store.set_preset(args.preset)
            return _session_ok(
                args, action,
                {"outcome": "sucesso", **_automation_payload(
                    config, GrantStore().list())},
                f"preset {config.preset} · modo {config.mode}; grants não mudaram")
        if args.sub == "pause":
            config = store.set_paused(True)
            return _session_ok(
                args, action,
                {"outcome": "sucesso", **_automation_payload(
                    config, GrantStore().list())},
                "automação pausada; modo e grants preservados")
        if args.sub == "resume":
            config = store.set_paused(False)
            return _session_ok(
                args, action,
                {"outcome": "sucesso", **_automation_payload(
                    config, GrantStore().list())},
                f"automação retomada no modo {config.mode}")
    except (ConfigError, GrantError) as exc:
        code = EXIT_UNKNOWN if "ilegível" in str(exc) else EXIT_REFUSED
        return _session_error(args, action, exc, code)
    return _session_error(args, action, ConfigError("subcomando desconhecido"),
                          EXIT_NEEDS_CONFIRM)


def _cmd_ecosystem(args) -> int:
    adapters = default_adapters()
    if args.adapter:
        wanted = set(args.adapter)
        adapters = tuple(adapter for adapter in adapters
                         if adapter.name in wanted)
    inventory = EcosystemInventory(adapters)
    results = inventory.collect()
    if args.json:
        _emit_machine({"acao": "ecosystem.inventory", "ok": True,
                       "exit": EXIT_OK, "outcome": "sucesso",
                       **inventory.to_dict(results)})
        return EXIT_OK
    for result in results:
        state = "disponível" if result.available else "indisponível"
        print(f"{result.name} · {state} · {len(result.items)} item(ns) · "
              f"{len(result.protected)} protegido(s)")
        if result.reason:
            print(f"  {result.reason}")
        if result.error:
            print(f"  erro: {result.error}")
        for item in result.items[:10]:
            mark = " · protegido" if item.protected else ""
            print(f"  · {item.kind} {item.label}{mark} · {item.reason}")
        if len(result.items) > 10:
            print(f"  … {len(result.items) - 10} item(ns) omitido(s)")
    print("inventário somente leitura: nenhuma ferramenta, volume ou VM foi alterada")
    return EXIT_OK


def _cmd_doctor(args) -> int:
    report = doctor_mod.collect()
    if args.json:
        _emit_machine({"acao": "doctor", "ok": True, "exit": EXIT_OK,
                       "outcome": "sucesso", "healthy": report.status != "error",
                       **report.to_dict()})
        return EXIT_OK
    for check in report.checks:
        print(f"[{check.status:7}] {check.name}: {check.detail}")
    print(f"diagnóstico {report.status}: {len(report.errors)} erro(s), "
          f"{len(report.warnings)} aviso(s); nada foi alterado")
    return EXIT_OK


def _cmd_migrate(args) -> int:
    action = "migrate.deckwellness"
    try:
        plan = build_plan()
        if not plan.entries:
            if args.json:
                _emit_machine({"acao": action, "ok": True, "exit": EXIT_OK,
                               "outcome": "sucesso", "migrated": False,
                               "plan": plan.to_dict()})
            else:
                print("nenhum estado DeckWellness encontrado; nada a migrar")
            return EXIT_OK
        if not plan.ready:
            detail = "; ".join(error for entry in plan.conflicts
                               for error in entry.errors) or "conflito no plano"
            return _session_error(args, action, MigrationError(detail))
        if not args.confirmar:
            if args.json:
                _emit_machine({"acao": action, "ok": True, "exit": EXIT_OK,
                               "outcome": "sucesso", "migrated": False,
                               "plan": plan.to_dict()})
            else:
                for entry in plan.entries:
                    print(f"{entry.kind}: {entry.source} → {entry.destination} · "
                          f"{entry.files} arquivo(s) · {entry.bytes} bytes")
                print("\ndry-run: nada foi copiado nem removido. Repita com "
                      "--confirmar para copiar; a origem permanece.")
            return EXIT_OK
        apply_plan(plan, confirm=True)
        if args.json:
            _emit_machine({"acao": action, "ok": True, "exit": EXIT_OK,
                           "outcome": "sucesso", "migrated": True,
                           "plan": plan.to_dict()})
        else:
            for entry in plan.entries:
                print(f"copiado {entry.kind}: {entry.source} → {entry.destination}")
            print("origem preservada; rollback = continuar usando a árvore antiga")
        return EXIT_OK
    except MigrationError as exc:
        return _session_error(args, action, exc)


def _cmd_logs(args) -> int:
    action = f"logs.{args.sub}"
    log = AuditLog()
    if args.sub == "status":
        status = log.status()
        return _session_ok(
            args, action, {"outcome": "sucesso", **status},
            f"auditoria ativa {status['active_bytes']} bytes de "
            f"{status['max_bytes']} · {status['archive_count']} arquivo(s) "
            f"compactado(s), {status['archive_bytes']} bytes")
    if args.sub == "archives":
        status = log.status()
        return _session_ok(
            args, action, {"outcome": "sucesso", **status},
            "\n".join(item["path"] for item in status["archives"])
            or "nenhum arquivo de auditoria compactado")
    if args.sub == "rotate":
        if not args.confirmar:
            if args.json:
                _emit_machine({"acao": action, "ok": True, "exit": EXIT_OK,
                               "outcome": "sucesso", "rotated": False,
                               "reason": "dry-run: use --confirmar para compactar",
                               **log.status()})
            else:
                print("dry-run: a rotação ainda não aconteceu. Repita com "
                      "--confirmar para compactar o diário ativo.")
            return EXIT_OK
        try:
            result = log.rotate()
        except OSError as exc:
            return _session_error(args, action, exc, EXIT_FAILED)
        return _session_ok(
            args, action, {"outcome": "sucesso", **result},
            (f"auditoria compactada em {result['archive']}"
             if result["rotated"] else "nada a rotacionar: diário ativo vazio"))
    return _session_error(args, action, ValueError("subcomando desconhecido"),
                          EXIT_NEEDS_CONFIRM)


def _cmd_orphans(args) -> int:
    if args.forcar and not args.confirmar:
        sys.stderr.write("refused: SIGKILL é mais disruptivo que SIGTERM; use "
                         "--confirmar --forcar\n")
        return EXIT_NEEDS_CONFIRM
    min_idle = args.janela if args.ocioso is None else args.ocioso
    from .core.sessions import read_boot_id
    boot = read_boot_id()
    protection = _protection_checker()
    found = scan.scan_orphans(
        scan.collector_for(),
        tracker=OrphanTracker(min_idle_s=min_idle, protected_fn=protection),
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
    run = _process_selection(found, reaper=reaper, boot_id=boot, force=args.forcar)
    if run.result is None or run.verdict.outcome is Outcome.UNKNOWN:
        sys.stderr.write(f"{run.verdict.reason} · operação {run.verdict.operation_id}\n")
        return EXIT_BY_OUTCOME[run.verdict.outcome]
    sent, refused, survivors = 0, 0, 0
    followed = False
    for result in run.result.results:
        if result.ok:
            sent += 1
            note = f" · {result.reason}" if result.reason else ""
            # R10/entrega 8: o sinal sair não prova encerramento — só o
            # acompanhamento observado autoriza a palavra "encerrado"
            if result.exited is True:
                print(f"encerrado: pid {result.pid} · {result.comm} saiu após o "
                      f"sinal{note}")
            elif result.exited is False:
                survivors += 1
                print(f"sinal enviado: pid {result.pid} · {result.comm} · continua "
                      f"ativo após o sinal{note}")
            else:
                print(f"sinal enviado: pid {result.pid} · {result.comm}{note}")
            followed = followed or result.exited is not None
        else:
            refused += 1
            sys.stderr.write(f"refused: pid {result.pid} · {result.reason}\n")
    if survivors or (sent and refused):
        detail = [f"{sent} sinalizado(s)"]
        if survivors:
            detail.append(f"{survivors} sobreviveu(aram) ao sinal")
        if refused:
            detail.append(f"{refused} recusado(s)")
        sys.stderr.write("resultado parcial: " + ", ".join(detail) + "\n")
    if survivors:
        sys.stderr.write("escalada não é automática: se for seguro, repita com "
                         "--confirmar --forcar (SIGKILL)\n")
    if sent and not followed:
        sys.stderr.write("sinal enviado não prova encerramento; a próxima leitura "
                         "confirma o efeito\n")
    if survivors or (sent and refused):
        return EXIT_PARTIAL
    return EXIT_BY_OUTCOME[run.verdict.outcome]


def _cmd_groups(args) -> int:
    if args.forcar and not args.confirmar:
        sys.stderr.write("refused: SIGKILL é mais disruptivo que SIGTERM; use "
                         "--confirmar --forcar\n")
        return EXIT_NEEDS_CONFIRM
    groups = (args.grupo,) if args.grupo else KILLABLE_GROUPS
    from .core.sessions import read_boot_id
    boot = read_boot_id()
    protection = _protection_checker()
    targets = group_targets(scan.collector_for().collect().procs, groups=groups,
                            protected_fn=protection)
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
                         "folego groups --grupo edge --confirmar (SIGTERM) ou "
                         "--confirmar --forcar (SIGKILL)\n")
        return EXIT_OK
    reaper = _reaper()
    results = []
    for target in targets:
        run = _process_selection(target.members, reaper=reaper, boot_id=boot,
                                 force=args.forcar, require_orphan=False, group=target.group)
        if run.result is None or run.verdict.outcome is Outcome.UNKNOWN:
            sys.stderr.write(f"{run.verdict.reason} · operação {run.verdict.operation_id}\n")
            if results and run.verdict.outcome is not Outcome.UNKNOWN:
                return EXIT_PARTIAL
            return EXIT_BY_OUTCOME[run.verdict.outcome]
        results.extend(run.result.results)
    sent = refused = survivors = 0
    followed = False
    for result in results:
        if result.ok:
            sent += 1
            if result.exited is True:
                print(f"encerrado: pid {result.pid} · {result.comm} saiu após o sinal")
            elif result.exited is False:
                survivors += 1
                print(f"sinal enviado: pid {result.pid} · {result.comm} · continua "
                      f"ativo após o sinal")
            else:
                print(f"sinal enviado: pid {result.pid} · {result.comm}")
            followed = followed or result.exited is not None
        else:
            refused += 1
            sys.stderr.write(f"refused: pid {result.pid} · {result.reason}\n")
    if survivors or (sent and refused):
        detail = [f"{sent} sinalizado(s)"]
        if survivors:
            detail.append(f"{survivors} sobreviveu(aram) ao sinal")
        if refused:
            detail.append(f"{refused} recusado(s)")
        sys.stderr.write("resultado parcial: " + ", ".join(detail) + "\n")
    if survivors:
        sys.stderr.write("escalada não é automática: se for seguro, repita com "
                         "--confirmar --forcar (SIGKILL)\n")
    if sent and not followed:
        sys.stderr.write("sinal enviado não prova encerramento; a próxima leitura "
                         "confirma o efeito\n")
    if survivors or (sent and refused) or (sent and any(r.ok and r.exited is None for r in results)):
        return EXIT_PARTIAL
    return EXIT_REFUSED if refused else EXIT_OK


def _process_selection(targets, *, reaper, boot_id, force=False, require_orphan=True, group=""):
    from .actions.orphans.coordinated import execute, plan_for
    plan = plan_for(targets, boot_id=boot_id, force=force, require_orphan=require_orphan, group=group)
    return execute(plan, reaper=reaper, confirm=True, force_confirm=force)


def _cmd_process(args):
    from .orchestration.models import ActionPlan, ValidationError
    from .actions.orphans.coordinated import execute
    try:
        plan = ActionPlan.from_dict(json.loads(args.plan))
    except (ValueError, TypeError, ValidationError) as exc:
        return _emit_gate_refusal(args, "process.signal", f"plano inválido: {exc}")
    if not args.confirmar or plan.params.get("signal") == 9 and not args.forcar:
        return _emit_gate_refusal(args, "process.signal", "sinal exige confirmação; SIGKILL exige --forcar separado", EXIT_NEEDS_CONFIRM)
    run = execute(plan, reaper=_reaper(), confirm=args.confirmar, force_confirm=args.forcar)
    result = run.verdict
    payload = result.to_dict()
    code = EXIT_BY_OUTCOME[result.outcome]
    payload.update(acao="process.signal", ok=result.ok, exit=code)
    if args.json:
        _emit_machine(payload)
    else:
        print(f"{result.operation_id} · {result.outcome} · {result.reason}")
    return code


def _worker(acao: str, tuning_id: str, *, confirmar: bool = False):
    """One tuning action, in a child the terminal can outlive."""
    argv = [sys.executable, "-m", WORKER_MODULE, acao, tuning_id]
    if confirmar:
        argv.append("--confirmar")
    from .safely.jobtemp import prepare_job_environment
    from .process.runner import RunResult
    try:
        env = prepare_job_environment()
    except OSError as exc:
        return RunResult(tuple(argv), refused=f"temporários do filho não comprovados: {exc}")
    return run_isolated(argv, timeout=TUNE_TIMEOUT_S, env=env)


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
    print("\nPara aplicar: folego tune apply <id> --confirmar "
          "(o Edge precisa estar fechado)")
    return EXIT_REFUSED if failures else EXIT_OK


def _report_mutation(res, acao: str, tuning_id: str) -> int:
    label = _tune_label(tuning_id)
    payload = _worker_answer(res)
    if payload is None:
        uncertain = res.timed_out or res.pid is not None
        prefix = "resultado desconhecido" if uncertain else "refused"
        sys.stderr.write(f"{prefix}: {_child_failure(res)}\n")
        return EXIT_UNKNOWN if uncertain else EXIT_REFUSED
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
            print(f"   reverta: folego tune revert {tuning_id} --confirmar")
        return EXIT_OK

    if exit_code == EXIT_NEEDS_CONFIRM:
        sys.stderr.write(f"dry-run: nada foi escrito ({payload.get('reason')}).\n")
        sys.stderr.write(f"        para aplicar: folego tune apply "
                         f"{tuning_id} --confirmar\n")
        return EXIT_NEEDS_CONFIRM
    prefix = "resultado desconhecido" if exit_code == EXIT_UNKNOWN else "refused"
    sys.stderr.write(f"{prefix}: {payload.get('reason')}\n")
    if payload.get("operation_id"):
        sys.stderr.write(f"operação: {payload['operation_id']}\n")
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


def _tmpfs_mounted_volumes(raiz=None) -> list:
    """Os volumes montados que a watch-list aceita, com a recusa dita **uma** vez.

    O filtro vive aqui, e não dentro de uma compreensão: `[v for v in _tmpfs_volumes()
    if v.path in _tmpfs_roots(raiz)]` reavalia `_tmpfs_roots` a cada iteração, e num
    host com `/tmp`, `/run/user/1000` e `/dev/shm` isso escrevia a mesma recusa de
    `--raiz` três vezes no stderr do usuário. Um volume por linha é o acordo; a
    recusa é uma linha só.
    """
    roots = _tmpfs_roots(raiz)
    return [v for v in _tmpfs_volumes() if v.path in roots]


def _scan_tmpfs(raiz=None, prazo: float = 10.0):
    volumes = _tmpfs_mounted_volumes(raiz)
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
    volumes = _tmpfs_mounted_volumes(args.raiz)
    if not volumes:
        return _emit_gate_refusal(
            args, "status", "refused: nenhum volume da watch-list montado "
                            "(nem /tmp, nem /run/user/1000, nem /dev/shm)")
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
    print("Para ver o plano: folego tmpfs plan (dry-run, nada muda)")
    return EXIT_OK


def _tmpfs_reconciles(result) -> bool:
    return result.scanned_entries == len(result.reclaimable) + len(result.protected)


def _cmd_tmpfs_plan(args) -> int:
    result = _build_tmpfs_plan(args.raiz, args.permitir, args.dias, args.prazo)
    if not result.volumes:
        return _emit_gate_refusal(args, "plan",
                                  "refused: nenhum volume da watch-list montado")
    if args.json:
        # o payload sai primeiro: um script precisa ler o plano parcial para saber o
        # que falta; o que combina com a honestidade é o código de saída, não o silêncio
        print(result.to_json())
        if not _tmpfs_reconciles(result):
            sys.stderr.write("aviso: a contagem não fechou — o plano é incompleto\n")
            return EXIT_REFUSED
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
    if not result.scanned_entries:
        # o contrato que a T3 assinou e deixou para cá: `inventory` engole o OSError do
        # `listdir` de propósito (fail-closed: sem item, nada é liberado) e diz que quem
        # apresenta tem de declarar que a lista vazia pode ser permissão, não limpeza
        print(f"\natenção: nenhum item lido em "
              f"{', '.join(v.path for v in result.volumes)} — ilegível (permissão) ou "
              f"de fato vazio; lista vazia aqui não é prova de limpeza")
    if not _tmpfs_reconciles(result):
        sys.stderr.write("aviso: a contagem não fechou — o plano é incompleto\n")
        return EXIT_REFUSED
    print("\nPara liberar um item: folego tmpfs release <caminho> --confirmar "
          "(vai para a SSD e volta com tmpfs restore)")
    return EXIT_OK


_TMPFS_HANDLERS = {
    "status": _cmd_tmpfs_status,
    "plan": _cmd_tmpfs_plan,
}


def _cmd_tmpfs_release(args) -> int:
    # o plano é refeito no ato: só se libera o que a política classificou agora
    plan = _build_tmpfs_plan(prazo=args.prazo)
    item = plan.find(args.target)
    if item is None:
        return _emit_gate_refusal(
            args, "release",
            f"refused: {args.target} não está no plano — só se libera o "
            f"que o plano classificou (folego tmpfs plan)")
    run = tmpfs_coordinated.release(
        coordinator=_tmpfs_coordinator(), confirm=args.confirmar, plan=plan, item=item,
        ledger=_tmpfs_ledger(), dest_root=_tmpfs_dest(), audit=_tmpfs_audit(),
        allowed_roots=_tmpfs_guard_roots(), now=_tmpfs_now())
    if run.result is None:
        # a porta do coordenador fechou antes do ato (trava entre processos, diário
        # corrompido, plano expirado): nada rodou e o diário não ganhou operação
        code = _door_refused(run)
        _emit_failure(args, "release", run, code)
        return code
    uncertain = _emit_uncertain(args, 'release', run)
    if uncertain is not None:
        return uncertain
    result = run.result
    if not result.ok:
        # parcial (clone retido, origem intacta) tem código próprio: parte do
        # efeito existe, e chamar isso de recusa mentiria sobre o byte na SSD
        code = EXIT_NEEDS_CONFIRM if not args.confirmar else \
            EXIT_BY_OUTCOME.get(_outcome_of(run) or Outcome.REFUSED, EXIT_REFUSED)
        sys.stderr.write(f"{result.reason}\n")
        _emit_failure(args, "release", run, code)
        return code
    if _emit_success(args, "release", result.to_dict()):
        return EXIT_OK
    # Contabilidade fina (6b): conteúdo que saiu da RAM, o que o clone ocupa de
    # verdade na SSD (st_blocks) e a variação observada do volume (statvfs) —
    # desconhecida quando o volume não responde, nunca zero por omissão.
    print(f"liberado: {planner.fmt_bytes(result.freed_bytes)} de conteúdo · "
          f"{item.path}")
    print(f"   transferidos: {planner.fmt_bytes(result.bytes)} para {result.stored}")
    print(f"   no SSD:    {planner.fmt_bytes(result.allocated_bytes)} alocados")
    observado = (f"{result.ram_observed_bytes:+d} bytes"
                 if result.ram_observed_bytes is not None else "não medido")
    print(f"   RAM:       variação observada {observado} (statvfs)")
    print(f"   sha256:    {result.sha256}")
    print(f"   id:        {result.entry_id}")
    print(f"   devolve:   folego tmpfs restore {result.entry_id} --confirmar")
    return EXIT_OK


def _cmd_tmpfs_restore(args) -> int:
    # uma porta só: quem manda na confirmação é o portão `if not confirm` no topo do
    # `restore_item` (citado por função para não apodrecer), que já tem a sua mensagem
    # própria. Checar aqui e chamar com `confirm=True` seriam duas decisões para a
    # mesma regra -- e a de cima passaria a ser a única que o resto do código nunca
    # exercita. Confirmado, o ato passa pelo coordenador (intenção antes do efeito).
    run = tmpfs_coordinated.restore(
        coordinator=_tmpfs_coordinator(), confirm=args.confirmar, target=args.target,
        ledger=_tmpfs_ledger(), audit=_tmpfs_audit(),
        allowed_roots=_tmpfs_guard_roots(), now=_tmpfs_now())
    if run.result is None:
        code = _door_refused(run)
        _emit_failure(args, "restore", run, code)
        return code
    uncertain = _emit_uncertain(args, 'restore', run)
    if uncertain is not None:
        return uncertain
    result = run.result
    if not result.ok:
        code = EXIT_NEEDS_CONFIRM if not args.confirmar else \
            EXIT_BY_OUTCOME.get(_outcome_of(run) or Outcome.REFUSED, EXIT_REFUSED)
        sys.stderr.write(f"{result.reason}\n")
        _emit_failure(args, "restore", run, code)
        return code
    if _emit_success(args, "restore", result.to_dict()):
        return EXIT_OK
    print(f"devolvido: {planner.fmt_bytes(result.bytes)} para {result.restored_to}")
    return EXIT_OK


def _cmd_tmpfs_ledger(args) -> int:
    book = _tmpfs_ledger()
    now = _tmpfs_now()
    problems = book.problems()
    if problems:
        # o que não pôde ser lido é nomeado; as mutações ficam recusadas até o
        # reparo (o `_ledger_refusal` dos quatro atos usa a mesma lista)
        for line in problems:
            sys.stderr.write(f"aviso: ledger inconsistente — {line}\n")
        sys.stderr.write("aviso: mutações de tmpfs ficam recusadas até o reparo\n")
    view = book.budget_view(now=now)
    records = [r.to_dict() for r in book.records().values()]
    # as vítimas EFETIVAS do `expire` (idade vencida ou excesso de orçamento): o
    # total retido não diz o que seria apagado, e a confirmação da aba (R07) precisa
    # listar exatamente o que o executor vai remover — nunca "tudo o que está retido"
    victims = book.over_budget(now=now)
    if args.json:
        print(json.dumps({"records": records, "problems": problems, "budget": {
            "retained_bytes": view.retained_bytes, "retained_count": view.retained_count,
            "oldest_days": round(view.oldest_days, 1), "slack_bytes": view.slack_bytes,
            "freed_bytes": view.freed_bytes, "by_volume": view.by_volume,
            "max_bytes": MAX_RETAINED_BYTES, "days": RETENTION_DAYS},
            "victims": [{"entry_id": r.entry_id, "bytes": r.bytes, "src": r.src}
                        for r in victims]},
            ensure_ascii=False))
        return EXIT_OK
    if not records:
        print("ledger vazio: nada retido na SSD")
        return EXIT_OK
    for record in sorted(records, key=lambda r: r["ts"]):
        print(f"{record['entry_id']} · {record['state']} · "
              f"{planner.fmt_bytes(record['bytes'])} · {record['src']}")
    mais_velho = f"{view.oldest_days:.1f}".replace(".", ",")
    print(f"\nretido na SSD: {planner.fmt_bytes(view.retained_bytes)} em "
          f"{view.retained_count} item(ns) · mais velho {mais_velho} d")
    print(f"saiu da RAM e não voltou: {planner.fmt_bytes(view.freed_bytes)} · "
          f"folga do orçamento: {planner.fmt_bytes(view.slack_bytes)} "
          f"de {planner.fmt_bytes(MAX_RETAINED_BYTES)}")
    if view.retained_bytes > MAX_RETAINED_BYTES:
        sys.stderr.write("aviso: a retenção estourou o orçamento — rode "
                         "folego tmpfs expire\n")
    return EXIT_OK


def _cmd_tmpfs_expire(args) -> int:
    run = tmpfs_coordinated.expire(
        coordinator=_tmpfs_coordinator(), confirm=args.confirmar,
        irreversible=args.irreversivel, ledger=_tmpfs_ledger(), audit=_tmpfs_audit(),
        days=args.dias, max_bytes=args.max_bytes,
        allowed_roots=_tmpfs_guard_roots(), now=_tmpfs_now())
    if run.result is None:
        # coordenado só com as duas flags (é o único caminho que muta); aqui só cai
        # a porta fechada (trava/diário), e o ato não rodou
        code = _door_refused(run)
        _emit_failure(args, "expire", run, code)
        return code
    uncertain = _emit_uncertain(args, 'expire', run)
    if uncertain is not None:
        return uncertain
    result = run.result
    if not result.ok:
        # sem as duas flags a recusa é "falta confirmar"; com elas, é o ato recusando
        # (ex.: ledger inconsistente) — códigos diferentes, os dois no stderr
        if not args.confirmar or not args.irreversivel:
            code = EXIT_NEEDS_CONFIRM
        else:
            code = EXIT_BY_OUTCOME.get(_outcome_of(run) or Outcome.REFUSED,
                                       EXIT_REFUSED)
        sys.stderr.write(f"{result.reason}\n")
        _emit_failure(args, "expire", run, code)
        return code
    # erros em vítimas não são sucesso pleno: o veredito do diário diz `parcial`
    # (T13), e a CLI devolve o mesmo desfecho — exit 3 e `outcome` no --json
    outcome = _outcome_of(run) or Outcome.OK
    parcial = outcome is Outcome.PARTIAL
    if parcial:
        _emit_failure(args, "expire", run, EXIT_PARTIAL)
    elif _emit_success(args, "expire", result.to_dict()):
        return EXIT_OK
    if getattr(args, "json", False):
        return EXIT_PARTIAL if parcial else EXIT_OK
    print(result.reason)
    for line in result.errors:
        # a suspeita vai para o stderr, como em todo o resto desta CLI: o stdout do
        # `expire` tem de continuar legível pela aba da T13
        sys.stderr.write(f"aviso: {line}\n")
    if result.freed_bytes:
        print(f"expirado: {planner.fmt_bytes(result.freed_bytes)} da SSD")
    return EXIT_PARTIAL if parcial else EXIT_OK


def _cmd_tmpfs_recover(args) -> int:
    run = tmpfs_coordinated.recover(
        coordinator=_tmpfs_coordinator(), confirm=args.confirmar,
        ledger=_tmpfs_ledger(), audit=_tmpfs_audit(),
        allowed_roots=_tmpfs_guard_roots())
    if run.result is None:
        # só o caminho confirmado é coordenado; aqui só cai a porta fechada
        # (trava/diário), e o ato não rodou
        code = _door_refused(run)
        _emit_failure(args, "recover", run, code)
        return code
    uncertain = _emit_uncertain(args, 'recover', run)
    if uncertain is not None:
        return uncertain
    result = run.result
    if not result.ok and not result.errors:
        # recusa pura (ledger inconsistente, porta): nada rodou, e o "ok" do stdout
        # seria mentira; sai pelo stderr com código de recusa. Erros de um recover
        # confirmado (parcial) continuam no relatório com avisos abaixo.
        code = EXIT_BY_OUTCOME.get(_outcome_of(run) or Outcome.REFUSED, EXIT_REFUSED)
        sys.stderr.write(f"{result.reason}\n")
        _emit_failure(args, "recover", run, code)
        return code
    # clone preservado para decisão manual (ou erro de recover confirmado) é o
    # parcial do veredito: exit 3 e `outcome` no --json, nunca "sucesso" por cima
    # do que ficou pendente
    outcome = _outcome_of(run) or Outcome.OK
    parcial = outcome is Outcome.PARTIAL
    if parcial:
        _emit_failure(args, "recover", run, EXIT_PARTIAL)
    elif _emit_success(args, "recover", result.to_dict()):
        return EXIT_OK
    if getattr(args, "json", False):
        return EXIT_PARTIAL if parcial else EXIT_OK
    print(result.reason)
    for line in result.notes:
        # clone preservado para decisão manual é o recado mais importante daqui:
        # vai no stdout, não como aviso
        print(f"  · {line}")
    for line in result.errors:
        sys.stderr.write(f"aviso: {line}\n")
    return EXIT_PARTIAL if parcial else EXIT_OK


def _cmd_tmpfs_diagnose(args) -> int:
    volumes, entries = _scan_tmpfs(args.raiz, args.prazo)
    if not volumes:
        return _emit_gate_refusal(args, "diagnose", "refused: nenhum volume da watch-list montado")
    worst = max(volumes, key=lambda v: v.used_frac)
    plan = tmpfs_plan.build_plan(volumes, entries, tmpfs_policy((), None, [v.path for v in volumes]),
                                 now=_tmpfs_now())
    items = [item for item in (*plan.protected, *plan.reclaimable) if item.volume == worst.path]
    consumers = tmpfs_diagnosis.diagnose(items)
    if args.json:
        print(json.dumps({"volume": worst.to_dict(), "consumers": [c.to_dict() for c in consumers]},
                         ensure_ascii=False))
        return EXIT_OK
    print(f"{worst.path}: {round(worst.used_frac * 100)}% "
          f"({planner.fmt_bytes(worst.used_bytes)} de {planner.fmt_bytes(worst.total_bytes)})")
    for consumer in consumers:
        print(f"\n· {consumer.path} · {planner.fmt_bytes(consumer.bytes)}")
        for path, size in consumer.largest_files:
            print(f"    arquivo: {path} · {planner.fmt_bytes(size)}")
        for holder in consumer.holders:
            print(f"    aberto por PID {holder.pid} ({holder.name})"
                  + (" · árvore órfã: quem a iniciou já saiu (adotada pelo systemd --user)" if holder.adopted else "")
                  + f"\n      {holder.cmdline}"
                  + (f"\n      raiz da árvore: {holder.tree_root}" if holder.tree_root else ""))
        print(f"    estado no plano: {consumer.reason}")
        if consumer.official_action:
            print(f"    dono: {consumer.owner}\n    caminho oficial: {consumer.official_action}")
    print("\nNada foi alterado. Encerrar o dono preserva dados; o Fôlego não sinaliza sessões alheias.")
    if worst.is_runtime and worst.used_frac >= 0.9:
        print("Espaço insuficiente de forma recorrente: folego tmpfs runtime-size (aumentar o volume)")
    return EXIT_OK


def _cmd_tmpfs_runtime_size(args) -> int:
    location = _tmpfs_runtime_volume()
    if location is None:
        return _emit_gate_refusal(args, "runtime-size", "refused: runtime do usuário não montado como tmpfs")
    choices = runtime_size.options(location.total_bytes, runtime_size.mem_total_bytes())
    configured = runtime_size.configured_size()
    if args.vezes is None or not args.confirmar:
        payload = {"runtime": location.path, "current_bytes": location.total_bytes,
                   "configured_bytes": configured, "options": [o.to_dict() for o in choices]}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
            return EXIT_OK
        print(f"{location.path}: {planner.fmt_bytes(location.total_bytes)} "
              f"(usado {round(location.used_frac * 100)}%)"
              + (f" · drop-in do Fôlego: {configured // runtime_size.MIB} MiB" if configured else ""))
        for option in choices:
            print(f"  {option.multiplier}× → {option.mib} MiB"
                  + ("" if option.allowed else f" · recusado: {option.reason}"))
        print("Aplicar: folego tmpfs runtime-size --vezes N --confirmar (pede a senha de administrador)")
        return EXIT_OK
    option = next(o for o in choices if o.multiplier == args.vezes)
    if not option.allowed:
        return _emit_gate_refusal(args, "runtime-size", f"refused: {option.reason}")
    command = runtime_size.apply_command(option.bytes, runtime=location.path)
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    if result.returncode:
        return _emit_gate_refusal(args, "runtime-size",
                                  f"refused: pkexec retornou {result.returncode}: {(result.stderr or '').strip()[-300:]}")
    after = _tmpfs_runtime_volume()
    print(json.dumps({"runtime": location.path, "before_bytes": location.total_bytes,
                      "after_bytes": after.total_bytes if after else None,
                      "dropin": runtime_size.DROPIN_PATH}, ensure_ascii=False))
    return EXIT_OK


def _tmpfs_runtime_volume():
    return next((v for v in _tmpfs_volumes() if v.is_runtime), None)


_TMPFS_HANDLERS.update({
    "diagnose": _cmd_tmpfs_diagnose,
    "runtime-size": _cmd_tmpfs_runtime_size,
    "release": _cmd_tmpfs_release,
    "restore": _cmd_tmpfs_restore,
    "ledger": _cmd_tmpfs_ledger,
    "expire": _cmd_tmpfs_expire,
    "recover": _cmd_tmpfs_recover,
})


_TUNE_HANDLERS = {
    "status": _cmd_tune_status,
    "apply": _cmd_tune_apply,
    "revert": _cmd_tune_revert,
}


def _dispatch(ns, argv) -> int:
    """A escolha do handler, separada do `main` para o protocolo de erro envolvê-la."""
    if ns.command is None:
        return run_gui(argv)
    if ns.command == "orphans":
        return _cmd_orphans(ns)
    if ns.command == "groups":
        return _cmd_groups(ns)
    if ns.command == "process":
        return _cmd_process(ns)
    if ns.command == "session":
        return _cmd_session(ns)
    if ns.command == "exclusions":
        return _cmd_exclusions(ns)
    if ns.command == "grant":
        return _cmd_grant(ns)
    if ns.command == "operation":
        return _cmd_operation(ns)
    if ns.command == "automation":
        return _cmd_automation(ns)
    if ns.command == "ecosystem":
        return _cmd_ecosystem(ns)
    if ns.command == "doctor":
        return _cmd_doctor(ns)
    if ns.command == "migrate":
        return _cmd_migrate(ns)
    if ns.command == "logs":
        return _cmd_logs(ns)
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
            f"usage: folego [disk plan|quarantine|restore|purge|list|tmp] "
            f"[orphans] [groups] [session ...] [exclusions ...] "
            f"[grant list|add|revoke] [automation status|mode|preset|pause|resume|decisions] "
            f"[ecosystem] [doctor] [migrate] [logs status|rotate|archives] "
            f"[tune status|apply|revert] "
            f"[tmpfs status|plan|release|restore|ledger|expire]\n")
        return EXIT_NEEDS_CONFIRM
    return handler(ns)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        ns = parser.parse_args(args)
    except SystemExit as exit_request:
        # `--help` sai 0; invocação inválida mantém o 2 do argparse (nada mutou —
        # o desfecho é de uso, e o erro do argparse já foi para o stderr)
        code = exit_request.code
        return int(code if code is not None else EXIT_NEEDS_CONFIRM)
    try:
        return _dispatch(ns, args)
    except KeyboardInterrupt:
        # entrega 7: interromper no meio não prova ausência de efeitos — o ato
        # pode ter começado e o diário tem a intenção; cancelamento (6) é
        # reservado para quem de fato cancela antes de efeitos
        return _interrupted(ns)
    except Exception as exc:  # noqa: BLE001 — desfecho de protocolo, não traceback
        return _failed(ns, exc)
