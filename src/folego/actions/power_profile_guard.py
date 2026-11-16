"""Lower the power profile while the battery sags, and give it back on external power.

Authorised on 09/11/2026 for this single effect. The guard only ever asks
power-profiles-daemon for a more frugal profile during a sustained discharge
sag, records the intention before the request, confirms it by reading the
profile back, and restores the profile it replaced once the charger is
connected and nobody changed the profile in between. It never signals a
process, suspends the host or touches brightness. An unconfirmed result stops
further automatic requests until the user turns the option off and on again.
"""
from __future__ import annotations

import shutil
import subprocess
import time
import uuid
import math
from functools import wraps
from pathlib import Path

from .. import paths
from ..safely.audit import AuditLog
from ..safely.persist import read_json, write_json_atomic
from ..orchestration.coordinator import Coordinator, CoordinatorBusy

RANK = {"performance": 0, "balanced": 1, "power-saver": 2}
TARGETS = {"attention": "balanced", "critical": "power-saver"}
SUSTAIN = 2          # consecutive sagging observations before a request
BUDGET = 4           # automatic requests per hour
BUDGET_WINDOW_S = 3600.0
NAMES = {"performance": "desempenho", "balanced": "equilibrado", "power-saver": "economia"}


class PowerProfileError(RuntimeError):
    pass


def state_path() -> Path:
    return paths.state_dir() / "power-profile-guard.json"


def _run(argv, *, timeout=4):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PowerProfileError("O serviço de perfis de energia não respondeu") from exc
    if result.returncode:
        raise PowerProfileError("O serviço de perfis de energia recusou a operação")
    return result.stdout


def _tool():
    return shutil.which("powerprofilesctl")


def _boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        return ""


def _serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        try:
            with self.coordinator.lock(wait=.2):
                return method(self, *args, **kwargs)
        except CoordinatorBusy as exc:
            raise PowerProfileError('Outra operação de energia está em andamento') from exc
    return call


