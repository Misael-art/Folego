#!/usr/bin/env python3
"""Run one sequential suite with persistent, bounded, private test state."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
MAX_RETAINED_SESSIONS = 20


def reserve_workspace(base: Path) -> Path:
    if base.is_symlink() or base.parent.is_symlink():
        raise OSError("QA roots must not be symlinks")
    from folego.core.tmpfs import read_mounts_checked
    from folego.safely.mounts import destination_verdict
    mounts, problem = read_mounts_checked()
    if problem:
        raise OSError(f"Cannot prove test storage: {problem}")
    verdict = destination_verdict(base, mounts=mounts)
    if not verdict.ok:
        raise OSError(f"Test storage refused: {verdict.reason}")
    base.mkdir(parents=True, mode=0o700, exist_ok=True)
    if len(list(base.iterdir())) >= MAX_RETAINED_SESSIONS:
        raise OSError("20 QA workspaces retained; inspect them before removing completed runs. No automatic cleanup.")
    measured = subprocess.run(["du", "-sk", str(base)], check=True, capture_output=True, text=True)
    if int(measured.stdout.split()[0]) >= 4 * 1024**2:
        raise OSError("QA reached its 4 GiB review budget; inspect retained runs. Nothing was removed.")
    capacity = os.statvfs(base)
    if capacity.f_bavail * (capacity.f_frsize or capacity.f_bsize) < 1024**3:
        raise OSError("QA requires at least 1 GiB free")
    run = Path(tempfile.mkdtemp(prefix="run-", dir=base))
    for name in ("home", "general", "pytest-root"):
        (run / name).mkdir(mode=0o700)
    return run


def test_environment(run: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTEST_ADDOPTS", "PYTEST_PLUGINS",
                "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "DECKWELLNESS_PROC_ROOT",
                "DECKWELLNESS_SYS_ROOT", "FOLEGO_RUN_ID"):
        env.pop(key, None)
    home = run / "home"
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_STATE_HOME=str(home / ".local/state"),
               XDG_DATA_HOME=str(home / ".local/share"),
               XDG_CACHE_HOME=str(home / ".cache"),
               TMPDIR=str(run / "general"),
               PYTEST_DEBUG_TEMPROOT=str(run / "pytest-root"),
               HYPOTHESIS_STORAGE_DIRECTORY=str(run / "hypothesis"),
               QT_QPA_PLATFORM="offscreen")
    return env


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in ("gui", "headless"):
        raise SystemExit("Expected gui or headless profile")
    profile = args.pop(0)
    if any("--basetemp" in arg for arg in args):
        raise SystemExit("The wrapper owns --basetemp; pass test names, -k or other pytest options")
    os.umask(0o077)
    # Validation of the headless profile happens before pytest imports modules.
    if profile == "headless":
        import importlib.util
        if importlib.util.find_spec("PySide6") is not None:
            raise SystemExit("Headless environment unexpectedly contains Qt")
    for key in ("DECKWELLNESS_PROC_ROOT", "DECKWELLNESS_SYS_ROOT"):
        os.environ.pop(key, None)
    lock_path = ROOT / ".dev/test.lock"
    lock_path.parent.mkdir(exist_ok=True, mode=0o700)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another suite owns the QA lock; run suites sequentially")
        run = reserve_workspace(ROOT / ".scratch/dev-tests")
        report = {"profile": profile, "status": "running", "runner_pid": os.getpid(),
                  "uid": os.getuid(), "gid": os.getgid(),
                  "python": sys.executable, "workspace": str(run), "started": time.time()}
        report_path = run / "run.json"
        report_path.write_text(json.dumps(report, indent=2))
        command = [sys.executable, "-m", "pytest", "-o", "addopts=",
                   f"--basetemp={run / 'base'}", "-q"]
        if profile == "headless":
            command.append("--without-qt")
        command.extend(args)
        print(f"QA workspace: {run}", flush=True)
        try:
            with (run / "pytest.log").open("w") as log:
                completed = subprocess.run(command, cwd=ROOT, env=test_environment(run),
                                           stdout=log, stderr=subprocess.STDOUT)
            report.update(status="passed" if completed.returncode == 0 else "failed",
                          exit_code=completed.returncode, elapsed_s=time.time() - report["started"])
            tail = (run / "pytest.log").read_text(errors="replace").splitlines()[-45:]
            print("\n".join(tail))
            return completed.returncode
        except BaseException:
            report.update(status="interrupted", elapsed_s=time.time() - report["started"])
            raise
        finally:
            report_path.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
