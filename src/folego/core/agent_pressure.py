"""Small, local, expiring request for cooperative agent load reduction.

This is an advisory channel. It never signals, throttles or suspends a process,
and a hook reading it does not prove that an agent complied.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
import uuid


LEVELS = {"danger", "critical"}


def _boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip()


def channel_dir(runtime=None):
    root = Path(runtime or os.environ.get("XDG_RUNTIME_DIR", ""))
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("Runtime de sessão indisponível")
    root_stat = root.stat()
    if root_stat.st_uid != os.getuid() or root_stat.st_mode & 0o077:
        raise ValueError("Runtime de sessão compartilhado ou de outro usuário")
    directory = root / "folego"
    if directory.is_symlink(): raise ValueError("Canal vinculado")
    if directory.exists():
        stat = directory.stat()
        if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            raise ValueError("Canal compartilhado ou de outro usuário")
    else:
        directory.mkdir(mode=0o700)
    return directory


def _atomic(path, value):
    if path.is_symlink(): raise ValueError("Canal vinculado")
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True)
            output.flush(); os.fsync(output.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def publish(level, *, runtime=None, clock=time.time):
    if level not in LEVELS: raise ValueError("Nível de pressão desconhecido")
    now = clock()
    payload = {"schema": 1, "id": uuid.uuid4().hex, "level": level,
               "boot_id": _boot_id(),
               "issued_at": now, "expires_at": now + 90,
               "request": "reduzir paralelismo ou aguardar no próximo checkpoint seguro"}
    _atomic(channel_dir(runtime) / "agent-pressure.json", payload)
    return payload


def clear(*, runtime=None):
    path = channel_dir(runtime) / "agent-pressure.json"
    if path.is_symlink(): raise ValueError("Canal vinculado")
    path.unlink(missing_ok=True)


def current(*, runtime=None, clock=time.time):
    try:
        path = channel_dir(runtime) / "agent-pressure.json"
        if path.is_symlink() or path.stat().st_size > 1024: return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if (value.get("schema") != 1 or value.get("level") not in LEVELS
                or value.get("boot_id") != _boot_id()
                or not isinstance(value.get("id"), str) or len(value["id"]) != 32
                or not isinstance(value.get("expires_at"), (int, float))
                or not isinstance(value.get("issued_at"), (int, float))
                or value["issued_at"] > clock() + 5 or value["expires_at"] <= clock()):
            return None
        return value
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def attention(kind, *, runtime=None, clock=time.time):
    if kind not in ("PermissionRequest", "Stop"):
        raise ValueError("Evento de atenção desconhecido")
    payload = {"schema": 1, "id": uuid.uuid4().hex, "kind": kind,
               "at": clock(), "expires_at": clock() + 60}
    _atomic(channel_dir(runtime) / "agent-attention.json", payload)
    return payload


def latest_attention(*, runtime=None, clock=time.time):
    try:
        path = channel_dir(runtime) / "agent-attention.json"
        if path.is_symlink() or path.stat().st_size > 512: return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if (value.get("schema") != 1 or value.get("kind") not in ("PermissionRequest", "Stop")
                or not isinstance(value.get("id"), str) or len(value["id"]) != 32
                or not isinstance(value.get("expires_at"), (int, float))
                or value["expires_at"] <= clock()): return None
        return value
    except (OSError, ValueError, TypeError, AttributeError):
        return None


class PressureBackend:
    def close(self):
        return None

    def perform(self, action, value=None):
        if action == "publish":
            payload = publish(value)
            return {"message": "Pedido cooperativo publicado para agentes participantes.",
                    "request_id": payload["id"], "level": value}
        if action == "clear":
            clear()
            return {"message": "Pedido cooperativo encerrado."}
        raise ValueError("Ação cooperativa desconhecida")
