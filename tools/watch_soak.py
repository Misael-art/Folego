#!/usr/bin/env python3
"""Wait for one identified QA process and analyze its completed soak report.

This observer never signals the process or retries the workload. It can run in
its own session so terminal interruptions do not lose the acceptance analysis.
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deadline-seconds", type=float, default=7800)
    args = parser.parse_args()
    if args.deadline_seconds <= 0:
        parser.error("deadline must be positive")
    launch = json.loads(args.launch.read_text())
    deadline = time.monotonic() + args.deadline_seconds
    status = {"status": "watching", "pid": launch["pid"],
              "launch": str(args.launch), "report": str(args.report)}
    monitor = args.output.with_name(args.output.stem + "-monitor.json")

    def save():
        status["observed_utc"] = datetime.now(timezone.utc).isoformat()
        temporary = monitor.with_suffix(".new")
        temporary.write_text(json.dumps(status, indent=2))
        temporary.replace(monitor)

    def same_process_alive():
        if Path("/proc/sys/kernel/random/boot_id").read_text().strip() != launch["boot_id"]:
            return False
        try:
            fields = Path(f"/proc/{launch['pid']}/stat").read_text().rsplit(")", 1)[1].split()
        except FileNotFoundError:
            return False
        return fields[19] == str(launch["start_ticks"]) and fields[0] != "Z"

    save()
    while same_process_alive() and time.monotonic() < deadline:
        time.sleep(10)
    if same_process_alive():
        status.update(status="deadline_exceeded", note="No signal or retry performed")
        save()
        return 1
    if not args.report.exists():
        status.update(status="incomplete", note="Process ended without a report")
        save()
        return 1
    # The analyzer itself rejects incomplete duration, bad effects and budgets.
    result = subprocess.run([
        sys.executable, "-I", str(Path(__file__).with_name("analyze_soak.py")),
        "--report", str(args.report), "--policy", str(args.policy),
        "--output", str(args.output),
    ], capture_output=True, text=True, timeout=60)
    args.output.with_suffix(".log").write_text(result.stdout + result.stderr)
    status.update(status="passed" if result.returncode == 0 else "failed",
                  analyzer_exit=result.returncode, analysis=str(args.output))
    save()
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
