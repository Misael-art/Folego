#!/usr/bin/env python3
"""Wall-clock GUI soak with private state, real workers and bounded telemetry.

Run with the managed GUI Python and -I. No checkout import is added. All tuning
effects concern this probe's disposable browser fixture. Cancellation kills
only a sleeping QProcess created here. Host telemetry comes from /proc/self.
"""
import argparse
import collections
import json
import math
import os
import sys
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path


def atomic_json(path, payload):
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    temporary.replace(path)


def self_metrics():
    values = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        key, _, raw = line.partition(":")
        if key in ("VmRSS", "VmHWM", "Threads"):
            values[key] = int(raw.split()[0])
    values["fds"] = len(list(Path("/proc/self/fd").iterdir()))
    values["cpu_s"] = time.process_time()
    times = os.times()
    values["children_cpu_s"] = times.children_user + times.children_system
    values["io"] = {key: int(value) for key, value in
                    (line.split(":", 1) for line in Path("/proc/self/io").read_text().splitlines())}
    children = Path(f"/proc/self/task/{os.getpid()}/children")
    values["children"] = [int(pid) for pid in children.read_text().split()]
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=7200)
    parser.add_argument("--job-interval", type=float, default=60)
    parser.add_argument("--sample-interval", type=float, default=10)
    parser.add_argument("--warmup", type=float, default=120)
    parser.add_argument("--platform", choices=("offscreen", "wayland", "xcb"), default="offscreen")
    args = parser.parse_args()
    if not 3 <= args.duration <= 86400 or args.job_interval < 1 or args.sample_interval < .25:
        parser.error("duration 3..86400; job interval >=1; sample interval >=.25")
    # Whole detect/apply/revert cycles finish before shutdown; never start a
    # mutation in the last worker-deadline window and then call its kill success.
    quiet = min(15, args.job_interval)
    planned_jobs = max(0, 1 + math.floor((args.duration - 1 - quiet) / args.job_interval))
    planned_jobs -= planned_jobs % 3
    if planned_jobs < 3:
        parser.error("duration/interval must fit one complete detect/apply/revert cycle")
    if planned_jobs + planned_jobs // 6 > 256:
        parser.error("planned children exceed the retained-run cap of 256; reduce job frequency")
    args.state = args.state.resolve()
    args.state.mkdir(mode=0o700, parents=True, exist_ok=False)
    args.output.mkdir(parents=True, exist_ok=True)
    home = args.state / "home"
    edge = home / ".config/microsoft-edge"
    edge.mkdir(parents=True)
    original = b'{"startup_boost":{"enabled":true},"soak_fixture":true}'
    (edge / "Local State").write_bytes(original)
    proc = args.state / "proc"
    proc.mkdir()
    # Keep browser/process discovery synthetic while proving the real backing
    # filesystem used by these disposable paths. Without mounts the product
    # correctly refuses to launch any child; a fake empty mount table is unsafe.
    (proc / "mounts").write_bytes(Path("/proc/mounts").read_bytes())
    (proc / "self").mkdir()
    (proc / "self/mountinfo").write_bytes(Path("/proc/self/mountinfo").read_bytes())
    # Each attempt needs its own retention budget. Reusing a caller's TMPDIR
    # pooled earlier runs and correctly hit the product's 256-run safety cap.
    general = args.state / "general"
    pytest_root = args.state / "pytest-root"
    general.mkdir(mode=0o700)
    pytest_root.mkdir(mode=0o700)
    os.environ.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
                      XDG_DATA_HOME=str(home / ".local/share"),
                      XDG_STATE_HOME=str(home / ".local/state"),
                      DECKWELLNESS_PROC_ROOT=str(proc), QT_QPA_PLATFORM=args.platform,
                      TMPDIR=str(general), PYTEST_DEBUG_TEMPROOT=str(pytest_root))
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer, qVersion
    from PySide6.QtWidgets import QApplication
    import folego
    from folego.core.snapshot import AppRSS, MemInfo, Pressure, Snapshot
    from folego.core.tmpfs import TmpfsVolume
    from folego.ui.main_window import MainWindow
    from folego.ui.theme import apply_theme
    from folego.ui.tune_jobs import TuneJobs
    from folego.ui.tmpfs_tab import SAMPLES_KEPT

    def source_signature():
        files = sorted(Path(folego.__file__).parent.rglob("*.py")) + [Path(__file__)]
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    source_before = source_signature()
    atomic_json(args.output / "source-manifest.json", source_before)

    app = QApplication([])
    app.setApplicationName("folego-soak")
    app.setDesktopFileName("folego-soak")
    app.setQuitOnLastWindowClosed(False)
    apply_theme(app)
    started = time.clock_gettime(time.CLOCK_BOOTTIME)
    started_utc = datetime.now(timezone.utc).isoformat()
    failures = set()
    counters = collections.Counter()
    latency = collections.Counter()
    heartbeat_max_ms = 0
    previous_tick = started
    baseline = None
    initial = self_metrics()
    peak = {"rss_kb": initial["VmRSS"], "fds": initial["fds"], "children": 0, "widgets": 0}
    trend = {"n": 0, "x": 0., "y": 0., "xx": 0., "xy": 0.}
    last = {}
    collection_count = 0
    last_worker = {}
    last_heartbeat = started

    def collect():
        nonlocal collection_count
        collection_count += 1
        if collection_count % 30 == 0:
            time.sleep(.20)  # synthetic slow collection, never on the Qt thread
        high = int((time.clock_gettime(time.CLOCK_BOOTTIME) - started) // 300) % 2
        return Snapshot(ts=time.time(), mono=time.clock_gettime(time.CLOCK_BOOTTIME), boot_id="soak-fixture",
            mem=MemInfo(16_000_000, 800_000 if high else 8_000_000),
            swap_used_kb=0, swap_total_kb=8_000_000,
            pressure_memory=Pressure(22 if high else 0, 0, 0, 0),
            pressure_io=None, pressure_cpu=None, load=None,
            apps=(AppRSS("fixture", 100_000, 1),), self_rss_kb=0,
            tmpfs=(TmpfsVolume("/fixture-tmpfs", "tmpfs", 1_000_000, 600_000, 400_000),))

    class SoakWindow(MainWindow):
        def closeEvent(self, event):
            if not self._quitting:
                event.ignore()  # fixed workload; explicit deadline still quits
                return
            super().closeEvent(event)

    win = SoakWindow(collector_factory=lambda: collect)
    # A tray is covered by the dedicated compositor probe. The soak must exit
    # deterministically and must not add a two-hour icon to the user's panel.
    win.tray._available = lambda: False
    # A fixed idle workload must not silently become an inventory/action test
    # when its taskbar entry is opened. Desktop interaction has separate probes.
    win.statusBar().showMessage("ENSAIO QA — métricas sintéticas; interação desabilitada")
    win.setEnabled(False)
    win.show()
    if args.platform != "offscreen":
        win.showMinimized()
        QTimer.singleShot(1000, win.showMinimized)
    win.start()
    win._poller.request()
    jobs = win._jobs
    cancel_jobs = TuneJobs(parent=win, timeout_ms=5000,
        argv_factory=lambda *_: [sys.executable, "-c", "import time; time.sleep(30)"])
    job_serial = 0
    sequence = ("detect", "apply", "revert")

    def record_result(kind, payload):
        with (args.output / "worker-results.jsonl").open("a") as out:
            out.write(json.dumps({"kind": kind, "elapsed_s": time.clock_gettime(time.CLOCK_BOOTTIME) - started,
                **{key: payload.get(key) for key in
                   ("acao", "ok", "outcome", "operation_id", "reason")}}, ensure_ascii=False) + "\n")

    def worker_done(payload):
        nonlocal last_worker
        record_result("tuning", payload)
        counters["worker_completed"] += 1
        last_worker = {key: payload.get(key) for key in ("acao", "ok", "outcome", "operation_id", "reason")}
        if not payload.get("ok"):
            failures.add("tuning worker did not complete successfully")

    def cancelled(payload):
        record_result("cancellation", payload)
        counters["cancel_completed"] += 1
        if payload.get("outcome") != "desconhecido":
            failures.add("cancelled mutation incorrectly reported as known/no-effect")

    def start_job():
        nonlocal job_serial
        if job_serial >= planned_jobs:
            return
        if jobs.in_flight or cancel_jobs.in_flight:
            failures.add("job still running at next launch interval")
            return
        action = sequence[job_serial % len(sequence)]
        job_serial += 1
        counters["worker_started"] += 1
        jobs.run(action, "edge.startup_boost", confirm=action != "detect", done=worker_done)
        if job_serial % 6 == 0:
            counters["cancel_started"] += 1
            cancel_jobs.run("apply", "synthetic-sleeper", confirm=True, done=cancelled)
            QTimer.singleShot(100, cancel_jobs.shutdown)

    def heartbeat():
        nonlocal previous_tick, heartbeat_max_ms, last_heartbeat
        now = time.clock_gettime(time.CLOCK_BOOTTIME)
        delay = max(0., (now - previous_tick - .05) * 1000)
        previous_tick = now
        last_heartbeat = now
        heartbeat_max_ms = max(heartbeat_max_ms, delay)
        for limit in (1, 5, 10, 50, 100, 250, 500, 1000):
            if delay <= limit:
                latency[str(limit)] += 1
                break
        else:
            latency[">1000"] += 1
        unplanned = sum(len(layer.procs) for layer in
                        (win._disk_jobs, win._tmpfs_jobs, win._process_jobs))
        active = len(jobs.procs) + len(cancel_jobs.procs) + unplanned
        if unplanned or win.tabs.currentIndex() != 0 or win._compact is not None:
            failures.add("fixed workload changed by an unplanned interaction")
        peak["children"] = max(peak["children"], active)
        if active > 2:
            failures.add("more than two owned jobs alive")
        if now - started >= args.duration:
            finish()

    def sample(final=False):
        nonlocal baseline, last
        now = time.clock_gettime(time.CLOCK_BOOTTIME)
        elapsed = now - started
        measured = self_metrics()
        all_widgets = QApplication.allWidgets()
        widgets = len(all_widgets)
        widget_classes = dict(collections.Counter(type(widget).__name__ for widget in all_widgets))
        peak["rss_kb"] = max(peak["rss_kb"], measured["VmRSS"])
        peak["fds"] = max(peak["fds"], measured["fds"])
        peak["widgets"] = max(peak["widgets"], widgets)
        if baseline is None and elapsed >= args.warmup:
            baseline = {**measured, "widgets": widgets, "elapsed_s": elapsed}
        if baseline:
            x = elapsed - baseline["elapsed_s"]
            y = measured["VmRSS"]
            trend["n"] += 1
            trend["x"] += x
            trend["y"] += y
            trend["xx"] += x * x
            trend["xy"] += x * y
            if y - baseline["VmRSS"] > 64 * 1024:
                failures.add("RSS grew more than 64 MiB after warmup")
            if measured["fds"] - baseline["fds"] > 16:
                failures.add("descriptor count grew by more than 16 after warmup")
            if widgets - baseline["widgets"] > 32:
                failures.add("widget count grew by more than 32 after warmup")
        samples = sum(len(series) for series in win.tmpfs._samples.values())
        if samples > SAMPLES_KEPT:
            failures.add("tmpfs sample buffer exceeded its cap")
        queue_size = win._poller._requests.qsize()
        history_queue = win._history_poller._requests.qsize() if win._history_poller else 0
        if queue_size > 1 or history_queue > 1:
            failures.add("worker queue exceeded its cap")
        denominator = trend["n"] * trend["xx"] - trend["x"] ** 2
        slope = ((trend["n"] * trend["xy"] - trend["x"] * trend["y"]) / denominator
                 if denominator else None)
        last = {"status": "complete" if final else "running", "pid": os.getpid(),
            "started_utc": started_utc, "elapsed_s": elapsed, "target_s": args.duration,
            "elapsed_clock": "CLOCK_BOOTTIME",
            "platform": app.platformName(), "qt": qVersion(), "module": folego.__file__,
            "state": str(args.state), "job_temp_root": str(general / "folego-jobs"),
            "metrics": measured, "initial": initial,
            "baseline": baseline, "peak": peak, "rss_trend_kb_per_hour": slope * 3600 if slope is not None else None,
            "cpu_average_percent": (measured["cpu_s"] - initial["cpu_s"]) / max(elapsed, .001) * 100,
            "heartbeat_max_delay_ms": heartbeat_max_ms, "heartbeat_histogram_ms": dict(latency),
            "widgets": widgets, "widget_classes": widget_classes,
            "window": {"enabled": win.isEnabled(), "minimized": win.isMinimized(),
                       "tab": win.tabs.currentIndex(), "input_isolated": True},
            "inventory_rows": {"disk": len(win.disk.rows),
                               "tmpfs_plan": len(win.tmpfs.plan_rows)},
            "samples": samples, "samples_cap": SAMPLES_KEPT,
            "collection_count": collection_count, "collector_queue": queue_size,
            "history_queue": history_queue, "history_bytes_read": win._history_reader.bytes_read,
            "active_qprocesses": len(jobs.procs) + len(cancel_jobs.procs),
            "job_counters": dict(counters), "last_worker": last_worker,
            "failures": sorted(failures)}
        last["planned_workers"] = planned_jobs
        last["source_unchanged"] = source_signature() == source_before if final else None
        with (args.output / "samples.jsonl").open("a") as out:
            out.write(json.dumps(last, ensure_ascii=False) + "\n")
            out.flush()
        atomic_json(args.output / "report.json", last)

    def finish():
        pulse.stop()
        sampler.stop()
        launcher.stop()
        cancel_jobs.shutdown()
        win.quit()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if jobs.procs or cancel_jobs.procs:
            failures.add("QProcesses remained after shutdown")
        if self_metrics()["children"]:
            failures.add("owned child remained after shutdown; inspect PID before any signal")
        if counters["worker_started"] != counters["worker_completed"]:
            failures.add("a worker result was lost")
        if counters["cancel_started"] != counters["cancel_completed"]:
            failures.add("a cancellation result was lost")
        sample(final=True)
        print(json.dumps({"status": last["status"], "elapsed_s": last["elapsed_s"],
                          "failures": last["failures"]}), flush=True)
        app.exit(1 if failures else 0)

    pulse = QTimer()
    pulse.setInterval(50)
    pulse.timeout.connect(heartbeat)
    sampler = QTimer()
    sampler.setInterval(round(args.sample_interval * 1000))
    sampler.timeout.connect(sample)
    launcher = QTimer()
    launcher.setInterval(round(args.job_interval * 1000))
    launcher.timeout.connect(start_job)
    pulse.start()
    sampler.start()
    launcher.start()
    QTimer.singleShot(1000, start_job)
    sample()
    print(json.dumps({"pid": os.getpid(), "target_s": args.duration, "output": str(args.output)}), flush=True)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
