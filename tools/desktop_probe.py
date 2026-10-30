#!/usr/bin/env python3
"""Drive a disposable installed GUI on a real compositor, without mutations.

Run with the installed environment's Python and -I: no checkout path injection.
Commands are a small allow-list of window/navigation actions in a private state
directory. This is a QA harness, not a product remote-control endpoint.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--send", help="append one JSON navigation command and exit")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--lifetime", type=int, default=1200)
    args = parser.parse_args()
    state = args.state.resolve()
    if args.send:
        command = json.loads(args.send)
        with (state / "commands.jsonl").open("a") as out:
            out.write(json.dumps(command) + "\n")
        return 0
    state.mkdir(mode=0o700, parents=True, exist_ok=False)
    output = (args.output or state / "images").resolve()
    output.mkdir(parents=True, exist_ok=True)
    home = state / "home"
    home.mkdir()
    os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                      XDG_DATA_HOME=str(home / ".local/share"),
                      XDG_STATE_HOME=str(home / ".local/state"))
    for key in ("DECKWELLNESS_PROC_ROOT", "DECKWELLNESS_SYS_ROOT"):
        os.environ.pop(key, None)
    from PySide6.QtCore import QTimer, Qt, qVersion
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    import folego
    from folego.core.collector import MetricsCollector
    from folego.ui.main_window import MainWindow
    from folego.ui.theme import apply_theme

    app = QApplication([])
    app.setApplicationName("folego-qa")
    app.setDesktopFileName("folego-qa")
    apply_theme(app)
    win = MainWindow(collector_factory=MetricsCollector)
    if args.no_tray:
        win.tray._available = lambda: False
    win.resize(800, 600)
    win.show()
    win.start()
    started = time.monotonic()
    offset = 0
    last_command = None
    errors = []

    def geometry(widget):
        rect = widget.frameGeometry()
        handle = widget.windowHandle()
        return {"visible": widget.isVisible(), "active": widget.isActiveWindow(),
                "geometry": [rect.x(), rect.y(), rect.width(), rect.height()],
                "client": [widget.width(), widget.height()],
                "decorated": not bool(widget.windowFlags() & Qt.FramelessWindowHint),
                "fullscreen": widget.isFullScreen(), "minimized": widget.isMinimized(),
                "pixel_ratio": widget.devicePixelRatioF(),
                "screen": handle.screen().name() if handle and handle.screen() else None,
                "exposed": handle.isExposed() if handle else None,
                "title": widget.windowTitle()}

    def poll():
        nonlocal offset, last_command
        commands = state / "commands.jsonl"
        if commands.exists():
            with commands.open() as stream:
                stream.seek(offset)
                for line in stream:
                    try:
                        command = json.loads(line)
                        action = command["action"]
                        last_command = command
                        if action == "compact":
                            win.show_compact()
                        elif action == "central":
                            win.raise_to_user()
                        elif action == "tab":
                            win.tabs.setCurrentIndex(int(command["index"]))
                        elif action == "pause":
                            win.pause_watching()
                        elif action == "resume":
                            win.resume_watching()
                        elif action == "close-central":
                            win.close()
                        elif action == "hide-central":
                            win.hide_window()
                        elif action == "hide-compact" and win._compact is not None:
                            win._compact.hide_button.click()
                        elif action == "fullscreen":
                            win.showFullScreen()
                        elif action == "normal":
                            win.showNormal()
                        elif action == "resize":
                            win.resize(int(command["width"]), int(command["height"]))
                        elif action == "capture":
                            name = Path(command["name"]).name
                            target = win._compact if command.get("target") == "compact" else win
                            if not target or not target.isVisible():
                                raise ValueError("capture requires a visible target")
                            target.grab().save(str(output / name))
                        elif action == "quit":
                            win.quit()
                            app.quit()
                        else:
                            raise ValueError(f"unsupported QA action: {action}")
                    except Exception as exc:
                        errors.append(str(exc))
                offset = stream.tell()
        result = {"pid": os.getpid(), "qt": qVersion(), "module": folego.__file__,
                  "platform": app.platformName(), "elapsed_s": time.monotonic() - started,
                  "central": geometry(win), "compact": geometry(win._compact) if win._compact else None,
                  "paused": win.paused, "tab": win.tabs.currentIndex(),
                  "focus": (app.focusWidget().accessibleName() or
                            getattr(app.focusWidget(), "text", lambda: "")()) if app.focusWidget() else None,
                  "poller_stopped": win._poller._stop.is_set() if win._poller else None,
                  "tray": win.tray.tray is not None,
                  "screens": [{"name": s.name(), "ratio": s.devicePixelRatio(),
                               "geometry": [s.geometry().x(), s.geometry().y(),
                                            s.geometry().width(), s.geometry().height()]}
                              for s in QGuiApplication.screens()],
                  "last_command": last_command, "errors": errors[-20:]}
        temporary = state / "state.new"
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        temporary.replace(state / "state.json")
    timer = QTimer()
    timer.setInterval(250)
    timer.timeout.connect(poll)
    timer.start()
    QTimer.singleShot(args.lifetime * 1000, lambda: (win.quit(), app.quit()))
    poll()
    print(json.dumps({"pid": os.getpid(), "state": str(state)}), flush=True)
    code = app.exec()
    win.quit()
    poll()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
