"""Cache inventory: size, regenerability, age and usage evidence (no actions)."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from .base import Adapter, AdapterResult, InventoryItem


def _measure(root: Path, *, deadline_s: float = 5.0) -> tuple[int, int, float, str]:
    total = files = 0
    newest = 0.0
    deadline = time.monotonic() + deadline_s
    stack = [root]
    while stack:
        if time.monotonic() > deadline:
            return total, files, newest, "leitura parcial: prazo esgotado"
        current = stack.pop()
        try:
            entry = current.lstat()
        except OSError as exc:
            return total, files, newest, f"ilegível: {exc}"
        if current.is_symlink():
            continue
        if current.is_file():
            total += max(0, entry.st_size)
            files += 1
            newest = max(newest, entry.st_mtime)
            continue
        if not current.is_dir():
            continue
        try:
            with os.scandir(current) as children:
                for child in children:
                    stack.append(Path(child.path))
        except OSError as exc:
            return total, files, newest, f"ilegível: {exc}"
    return total, files, newest, ""


@dataclass(frozen=True)
class CacheSpec:
    cache_id: str
    path: Path
    rebuild: str = "ferramenta recria sob demanda"


class CacheAdapter(Adapter):
    name = "caches"

    def __init__(self, roots=None, *, deadline_s: float = 5.0, clock=None):
        self._roots = [CacheSpec(root) if isinstance(root, (str, Path)) else root
                       for root in (roots if roots is not None else self._defaults())]
        self._deadline_s = deadline_s
        self._clock = clock or time.time

    @staticmethod
    def _defaults():
        cache = Path.home() / ".cache"
        return [CacheSpec("pip", cache / "pip", "pip baixa de novo"),
                CacheSpec("thumbnails", cache / "thumbnails",
                          "o gerenciador de arquivos recria"),
                CacheSpec("edge-cache", Path.home() / ".cache" / "microsoft-edge",
                          "o navegador recria após visita")]

    def inventory(self) -> AdapterResult:
        if not self._roots:
            return AdapterResult(self.name, True, reason="nenhum cache cadastrado")
        items = []
        now = self._clock()
        nested = []
        for spec in sorted(self._roots, key=lambda item: len(str(item.path))):
            path = spec.path
            if any(str(path).startswith(str(parent) + os.sep) for parent in nested):
                continue
            nested.append(path)
            try:
                path.lstat()
            except FileNotFoundError:
                items.append(InventoryItem(
                    spec.cache_id, str(path), "cache", None, True,
                    "cache ausente: não há tamanho comprovado",
                    {"rebuild": spec.rebuild}))
                continue
            except OSError as exc:
                items.append(InventoryItem(
                    spec.cache_id, str(path), "cache", None, True,
                    f"cache ilegível: {exc}", {"rebuild": spec.rebuild}))
                continue
            total, files, newest, problem = _measure(
                path, deadline_s=self._deadline_s)
            age_days = None if not newest else max(0.0, (now - newest) / 86400)
            protected = bool(problem)
            items.append(InventoryItem(
                spec.cache_id, str(path), "cache",
                None if problem else total,
                protected,
                problem or "cache regenerável; ação ainda não habilitada",
                {"files": files, "regenerable": True, "rebuild": spec.rebuild,
                 "age_days": None if age_days is None else round(age_days, 1)}))
        return AdapterResult(
            self.name, True, tuple(items),
            evidence=("tamanho observado por varredura sem seguir links",),
            reason="somente inventário; nenhum cache é apagado nesta entrega")
