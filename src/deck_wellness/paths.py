"""XDG paths and test seams. All functions read the environment at call time
so tests can monkeypatch HOME/XDG without reimporting."""
import os
from pathlib import Path

APP_NAME = "deck-wellness"


def _env_dir(var: str, fallback: Path) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else fallback


def config_dir() -> Path:
    return _env_dir("XDG_CONFIG_HOME", Path.home() / ".config") / APP_NAME


def data_dir() -> Path:
    return _env_dir("XDG_DATA_HOME", Path.home() / ".local" / "share") / APP_NAME


def state_dir() -> Path:
    return _env_dir("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP_NAME


def backup_dir() -> Path:
    return data_dir() / "backups"


def tmp_dir() -> Path:
    return data_dir() / "tmp"


def audit_log_path() -> Path:
    return state_dir() / "audit.jsonl"


def proc_root() -> str:
    return os.environ.get("DECKWELLNESS_PROC_ROOT", "/proc")


def sys_root() -> str:
    return os.environ.get("DECKWELLNESS_SYS_ROOT", "/sys")
