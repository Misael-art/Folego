"""F4 layout floor: the central must fit 800x600 and the tested desktop sizes.

These are offscreen geometry checks, not a substitute for KDE/Wayland visual
validation. They exist to catch the concrete regression where a long label made
the window refuse to shrink below 1008 px.
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

from fixtures_automation import stores

pytest.importorskip("PySide6")

REPO = pathlib.Path(__file__).resolve().parent.parent


class _Jobs:
    def run(self, *args, **kwargs):
        pass

    def shutdown(self):
        pass


class _Sessions:
    def snapshot(self):
        return ()


class _Exclusions:
    def list(self):
        return ()


class _Journal:
    def load(self):
        return [], []


@pytest.fixture
def window(qapp):
    from folego.ui.main_window import MainWindow
    config_store, grant_store = stores()
    win = MainWindow(collector_factory=None, jobs=_Jobs(), disk_jobs=_Jobs(),
                     tmpfs_jobs=_Jobs(), sessions=_Sessions(),
                     exclusions=_Exclusions(), journal=_Journal(),
                     config_store=config_store, grant_store=grant_store)
    yield win
    win.close()


@pytest.mark.parametrize("size", [(800, 600), (1280, 800), (1920, 1080)])
def test_the_window_fits_the_required_sizes(window, qapp, size):
    window.resize(*size)
    window.show()
    qapp.processEvents()

    assert (window.width(), window.height()) == size
    for index in range(window.tabs.count()):
        tab = window.tabs.widget(index)
        assert tab.minimumSizeHint().width() <= size[0], window.tabs.tabText(index)


def test_custom_controls_have_accessible_names(window):
    assert window.dashboard.resources.accessibleName()
    assert window.dashboard.copy_button.accessibleName()
    assert window.disk.quarantine_button.accessibleName()
    assert window.orphans.protections_label.accessibleName()


def test_critical_runtime_and_browser_group_still_fit_800_pixels(window, qapp):
    from folego.core.orphans import GroupMember, GroupTarget
    from folego.core.tmpfs import TmpfsVolume
    from test_ui_main_window_tabs import snap
    window.apply_snapshot(snap(tmpfs=(TmpfsVolume("/run/user/fixture", "tmpfs",
        1000, 990, 10, is_runtime=True),)))
    window.orphans.show_groups((GroupTarget("chrome", "Google Chrome/Chromium",
        (GroupMember(800, "chrome", 3_000_000, 11, 800),)),))
    window.resize(800, 600)
    window.show()
    qapp.processEvents()
    assert window.width() == 800
    assert "Runtime da sessão crítico" in window.dashboard.headline.text()
    assert window.minimumSizeHint().width() <= 800


def test_the_scale_factor_subprocess_keeps_the_same_logical_floor(tmp_path):
    """150/200% scaling is exercised in a fresh Qt app, not the shared qapp."""
    code = """
import json, sys
from PySide6.QtWidgets import QApplication
from folego.ui.main_window import MainWindow
class J:
    def run(self, *a, **k): pass
    def shutdown(self): pass
class S:
    def snapshot(self): return ()
class E:
    def list(self): return ()
class Jr:
    def load(self): return [], []
class C:
    def read(self): return type("S", (), {"mode": "manual", "preset": "equilibrado",
                                         "paused": False, "updated_at": 0.0})()
class G:
    def for_action(self, action, **kw): return []
app = QApplication([])
w = MainWindow(collector_factory=None, jobs=J(), disk_jobs=J(), tmpfs_jobs=J(),
               sessions=S(), exclusions=E(), journal=Jr(),
               config_store=C(), grant_store=G())
w.resize(800, 600); w.show(); app.processEvents()
print(json.dumps({"width": w.width(), "height": w.height(),
                  "minimum": w.minimumSizeHint().width()}))
w.close()
"""
    for factor in ("1.5", "2.0"):
        env = dict(os.environ, PYTHONPATH=str(REPO / "src"),
                   QT_QPA_PLATFORM="offscreen", QT_SCALE_FACTOR=factor)
        result = subprocess.run([sys.executable, "-c", code], env=env,
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["width"] == 800 and payload["height"] == 600, factor
        assert payload["minimum"] <= 800, factor
