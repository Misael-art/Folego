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
from pathlib import Path

from .. import paths
from ..safely.audit import AuditLog
from ..safely.persist import read_json, write_json_atomic

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


class PowerProfileGuard:
    """Backend for ``DesktopController``; all calls run off the GUI thread."""

    def __init__(self, *, path=None, command=_run, tool=None, audit=None, clock=time.monotonic):
        self.path = Path(path) if path else state_path()
        self.command = command
        self.tool = tool if tool is not None else _tool()
        self.audit = audit
        self.clock = clock
        self._streak = 0
        self._requests = []

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
        if problems or (value is not None and (not isinstance(value, dict) or value.get("schema") != 1)):
            raise PowerProfileError("Estado do guarda de perfil ilegível; revisão manual necessária")
        return value or {"schema": 1, "enabled": True, "receipt": None}

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
        if receipt.get("state") == "intended":
            if current == receipt["target"]:
                receipt["state"] = "applied"
            else:  # the request never took effect, or somebody chose another profile
                state["receipt"] = None
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
        state = self._load()
        try:
            current = self._current()
        except PowerProfileError as exc:
            return self._payload(state, None, str(exc), unavailable=True)
        if reconcile:
            state = self._reconcile(state, current)
        return self._payload(state, current, self._describe(state, current))

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
        if level == "external":
            if not receipt:
                return {"guard": True, "idle": True}
            return self._switch(state, dict(receipt, target=receipt["original"],
                                            original=receipt["target"]), restore=True)
        self._streak += 1
        target = TARGETS[level]
        if self._streak < SUSTAIN or RANK[current] >= RANK[target]:
            return {"guard": True, "idle": True}
        if target not in self._available():
            return {"guard": True, "idle": True}
        now = self.clock()
        self._requests = [at for at in self._requests if now - at < BUDGET_WINDOW_S]
        if len(self._requests) >= BUDGET:
            return self._payload(state, current, "Limite de trocas automáticas por hora atingido.")
        self._requests.append(now)
        original = receipt["original"] if receipt else current
        return self._switch(state, {"id": uuid.uuid4().hex, "boot_id": _boot_id(),
                                    "original": original, "target": target, "level": level})

    def _switch(self, state, receipt, *, restore=False):
        target = receipt["target"]
        if not restore:
            state["receipt"] = dict(receipt, state="intended")
            self._save(state)  # intention is durable before the effect
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
