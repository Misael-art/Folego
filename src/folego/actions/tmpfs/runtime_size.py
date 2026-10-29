"""Journaled runtime resizing and read-only evidence for explicit reconciliation."""
import os
import re
import stat
import subprocess
from pathlib import Path

from ...core import runtime_size as sizes
from ...core.sessions import read_boot_id
from ...orchestration.models import ActionPlan, ActionResult, Outcome, ResourceIdentity

ACTION = "tmpfs.runtime-size"


def identity(volume):
    if volume is None or volume.quality != "ok" or volume.total_bytes <= 0:
        raise ValueError("capacidade atual do runtime não comprovada")
    if volume.path != f"/run/user/{os.getuid()}":
        raise ValueError("runtime fora do UID atual")
    info = os.lstat(volume.path)
    boot = read_boot_id()
    if (not boot or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError("identidade privada do runtime não comprovada")
    return ResourceIdentity("volume", volume.path,
                            {"dev": info.st_dev, "ino": info.st_ino, "boot_id": boot})


def plan_for(volume, size_bytes):
    return ActionPlan(ACTION, identity(volume),
                      {"before_bytes": volume.total_bytes, "size_bytes": size_bytes})


def _result(plan, outcome, reason, **effects):
    return ActionResult(ACTION, outcome, plan.operation_id, target_key=plan.target.key,
                        reason=reason, effects=effects)


def pending(journal, target):
    records, problems = journal.load()
    if problems:
        raise ValueError("diário inconsistente: " + "; ".join(problems))
    intents, results = {}, {}
    for row in records:
        if row.kind == "intent" and row.plan.action == ACTION and row.plan.target.key == target:
            intents[row.operation_id] = row.plan
        elif row.kind == "result":
            results[row.operation_id] = row.result
    return [key for key in intents if key not in results or results[key].outcome == Outcome.UNKNOWN]


def receipt(operation_id):
    if not re.fullmatch(r"[a-f0-9]{32}", operation_id):
        raise ValueError("ID de operação inválido")
    path = Path(f"{sizes.DROPIN_PATH}.result-{operation_id}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise ValueError("recibo privilegiado não comprovado")
        fields = os.read(fd, 256).decode("ascii").split()
    finally:
        os.close(fd)
    if (len(fields) != 5 or fields[0] != operation_id or
            not all(value.isdigit() for value in fields[1:]) or
            fields[2] not in ("0", "1") or fields[3] not in ("0", "1")):
        raise ValueError("recibo privilegiado inválido")
    return tuple(map(int, fields[1:]))


def observe(plan, volume_fn, receipt_fn=receipt):
    try:
        code, configured, mounted, mib = receipt_fn(plan.operation_id)
        after = volume_fn()
        if identity(after) != plan.target or mib * sizes.MIB != plan.params["size_bytes"]:
            raise ValueError("identidade/tamanho do recibo divergente do plano")
        configured_bytes = sizes.configured_size()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _result(plan, Outcome.UNKNOWN, f"resultado não comprovado: {exc}; não repetir")
    effects = {"before_bytes": plan.params["before_bytes"], "after_bytes": after.total_bytes,
               "configured_bytes": configured_bytes, "dropin": sizes.DROPIN_PATH,
               "previous_config": f"{sizes.DROPIN_PATH}.before-{plan.operation_id}"}
    if (code == 0 and configured and mounted and after.total_bytes == mib * sizes.MIB
            and configured_bytes == mib * sizes.MIB):
        return _result(plan, Outcome.OK, "configuração e montagem verificadas", **effects)
    if configured:
        return _result(plan, Outcome.PARTIAL,
                       "configuração persistente alterada; remontagem não concluída/verificada; "
                       "configuração anterior preservada se existia", **effects)
    return _result(plan, Outcome.REFUSED, "comando privilegiado terminou antes da alteração", **effects)


def apply(plan, *, coordinator, volume_fn, run=subprocess.run, receipt_fn=receipt):
    if (plan.action != ACTION or plan.target.kind != "volume" or
            not re.fullmatch(r"[a-f0-9]{32}", plan.operation_id) or
            set(plan.params) != {"before_bytes", "size_bytes"} or
            any(type(value) is not int or value <= 0 for value in plan.params.values())):
        raise ValueError("plano de redimensionamento inválido")
    def execute(confirmed):
        unresolved = [key for key in pending(coordinator.journal, confirmed.target.key)
                      if key != confirmed.operation_id]
        if unresolved:
            return _result(confirmed, Outcome.REFUSED,
                           f"reconcilie a operação {unresolved[0]} antes de outra alteração")
        current = volume_fn()
        size = confirmed.params.get("size_bytes")
        if (confirmed.action != ACTION or identity(current) != confirmed.target or
                current.total_bytes != confirmed.params.get("before_bytes") or
                type(size) is not int or size < 64 * sizes.MIB or size % sizes.MIB or
                size > int(sizes.mem_total_bytes() * sizes.MAX_RAM_FRACTION)):
            return _result(confirmed, Outcome.REFUSED, "runtime/plano mudou; revise as opções")
        detail = confirmed.target.detail
        command = sizes.apply_command(size, runtime=current.path, operation_id=confirmed.operation_id,
                                      expected_identity=f"{detail['dev']}:{detail['ino']}",
                                      before_bytes=current.total_bytes)
        try:
            completed = run(command, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, timeout=175)
        except OSError as exc:
            return _result(confirmed, Outcome.REFUSED, f"comando não iniciado: {exc}")
        except subprocess.TimeoutExpired:
            return _result(confirmed, Outcome.UNKNOWN,
                           "prazo da autenticação/execução excedido; não repetir antes de reconciliar")
        observed = observe(confirmed, volume_fn, receipt_fn)
        # pkexec's documented cancellation/not-authorized statuses precede the shell.
        if (observed.outcome == Outcome.UNKNOWN and completed.returncode in (126, 127)
                and not completed.stdout.strip()):
            return _result(confirmed, Outcome.REFUSED, "autenticação cancelada ou não autorizada")
        return observed

    return coordinator.run(plan, execute)


def reconcile(operation_id, *, coordinator, volume_fn, receipt_fn=receipt):
    with coordinator.lock(wait=5):
        state = coordinator.journal.state_of(operation_id)
        if state is None or state.intent is None or state.intent.action != ACTION:
            raise ValueError("operação de redimensionamento não encontrada")
        if state.result is not None and state.result.outcome != Outcome.UNKNOWN:
            return state.result
        result = observe(state.intent, volume_fn, receipt_fn)
        if result.outcome != Outcome.UNKNOWN:
            coordinator.journal.append_result(result)
        return result
