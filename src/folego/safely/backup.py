"""Backup store: byte-exact originals + manifest, with integrity-checked restore.

Layout: <root>/<action_id>/<ts>-<uid>/{manifest.json, files/NNN.bin}
Restore verifies the payload's sha256 against the manifest *before* writing,
so a tampered/corrupted backup can never overwrite a live file. Creation is
private (dirs 0700, files 0600) and durable (fsync payload, manifest and every
directory that names them); a backup that a crash can lose is not a backup.
"""
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import hashing
from .atomicfile import fsync_dir, write_atomic


@dataclass(frozen=True)
class BackupEntry:
    target: Path
    sha_after_expected: str | None


@dataclass(frozen=True)
class RestoreResult:
    target: Path
    ok: bool
    sha: str | None = None
    error: str | None = None


class BackupStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def path_of(self, backup_id: str) -> Path:
        action, tail = backup_id.split("/", 1)
        return self.root / action / tail

    def create(self, action_id: str, entries: list[BackupEntry]) -> str:
        if "/" in action_id or not action_id:
            raise ValueError(f"invalid action_id: {action_id!r}")
        for e in entries:
            if not e.target.is_file():
                raise FileNotFoundError(f"backup target missing: {e.target}")

        backup_id = f"{action_id}/{int(time.time())}-{uuid.uuid4().hex[:8]}"
        bdir = self.path_of(backup_id)
        (bdir / "files").mkdir(parents=True)
        # o backup guarda cópias do perfil (que pode conter tokens): nem grupo nem
        # outros leem — e o modo é explícito, não o que a umask do dia deixar
        for directory in (self.root, self.root / action_id, bdir, bdir / "files"):
            os.chmod(directory, 0o700)

        manifest = {
            "backup_id": backup_id,
            "action_id": action_id,
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "entries": [],
        }
        for i, e in enumerate(entries):
            data, sha_before = hashing.read_hashed(e.target)
            st = e.target.stat()
            stored = f"files/{i:03d}.bin"
            _write_private(bdir / stored, data)
            manifest["entries"].append({
                "index": i,
                "target": str(e.target),
                "sha_before": sha_before,
                "sha_after_expected": e.sha_after_expected,
                "mode": st.st_mode & 0o777,
                "mtime_ns": st.st_mtime_ns,
                "size": st.st_size,
                "stored": stored,
            })
        _write_private(bdir / "manifest.json",
                       json.dumps(manifest, indent=2).encode("utf-8"))
        # o apply só escreve depois de o backup terminar; se faltar energia logo
        # após, cada byte e cada diretório que o nomeia precisa estar no disco
        for directory in (bdir / "files", bdir, bdir.parent, self.root):
            fsync_dir(directory)
        return backup_id

    def list_backups(self, action_id: str) -> list[str]:
        base = self.root / action_id
        if not base.is_dir():
            return []
        names = sorted(p.name for p in base.iterdir() if (p / "manifest.json").is_file())
        return [f"{action_id}/{n}" for n in names]

    def latest_backup_id(self, action_id: str) -> str | None:
        ids = self.list_backups(action_id)
        return ids[-1] if ids else None

    def read_manifest(self, backup_id: str) -> dict:
        return json.loads((self.path_of(backup_id) / "manifest.json").read_text())

    def restore(self, backup_id: str) -> list[RestoreResult]:
        bdir = self.path_of(backup_id)
        manifest = self.read_manifest(backup_id)
        results = []
        for entry in manifest["entries"]:
            target = Path(entry["target"])
            payload = bdir / entry["stored"]
            data, actual_sha = hashing.read_hashed(payload)
            if actual_sha != entry["sha_before"]:
                results.append(RestoreResult(
                    target, False, error="backup payload integrity check failed"))
                continue
            write_atomic(target, data)
            _, after = hashing.read_hashed(target)
            if after != entry["sha_before"]:
                results.append(RestoreResult(target, False, error="post-restore verify failed"))
                continue
            results.append(RestoreResult(target, True, sha=after))
        return results


def _write_private(path: Path, data: bytes) -> None:
    """0600 + fsync: um backup nunca nasce legível pelo grupo nem só em cache."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
