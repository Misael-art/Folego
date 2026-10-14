import hashlib
import os
from pathlib import Path

import pytest

REAL_EDGE_LOCAL_STATE = Path.home() / ".config" / "microsoft-edge" / "Local State"


def _edge_tripwire_state():
    if not REAL_EDGE_LOCAL_STATE.exists():
        return None
    st = REAL_EDGE_LOCAL_STATE.stat()
    return (st.st_mtime_ns, hashlib.sha256(REAL_EDGE_LOCAL_STATE.read_bytes()).hexdigest())


@pytest.fixture(scope="session", autouse=True)
def never_touch_real_edge_config():
    """Tripwire: the suite must never modify the real user's Edge config."""
    before = _edge_tripwire_state()
    yield
    after = _edge_tripwire_state()
    assert before == after, "test suite touched ~/.config/microsoft-edge/Local State"


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Isolated HOME + XDG dirs; every path resolved through deck_wellness.paths lands here."""
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.delenv("DECKWELLNESS_PROC_ROOT", raising=False)
    monkeypatch.delenv("DECKWELLNESS_SYS_ROOT", raising=False)
    return home


@pytest.fixture
def fake_proc(tmp_path, monkeypatch):
    root = tmp_path / "proc"
    root.mkdir()
    monkeypatch.setenv("DECKWELLNESS_PROC_ROOT", str(root))
    return root
