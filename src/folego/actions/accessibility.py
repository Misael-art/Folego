"""Input supervision independent of any third-party project or graphical window.

Native repair is deliberately additive: enable one identified KWin device. No
grabs, key/audio capture, driver resets, profile replacement or process signals.
"""
import json
import math
import os
from pathlib import Path
import stat
import time
import uuid

from .. import paths
from ..adapters.accessibility import NativeInput, ProbeError, bounded_read, DEVICE_ROOT, DEVICE_IFACE, PROPERTIES
from ..core.accessibility import SCHEMA, STALE_SECONDS, ACTION
from ..core.sessions import read_boot_id
from ..orchestration import Coordinator
from ..orchestration.models import ActionPlan, ActionResult, ResourceIdentity, Outcome
from ..safely.atomicfile import write_atomic

def directory():
    return paths.state_dir() / "accessibility"


def private_path(path, *, create=False):
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError("estado de acessibilidade simbólico; preservado")
    if create:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        parent = path.parent.stat()
    except FileNotFoundError:
        return
    if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o022:
        raise ValueError("diretório de estado não pertence ao usuário ou permite escrita alheia")


def read_object(path):
    private_path(path)
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError("estado não é arquivo privado do usuário")
    value = json.loads(bounded_read(path, 65536))
    if not isinstance(value, dict) or type(value.get("schema")) is not int or value.get("schema") != SCHEMA:
        raise ValueError("schema de acessibilidade desconhecido")
    return value


def save_object(path, value):
    private_path(path, create=True)
    write_atomic(path, json.dumps(value, ensure_ascii=False).encode(), mode=0o600)


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root else directory()
        self.path = self.root / "policy.json"

    def read(self):
        value = read_object(self.path)
        if value is None:
            return {"schema": SCHEMA, "enabled": False, "baseline": {}, "attempts": [], "circuit": ""}
        if (type(value.get("enabled")) is not bool or not isinstance(value.get("baseline"), dict)
                or len(value["baseline"]) > 128
                or not isinstance(value.get("attempts"), list) or len(value["attempts"]) > 64
                or not isinstance(value.get("circuit"), str)):
            raise ValueError("política ilegível; automação bloqueada")
        for key, device in value["baseline"].items():
            if (not isinstance(key, str) or not isinstance(device, dict) or device.get("enabled") is not True
                    or not isinstance(device.get("name"), str)):
                raise ValueError("baseline desconhecido; preservado")
        for attempt in value["attempts"]:
            if (not isinstance(attempt, dict) or type(attempt.get("ts")) not in (int, float)
                    or not math.isfinite(attempt["ts"]) or attempt["ts"] <= 0
                    or not isinstance(attempt.get("operation_id"), str)):
                raise ValueError("histórico de tentativas inválido")
        return value

    def save(self, value):
        save_object(self.path, value)


def _alive(owner, proc_root="/proc"):
    if not isinstance(owner, dict) or set(owner) != {"pid", "start_ticks", "boot_id"}:
        return None
    if (type(owner["pid"]) is not int or owner["pid"] <= 1 or type(owner["start_ticks"]) is not int
            or owner["start_ticks"] < 0 or not isinstance(owner["boot_id"], str)):
        return None
    try:
        uuid.UUID(owner["boot_id"])
    except ValueError:
        return None
    boot = read_boot_id(proc_root)
    if not boot:
        return None
    if owner["boot_id"] != boot:
        return False
    try:
        path = Path(proc_root) / str(owner["pid"]) / "stat"
        fields = bounded_read(path, 8192).rsplit(")", 1)[1].split()
        return fields[0] != "Z" and int(fields[19]) == owner["start_ticks"]
    except FileNotFoundError:
        return False
    except (OSError, ValueError, IndexError, ProbeError):
        return None


