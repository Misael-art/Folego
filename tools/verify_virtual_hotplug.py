#!/usr/bin/env python3
"""Remove a virtual output only in the explicitly isolated KWin QA session."""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from verify_desktop_flow import send, wait_state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.workspace.resolve()
    assert os.environ["DBUS_SESSION_BUS_ADDRESS"] == (root / "nested-bus-address").read_text()
    assert Path(os.environ["XDG_RUNTIME_DIR"]).resolve() == root / "nested-runtime"
    assert os.environ["WAYLAND_DISPLAY"] == "qa-wayland"
    args.output.mkdir(parents=True, exist_ok=True)
    current = wait_state(args.state, lambda s: len(s["screens"]) == 2)
    assert {screen["name"] for screen in current["screens"]} == {"Virtual-0", "Virtual-1"}
    send(args.state, "compact")
    current = wait_state(args.state, lambda s: s["compact"] and s["compact"]["visible"])
    pid = current["pid"]
    source = root / "move-owned-compact.js"
    source.write_text("""
for (const window of workspace.stackingOrder) {
    if (window.pid === PID && window.caption === "Fôlego — controle compacto") {
        const output = workspace.screens.find(screen => screen.name === "Virtual-1");
        workspace.sendClientToScreen(window, output);
        workspace.activeWindow = window;
    }
}
""".replace("PID", str(pid)))
    identifier = subprocess.check_output(["qdbus6", "org.kde.KWin", "/Scripting",
        "org.kde.kwin.Scripting.loadScript", str(source), "folego-qa-owned-move"], text=True).strip()
    subprocess.run(["qdbus6", "org.kde.KWin", f"/Scripting/Script{identifier}",
                    "org.kde.kwin.Script.run"], check=True)
    before = wait_state(args.state, lambda s: s["compact"]["screen"] == "Virtual-1")
    observer = Path(__file__).with_name("record_kwin_geometry.py")
    def frame(name):
        destination = args.output / (name + ".json")
        subprocess.run([sys.executable, str(observer), "--workspace", str(root),
                        "--pid", str(pid), "--output", str(destination)], check=True,
                       stdout=subprocess.PIPE)
        return json.loads(destination.read_text())
    before_frame = frame("frame-before")
    send(args.state, "capture", target="compact", name=args.output.name + "-before.png")
    subprocess.run(["kscreen-doctor", "output.Virtual-1.disable"], check=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        after = wait_state(args.state, lambda s: len(s["screens"]) == 1 and
            s["compact"]["screen"] == "Virtual-0" and s["compact"]["exposed"])
        assert after["compact"]["visible"] and not after["poller_stopped"]
        after_frame = frame("frame-after")
        sx, sy, sw, sh = after["screens"][0]["geometry"]
        assert sx <= after_frame["x"] and sy <= after_frame["y"]
        assert after_frame["x"] + after_frame["width"] <= sx + sw
        assert after_frame["y"] + after_frame["height"] <= sy + sh
        assert not after_frame["noBorder"]
        send(args.state, "capture", target="compact", name=args.output.name + "-after.png")
        capture = args.output / "compact-after-compositor.png"
        shot = subprocess.run(["spectacle", "--background", "--nonotify", "--activewindow",
                        "--output", str(capture)], timeout=15,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        (args.output / "spectacle.log").write_text(shot.stdout + shot.stderr)
        deadline = time.monotonic() + 3
        while not capture.exists() and time.monotonic() < deadline:
            time.sleep(.1)
        report = {"status": "passed", "scope": "isolated KWin virtual outputs; no physical display changed",
                  "before": before, "after": after, "frame_before": before_frame,
                  "frame_after": after_frame, "all_controls_inside_remaining_output": True,
                  "compositor_capture": "created" if capture.exists() else "not created; see spectacle.log"}
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({"status": "passed", "before_screen": "Virtual-1", "after_screen": "Virtual-0"}))
    finally:
        subprocess.run(["kscreen-doctor", "output.Virtual-1.enable"], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
            "org.kde.kwin.Scripting.unloadScript", "folego-qa-owned-move"], check=True,
            stdout=subprocess.PIPE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
