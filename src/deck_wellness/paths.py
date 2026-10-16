"""XDG paths and test seams. All functions read the environment at call time
so tests can monkeypatch HOME/XDG without reimporting."""
import os
from pathlib import Path

APP_NAME = "deck-wellness"


def _env_dir(var: str, fallback: Path) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else fallback


def config_dir() -> Path:
    return xdg_config_home() / APP_NAME


def xdg_config_home() -> Path:
    return _env_dir("XDG_CONFIG_HOME", Path.home() / ".config")


def data_dir() -> Path:
    return _env_dir("XDG_DATA_HOME", Path.home() / ".local" / "share") / APP_NAME


def state_dir() -> Path:
    return _env_dir("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP_NAME


def backup_dir() -> Path:
    return data_dir() / "backups"


def tmp_dir() -> Path:
    return data_dir() / "tmp"


def tmp_quarantine_dir() -> Path:
    """Retenção de tmpfs: o destino é a SSD, nunca um tmpfs (RAM)."""
    return data_dir() / "tmp-quarantine"


def tmp_ledger_path() -> Path:
    return state_dir() / "tmp-ledger.jsonl"


def audit_log_path() -> Path:
    return state_dir() / "audit.jsonl"


def proc_root() -> str:
    return os.environ.get("DECKWELLNESS_PROC_ROOT", "/proc")


def sys_root() -> str:
    return os.environ.get("DECKWELLNESS_SYS_ROOT", "/sys")


EDGE_DIR_NAME = "microsoft-edge"


def edge_config_dir() -> Path:
    """Where Edge keeps the profile the browser rewrites on exit. Read through
    XDG at call time so an isolated HOME in a test moves the whole app."""
    return xdg_config_home() / EDGE_DIR_NAME


def edge_local_state() -> Path:
    return edge_config_dir() / "Local State"


def edge_profile_preferences(profile: str = "Default") -> Path:
    return edge_config_dir() / profile / "Preferences"
