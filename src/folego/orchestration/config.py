"""Persisted automation mode/preset/pause (F6), separate from grants.

The three knobs are deliberately not one object in the authorization sense:
changing a preset writes only this file and can never add an action or a limit to
a grant. A corrupt file fails closed; a missing file means manual/equilibrado,
never automatic. Enabling automatic mode requires an already-active grant for the
one action automation is allowed to touch today.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path

from .. import paths
from ..safely.atomicfile import write_atomic
from .automation import MANUAL, MODES, PRESETS
from .grants import GrantError, GrantStore

CONFIG_VERSION = 1


class ConfigError(Exception):
    """The automation config cannot be read or changed safely."""


@dataclass(frozen=True)
class AutomationConfig:
    mode: str = MANUAL
    preset: str = "equilibrado"
    paused: bool = False
    updated_at: float = 0.0


class ConfigStore:
    def __init__(self, path: Path | None = None, *, clock=None):
        self.path = Path(path) if path else paths.automation_path()
        self._clock = clock or time.time

    def read(self) -> AutomationConfig:
        if not self.path.exists():
            return AutomationConfig()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("version") != CONFIG_VERSION:
                raise ConfigError(
                    "versão de automação não suportada: "
                    f"{raw.get('version') if isinstance(raw, dict) else raw!r}")
            mode = raw.get("mode", MANUAL)
            preset = raw.get("preset", "equilibrado")
            paused = raw.get("paused", False)
            if mode not in MODES:
                raise ConfigError(f"modo inválido no registro: {mode!r}")
            if preset not in PRESETS:
                raise ConfigError(f"preset inválido no registro: {preset!r}")
            if not isinstance(paused, bool):
                raise ConfigError("pausa inválida no registro")
            return AutomationConfig(mode=mode, preset=preset, paused=paused,
                                    updated_at=float(raw.get("updated_at") or 0.0))
        except ConfigError:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise ConfigError(f"registro de automação ilegível: {exc}") from exc

    def set_mode(self, mode: str, *, grant_store: GrantStore | None = None,
                 now: float | None = None) -> AutomationConfig:
        if mode not in MODES:
            raise ConfigError(f"modo desconhecido: {mode!r}")
        now = self._clock() if now is None else now
        if mode == "automatico":
            store = grant_store or GrantStore(clock=lambda: now)
            try:
                active = store.for_action("tmpfs.release", now=now)
            except GrantError as exc:
                raise ConfigError(
                    f"não é possível provar um grant ativo: {exc}") from exc
            if not active:
                raise ConfigError(
                    "modo automático exige um grant ativo para tmpfs.release; "
                    "nada foi alterado")
        return self._update(mode=mode, updated_at=now)

    def set_preset(self, preset: str) -> AutomationConfig:
        if preset not in PRESETS:
            raise ConfigError(f"preset desconhecido: {preset!r}")
        # Intencionalmente não toca em GrantStore: preset nunca amplia grant.
        return self._update(preset=preset, updated_at=self._clock())

    def set_paused(self, paused: bool) -> AutomationConfig:
        return self._update(paused=bool(paused), updated_at=self._clock())

    def _update(self, **changes) -> AutomationConfig:
        # Serialize the complete read/modify/write transaction, including reads
        # from another CLI. Never write an earlier snapshot over a newer pause.
        with self._locked():
            return self._write(replace(self.read(), **changes))

    def _write(self, config: AutomationConfig) -> AutomationConfig:
        payload = json.dumps({
            "version": CONFIG_VERSION,
            "mode": config.mode,
            "preset": config.preset,
            "paused": config.paused,
            "updated_at": config.updated_at,
        }, ensure_ascii=False, sort_keys=True).encode("utf-8")
        try:
            write_atomic(self.path, payload, mode=0o600)
        except OSError as exc:
            raise ConfigError(
                f"não foi possível gravar a automação: {exc}") from exc
        return config

    @contextlib.contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_path = self.path.with_name(self.path.name + ".lock")
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            deadline = time.monotonic() + 5.0
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ConfigError("prazo de espera da trava de configuração expirou")
                    time.sleep(.02)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
