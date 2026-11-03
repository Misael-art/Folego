#!/usr/bin/env python3
"""Ask an isolated KWin for the actual frame geometry of one owned QA window.

Reference: https://develop.kde.org/docs/plasma/kwin/api/
The read-only script targets the supplied PID/caption; it never moves a window.
"""
import argparse
import json
import os
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.workspace.resolve()
    assert os.environ["DBUS_SESSION_BUS_ADDRESS"] == (root / "nested-bus-address").read_text()
    assert Path(os.environ["XDG_RUNTIME_DIR"]).resolve() == root / "nested-runtime"
    assert b"desktop_probe.py" in Path(f"/proc/{args.pid}/cmdline").read_bytes()
    from PySide6.QtCore import QCoreApplication, QObject, QTimer, Slot, ClassInfo
    from PySide6.QtDBus import QDBusConnection

    app = QCoreApplication([])
    records = []
    @ClassInfo(**{"D-Bus Interface": "org.folego.QA.Observer"})
    class Observer(QObject):
        @Slot(str)
        def record(self, payload):
            records.append(json.loads(payload))
            app.quit()
    receiver = Observer()
    bus = QDBusConnection.sessionBus()
    service = f"org.folego.QA.p{os.getpid()}"
    assert bus.registerService(service)
    assert bus.registerObject("/qa", receiver, QDBusConnection.ExportAllSlots)
    name = f"folego-qa-observer-{os.getpid()}"
    source = root / (name + ".js")
    source.write_text("""
for (const window of workspace.stackingOrder) {
    if (window.pid === PID && window.caption === "Fôlego — controle compacto") {
        const g = window.frameGeometry;
        const result = {pid: window.pid, caption: window.caption,
            x:g.x, y:g.y, width:g.width, height:g.height, noBorder:window.noBorder};
        callDBus(SERVICE, "/qa", "org.folego.QA.Observer", "record", JSON.stringify(result));
    }
}
""".replace("PID", str(args.pid)).replace("SERVICE", json.dumps(service)))
    identifier = subprocess.check_output(["qdbus6", "org.kde.KWin", "/Scripting",
        "org.kde.kwin.Scripting.loadScript", str(source), name], text=True).strip()
    try:
        subprocess.run(["qdbus6", "org.kde.KWin", f"/Scripting/Script{identifier}",
                        "org.kde.kwin.Script.run"], check=True)
        QTimer.singleShot(5000, app.quit)
        app.exec()
        assert len(records) == 1, "KWin did not certify exactly one target frame"
        args.output.write_text(json.dumps(records[0], ensure_ascii=False, indent=2))
        print(json.dumps(records[0], ensure_ascii=False))
    finally:
        subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
            "org.kde.kwin.Scripting.unloadScript", name], stdout=subprocess.PIPE, check=True)
        bus.unregisterService(service)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