def lease_blockers(root=None, *, ignore=None):
    deadline = time.monotonic() + 1
    root = Path(root) if root else directory()
    folder = root / "leases"
    private_path(folder)
    if not folder.exists():
        return []
    info = folder.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        return ["diretório de leases sem propriedade/permissões privadas"]
    blockers = []
    with os.scandir(folder) as entries:
        names = []
        for entry in entries:
            names.append(entry.name)
            if len(names) > 32:
                return ["inventário de leases excede orçamento"]
    for name in names:
        if time.monotonic() > deadline:
            return ["prazo de leitura das propriedades excedido"]
        if name == ignore:
            continue
        value = read_object(folder / name)
        if value is None:
            blockers.append("lease mudou durante a leitura")
            continue
        if (not isinstance(value.get("provider"), str) or value.get("resource") != "input"
                or value.get("state") not in ("using", "repairing", "released")):
            blockers.append("lease com contrato desconhecido")
            continue
        if value["state"] == "released":
            continue
        alive = _alive(value.get("owner"))
        children = value.get("children", [])
        if not isinstance(children, list) or len(children) > 64:
            alive = None
        else:
            states = [alive]
            for child in children:
                if time.monotonic() > deadline:
                    return ["prazo de verificação de filhos excedido"]
                states.append(_alive(child))
            alive = True if True in states else None if None in states else False
        if alive is False and value["state"] == "using":
            continue
        # A dead repairer may have left effects. Only explicit reconciliation
        # releases this lease; age or missing PID never proves repair completion.
        blockers.append(f"{value['provider']}: {value['state']}" if alive is True else
                        f"{value['provider']}: resultado/propriedade desconhecido")
    return blockers


def publish_lease(provider, pid, state, *, store=None, coordinator=None, child_pids=()):
    store, coordinator = store or Store(), coordinator or Coordinator()
    if (state not in ("using", "repairing", "released") or not provider or len(provider) > 80
            or len(child_pids) > 64):
        raise ValueError("lease inválido")
    proc = Path("/proc") / str(pid)
    if type(pid) is not int or pid <= 1 or proc.stat().st_uid != os.getuid():
        raise ValueError("proprietário precisa ser processo do usuário")
    fields = bounded_read(proc / "stat", 8192).rsplit(")", 1)[1].split()
    owner = {"pid": pid, "start_ticks": int(fields[19]), "boot_id": read_boot_id()}
    if _alive(owner) is not True:
        raise ValueError("identidade do proprietário não comprovada")
    children = []
    for child in child_pids:
        path = Path("/proc") / str(child)
        if type(child) is not int or child <= 1 or path.stat().st_uid != os.getuid():
            raise ValueError("filho de outro usuário ou identidade inválida")
        parts = bounded_read(path / "stat", 8192).rsplit(")", 1)[1].split()
        children.append({"pid": child, "start_ticks": int(parts[19]), "boot_id": owner["boot_id"]})
    with coordinator.lock(wait=.2):
        key = uuid.uuid5(uuid.NAMESPACE_URL, "folego-input:" + provider).hex
        path = store.root / "leases" / (key + ".json")
        previous = read_object(path)
        if previous is not None:
            if (previous.get("provider") != provider or previous.get("resource") != "input"
                    or previous.get("state") not in ("using", "repairing", "released")
                    or not isinstance(previous.get("children", []), list)):
                raise ValueError("lease anterior desconhecido; preservado")
            old_owners = [previous.get("owner"), *previous.get("children", [])]
            if previous.get("owner") != owner and previous["state"] != "released":
                if previous["state"] == "repairing" or not all(_alive(item) is False for item in old_owners):
                    raise ValueError("outro proprietário/resultado anterior ainda ocupa este slot")
            if previous.get("owner") == owner:
                retained = [item for item in previous.get("children", []) if _alive(item) is not False]
                for item in retained:
                    if item not in children:
                        children.append(item)
        if state == "released" and (previous is None or any(_alive(item) is not False for item in children)):
            raise ValueError("lease ausente ou filhos ainda ativos/desconhecidos; encerramento recusado")
        if len(children) > 64:
            raise ValueError("filhos excedem orçamento; lease anterior preservado")
        if state != "released" and lease_blockers(store.root, ignore=path.name):
            raise ValueError("outro proprietário ocupa a entrada")
        value = {"schema": SCHEMA, "provider": provider, "resource": "input", "state": state,
                 "owner": owner, "children": children, "lease_id": key}
        save_object(path, value)
        return value


