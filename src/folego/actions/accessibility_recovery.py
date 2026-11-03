"""User-requested capability recovery on the existing coordinator and journal."""
import os
from pathlib import Path
import time
import uuid

from .accessibility import (fresh, lease_blockers, read_object, save_object, _alive, unresolved)
from ..adapters.accessibility import ProbeError
from ..adapters.accessibility_recovery import DesktopRecovery, UncertainEffect
from ..core.accessibility import LABELS
from ..core.sessions import read_boot_id
from ..orchestration.models import ActionPlan, ActionResult, ResourceIdentity, Outcome

ACTION = "accessibility.activate"
SAVE_ACTION = "accessibility.save-profile"
ORDER = ("keyboard", "pointer", "touchpad", "virtual-keyboard", "touch", "gamepad", "audio", "microphone")
INPUTS = frozenset(ORDER) - {"audio", "microphone"}
PEER_WAIT = "PhaseZero ativo ou sem estado comprovado; aguardando executor existente"


class Recovery:
    def __init__(self, supervisor, *, backend=None):
        self.supervisor = supervisor
        self.backend = backend or DesktopRecovery(supervisor.native)

    def prepare(self, capability, *, save=False):
        if capability not in (*LABELS, "all"):
            raise ValueError("capacidade desconhecida")
        if save and capability != "all":
            raise ValueError("perfil persistente exige revisão de todas as capacidades")
        scope = list(ORDER) if capability == "all" else [capability]
        report = self.supervisor.native.collect()
        peer = self._peer(scope)
        params = {"capabilities": scope, "boot_id": report["boot_id"],
                  "service_owner": report["service_owner"], "peer": peer,
                  "devices": self._devices(report, scope),
                  "audio_targets": self.backend.audio_targets(scope)}
        return ActionPlan(SAVE_ACTION if save else ACTION, ResourceIdentity.entry(capability), params,
            notes=("Ação manual: habilitar e verificar cada capacidade; nunca desabilitar entradas.",
                   "Provedor externo registrado, quando presente, será solicitado e revalidado por hash.",
                   "Tela FTS ausente pode exigir autenticação para o reparador do proprietário; sem reset USB.",
                   "Áudio sem mute; volume zero sobe a 25%; volumes existentes são preservados.",
                   "Verde confirma configuração no sistema; funcionamento físico exige teste."))

    def _peer(self, scope):
        if not any(key in INPUTS for key in scope):
            return None
        try:
            return self.backend.peer()
        except (OSError, ValueError, ProbeError) as exc:
            return {"error": str(exc)}

    @staticmethod
    def _devices(report, scope):
        kinds = set(scope) | ({"pointer"} if "touchpad" in scope else set())
        return [{k: d[k] for k in ("key", "event", "name", "stable")} for d in report["devices"]
                if kinds.intersection(d["kinds"])]

    def _receipt(self, key):
        if not isinstance(key, str) or len(key) != 32:
            raise ValueError("ID de operação inválido")
        int(key, 16)
        return self.supervisor.store.root / "manual-operations" / (key + ".json")

    def _pending(self, key):
        return [i for i in unresolved(self.supervisor.coordinator.journal) if i != key]

    def execute(self, plan, *, confirmed=False):
        expected = ("capabilities", "boot_id", "service_owner", "peer", "devices", "audio_targets")
        if (not confirmed or plan.action not in (ACTION, SAVE_ACTION) or plan.target.kind != "entry"
                or plan.target.key not in (*LABELS, "all") or set(plan.params) != set(expected)
                or list(plan.params["capabilities"]) != (list(ORDER) if plan.target.key == "all" else [plan.target.key])):
            return ActionResult(plan.action, Outcome.REFUSED, plan.operation_id, target_key=plan.target.key,
                                reason="plano manual/confirmacão inválido")
        def run(_):
            report = self.supervisor.native.collect()
            if (not fresh(report) or not report["boot_id"] or report["boot_id"] != plan.params["boot_id"]
                    or report["service_owner"] != plan.params["service_owner"]
                    or self._devices(report, plan.params["capabilities"]) != list(plan.to_dict()["params"]["devices"])):
                return self._result(plan, [], Outcome.REFUSED, "dispositivos/sessão mudaram; verificar antes de habilitar")
            # Re-derive the owner command, never execute a command from the plan.
            peer = self._peer(plan.params["capabilities"])
            if peer != plan.to_dict()["params"]["peer"]:
                return self._result(plan, [], Outcome.REFUSED, "responsável registrado mudou; nenhuma rotina executada")
            keyboard_only = plan.action == ACTION and plan.target.key == "virtual-keyboard"
            if self._pending(plan.operation_id) and not keyboard_only:
                return self._result(plan, [], Outcome.REFUSED, "operação anterior incerta; consultar seu código sem repetir")
            receipt = {"schema": 1, "plan": plan.to_dict(), "rows": [], "complete": False,
                       "owner": self._owner(), "started_at": time.time()}
            save_object(self._receipt(plan.operation_id), receipt)
            if plan.action == SAVE_ACTION:
                result = self._save_profile(plan, report, peer)
                receipt.update(complete=True, result=result.to_dict())
                save_object(self._receipt(plan.operation_id), receipt)
                return result
            rows, delegated = [], False
            input_block = list(lease_blockers(self.supervisor.store.root))
            if peer and peer.get("error"):
                input_block.append(peer["error"])
            usable_peer = peer if peer and not peer.get("error") else None
            if keyboard_only:
                # Explicit opening touches only the current session's IM panel.
                # It remains an escape path while a hardware repair is unknown.
                input_block = []
                usable_peer = None
            if not keyboard_only:
                input_block.extend(v for v in report["blockers"] if not (usable_peer and v == PEER_WAIT))
            if not input_block and usable_peer and any(k in INPUTS for k in plan.params["capabilities"]):
                try:
                    self.backend.peer_idle(usable_peer)
                    warning = self.backend.delegate(usable_peer)
                    if warning:
                        input_block.append(warning)
                    else:
                        delegated = True
                    report = self.supervisor.native.collect()
                except (ValueError, ProbeError) as exc:
                    input_block.append(str(exc))
            for key in plan.params["capabilities"]:
                receipt["current"] = key
                save_object(self._receipt(plan.operation_id), receipt)
                try:
                    if key in INPUTS and not input_block:
                        current = self.supervisor.native.collect()
                        if (not fresh(current) or current["boot_id"] != plan.params["boot_id"]
                                or current["service_owner"] != plan.params["service_owner"]
                                or self._peer(plan.params["capabilities"]) != peer):
                            input_block.append("sessão/responsável mudou antes da rotina; verificar novamente")
                        if not keyboard_only:
                            input_block.extend(lease_blockers(self.supervisor.store.root))
                            input_block.extend(v for v in current["blockers"] if not (usable_peer and v == PEER_WAIT))
                        if not input_block and usable_peer:
                            self.backend.peer_idle(usable_peer)
                        report = current
                    if key in INPUTS and input_block:
                        ready, reason = False, "; ".join(input_block)
                    elif key in ("audio", "microphone"):
                        ready, reason = self.backend.enable_audio(key, plan.params["audio_targets"].get(key))
                    elif key == "virtual-keyboard":
                        ready, reason = self.backend.open_keyboard(report)
                    elif key == "gamepad":
                        ready, reason = self.backend.gamepad(report)
                    elif key == "touch" and not any("touch" in d["kinds"] for d in report["devices"]):
                        self._reserve_touch_attempt(plan)
                        ready, reason = self.backend.repair_touch(usable_peer)
                    else:
                        ready, reason = self.backend.enable_devices(key, report, delegated=delegated)
                    row = {"key": key, "ready": bool(ready), "outcome": "sucesso" if ready else "parcial",
                           "reason": str(reason)[:800], "physical_verified": False}
                except ValueError as exc:
                    row = {"key": key, "ready": False, "outcome": "parcial", "reason": str(exc)[:800],
                           "physical_verified": False}
                except (ProbeError, OSError, UncertainEffect) as exc:
                    row = {"key": key, "ready": False, "outcome": "desconhecido", "reason": str(exc)[:800],
                           "physical_verified": False}
                rows.append(row)
                receipt["rows"] = rows
                save_object(self._receipt(plan.operation_id), receipt)
                if row["outcome"] == "desconhecido":
                    break  # A timed-out routine can still be acting. Never overlap another repair.
            outcome = (Outcome.UNKNOWN if any(r["outcome"] == "desconhecido" for r in rows)
                       else Outcome.OK if all(r["ready"] for r in rows) else Outcome.PARTIAL)
            reason = f"{sum(r['ready'] for r in rows)}/{len(plan.params['capabilities'])} capacidades verificadas no sistema"
            if len(rows) == 1:
                reason += " · " + rows[0]["reason"]
            result = self._result(plan, rows, outcome, reason)
            receipt.update(complete=outcome != Outcome.UNKNOWN, result=result.to_dict())
            save_object(self._receipt(plan.operation_id), receipt)
            return result
        return self.supervisor.coordinator.run(plan, run, wait=.2)

    def _reserve_touch_attempt(self, plan):
        """Share the existing durable input budget before a hardware routine."""
        policy = self.supervisor.store.read()
        now = self.supervisor.now()
        if policy["circuit"] or any(row["ts"] > now for row in policy["attempts"]):
            raise ValueError("disjuntor/relógio impede repetição do reparo FTS; revisar antes de rearmar")
        attempts = [row for row in policy["attempts"] if 0 <= now - row["ts"] < 3600]
        if len(attempts) >= 3 or (attempts and now - attempts[-1]["ts"] < 60):
            raise ValueError("orçamento de reparo: aguarde 60 s; no máximo três intervenções por hora")
        policy["attempts"] = [*attempts, {"ts": now, "operation_id": plan.operation_id}]
        self.supervisor.store.save(policy)

    @staticmethod
    def _owner():
        fields = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()
        return {"pid": os.getpid(), "boot_id": read_boot_id(), "start_ticks": int(fields[19])}

    @staticmethod
    def _result(plan, rows, outcome, reason):
        return ActionResult(plan.action, outcome, plan.operation_id, target_key=plan.target.key,
                            reason=reason, effects={"capabilities": rows, "software_verification_only": True,
                                                   "boot_id": plan.params["boot_id"],
                                                   "service_owner": plan.params["service_owner"]})

    def _save_profile(self, plan, report, peer):
        usable_peer = peer if peer and not peer.get("error") else None
        blockers = lease_blockers(self.supervisor.store.root) + [v for v in report["blockers"] if not (usable_peer and v == PEER_WAIT)]
        if peer and peer.get("error"):
            blockers.append(peer["error"])
        eligible = [d for d in report["devices"] if d["repairable"]]
        if blockers or not eligible or any(d["enabled"] is not True for d in eligible):
            return self._result(plan, [], Outcome.REFUSED, "; ".join(blockers) or "configuração habilitada não comprovada; perfil anterior preservado")
        if peer:
            self.backend.peer_idle(peer)
            warning = self.backend.delegate(peer, capture=True)
            if warning:
                return self._result(plan, [], Outcome.PARTIAL, warning + "; perfil anterior do Fôlego preservado")
            if any("touch" in d["kinds"] and "FTS3528" in d["name"] for d in eligible):
                ready, why = self.backend.persist_touch(peer)
                if not ready:
                    return self._result(plan, [], Outcome.PARTIAL, "persistência da tela não confirmada: " + why)
        current = self.supervisor.native.collect()
        if (not fresh(current) or current["boot_id"] != report["boot_id"]
                or current["service_owner"] != report["service_owner"]
                or self._devices(current, ORDER) != self._devices(report, ORDER)
                or any(d["enabled"] is not True for d in current["devices"] if d["repairable"])
                or lease_blockers(self.supervisor.store.root)
                or any(v != PEER_WAIT or not usable_peer for v in current["blockers"])
                or self._peer(ORDER) != peer):
            return self._result(plan, [], Outcome.PARTIAL, "estado mudou após solicitação; perfil local anterior preservado")
        policy = self.supervisor.store.read()
        baseline = {**policy["baseline"], **{d["key"]: {"enabled": True, "name": d["name"]} for d in eligible}}
        if len(baseline) > 128:
            return self._result(plan, [], Outcome.REFUSED, "baseline excede limite; configuração anterior preservada")
        policy["baseline"] = baseline
        policy["manual_profile"] = {"schema": 1, "saved_at": time.time(), "boot_id": report["boot_id"],
                                    "audio_targets": plan.to_dict()["params"]["audio_targets"],
                                    "delegated_preferences": bool(peer)}
        self.supervisor.store.save(policy)
        missing = [r["key"] for r in report["cards"] if r["state"] in ("unknown", "unavailable", "not-observed", "degraded")]
        reason = f"Perfil persistente salvo: {len(baseline)} entradas habilitadas"
        if missing:
            reason += "; capacidades ausentes/não saudáveis não foram registradas: " + ", ".join(missing)
        reason += ". Não certifica entrada antes do login nem hardware ausente."
        return self._result(plan, [], Outcome.PARTIAL if missing else Outcome.OK, reason)

    def reconcile(self, key):
        c = self.supervisor.coordinator
        state = c.journal.state_of(key)
        if state and state.intent and state.intent.action == "accessibility.enable-input":
            return self.supervisor.reconcile(key)
        with c.lock(wait=.2):
            state = c.journal.state_of(key)
            if state is None:
                uuid.UUID(hex=key)
                return ActionResult(ACTION, Outcome.REFUSED, key, target_key="all",
                                    reason="nenhuma intenção registrada; a rotina não foi autorizada a executar")
            if state.intent.action not in (ACTION, SAVE_ACTION):
                raise ValueError("operação de outro domínio")
            if state.result and state.result.outcome != Outcome.UNKNOWN:
                return state.result
            receipt = read_object(self._receipt(key))
            if (receipt and receipt.get("complete") is True and _alive(receipt.get("owner")) is False
                    and receipt.get("plan") == state.intent.to_dict() and isinstance(receipt.get("result"), dict)):
                result = ActionResult.from_dict(receipt["result"])
                if (result.outcome != Outcome.UNKNOWN and result.operation_id == key
                        and result.action == state.intent.action and result.target_key == state.intent.target.key):
                    c.journal.append_result(result)
                    return result
            return self._result(state.intent, (receipt or {}).get("rows", []), Outcome.UNKNOWN,
                                "rotina sem prova de término; não repetir. Consulte o responsável e o código desta operação")