class PowerProfileGuard:
    """Backend for ``DesktopController``; all calls run off the GUI thread."""

    def __init__(self, *, path=None, command=_run, tool=None, audit=None, clock=time.time):
        self.path = Path(path) if path else state_path()
        self.command = command
        self.tool = tool if tool is not None else _tool()
        self.audit = audit
        self.clock = clock
        self._streak = 0
        self.coordinator = Coordinator(lock_path=self.path.with_suffix('.lock'))

    def close(self):
        pass

    # --- daemon -----------------------------------------------------------
    def _current(self):
        if not self.tool:
            raise PowerProfileError("powerprofilesctl ausente; perfil de energia não gerenciado")
        value = self.command([self.tool, "get"]).strip()
        if value not in RANK:
            raise PowerProfileError("Perfil de energia desconhecido; nenhuma troca automática")
        return value

    def _available(self):
        found = set()
        for line in self.command([self.tool, "list"]).splitlines():
            name = line.strip().lstrip("*").strip()
            if name.endswith(":") and name[:-1] in RANK:
                found.add(name[:-1])
        return found

    # --- state ------------------------------------------------------------
    def _load(self):
        value, problems = read_json(self.path)
        if problems or (value is not None and (not isinstance(value, dict)
                or type(value.get('schema')) is not int or value['schema'] != 1)):
            raise PowerProfileError("Estado do guarda de perfil ilegível; revisão manual necessária")
        state = value if value is not None else {"schema": 1, "enabled": True, "receipt": None}
        state.setdefault('requests', [])  # compatible with receipts from earlier previews
        receipt = state.get('receipt')
        if (type(state.get('enabled')) is not bool or 'receipt' not in state or not isinstance(state['requests'], list)
                or len(state['requests']) > BUDGET
                or any(type(at) not in (int, float) or not math.isfinite(at) or at < 0
                       for at in state['requests'])
                or (receipt is not None and (not isinstance(receipt, dict)
                    or receipt.get('state') not in ('intended', 'applied', 'unknown')
                    or not isinstance(receipt.get('original'), str) or receipt['original'] not in RANK
                    or not isinstance(receipt.get('target'), str) or receipt['target'] not in RANK
                    or not isinstance(receipt.get('id'), str)
                    or not isinstance(receipt.get('boot_id'), str)
                    or type(receipt.get('restore', False)) is not bool))):
            raise PowerProfileError('Estado do guarda de perfil incompleto; revisão manual necessária')
        return state

    def _save(self, state):
        write_json_atomic(self.path, state, keep_backup=False)

    def _log(self, outcome, receipt, error=None):
        try:
            (self.audit or AuditLog()).append(
                kind="power-profile", action_id=receipt["id"], outcome=outcome,
                targets=[f"{receipt['original']}->{receipt['target']}"],
                error=error, actor="voltage-guard")
        except (OSError, ValueError):
            pass  # the receipt is the authority; the audit line is a courtesy

    def _reconcile(self, state, current):
        """Settle a receipt against the profile actually in force."""
        receipt = state.get("receipt")
        if not receipt:
            return state
        if receipt.get('boot_id') != _boot_id() and receipt.get('state') != 'unknown':
            receipt['state'] = 'unknown'
            self._save(state)
        elif receipt.get("state") == "intended":
            if current == receipt['target'] and receipt.get('restore'):
                state['receipt'] = None
            elif current == receipt["target"]:
                receipt["state"] = "applied"
            else:
                receipt['state'] = 'unknown'
            self._save(state)
        elif receipt.get("state") == "applied" and current != receipt["target"]:
            state["receipt"] = None  # the user or another tool owns the profile now
            self._save(state)
        return state

    def _payload(self, state, current, message, **extra):
        receipt = state.get("receipt") or {}
        return {"guard": True, "enabled": bool(state.get("enabled")),
                "blocked": receipt.get("state") == "unknown", "profile": current,
                "managed": receipt.get("state") == "applied", "message": message, **extra}

    def _describe(self, state, current):
        receipt = state.get("receipt") or {}
        if not state.get("enabled"):
            return f"Desligado. Perfil atual: {NAMES[current]}."
        if receipt.get("state") == "unknown":
            return ("Última troca sem confirmação; automação pausada. "
                    "Confira o perfil e reative a opção.")
        if receipt.get("state") == "applied":
            return (f"Perfil {NAMES[current]} aplicado pela queda de voltagem; "
                    f"volta a {NAMES[receipt['original']]} com o carregador.")
        return f"Ativo. Perfil atual: {NAMES[current]}."

    # --- actions ----------------------------------------------------------
    def status(self, *, reconcile=True):
        if reconcile:
            try:
                with self.coordinator.lock(wait=.2):
                    return self._status(reconcile=True)
            except CoordinatorBusy as exc:
                raise PowerProfileError('Outra operação de energia está em andamento') from exc
        return self._status(reconcile=False)

    def _status(self, *, reconcile):
        state = self._load()
        try:
            current = self._current()
        except PowerProfileError as exc:
            return self._payload(state, None, str(exc), unavailable=True)
        if reconcile:
            state = self._reconcile(state, current)
        return self._payload(state, current, self._describe(state, current))

    @_serialized
    def set_enabled(self, enabled):
        current = self._current()
        state = self._load()
        receipt = state.get("receipt")
        if receipt and receipt.get("state") == "unknown":
            state["receipt"] = None  # explicit user review clears the breaker
        state["enabled"] = bool(enabled)
        self._save(state)
        state = self._reconcile(state, current)
        self._streak = 0
        return self._payload(state, current, self._describe(state, current))

    @_serialized
    def observe(self, level):
        """``level`` is 'attention', 'critical', 'external' or None (no opinion)."""
        if level not in TARGETS:
            self._streak = 0
        if level not in TARGETS and level != "external":
            return {"guard": True, "idle": True}
        state = self._load()
        if (state.get("receipt") or {}).get("state") == "unknown":
            return {"guard": True, "idle": True}
        if level != "external" and not state.get("enabled"):
            return {"guard": True, "idle": True}  # a pending restore still happens when off
        current = self._current()
        state = self._reconcile(state, current)
        receipt = state.get("receipt")
        if receipt and receipt['state'] == 'unknown':
            return self._payload(state, current, self._describe(state, current))
        if level == "external":
            if not receipt:
                return {"guard": True, "idle": True}
            restoration = dict(receipt, id=uuid.uuid4().hex, parent_id=receipt['id'],
                               target=receipt['original'], original=receipt['target'], restore=True)
            return self._switch(state, restoration, current=current)
        self._streak += 1
        target = TARGETS[level]
        if self._streak < SUSTAIN or RANK[current] >= RANK[target]:
            return {"guard": True, "idle": True}
        if target not in self._available():
            return {"guard": True, "idle": True}
        original = receipt["original"] if receipt else current
        return self._switch(state, {"id": uuid.uuid4().hex, "boot_id": _boot_id(),
                                    "original": original, "target": target, "level": level}, current=current)

    def _switch(self, state, receipt, *, current):
        target = receipt["target"]
        if not receipt['boot_id']:
            raise PowerProfileError('Boot desconhecido; nenhuma troca de perfil autorizada')
        now = self.clock()
        if any(at > now for at in state['requests']):
            return self._payload(state, current, 'Relógio regressou; orçamento de energia preservado.')
        recent = [at for at in state['requests'] if now - at < BUDGET_WINDOW_S]
        if len(recent) >= BUDGET:
            return self._payload(state, current, 'Limite de trocas automáticas por hora atingido.')
        if self._current() != current:
            return self._payload(state, current, 'Perfil mudou antes da solicitação; aguarde nova leitura.')
        state['requests'] = [*recent, now]
        state["receipt"] = dict(receipt, state="intended")
        self._save(state)  # reserve the budget and intention before either effect
        error = None
        try:
            self.command([self.tool, "set", target])
            confirmed = self._current() == target
        except PowerProfileError as exc:
            confirmed, error = False, str(exc)
        if not confirmed:
            kept = state.get("receipt") or receipt
            state["receipt"] = dict(kept, state="unknown")
            self._save(state)
            self._log("unknown", receipt, error or "perfil não confirmado")
            return self._payload(state, None, self._describe(state, target), failed=True)
        restore = receipt.get('restore', False)
        if restore:
            state["receipt"] = None
        else:
            state["receipt"]["state"] = "applied"
        self._save(state)
        self._log("restored" if restore else "applied", receipt)
        return self._payload(state, target, self._describe(state, target),
                             changed={"from": receipt["original"], "to": target,
                                      "restore": restore, "level": receipt.get("level")})

    def perform(self, action, value=None):
        if action == "status":
            return self.status()
        if action == "observe":
            return self.observe(value)
        if action in ("enable", "disable"):
            return self.set_enabled(action == "enable")
        raise ValueError("Ação de perfil de energia desconhecida")