def reconcile_lease(key, *, confirmed=False, supervisor=None):
    supervisor = supervisor or Supervisor()
    import re
    if not confirmed or not re.fullmatch(r"[a-f0-9]{32}", key):
        raise ValueError("ID/confirmacão de reconciliação inválido")
    with supervisor.coordinator.lock(wait=.2):
        path = supervisor.store.root / "leases" / (key + ".json")
        value = read_object(path)
        if value is None:
            raise ValueError("lease não encontrado")
        owners = [value.get("owner"), *value.get("children", [])]
        if not all(_alive(owner) is False for owner in owners):
            raise ValueError("proprietário/filhos ainda vivos ou desconhecidos")
        report = supervisor.native.collect()
        devices = [device for device in report["devices"] if device["repairable"]]
        if (not fresh(report) or report["errors"] or not devices
                or not all(device["enabled"] is True for device in devices)):
            raise ValueError("configuração atual não comprovada; lease preservado")
        value.update(state="released", reconciled_at=time.time())
        save_object(path, value)
        return {"ok": True, "reason": "proprietários encerrados e configuração habilitada observada; sem reaplicar"}


def fresh(report):
    return (type(report.get("schema")) is int and report.get("schema") == SCHEMA and type(report.get("mono")) in (int, float)
            and 0 <= time.monotonic() - report["mono"] <= STALE_SECONDS
            and isinstance(report.get("boot_id"), str) and bool(report["boot_id"]))


def plans(report, *, automatic=False, baseline=None):
    if not fresh(report) or report.get("backend") != "kwin" or report.get("blockers") or report.get("errors"):
        return []
    result = []
    for device in report["devices"]:
        if (device["enabled"] is not False or not device["repairable"] or
                (automatic and device["key"] not in (baseline or {}))):
            continue
        result.append(ActionPlan(ACTION, ResourceIdentity.entry(device["key"]),
            {"event": device["event"], "name": device["name"], "service_owner": report["service_owner"],
             "boot_id": report["boot_id"], "automatic": automatic},
            notes=("Reabilitar somente este dispositivo no KWin; teste físico permanece necessário.",)))
    return result


def unresolved(journal):
    records, errors = journal.load()
    if errors:
        raise ValueError("diário inconsistente; nenhuma ação autorizada")
    pending = {}
    for row in records:
        if row.kind == "intent" and row.plan.action == ACTION:
            pending[row.operation_id] = True
        elif row.kind == "result" and row.result.action == ACTION:
            pending[row.operation_id] = row.result.outcome == Outcome.UNKNOWN
    return [key for key, value in pending.items() if value]


