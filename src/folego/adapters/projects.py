"""Projects/Git inventory: dirty worktrees and locks are evidence, not a plan."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from .base import Adapter, AdapterResult, InventoryItem

CONFIG_VERSION = 1


@dataclass(frozen=True)
class ProjectSpec:
    project_id: str
    path: Path


class ProjectConfigError(Exception):
    pass


def load_projects(path: Path | None = None) -> list[ProjectSpec]:
    path = path or paths.projects_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("version") != CONFIG_VERSION:
            raise ProjectConfigError("versão de projetos não suportada")
        rows = raw.get("projects")
        if not isinstance(rows, list):
            raise ProjectConfigError("projetos não são uma lista")
        specs = []
        for row in rows:
            if not isinstance(row, dict):
                raise ProjectConfigError("projeto não é objeto")
            value = row.get("path")
            if not isinstance(value, str) or not value:
                raise ProjectConfigError("projeto sem caminho")
            specs.append(ProjectSpec(str(row.get("id") or value),
                                     Path(value).expanduser()))
        return specs
    except (OSError, ValueError, TypeError) as exc:
        raise ProjectConfigError(f"registro de projetos ilegível: {exc}") from exc


def _run_git(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=5,
                          check=False)


class ProjectAdapter(Adapter):
    name = "projects"

    def __init__(self, projects=None, *, runner=None, config_path=None):
        self._explicit = projects is not None
        self._projects = list(projects or [])
        self._config_path = config_path
        self._runner = runner or _run_git

    def _load(self):
        if self._explicit:
            return self._projects
        return load_projects(self._config_path)

    def inventory(self) -> AdapterResult:
        try:
            projects = self._load()
        except ProjectConfigError as exc:
            return AdapterResult(self.name, True, error=str(exc),
                                 reason="registro ilegível; nenhum projeto lido")
        if not projects:
            return AdapterResult(self.name, True,
                                 reason="nenhum projeto cadastrado")
        git = shutil.which("git")
        items = []
        for spec in projects:
            path = Path(spec.path)
            lock = path / ".git" / "index.lock"
            if not path.exists():
                items.append(InventoryItem(
                    spec.project_id, str(path), "project", None, True,
                    "projeto ausente: nada pode ser concluído"))
                continue
            if lock.exists():
                items.append(InventoryItem(
                    spec.project_id, str(path), "project", None, True,
                    "índice do Git travado (.git/index.lock); trabalho em curso",
                    {"lock": str(lock)}))
                continue
            if not git:
                items.append(InventoryItem(
                    spec.project_id, str(path), "project", None, True,
                    "git indisponível: estado do trabalho não comprovado"))
                continue
            try:
                status = self._runner([git, "-C", str(path), "status",
                                       "--porcelain=v1", "--branch"])
            except (OSError, subprocess.TimeoutExpired) as exc:
                items.append(InventoryItem(
                    spec.project_id, str(path), "project", None, True,
                    f"git ilegível: {exc}"))
                continue
            if status.returncode != 0:
                items.append(InventoryItem(
                    spec.project_id, str(path), "project", None, True,
                    "não é um worktree Git legível: " +
                    (status.stderr.strip() or "sem detalhe")))
                continue
            lines = [line for line in status.stdout.splitlines() if line]
            branch = ""
            changes = []
            for line in lines:
                if line.startswith("## "):
                    branch = line[3:].split("...", 1)[0].strip()
                else:
                    changes.append(line)
            dirty = bool(changes)
            worktrees = 0
            try:
                wt = self._runner([git, "-C", str(path), "worktree", "list",
                                   "--porcelain"])
                if wt.returncode == 0:
                    worktrees = sum(1 for line in wt.stdout.splitlines()
                                    if line.startswith("worktree "))
            except (OSError, subprocess.TimeoutExpired):
                pass
            reason = ("trabalho não salvo; preservado até declaração explícita"
                      if dirty else "worktree limpo; ação ainda não habilitada")
            items.append(InventoryItem(
                spec.project_id, str(path), "project", None, dirty, reason,
                {"branch": branch, "dirty_entries": len(changes),
                 "worktrees": worktrees,
                 "regenerable": False}))
        return AdapterResult(
            self.name, True, tuple(items),
            evidence=("git status --porcelain --branch", "git worktree list"),
            reason="somente inventário; nenhum projeto é descartado")
