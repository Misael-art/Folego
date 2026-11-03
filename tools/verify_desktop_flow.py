#!/usr/bin/env python3
"""Repeat safe window lifecycle cases on an installed GUI and real compositor."""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def wait_state(state, predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            current = json.loads((state / "state.json").read_text())
            if predicate(current):
                return current
        except (FileNotFoundError, ValueError):
            pass
        time.sleep(.1)
    raise AssertionError(f"desktop state deadline: {state}")


def send(state, action, **params):
    with (state / "commands.jsonl").open("a") as stream:
        stream.write(json.dumps({"action": action, **params}) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", choices=("wayland", "xcb", "offscreen"), required=True)
    parser.add_argument("--with-tray", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM=args.platform)
    for key in ("PYTHONPATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        env.pop(key, None)
    probe = Path(__file__).with_name("desktop_probe.py").resolve()
    records = []
    with (args.output / "process.log").open("w") as log:
        command = [str(args.python), "-I", str(probe), "--state", str(args.state),
                   "--output", str(args.output / "images")]
        if not args.with_tray:
            command.append("--no-tray")
        child = subprocess.Popen(command,
                                 env=env, stdout=log, stderr=log, start_new_session=True)
        try:
            initial = wait_state(args.state, lambda s: s["central"]["visible"])
            assert initial["tray"] == args.with_tray
            records.append({"case": "open-with-tray" if args.with_tray else "open-no-tray", "state": initial})
            send(args.state, "compact")
            compact = wait_state(args.state, lambda s: s["compact"] and s["compact"]["visible"])
            if args.platform == "wayland":
                assert compact["compact"]["decorated"]
            send(args.state, "close-central")
            hidden = wait_state(args.state, lambda s: not s["central"]["visible"])
            assert hidden["compact"]["visible"] and not hidden["poller_stopped"]
            records.append({"case": "close-central-keeps-compact-and-workers", "state": hidden})
            send(args.state, "hide-compact")
            if args.with_tray:
                wait_state(args.state, lambda s: not s["central"]["visible"] and not s["compact"]["visible"])
                items = subprocess.check_output(["qdbus6", "org.kde.StatusNotifierWatcher",
                    "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher.RegisteredStatusNotifierItems"], text=True).splitlines()
                ours = []
                for item in items:
                    service, _, suffix = item.partition("/")
                    pid = subprocess.check_output(["qdbus6", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                        "org.freedesktop.DBus.GetConnectionUnixProcessID", service], text=True).strip()
                    if int(pid) == child.pid:
                        ours.append((service, "/" + suffix))
                assert len(ours) == 1, f"expected exactly one notifier owned by child {child.pid}"
                subprocess.run(["qdbus6", *ours[0], "org.kde.StatusNotifierItem.Activate", "0", "0"], check=True)
            back = wait_state(args.state, lambda s: s["central"]["visible"] and not s["compact"]["visible"])
            assert not back["poller_stopped"]
            if not args.with_tray:
                send(args.state, "hide-central")
                guarded = wait_state(args.state, lambda s: s["last_command"]["action"] == "hide-central")
                assert guarded["central"]["visible"]
                records.append({"case": "last-visible-route-preserved", "state": guarded})
            else:
                records.append({"case": "owned-SNI-activation-restores-central", "state": back})
            send(args.state, "pause")
            paused = wait_state(args.state, lambda s: s["paused"] and "pausado" in s["central"]["title"])
            records.append({"case": "pause-invalidates-health", "state": paused})
            send(args.state, "capture", name="paused.png")
            send(args.state, "resume")
            wait_state(args.state, lambda s: not s["paused"] and "pausado" not in s["central"]["title"])
            for index in range(5):
                send(args.state, "tab", index=index)
                wait_state(args.state, lambda s: s["tab"] == index)
                send(args.state, "capture", name=f"tab-{index}.png")
                wait_state(args.state, lambda s: s["last_command"].get("name") == f"tab-{index}.png")
            send(args.state, "tab", index=0)
            send(args.state, "fullscreen")
            full = wait_state(args.state, lambda s: s["central"]["fullscreen"])
            records.append({"case": "fullscreen", "state": full})
            send(args.state, "capture", name="fullscreen.png")
            send(args.state, "normal")
            wait_state(args.state, lambda s: not s["central"]["fullscreen"])
            send(args.state, "compact")
            wait_state(args.state, lambda s: s["compact"]["visible"])
            send(args.state, "quit")
            assert child.wait(timeout=10) == 0
            final = json.loads((args.state / "state.json").read_text())
            assert final["poller_stopped"] and not final["errors"]
            records.append({"case": "quit-stops-workers", "state": final})
            result = {"status": "passed", "platform": args.platform, "cases": records}
        except Exception as exc:
            result = {"status": "failed", "platform": args.platform, "error": str(exc), "cases": records}
            raise
        finally:
            if child.poll() is None:
                send(args.state, "quit")
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()  # only the exact child started by this harness
                    child.wait(timeout=5)
            (args.output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({"status": result["status"], "cases": len(records), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
