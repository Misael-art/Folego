#!/usr/bin/env python3
"""Reproducible real-Qt screenshots with fixture data; no mutation is allowed."""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    from folego.orchestration.models import ActionPlan, ResourceIdentity
    from folego.ui.disk_tab import DiskTab
    from folego.ui.theme import apply_theme

    class NoEffects:
        def run(self, *args, **kwargs):
            raise AssertionError("screenshot fixture must never execute a job")

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    plan = ActionPlan("disk.quarantine", ResourceIdentity.path(
        "/home/fixture/.cache/cache-descartavel", dev=8, ino=42))
    view = DiskTab(jobs=NoEffects())
    view.resize(800, 600)
    view.show_plan({"items": [{"path": plan.target.key, "bytes": 4096,
        "files": 2, "reclaimable": True, "reason": "fixture de demonstração",
        "action_plan": plan.to_dict()}], "scanned_bytes": 4096})
    view.show()
    view.table.selectRow(0)
    app.processEvents()
    assert view.grab().save(str(output / "disk-plan.png"))
    captured = []

    def capture_dialog():
        dialog = QApplication.activeModalWidget()
        if dialog is None:
            raise AssertionError("review dialog was not shown")
        assert dialog.grab().save(str(output / "disk-review.png"))
        captured.append(True)
        dialog.done(int(QMessageBox.StandardButton.No))

    QTimer.singleShot(50, capture_dialog)
    view.quarantine_selected()
    assert captured
    assert "Cancelado" in view.status.text()
    view.close()
    print("captured fixture plan/review at 800x600; mutation cancelled")


if __name__ == "__main__":
    main()
