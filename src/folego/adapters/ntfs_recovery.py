"""Bounded, read-only preflight for an offline NTFS rescue image.

This is a planning probe. It never opens the source block device or the NTFS
mount and never treats a preflight result as authorization for a later effect.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

_MIN_MARGIN = 10 * 1024**3
_PERSISTENT = {"btrfs", "ext4", "xfs"}


def _run(argv: list[str]) -> dict:
    try:
        result = subprocess.run(argv, text=True, capture_output=True,
                                timeout=3, check=False)
        if result.returncode != 0 or len(result.stdout) > 65536:
            raise ValueError("inventário de volumes indisponível ou excessivo")
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"não foi possível confirmar os volumes: {exc}") from exc


def _device_rows(data: dict) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    pending = list(data.get("blockdevices", []))
    while pending:
        row = pending.pop()
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("inventário de dispositivos inválido")
        if row["path"] in rows or len(rows) >= 256:
            raise ValueError("inventário de dispositivos duplicado ou excessivo")
        rows[row["path"]] = row
        pending.extend(row.get("children") or [])
    return rows


def _physical_disk(path: str, rows: dict[str, dict]) -> str:
    seen = set()
    current = path
    while current in rows and current not in seen:
        seen.add(current)
        row = rows[current]
        parent = row.get("pkname")
        if not parent:
            if row.get("type") != "disk" or current.startswith("/dev/loop"):
                raise ValueError("dispositivo físico não comprovado")
            return current
        current = "/dev/" + str(parent)
    raise ValueError("ancestral físico do dispositivo desconhecido")


def assess_ntfs_recovery(source: str, destination: str | None = None, *,
                         run=_run, access=os.access, statvfs=os.statvfs,
                         which=shutil.which) -> dict:
    """Explain prerequisites for imaging without touching either filesystem data."""
    blockers: list[str] = []
    source_path = os.path.realpath(source)
    result = {"source": source_path, "destination": destination,
              "can_image": False, "blockers": blockers,
              "source_size_bytes": None, "required_free_bytes": None,
              "destination_free_bytes": None, "source_uuid": None}
    try:
        rows = _device_rows(run(["lsblk", "--json", "--bytes", "--output",
                                 "PATH,PKNAME,SIZE,FSTYPE,UUID,TYPE,MOUNTPOINTS,RO,RM"]))
    except (ValueError, TypeError) as exc:
        blockers.append(str(exc))
        return result
    volume = rows.get(source_path)
    if (volume is None or volume.get("type") not in ("part", "disk")
            or str(volume.get("fstype", "")).lower() != "ntfs"):
        blockers.append("origem NTFS em bloco não identificada")
        return result
    size = volume.get("size")
    uuid = volume.get("uuid")
    if type(size) is not int or size <= 0 or not isinstance(uuid, str) or not uuid:
        blockers.append("identidade ou tamanho da origem desconhecido")
        return result
    result["source_size_bytes"] = size
    result["source_uuid"] = uuid
    required = size + max(_MIN_MARGIN, size // 20)
    result["required_free_bytes"] = required
    if volume.get("mountpoints"):
        blockers.append("origem ainda montada; desmontagem segura depende dos consumidores")
    if not access(source_path, os.R_OK):
        blockers.append("leitura bruta da origem requer autenticação do sistema")
    if not which("ddrescue"):
        blockers.append("GNU ddrescue não disponível no ambiente")
    if not destination:
        blockers.append("destino externo persistente não informado")
        return result
    target = Path(destination)
    try:
        if target.is_symlink() or not target.is_dir():
            raise ValueError("destino ausente, não é diretório ou é link simbólico")
        resolved = str(target.resolve(strict=True))
        mount = run(["findmnt", "--json", "--target", resolved,
                     "--output", "SOURCE,FSTYPE,TARGET"]).get("filesystems", [])
        if len(mount) != 1 or not isinstance(mount[0], dict):
            raise ValueError("montagem do destino não comprovada")
        dest_source = mount[0].get("source", "").split("[", 1)[0]
        dest_fs = mount[0].get("fstype")
        if dest_fs not in _PERSISTENT or dest_source not in rows:
            raise ValueError("persistência e dispositivo do destino não comprovados")
        if not access(resolved, os.W_OK):
            raise ValueError("destino sem permissão de escrita")
        source_disk = _physical_disk(source_path, rows)
        destination_disk = _physical_disk(dest_source, rows)
        if source_disk == destination_disk:
            raise ValueError("destino está no mesmo dispositivo físico da origem")
        usage = statvfs(resolved)
        free = usage.f_bavail * usage.f_frsize
        result["destination"] = resolved
        result["destination_free_bytes"] = free
        if free < required:
            blockers.append("espaço insuficiente para imagem integral e margem")
    except (OSError, TypeError, AttributeError, ValueError) as exc:
        blockers.append(f"destino não confirmado: {exc}")
    result["can_image"] = not blockers
    return result
