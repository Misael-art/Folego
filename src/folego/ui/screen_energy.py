"""Opt-in Plasma display timeout, with a recoverable configuration receipt.

PowerDevil owns idle detection and input wakeup. Fôlego only changes its display
timeout and asks KScreen to wake for a confirmed attention event. No suspend,
brightness, process or power-profile setting is touched here.
"""
from __future__ import annotations

import configparser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid


PROFILES = ("AC", "Battery", "LowBattery")
MANAGED = ("TurnOffDisplayWhenIdle", "TurnOffDisplayIdleTimeoutSec")
TIMEOUT = {"AC": "180", "Battery": "120", "LowBattery": "120"}


class ScreenEnergyError(RuntimeError):
    pass


def _run(argv, *, timeout=3):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise ScreenEnergyError("O Plasma não confirmou a operação da tela; confira o estado antes de repetir")
    return result.stdout.strip()


def _settings(path):
    parser = configparser.RawConfigParser(interpolation=None, strict=False)
    if path.is_symlink():
        raise ScreenEnergyError("Configuração da tela vinculada; revisão manual necessária")
    if path.exists():
        parser.read(path, encoding="utf-8")
    return {profile: {key: parser.get(f"{profile}][Display", key, fallback=None)
                      for key in MANAGED} for profile in PROFILES}


def _target(enabled):
    return {p: {"TurnOffDisplayWhenIdle": "true" if enabled else "false",
                "TurnOffDisplayIdleTimeoutSec": TIMEOUT[p]} for p in PROFILES}


