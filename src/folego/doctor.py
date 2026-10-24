"""Read-only `doctor` (F8): capabilities, state schemas, permissions, tools.

No check creates a directory, writes a lock or starts a child. Missing optional
tools are warnings, not crashes; a corrupt state file is an error because the
mutation gate must refuse until it is repaired.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import platform
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .core.exclusions import ExclusionError, ExclusionList
from .core.sessions import SessionError, SessionRegistry
from .orchestration.config import ConfigError, ConfigStore
from .orchestration.grants import GrantError, GrantStore
from .orchestration.journal import Journal
from .safely.audit import AuditLog

OK = "ok"
WARN = "warn"
ERROR = "error"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[Check, ...]

    @property
    def errors(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if check.status == ERROR)

    @property
    def warnings(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if check.status == WARN)

    @property
    def status(self) -> str:
        if self.errors:
            return ERROR
        if self.warnings:
            return WARN
        return OK

    def to_dict(self) -> dict:
        return {"status": self.status, "checks": [c.to_dict() for c in self.checks],
                "errors": len(self.errors), "warnings": len(self.warnings)}


def _permission_check(path: Path) -> Check:
    target = path
    while not target.exists() and target != target.parent:
        target = target.parent
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except OSError as exc:
        return Check(f"permissões {path}", UNKNOWN, f"não foi possível ler: {exc}")
    if not os.access(target, os.W_OK):
        return Check(f"permissões {path}", WARN,
                     f"{target} ({mode:o}) não é gravável pelo usuário")
    if path == target and mode & 0o077:
        return Check(f"permissões {path}", WARN,
                     f"{target} ({mode:o}) é legível por outros usuários")
    return Check(f"permissões {path}", OK,
                 f"{target} ({mode:o}) gravável sem exposição ampla")


def _schema_checks() -> list[Check]:
    checks = []
    try:
        ConfigStore().read()
        checks.append(Check("schema automação", OK, "config válida ou ausente"))
    except ConfigError as exc:
        checks.append(Check("schema automação", ERROR, str(exc)))
    try:
        GrantStore().list()
        checks.append(Check("schema grants", OK, "registro válido ou ausente"))
    except GrantError as exc:
        checks.append(Check("schema grants", ERROR, str(exc)))
    try:
        SessionRegistry().snapshot()
        checks.append(Check("schema sessões", OK, "registro válido ou ausente"))
    except SessionError as exc:
        checks.append(Check("schema sessões", ERROR, str(exc)))
    try:
        ExclusionList().list()
        checks.append(Check("schema exclusões", OK, "registro válido ou ausente"))
    except ExclusionError as exc:
        checks.append(Check("schema exclusões", ERROR, str(exc)))
    try:
        _, problems = Journal().load()
        if problems:
            checks.append(Check("schema diário", ERROR,
                                f"{len(problems)} problema(s): {problems[0]}"))
        else:
            checks.append(Check("schema diário", OK, "diário íntegro ou ausente"))
    except OSError as exc:
        checks.append(Check("schema diário", ERROR, f"ilegível: {exc}"))
    return checks


def _tool_check(name: str, required: bool = False) -> Check:
    found = shutil.which(name)
    if found:
        return Check(f"ferramenta {name}", OK, found)
    status = ERROR if required else WARN
    return Check(f"ferramenta {name}", status,
                 "não instalada" + ("" if required else " (opcional)"))


def _qt_check() -> Check:
    if importlib.util.find_spec("PySide6") is None:
        return Check("Qt/PySide6", WARN,
                     "não instalado; a GUI fica indisponível, o CLI continua")
    try:
        version = importlib.metadata.version("PySide6")
    except importlib.metadata.PackageNotFoundError:
        version = "presente sem metadados"
    return Check("Qt/PySide6", OK, version)


def _desktop_check() -> Check:
    session = os.environ.get("XDG_SESSION_TYPE", "")
    display = os.environ.get("DISPLAY", "")
    wayland = os.environ.get("WAYLAND_DISPLAY", "")
    if not session and not display and not wayland:
        return Check("sessão gráfica", UNKNOWN,
                     "sem XDG_SESSION_TYPE/DISPLAY/WAYLAND_DISPLAY")
    return Check("sessão gráfica", OK,
                 f"tipo={session or 'desconhecido'} display={display or '—'} "
                 f"wayland={wayland or '—'}")


def _autostart_check() -> Check:
    path = paths.autostart_path()
    if not path.exists():
        return Check("autostart", OK, f"desativado (ausente: {path})")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return Check("autostart", WARN, f"presente mas ilegível: {exc}")
    if "Hidden=true" in text:
        return Check("autostart", OK, f"presente e oculto: {path}")
    return Check("autostart", WARN,
                 f"presente; revise Exec/Hidden antes de confiar: {path}")


def _instance_check() -> Check:
    path = paths.instance_lock_path()
    if not path.exists():
        return Check("instância GUI", OK, "nenhuma trava existente")
    try:
        text = path.read_text(encoding="ascii").strip()
    except OSError as exc:
        return Check("instância GUI", UNKNOWN, f"trava ilegível: {exc}")
    if not text.isdigit():
        return Check("instância GUI", UNKNOWN, "trava sem PID legível")
    pid = int(text)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return Check("instância GUI", OK, f"trava órfã de pid {pid} (não removida)")
    except PermissionError:
        return Check("instância GUI", OK, f"trava de pid {pid} pertence a outro usuário")
    return Check("instância GUI", OK, f"GUI em execução (pid {pid})")


def _audit_check() -> Check:
    try:
        status = AuditLog().status()
    except OSError as exc:
        return Check("auditoria", UNKNOWN, f"não foi possível medir: {exc}")
    if status["active_over_budget"] or status["archive_over_budget"]:
        return Check(
            "auditoria", WARN,
            f"ativo {status['active_bytes']}/{status['max_bytes']} bytes · "
            f"arquivos {status['archive_bytes']}/{status['archive_max_bytes']} "
            "bytes · rode `folego logs rotate --confirmar`")
    return Check(
        "auditoria", OK,
        f"ativo {status['active_bytes']}/{status['max_bytes']} bytes · "
        f"{status['archive_count']} arquivo(s) preservado(s)")


def collect() -> DoctorReport:
    from .core.runtime import discover_runtime
    from .safely.jobtemp import prevention_status
    runtime = discover_runtime()
    prevention = prevention_status()
    checks = [
        Check("runtime da sessão", OK if runtime.valid else UNKNOWN,
              runtime.path if runtime.valid else runtime.reason),
        Check("temporários de novos filhos", WARN if prevention["inherited_runtime_tmpdir"] else OK,
              prevention["message"]),
        Check("python", OK, f"{platform.python_version()} ({sys.executable})"),
        Check("plataforma", OK, platform.platform()),
        _qt_check(),
        _permission_check(paths.state_dir()),
        _permission_check(paths.data_dir()),
        _permission_check(paths.config_dir()),
        _desktop_check(),
        _autostart_check(),
        _instance_check(),
        _audit_check(),
        _tool_check("git"),
        _tool_check("docker"),
        _tool_check("podman"),
        _tool_check("virsh"),
        _tool_check("qemu-img"),
    ]
    checks.extend(_schema_checks())
    return DoctorReport(tuple(checks))
