"""libvirt inventory: paused VM is not free RAM, disks stay referenced (F7)."""
from __future__ import annotations

import shutil
import subprocess

from .base import Adapter, AdapterResult, InventoryItem


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=8,
                          check=False)


class LibvirtAdapter(Adapter):
    name = "libvirt"

    def __init__(self, *, uri: str = "", runner=None, which=None):
        self.uri = uri
        self.runner = runner or _run
        self.which = which or shutil.which

    def _argv(self, *args: str) -> list[str]:
        base = ["virsh"]
        if self.uri:
            base.extend(["--connect", self.uri])
        base.extend(["-r", *args])
        return base

    def inventory(self) -> AdapterResult:
        if not self.which("virsh"):
            return AdapterResult("libvirt", False,
                                 reason="virsh não instalado; inventário "
                                        "indisponível")
        try:
            listing = self.runner(self._argv("list", "--all", "--name"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            return AdapterResult("libvirt", False, error=str(exc),
                                 reason="libvirt não respondeu")
        if listing.returncode != 0:
            return AdapterResult(
                "libvirt", False, error=listing.stderr.strip(),
                reason=f"URI {self.uri or 'padrão'} inacessível; nenhum domínio "
                       "foi misturado")
        items = []
        for name in [line.strip() for line in listing.stdout.splitlines()
                     if line.strip()]:
            try:
                state = self.runner(self._argv("domstate", name))
                blocks = self.runner(self._argv("domblklist", name))
            except (OSError, subprocess.TimeoutExpired) as exc:
                items.append(InventoryItem(
                    f"libvirt/{self.uri or 'default'}/domain/{name}", name,
                    "domain", None, True, f"estado ilegível: {exc}",
                    {"uri": self.uri, "state": "unknown"}))
                continue
            state_text = (state.stdout.strip().splitlines()[0]
                          if state.returncode == 0 and state.stdout.strip()
                          else "unknown")
            paused = state_text.lower() == "paused"
            items.append(InventoryItem(
                f"libvirt/{self.uri or 'default'}/domain/{name}", name,
                "domain", None, True,
                ("VM pausada: a RAM não é liberada por inventário"
                 if paused else "operação via gerenciador; nenhuma ação automática"),
                {"uri": self.uri, "state": state_text,
                 "ram_reclaimed": False}))
            if blocks.returncode != 0:
                items.append(InventoryItem(
                    f"libvirt/{self.uri or 'default'}/domain/{name}/disks",
                    f"discos de {name}", "disk", None, True,
                    "lista de discos ilegível; preservada", {"uri": self.uri}))
                continue
            for line in blocks.stdout.splitlines():
                fields = line.split()
                if len(fields) < 2 or fields[0].lower() == "target":
                    continue
                source = fields[1]
                if source in ("-", ""):
                    continue
                items.append(InventoryItem(
                    f"libvirt/{self.uri or 'default'}/disk/{source}",
                    source, "disk", None, True,
                    "disco referenciado por VM; base/backing preservados",
                    {"uri": self.uri, "domain": name,
                     "backing_verified": False}))
        return AdapterResult(
            "libvirt", True, tuple(items),
            evidence=(f"URI: {self.uri or 'padrão'}", "virsh -r list --all",
                      "domstate", "domblklist"),
            reason="somente inventário; snapshots e discos exigem revisão manual")
