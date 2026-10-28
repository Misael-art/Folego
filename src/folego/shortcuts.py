"""Launcher shortcuts in the application menu and on the Desktop — never autostart.

`ensure()` runs on every GUI start: it creates a missing shortcut, refreshes one that
Fôlego created earlier when the installation moved, and preserves any file it did not
create (a user's own launcher is reported, never overwritten). Only the two launcher
locations are touched; ~/.config/autostart stays out of scope by contract.
"""
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from . import paths

FILENAME = "folego.desktop"
MARKER = "X-Folego-Managed=true"
# Characters the desktop-entry Exec quoting subset cannot express safely.
_UNSAFE = re.compile(r'[\n\r\x00"\\`$%]')

TEMPLATE = """[Desktop Entry]
Type=Application
Version=1.0
Name=Fôlego
GenericName=Monitor de recursos
Comment=Diagnóstico e higiene reversível de RAM, CPU e disco
Exec="{executable}"
TryExec={executable}
Icon=utilities-system-monitor
Terminal=false
Categories=System;Monitor;
Keywords=memoria;ram;cpu;disco;steamdeck;kde;
StartupNotify=true
{marker}
"""


@dataclass(frozen=True)
class ShortcutState:
    location: str
    path: str
    status: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {"location": self.location, "path": self.path, "status": self.status, "detail": self.detail}


def launcher_executable() -> Path | None:
    """The absolute program a shortcut must start: the checkout's run.sh, or the installed entrypoint."""
    checkout = Path(__file__).resolve().parents[2]
    run_sh = checkout / "run.sh"
    if run_sh.is_file() and (checkout / "dev").is_file() and os.access(run_sh, os.X_OK):
        return run_sh
    argv0 = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
    if argv0 and argv0.name == "folego" and argv0.is_file() and os.access(argv0, os.X_OK):
        return argv0
    found = shutil.which("folego")
    return Path(found).resolve() if found else None


def desktop_dir() -> Path:
    """XDG_DESKTOP_DIR from user-dirs.dirs (localized, e.g. "Área de trabalho"), else ~/Desktop."""
    config = paths.xdg_config_home() / "user-dirs.dirs"
    try:
        for line in config.read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r'\s*XDG_DESKTOP_DIR="(.*)"\s*', line)
            if match:
                value = match.group(1).replace("$HOME", str(Path.home()))
                if Path(value).is_absolute() and Path(value) != Path.home():
                    return Path(value)
    except OSError:
        pass
    return Path.home() / "Desktop"


def applications_dir() -> Path:
    return paths._env_dir("XDG_DATA_HOME", Path.home() / ".local" / "share") / "applications"


def entry_text(executable: Path) -> str:
    if _UNSAFE.search(str(executable)):
        raise ValueError("caminho do executável exige escape não suportado no Exec")
    return TEMPLATE.format(executable=executable, marker=MARKER)


def _write(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    # Plasma only runs Desktop launchers that are executable (trusted) by the owner.
    tmp.chmod(0o755)
    os.replace(tmp, target)


def ensure(*, executable: Path | None = None, locations=None) -> tuple:
    """Create or refresh the managed shortcuts; preserve anything else. Returns one state per location."""
    executable = executable or launcher_executable()
    locations = locations or (("menu", applications_dir()), ("desktop", desktop_dir()))
    if executable is None:
        return tuple(ShortcutState(name, str(folder / FILENAME), "skipped", "executável do Fôlego não encontrado")
                     for name, folder in locations)
    text = entry_text(executable)
    states = []
    for name, folder in locations:
        target = folder / FILENAME
        try:
            if target.is_symlink() or (target.exists() and not target.is_file()):
                states.append(ShortcutState(name, str(target), "preserved", "não é arquivo regular"))
                continue
            if target.is_file():
                current = target.read_text(encoding="utf-8", errors="replace")
                if MARKER not in current:
                    states.append(ShortcutState(name, str(target), "preserved", "atalho do usuário; não alterado"))
                    continue
                if current == text and os.access(target, os.X_OK):
                    states.append(ShortcutState(name, str(target), "present"))
                    continue
                _write(target, text)
                states.append(ShortcutState(name, str(target), "updated", f"aponta para {executable}"))
                continue
            if name == "desktop" and not folder.is_dir():
                states.append(ShortcutState(name, str(target), "skipped", "pasta da Área de trabalho inexistente"))
                continue
            _write(target, text)
            states.append(ShortcutState(name, str(target), "created", f"aponta para {executable}"))
        except OSError as exc:
            states.append(ShortcutState(name, str(target), "failed", f"{type(exc).__name__}: {exc}"))
    return tuple(states)