class Supervisor:
    def __init__(self, *, native=None, store=None, coordinator=None, now=time.time):
        self.native, self.store = native or NativeInput(), store or Store()
        self.coordinator, self.now = coordinator or Coordinator(), now

    def inspect(self):
        report = self.native.collect()
        report["plans"] = []
        try:
            report["blockers"].extend(lease_blockers(self.store.root))
            policy = self.store.read()
            report["policy"] = {key: policy[key] for key in ("enabled", "circuit")}
            report["baseline_count"] = len(policy["baseline"])
            report["pending_operations"] = unresolved(self.coordinator.journal)
            if report["pending_operations"]:
                report["blockers"].append("operação desconhecida; verificar antes de repetir")
            report["plans"] = [plan.to_dict() for plan in plans(report)]
        except (OSError, ValueError, ProbeError) as exc:
            report.update(policy={"enabled": False, "circuit": "estado ilegível"}, pending_operations=[])
            report["blockers"].append(str(exc))
        try:
            watched = read_object(self.store.root / "watch-status.json")
            recent = (watched is not None and type(watched.get("checked_at")) in (int, float)
                      and 0 <= self.now() - watched["checked_at"] <= 30 and _alive(watched.get("owner")) is True)
            report["watcher"] = {"state": "observed" if recent else "not-observed" if watched is None else "unknown",
                                 "result": watched.get("result", {}) if recent else {}}
        except (OSError, ValueError, ProbeError):
            report["watcher"] = {"state": "unknown", "result": {}}
        report["state"] = ("unknown" if report["errors"] else "waiting" if report["blockers"] else
                           "degraded" if any(card["state"] in ("degraded", "unavailable", "unknown")
                                             for card in report["cards"]) else "observed")
        return report

    def configure(self, *, enabled=None, capture=False, rearm=False):
        report = self.native.collect() if capture or rearm else None
        with self.coordinator.lock(wait=.2):
            policy = self.store.read()
            if capture or rearm:
                if not fresh(report) or report["blockers"] or lease_blockers(self.store.root):
                    raise ValueError("leitura incompleta/antiga; baseline preservado")
                if unresolved(self.coordinator.journal):
                    raise ValueError("operação pendente exige reconciliação antes de registrar/rearmar")
                eligible = [device for device in report["devices"] if device["repairable"]]
                if not eligible:
                    raise ValueError("backend/dispositivos reparáveis não comprovados")
                if any(device["enabled"] is not True for device in eligible):
                    raise ValueError("dispositivos desabilitados não viram baseline saudável")
                if capture:
                    baseline = {**policy["baseline"], **{device["key"]: {"enabled": True, "name": device["name"]}
                                                          for device in eligible}}
                    if len(baseline) > 128:
                        raise ValueError("configuração retida excede orçamento; revisão necessária, nada descartado")
                    policy["baseline"] = baseline
                if rearm:
                    policy["circuit"] = ""
                    policy["attempts"] = []
            if enabled is not None:
                policy["enabled"] = bool(enabled)
            self.store.save(policy)
            return {"ok": True, "enabled": policy["enabled"], "baseline_count": len(policy["baseline"]),
                    "circuit": policy["circuit"]}

    def repair(self, plan, *, confirm=False):
        def verdict(outcome, reason, **effects):
            return ActionResult(ACTION, outcome, plan.operation_id, reason=reason,
                                target_key=plan.target.key, effects=effects)
        if (not confirm or plan.action != ACTION or plan.target.kind != "entry" or
                set(plan.params) != {"event", "name", "service_owner", "boot_id", "automatic"} or
                type(plan.params["automatic"]) is not bool):
            return verdict(Outcome.REFUSED, "plano/confirmacão inválido")
        def execute(_):
            report = self.native.collect()
            blockers = report["blockers"] + lease_blockers(self.store.root)
            pending = [key for key in unresolved(self.coordinator.journal) if key != plan.operation_id]
            if blockers or pending or not fresh(report):
                return verdict(Outcome.REFUSED, "; ".join(blockers) or "estado antigo/operação pendente")
            policy = self.store.read()
            if policy["circuit"]:
                return verdict(Outcome.REFUSED, "disjuntor aberto: " + policy["circuit"])
            if plan.params["automatic"] and (not policy["enabled"] or plan.target.key not in policy["baseline"]):
                return verdict(Outcome.REFUSED, "automação desabilitada ou baseline não cobre dispositivo")
            matching = next((p for p in plans(report, automatic=plan.params["automatic"], baseline=policy["baseline"])
                             if p.target == plan.target and dict(p.params) == dict(plan.params)), None)
            if matching is None:
                return verdict(Outcome.REFUSED, "dispositivo/sessão mudou; revisar o mesmo alvo")
            now = self.now()
            attempts = [row for row in policy["attempts"] if 0 <= now - row["ts"] < 3600]
            if len(attempts) != len(policy["attempts"]) and any(row["ts"] > now for row in policy["attempts"]):
                return verdict(Outcome.REFUSED, "relógio regressou; orçamento não comprovado")
            if len(attempts) >= 3 or (attempts and now - attempts[-1]["ts"] < 60):
                return verdict(Outcome.REFUSED, "orçamento/cooldown de reparo protege contra oscilação")
            attempts.append({"ts": now, "operation_id": plan.operation_id})
            policy["attempts"] = attempts
            self.store.save(policy)  # Durable budget before effect; journal intent already exists.
            try:
                self.native.deadline = self.native.clock() + 2
                self.native.call([self.native.qdbus, plan.params["service_owner"],
                    DEVICE_ROOT + "/" + plan.params["event"], PROPERTIES + ".Set", DEVICE_IFACE, "enabled", "true"])
                after = self.native.collect()
                device = next((d for d in after["devices"] if d["key"] == plan.target.key), None)
                if (not fresh(after) or after["errors"] or device is None or device["enabled"] is not True
                        or after["boot_id"] != plan.params["boot_id"] or
                        after["service_owner"] != plan.params["service_owner"]):
                    policy["circuit"] = "efeito não verificado; reconciliação necessária"
                    self.store.save(policy)
                    return verdict(Outcome.UNKNOWN, policy["circuit"])
                return verdict(Outcome.OK, "habilitado no compositor; funcionamento físico não testado",
                               device=plan.target.key, enabled=True)
            except (ProbeError, OSError) as exc:
                policy["circuit"] = "resposta perdida; não repetir antes de verificar"
                self.store.save(policy)
                return verdict(Outcome.UNKNOWN, str(exc))
        return self.coordinator.run(plan, execute, wait=.2)

    def reconcile(self, operation_id):
        with self.coordinator.lock(wait=.2):
            state = self.coordinator.journal.state_of(operation_id)
            if state is None or state.intent is None or state.intent.action != ACTION:
                raise ValueError("operação de entrada não encontrada")
            if state.result and state.result.outcome != Outcome.UNKNOWN:
                return state.result
            report = self.native.collect()
            device = next((d for d in report["devices"] if d["key"] == state.intent.target.key), None)
            ok = fresh(report) and not report["errors"] and device is not None and device["enabled"] is True
            result = ActionResult(ACTION, Outcome.OK if ok else Outcome.UNKNOWN, operation_id,
                target_key=state.intent.target.key,
                reason="estado atual habilitado; nenhuma ação reaplicada" if ok else "resultado ainda não comprovado")
            if ok:
                self.coordinator.journal.append_result(result)
            return result

    def tick(self):
        report = self.inspect()
        policy = self.store.read()
        if not policy["enabled"] or policy["circuit"] or report["blockers"]:
            return {"ok": True, "state": "waiting" if report["blockers"] else "paused",
                    "reason": "; ".join(report["blockers"]) or policy["circuit"] or "automação desabilitada"}
        eligible = [device for device in report["devices"] if device["repairable"]]
        new = [device for device in eligible if device["key"] not in policy["baseline"]]
        if new and all(device["enabled"] is True for device in eligible):
            self.configure(capture=True)
            return {"ok": True, "state": "observing", "reason": "dispositivos habilitados registrados; anteriores preservados"}
        if not policy["baseline"]:
            return {"ok": True, "state": "observing", "reason": "sem baseline saudável ou backend de reparo; somente observação"}
        candidates = plans(report, automatic=True, baseline=policy["baseline"])
        if not candidates:
            return {"ok": True, "state": "observing", "reason": "nenhum reparo nativo autorizado necessário"}
        now = self.now()
        attempts = [row for row in policy["attempts"] if 0 <= now - row["ts"] < 3600]
        if any(row["ts"] > now for row in policy["attempts"]):
            return {"ok": False, "outcome": "recusa", "state": "waiting", "reason": "relógio regressou"}
        if len(attempts) >= 3:
            with self.coordinator.lock(wait=.2):
                current = self.store.read()
                current["circuit"] = "reparos repetidos; investigar aplicação que desfaz a configuração"
                self.store.save(current)
            return {"ok": False, "outcome": "recusa", "state": "paused", "reason": current["circuit"]}
        if attempts and now - attempts[-1]["ts"] < 60:
            return {"ok": False, "outcome": "recusa", "state": "cooldown", "reason": "aguardando intervalo de reparo"}
        return self.repair(candidates[0], confirm=True).to_dict()
