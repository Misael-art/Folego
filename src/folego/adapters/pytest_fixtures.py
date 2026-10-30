"""Read-only diagnosis of legacy pytest fixtures in the session runtime.

Convention discovery is not registration or proof of a managed lifecycle. Every
item stays protected; this adapter has no archive/delete method.
"""
import os
import pwd
import re
import stat
from pathlib import Path

from .base import Adapter, AdapterResult, InventoryItem, unavailable
from ..core.runtime import discover_runtime
from ..actions.tmpfs.holders import holder_index


def _lock_present(path):
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


class PytestFixtureAdapter(Adapter):
    name = "pytest-fixtures"

    def __init__(self, *, runtime=None, proc_root=None, holders_fn=holder_index, max_items=256):
        self.runtime = runtime
        self.proc_root = proc_root
        self.holders_fn = holders_fn
        self.max_items = max_items

    def inventory(self):
        location = discover_runtime(env={"XDG_RUNTIME_DIR": str(self.runtime)}) if self.runtime else discover_runtime()
        if not location.valid:
            return unavailable(self.name, location.reason)
        runtime = Path(location.path)
        username = pwd.getpwuid(os.getuid()).pw_name
        root = runtime / "codex-desktop/tmp" / f"pytest-of-{username}"
        try:
            for path in (runtime / "codex-desktop", root.parent, root):
                info = path.lstat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                    return unavailable(self.name, "raiz/ancestral pytest não privado ou identidade desconhecida")
            current_path = root / "pytest-current"
            current = None
            current_error = ""
            try:
                target = os.readlink(current_path)
                candidate = Path(os.path.abspath(root / target))
                if candidate.parent != root or not re.fullmatch(r"pytest-\d+", candidate.name):
                    current_error = "pytest-current fora da raiz reconhecida"
                elif not candidate.is_dir() or candidate.is_symlink():
                    current_error = "pytest-current aponta a fixture ausente/ambígua"
                else:
                    current = candidate.name
            except FileNotFoundError:
                pass
            except OSError as exc:
                current_error = f"pytest-current ilegível: {exc}"
            names = []
            truncated = False
            with os.scandir(root) as entries:
                for entry in entries:
                    if len(names) >= self.max_items:
                        truncated = True
                        break
                    names.append(entry.name)
            holders = self.holders_fn(proc_root=self.proc_root, prefixes=(str(root),),
                                      include_process_refs=True)
            items = []
            for name in sorted(names):
                if not re.fullmatch(r"pytest-\d+", name):
                    continue
                path = root / name
                info = path.lstat()
                refs = tuple(sorted(holders.pids_holding(str(path))))
                state = "legacy_review"
                reason = "fixture legada; ciclo de vida e exclusão de novos escritores não comprovados"
                if current_error:
                    state, reason = "unknown", current_error
                elif not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                    state, reason = "unknown", "tipo/dono desconhecido ou simbólico"
                elif name == current:
                    state, reason = "current", "fixture atual: preservada"
                elif _lock_present(path / ".lock"):
                    state, reason = "locked", "lock presente; atividade/identidade não descartada"
                elif refs:
                    state, reason = "referenced", "referência por fd/cwd/maps: preservada"
                elif holders.state != "complete" or holders.proc_count == 0:
                    state, reason = "unknown", "referências de processos incompletas: preservada"
                items.append(InventoryItem(
                    f"{info.st_dev}:{info.st_ino}", str(path), "pytest-fixture", protected=True,
                    reason=reason, detail={"state": state, "pids": list(refs),
                                          "root_registered": False, "automatic_eligible": False,
                                          "holder_state": holders.state}))
            return AdapterResult(self.name, True, tuple(items),
                                 evidence=(str(root), "descoberta somente leitura; não concede autoridade"),
                                 reason="todas as fixtures preservadas; arquivamento indisponível",
                                 error="inventário truncado" if truncated else current_error)
        except OSError as exc:
            return unavailable(self.name, f"inventário pytest não comprovado: {exc}")
