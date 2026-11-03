"""Persisted, limited, revocable grants (F6). No grant means no automation.

The store is opt-in: a missing file is an empty set, never an inferred grant. A
corrupt or future-version file raises and callers must fail closed. Adding a
grant never expands an existing one; ``revoke`` keeps the record with a
``revoked_at`` timestamp so the decision log can explain why it stopped.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import math
import os
import time
import uuid
from pathlib import Path

from .. import paths
from ..safely.atomicfile import write_atomic
from .models import SCHEMA, Grant, ValidationError

SCHEMA_VERSION = 1


class GrantError(Exception):
    """The grant store cannot be read or updated safely."""


class GrantStore:
    def __init__(self, path: Path | None = None, *, clock=None):
        self.path = Path(path) if path else paths.grants_path()
        self._clock = clock or time.time

    # ------------------------------------------------------------------ leitura

    def list(self) -> list[Grant]:
        return self._read()

    def for_action(self, action: str, *, now: float | None = None) -> list[Grant]:
        now = self._clock() if now is None else now
        return [grant for grant in self._read()
                if grant.action == action and grant.active(now)]

    def find(self, grant_id: str) -> Grant | None:
        return next((grant for grant in self._read()
                     if grant.grant_id == grant_id), None)

    def _read(self) -> list[Grant]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("version") != SCHEMA_VERSION:
                raise GrantError(
                    f"versão de grants não suportada: {raw.get('version') if isinstance(raw, dict) else raw!r}")
            rows = raw.get("grants", [])
            if not isinstance(rows, list):
                raise GrantError("lista de grants não é uma lista")
            return [Grant.from_dict(row) for row in rows]
        except GrantError:
            raise
        except (OSError, ValueError, TypeError, ValidationError) as exc:
            raise GrantError(f"registro de grants ilegível: {exc}") from exc

    # ------------------------------------------------------------------ escrita

    def add(self, action: str, limits: dict | None = None, *,
            ttl_s: float | None = 3600, source: str = "usuario", resources=()) -> Grant:
        limits = dict(limits or {})
        if not isinstance(action, str) or "." not in action:
            raise GrantError(f"ação de grant inválida: {action!r}")
        if ttl_s is not None:
            try:
                valid_ttl = not isinstance(ttl_s, bool) and math.isfinite(float(ttl_s)) and float(ttl_s) > 0
            except (TypeError, ValueError):
                valid_ttl = False
            if not valid_ttl:
                raise GrantError("ttl do grant precisa ser positivo e finito")
        try:
            json.dumps(limits, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise GrantError(f"limites do grant não são JSON: {exc}") from exc
        if not limits:
            raise GrantError("grant vazio não é uma autorização limitada")
        if any(isinstance(value, (int, float)) and not isinstance(value, bool)
               and value < 0 for value in limits.values()):
            raise GrantError("limites negativos não são permitidos")
        if not resources:
            raise GrantError("grant exige identidades de recursos explícitas")
        from .models import ResourceIdentity
        for resource in resources:
            if not isinstance(resource, ResourceIdentity):
                raise GrantError("escopo precisa conter ResourceIdentity")
            if resource.kind == "path" and any(type(resource.detail.get(k)) is not int
                    or resource.detail[k] <= 0 for k in ("dev", "ino")):
                raise GrantError("escopo de caminho exige device/inode comprovados")
        if action != "tmpfs.release" or set(limits) - {"bytes", "volume"}:
            raise GrantError("ação ou parâmetros fora do schema de autorização suportado")
        if type(limits.get("bytes")) is not int or limits["bytes"] < 0:
            raise GrantError("bytes precisa ser um teto inteiro não negativo")
        if ttl_s is None or float(ttl_s) > 86400:
            raise GrantError("validade precisa ser limitada a no máximo 86400 segundos")
        now = self._clock()
        grant = Grant(
            grant_id=str(uuid.uuid4()), action=action, limits=limits,
            issued_at=now,
            expires_at=None if ttl_s is None else now + float(ttl_s),
            source=source, resources=tuple(resources))
        with self._locked():
            grants = self._read()
            if any(item.grant_id == grant.grant_id for item in grants):
                raise GrantError("colisão de grant_id; nada foi gravado")
            grants.append(grant)
            self._write(grants)
        return grant

    def revoke(self, grant_id: str) -> Grant:
        now = self._clock()
        with self._locked():
            grants = self._read()
            for index, grant in enumerate(grants):
                if grant.grant_id != grant_id:
                    continue
                if grant.revoked_at is not None:
                    return grant
                revoked = Grant(
                    grant_id=grant.grant_id, action=grant.action,
                    limits=grant.limits, issued_at=grant.issued_at,
                    expires_at=grant.expires_at, revoked_at=now,
                    source=grant.source, resources=grant.resources)
                grants[index] = revoked
                self._write(grants)
                return revoked
        raise GrantError(f"grant {grant_id} não existe; nada foi revogado")

    def _write(self, grants: list[Grant]) -> None:
        payload = json.dumps(
            {"version": SCHEMA_VERSION,
             "grants": [grant.to_dict() for grant in grants]},
            ensure_ascii=False, sort_keys=True).encode("utf-8")
        try:
            write_atomic(self.path, payload, mode=0o600)
        except OSError as exc:
            raise GrantError(f"não foi possível gravar os grants: {exc}") from exc

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
                        raise GrantError("prazo de espera da trava de grants expirou")
                    time.sleep(.02)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