def _save(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise ScreenEnergyError("Estado da tela vinculado; revisão manual necessária")
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True)
            output.flush(); os.fsync(output.fileno())
        os.replace(temp, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(parent)
        finally: os.close(parent)
    finally:
        temp.unlink(missing_ok=True)


def _load(path):
    if path.is_symlink():
        raise ScreenEnergyError("Estado da tela vinculado; revisão manual necessária")
    if not path.exists(): return None
    if path.stat().st_size > 8192:
        raise ScreenEnergyError("Estado da tela excede o limite de leitura")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScreenEnergyError("Estado da tela ilegível; revisão manual necessária") from exc
    if (not isinstance(value, dict) or value.get("schema") != 1
            or value.get("phase") not in ("intent", "applied", "restore")
            or not isinstance(value.get("baseline"), dict)
            or not isinstance(value.get("target"), dict)):
        raise ScreenEnergyError("Estado da tela desconhecido; revisão manual necessária")
    dock = value.get("dock")
    if dock is not None and (not isinstance(dock, dict)
                             or dock.get("phase") not in ("intent", "disabled")
                             or not isinstance(dock.get("internal"), str)
                             or not re.fullmatch(r"eDP-[A-Za-z0-9-]+", dock["internal"])):
        raise ScreenEnergyError("Estado do dock desconhecido; revisão manual necessária")
    return value


def _outputs():
    data = json.loads(_run(["kscreen-doctor", "--json"]))
    outputs = data.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ScreenEnergyError("Monitores indisponíveis")
    internal = [x for x in outputs if x.get("name", "").startswith("eDP-") and x.get("connected")]
    if len(internal) != 1:
        raise ScreenEnergyError("Tela interna não identificada de forma única")
    external = [x for x in outputs if x.get("connected") and x.get("enabled") and x is not internal[0]]
    return {"mode": "dock" if external else "portátil", "internal": internal[0]["name"],
            "internal_enabled": internal[0].get("enabled") is True,
            "external_active": bool(external)}


def _fullscreen():
    active = _run(["kdotool", "getactivewindow"])
    if not re.fullmatch(r"\{[0-9a-fA-F-]{36}\}", active):
        raise ScreenEnergyError("Janela ativa desconhecida")
    info = _run(["qdbus6", "org.kde.KWin", "/KWin", "org.kde.KWin.getWindowInfo", active])
    flags = [line.split(":", 1)[1].strip() for line in info.splitlines() if line.startswith("fullscreen:")]
    if len(flags) != 1 or flags[0] not in ("true", "false"):
        raise ScreenEnergyError("Estado de tela cheia desconhecido")
    return flags[0] == "true"


class ScreenEnergy:
    """All methods are called serially by one GUI worker, never on the Qt loop."""

    def __init__(self, *, config=None, receipt=None, command=_run, topology=_outputs,
                 fullscreen=_fullscreen):
        config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        state_home = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
        self.config = Path(config) if config else config_home / "powerdevilrc"
        self.receipt = Path(receipt) if receipt else state_home / "folego/screen-energy.json"
        self.command = command
        self.topology = topology
        self.fullscreen = fullscreen

    def close(self):
        """The worker owns no persistent subprocess or desktop handle."""
        return None

    def _write(self, values):
        if not shutil.which("kwriteconfig6"):
            raise ScreenEnergyError("Ferramenta de configuração do Plasma ausente")
        for profile in PROFILES:
            for key in MANAGED:
                value = values[profile][key]
                argv = ["kwriteconfig6", "--file", str(self.config), "--group", profile,
                        "--group", "Display", "--key", key]
                if value is None: argv.append("--delete")
                else: argv.append(value)
                self.command(argv)
        self.command(["qdbus6", "org.kde.Solid.PowerManagement",
                      "/org/kde/Solid/PowerManagement",
                      "org.kde.Solid.PowerManagement.reparseConfiguration"])

    def _desired(self):
        try:
            topology = self.topology()
            mode = topology["mode"] if isinstance(topology, dict) else topology
            return _target(mode == "portátil" and not self.fullscreen())
        except (ScreenEnergyError, OSError, ValueError, subprocess.TimeoutExpired):
            # Uncertain game/dock state protects the display.
            return _target(False)

    def status(self):
        state = _load(self.receipt)
        if state is None:
            return {"enabled": False, "message": "Economia de tela desligada. Ative nesta aba."}
        current = _settings(self.config)
        if state["phase"] != "applied" or current != state["target"]:
            return {"enabled": True, "unknown": True,
                    "message": "Configuração da tela divergente ou incompleta; nenhuma repetição automática."}
        if state.get("dock", {}).get("phase") == "disabled":
            try:
                topology = self.topology()
                if (isinstance(topology, dict) and topology["external_active"]
                        and not topology["internal_enabled"]):
                    return {"enabled": True, "active": True,
                            "message": "Dock ativo: monitor externo ligado e tela interna desativada."}
            except (ScreenEnergyError, OSError, ValueError, subprocess.TimeoutExpired):
                pass
            return {"enabled": True, "unknown": True,
                    "message": "Dock mudou; aguardando reconciliação da tela interna."}
        active = all(current[p]["TurnOffDisplayWhenIdle"] == "true" for p in PROFILES)
        if active:
            try:
                inhibitors = self.command(["busctl", "--user", "get-property",
                    "org.kde.Solid.PowerManagement.PolicyAgent",
                    "/org/kde/Solid/PowerManagement/PolicyAgent",
                    "org.kde.Solid.PowerManagement.PolicyAgent", "ActiveInhibitions"])
                if re.search(r'(?:^| )"idle" ', inhibitors):
                    return {"enabled": True, "active": False, "blocked": True,
                            "message": "Plasma mantém a tela acesa: outro aplicativo inibe a ociosidade."}
            except (ScreenEnergyError, OSError, subprocess.TimeoutExpired):
                return {"enabled": True, "active": False, "unknown": True,
                        "message": "Não foi possível verificar as inibições do Plasma."}
        if not active:
            try:
                topology = self.topology()
                mode = topology["mode"] if isinstance(topology, dict) else topology
                if mode == "dock":
                    message = "Dock ativo: temporizador de inatividade pausado; monitor externo preservado."
                elif self.fullscreen():
                    message = "Aplicativo em tela cheia: economia pausada até sair do jogo."
                else:
                    message = "Economia pausada; o estado do Plasma está em reconciliação."
            except (ScreenEnergyError, OSError, ValueError, subprocess.TimeoutExpired):
                message = "Economia pausada: não foi possível confirmar janela ou monitores."
            return {"enabled": True, "active": False, "message": message}
        return {"enabled": True, "active": active,
                "message": "Tela apaga após 2 min na bateria ou 3 min na tomada; movimento a reacende."}

    def enable(self):
        if os.environ.get("XDG_SESSION_TYPE") != "wayland" or "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", ""):
            raise ScreenEnergyError("Economia automática exige sessão KDE Wayland")
        missing = [tool for tool in ("kwriteconfig6", "qdbus6", "kscreen-doctor", "kdotool", "busctl")
                   if not shutil.which(tool)]
        if missing:
            raise ScreenEnergyError("Integração de tela incompleta: " + ", ".join(missing))
        if _load(self.receipt) is not None:
            raise ScreenEnergyError("Já existe intenção de tela; consulte o estado antes de alterar")
        baseline = _settings(self.config)
        target = self._desired()
        state = {"schema": 1, "id": uuid.uuid4().hex, "phase": "intent",
                 "baseline": baseline, "target": target}
        _save(self.receipt, state)
        self._write(target)
        if _settings(self.config) != target:
            raise ScreenEnergyError("Configuração da tela não foi confirmada")
        state["phase"] = "applied"
        _save(self.receipt, state)
        self._reconcile_dock(state)
        return self.status()

    def _reconcile_dock(self, state):
        """Remove eDP only after an active external output is observed.

        A pending operation is inspected, never repeated blindly. KScreen moves
        windows as part of disabling an output; Fôlego does not move windows itself.
        """
        topology = self.topology()
        if not isinstance(topology, dict): return
        internal = topology["internal"]
        if not re.fullmatch(r"eDP-[A-Za-z0-9-]+", internal):
            raise ScreenEnergyError("Identidade da tela interna desconhecida")
        dock = state.get("dock")
        if dock and dock.get("internal") != internal:
            raise ScreenEnergyError("Tela interna mudou desde a intenção; revisão necessária")
        if dock and dock.get("phase") == "intent":
            if topology["internal_enabled"]:
                raise ScreenEnergyError("Desativação da tela interna incerta; nenhuma repetição")
            if not topology["external_active"]:
                self.command(["kscreen-doctor", f"output.{internal}.enable"])
                if not self.topology()["internal_enabled"]:
                    raise ScreenEnergyError("Tela interna não foi recuperada")
                state.pop("dock"); _save(self.receipt, state)
                return
            dock["phase"] = "disabled"; _save(self.receipt, state)
            return
        if topology["external_active"] and topology["internal_enabled"] and not dock:
            state["dock"] = {"internal": internal, "phase": "intent"}
            _save(self.receipt, state)
            self.command(["kscreen-doctor", f"output.{internal}.disable"])
            after = self.topology()
            if after["internal_enabled"] or not after["external_active"]:
                if not after["internal_enabled"]:
                    self.command(["kscreen-doctor", f"output.{internal}.enable"])
                raise ScreenEnergyError("Dock não confirmou uma saída externa ativa")
            state["dock"]["phase"] = "disabled"; _save(self.receipt, state)
        elif dock and not topology["external_active"]:
            if not topology["internal_enabled"]:
                self.command(["kscreen-doctor", f"output.{internal}.enable"])
                if not self.topology()["internal_enabled"]:
                    raise ScreenEnergyError("Tela interna não foi recuperada")
            state.pop("dock"); _save(self.receipt, state)

    def reconcile(self):
        state = _load(self.receipt)
        if state is None or state["phase"] != "applied": return self.status()
        if state.get("dock"):
            topology = self.topology()
            if isinstance(topology, dict) and not topology["external_active"]:
                self._reconcile_dock(state)
        current = _settings(self.config)
        if current != state["target"]:
            return self.status()
        target = self._desired()
        if target != current:
            state["phase"] = "intent"; state["target"] = target
            _save(self.receipt, state)
            self._write(target)
            if _settings(self.config) != target:
                raise ScreenEnergyError("Nova configuração da tela não confirmada")
            state["phase"] = "applied"; _save(self.receipt, state)
        self._reconcile_dock(state)
        return self.status()

    def disable(self):
        state = _load(self.receipt)
        if state is None: return self.status()
        current = _settings(self.config)
        if state["phase"] not in ("intent", "applied", "restore"):
            raise ScreenEnergyError("Intenção da tela desconhecida")
        for profile in PROFILES:
            for key in MANAGED:
                if current[profile][key] not in (state["target"][profile][key], state["baseline"][profile][key]):
                    raise ScreenEnergyError("Configuração alterada por outro owner; preservada para revisão")
        dock = state.get("dock")
        if dock:
            topology = self.topology()
            if not isinstance(topology, dict) or dock.get("internal") != topology.get("internal"):
                raise ScreenEnergyError("Dock desconhecido; não é seguro restaurar a tela")
            if not topology["internal_enabled"]:
                self.command(["kscreen-doctor", f"output.{dock['internal']}.enable"])
                if not self.topology()["internal_enabled"]:
                    raise ScreenEnergyError("Tela interna não foi recuperada")
            state.pop("dock"); _save(self.receipt, state)
        state["phase"] = "restore"; _save(self.receipt, state)
        self._write(state["baseline"])
        if _settings(self.config) != state["baseline"]:
            raise ScreenEnergyError("Restauração da tela não confirmada")
        self.receipt.unlink()
        return self.status()

    def wake(self):
        if _load(self.receipt) is None:
            return self.status()
        self.command(["kscreen-doctor", "--dpms", "on"])
        return self.status()

    def attention(self):
        from ..core.agent_pressure import latest_attention
        event = latest_attention()
        return {"attention_id": event["id"] if event else None}

    def perform(self, action, value=None):
        if action not in ("status", "enable", "disable", "reconcile", "wake", "attention"):
            raise ScreenEnergyError("Ação de tela desconhecida")
        return getattr(self, action)()
