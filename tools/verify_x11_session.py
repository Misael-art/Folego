#!/usr/bin/env python3
"""Start owned Xvfb/KWin X11 and verify an installed GUI, never the host server.

Designed to run inside bwrap with a private /tmp, PID/network namespaces and
dbus-run-session. All pointer/keyboard input stays in that disposable X server.
"""
import argparse
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

from verify_desktop_flow import send, wait_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert os.environ.get("FOLEGO_QA_HOST_PID_NS")
    assert os.environ.get("FOLEGO_QA_HOST_NET_NS")
    assert os.readlink("/proc/self/ns/pid") != os.environ["FOLEGO_QA_HOST_PID_NS"]
    assert os.readlink("/proc/self/ns/net") != os.environ["FOLEGO_QA_HOST_NET_NS"]
    private_tmp = Path(os.environ["FOLEGO_QA_PRIVATE_TMP"])
    assert os.stat("/tmp").st_ino == private_tmp.stat().st_ino
    assert os.stat("/tmp").st_dev == private_tmp.stat().st_dev
    args.output.mkdir(parents=True, exist_ok=True)
    state_root = args.workspace / "x11-state"
    state_root.mkdir()
    env = dict(os.environ, QT_QPA_PLATFORM="xcb", XDG_SESSION_TYPE="x11",
               LIBGL_ALWAYS_SOFTWARE="1", KWIN_COMPOSE="O2")
    for key in ("WAYLAND_DISPLAY", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "PYTHONPATH", "VIRTUAL_ENV"):
        env.pop(key, None)
    env["XAUTHORITY"] = str(state_root / "Xauthority")
    Path(env["XAUTHORITY"]).touch()
    read_fd, write_fd = os.pipe()
    children = []
    records = []
    logs = []
    try:
        log = (args.output / "xvfb.log").open("w")
        logs.append(log)
        server = subprocess.Popen(["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "1920x1440x24",
            "-nolisten", "tcp", "-noreset", "-ac"], env=env, pass_fds=(write_fd,), stdout=log, stderr=log)
        children.append(server)
        os.close(write_fd)
        assert select.select([read_fd], [], [], 10)[0], "Xvfb did not publish an owned display"
        display = ":" + os.read(read_fd, 32).decode().strip()
        assert display.startswith(":") and display[1:].isdigit()
        env["DISPLAY"] = display
        log = (args.output / "kwin-x11.log").open("w")
        logs.append(log)
        manager = subprocess.Popen(["kwin_x11", "--replace"], env=env, stdout=log, stderr=log)
        children.append(manager)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            query = subprocess.run(["qdbus6", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus.GetConnectionUnixProcessID", "org.kde.KWin"], env=env,
                capture_output=True, text=True)
            if query.returncode == 0 and query.stdout.strip() == str(manager.pid):
                break
            assert manager.poll() is None, "owned KWin X11 exited during startup"
            time.sleep(.1)
        else:
            raise AssertionError("private D-Bus did not expose the owned KWin")
        support = subprocess.check_output(["qdbus6", "org.kde.KWin", "/KWin", "supportInformation"],
                                           env=env, text=True)
        (args.output / "support.txt").write_text(support)
        controller = Path(__file__).with_name("verify_desktop_flow.py")
        for factor, label in (("1", "100"), ("1.5", "150"), ("2", "200")):
            child_env = {**env, "QT_SCALE_FACTOR": factor}
            target = args.output / ("scale-" + label)
            subprocess.run([sys.executable, str(controller), "--python", str(args.python),
                "--state", str(state_root / ("scale-" + label)), "--output", str(target),
                "--platform", "xcb"], env=child_env, check=True, timeout=90)
            report = json.loads((target / "report.json").read_text())
            assert report["status"] == "passed"
            records.append({"scale": factor, "status": "passed", "report": str(target / "report.json")})
        probe = Path(__file__).with_name("desktop_probe.py")
        gesture_state = state_root / "gestures"
        log = (args.output / "gestures.log").open("w")
        logs.append(log)
        probe_env = {**env, "QT_SCALE_FACTOR": "1"}
        child = subprocess.Popen([str(args.python), "-I", str(probe), "--state", str(gesture_state),
            "--output", str(args.output / "gesture-images"), "--no-tray"],
            env=probe_env, stdout=log, stderr=log)
        children.append(child)
        wait_state(gesture_state, lambda s: s["central"]["visible"])
        send(gesture_state, "compact")
        wait_state(gesture_state, lambda s: s["compact"] and s["compact"]["visible"])
        identifiers = subprocess.check_output(["xdotool", "search", "--onlyvisible", "--all", "--pid", str(child.pid),
            "--name", "Fôlego — controle compacto"], env=env, text=True).splitlines()
        assert len(identifiers) == 1
        identifier = identifiers[0]
        subprocess.run(["xdotool", "windowactivate", "--sync", identifier,
                        "windowmove", identifier, "200", "200"], env=env, check=True)
        before = wait_state(gesture_state, lambda s: s["compact"]["geometry"][0] == 200)
        subprocess.run(["xdotool", "mousemove", "--window", identifier, "10", "10",
                        "mousedown", "1", "sleep", ".15", "mousemove_relative", "--sync", "80", "60",
                        "sleep", ".15", "mouseup", "1"], env=env, check=True)
        after = wait_state(gesture_state, lambda s: s["compact"]["geometry"][0] > 200)
        assert after["compact"]["geometry"][1] > before["compact"]["geometry"][1]
        assert not (gesture_state / "home/.local/state/folego/operations.jsonl").exists()
        focus_before = after["focus"]
        subprocess.run(["xdotool", "key", "--window", identifier, "Tab"], env=env, check=True)
        tabbed = wait_state(gesture_state, lambda s: s["focus"] != focus_before)
        capture = args.output / "gesture-compositor.png"
        subprocess.run(["import", "-display", display, "-window", "root", str(capture)], env=env, check=True)
        assert capture.is_file() and capture.stat().st_size > 0
        records.append({"case": "native-x11-drag-and-tab", "before": before, "after": after,
                        "after_tab": tabbed, "operation_journal_created": False})
        send(gesture_state, "quit")
        assert child.wait(timeout=10) == 0
        result = {"status": "passed", "scope": "owned Xvfb/KWin, not a physical X11 login",
                  "display": display, "cases": records}
        (args.output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({"status": "passed", "scales": [100,150,200], "drag_and_keyboard": True}))
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        os.close(read_fd)
        for log in logs:
            log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
