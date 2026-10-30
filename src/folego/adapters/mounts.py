"""External mount inventory: identify, never unmount or delete by extension (F7)."""
from __future__ import annotations

import os
from pathlib import Path

from .base import Adapter, AdapterResult, InventoryItem

DEFAULT_PREFIXES = ("/media/", "/run/media/", "/mnt/")


def _unescape(value: str) -> str:
    return (value.replace("\\040", " ").replace("\\011", "\t")
            .replace("\\012", "\n").replace("\\134", "\\"))


class MountAdapter(Adapter):
    name = "mounts"

    def __init__(self, path: Path | None = None, *, prefixes=DEFAULT_PREFIXES,
                 extra_paths=()):
        self.path = Path(path) if path else Path(
            os.environ.get("DECKWELLNESS_MOUNTINFO", "/proc/self/mountinfo"))
        self.prefixes = tuple(prefixes) + tuple(extra_paths)

    def inventory(self) -> AdapterResult:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return AdapterResult(self.name, False, error=str(exc),
                                 reason="mountinfo ilegível; nenhum volume "
                                        "foi presumido")
        items = []
        for line in lines:
            fields = line.split()
            if "-" not in fields:
                continue
            try:
                separator = fields.index("-")
            except ValueError:
                continue
            if len(fields) < separator + 3 or len(fields) < 5:
                continue
            mount_point = _unescape(fields[4])
            if not any(mount_point.startswith(prefix)
                       for prefix in self.prefixes):
                continue
            fs_type = fields[separator + 1]
            source = _unescape(fields[separator + 2])
            identity = fields[2]
            items.append(InventoryItem(
                f"mount/{identity}/{mount_point}", mount_point, "mount", None,
                True,
                "revisão manual: nenhum unmount ou exclusão por extensão/idade",
                {"fs_type": fs_type, "source": source, "identity": identity}))
        return AdapterResult(
            self.name, True, tuple(items),
            evidence=(str(self.path), "prefixos " + ", ".join(self.prefixes)),
            reason="somente inventário; montagens externas nunca são desmontadas "
                   "automaticamente")
