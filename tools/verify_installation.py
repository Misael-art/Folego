#!/usr/bin/env python3
"""Verify wheel-only CLI installation and GUI-package removal in fresh venvs."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def run(argv, *, env, log):
    try:
        result = subprocess.run([str(arg) for arg in argv], env=env,
                                capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired as exc:
        def decoded(value):
            return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
        log.write_text(decoded(exc.stdout) + decoded(exc.stderr) + "\nTIMEOUT after 180 seconds\n")
        raise
    log.write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}); see {log}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    uv = shutil.which("uv")
    if not uv:
        parser.error("uv must be available")
    env = dict(os.environ, TMPDIR=str(args.workspace / "general"),
               UV_CACHE_DIR=str(args.cache_root or args.workspace / "installer-cache"))
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        env.pop(key, None)
    report = {"wheel": str(args.wheel.resolve()),
              "wheel_sha256": hashlib.sha256(args.wheel.read_bytes()).hexdigest()}
    cli = args.workspace / "wheel-cli-venv"
    removal = args.workspace / "removal-gui-venv"
    for label, prefix in (("cli", cli), ("removal", removal)):
        if prefix.exists():
            raise RuntimeError(f"refusing to replace existing environment: {prefix}")
        run([uv, "venv", "--python", "/usr/bin/python", prefix], env=env,
            log=args.output / f"{label}-venv.log")
        package = str(args.wheel.resolve()) + ("[gui]" if label == "removal" else "")
        offline = ["--offline"] if args.offline else []
        run([uv, "pip", "install", *offline, "--python", prefix / "bin/python", package], env=env,
            log=args.output / f"{label}-install.log")
    probe = """
import folego, importlib.util, json, sys
assert importlib.util.find_spec('PySide6') is None
assert 'site-packages' in folego.__file__
assert not any('Folego/src' in path for path in sys.path)
print(json.dumps({'module':folego.__file__,'pyside':None,'prefix':sys.prefix,'path':sys.path}))
"""
    report["cli"] = json.loads(run([cli / "bin/python", "-I", "-c", probe], env=env,
                                    log=args.output / "cli-import.log"))
    home = args.workspace / "removal-home"
    home.mkdir()
    isolated = {**env, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
                "XDG_STATE_HOME": str(home / ".local/state"), "XDG_DATA_HOME": str(home / ".local/share")}
    run([cli / "bin/folego", "doctor", "--json"], env=isolated,
        log=args.output / "wheel-cli-doctor.json")
    seed = """
import os
from pathlib import Path
from folego.orchestration.config import ConfigStore
from folego.orchestration.journal import Journal
from folego.orchestration.models import ActionPlan, ResourceIdentity
ConfigStore().set_paused(True)
root = Path(os.environ['XDG_DATA_HOME']) / 'folego/backups/fixture'
root.mkdir(parents=True)
(root / 'original.bin').write_bytes(b'preserve this disposable backup')
Journal().append_intent(ActionPlan('disk.quarantine', ResourceIdentity('entry','removal-fixture'), {}))
"""
    run([removal / "bin/python", "-I", "-c", seed], env=isolated,
        log=args.output / "removal-seed.log")
    def hashes():
        return {str(path.relative_to(home)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(home.rglob("*")) if path.is_file()}
    before = hashes()
    (args.output / "state-before.json").write_text(json.dumps(before, indent=2))
    assert before
    run([uv, "pip", "uninstall", "--python", removal / "bin/python", "folego"], env=isolated,
        log=args.output / "uninstall-gui.log")
    check = """
import importlib.util, json
assert importlib.util.find_spec('folego') is None
assert importlib.util.find_spec('PySide6') is not None
print(json.dumps({'folego':None,'PySide6_retained':True}))
"""
    removed = json.loads(run([removal / "bin/python", "-I", "-c", check], env=isolated,
                            log=args.output / "uninstall-import.log"))
    assert not (removal / "bin/folego").exists()
    after = hashes()
    (args.output / "state-after.json").write_text(json.dumps(after, indent=2))
    assert after == before, "uninstall changed the disposable user's state"
    assert not (home / ".config/autostart/folego.desktop").exists()
    report["removal"] = {"status": "passed", "imports": removed,
                         "preserved_sha256": before, "autostart_created": False}
    report["status"] = "passed"
    (args.output / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"status": "passed", "cli_without_qt": True,
                      "state_preserved_after_gui_uninstall": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
