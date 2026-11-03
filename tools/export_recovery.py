#!/usr/bin/env python3
"""Export committed code/history and explicitly selected private recovery data.

Never copies virtualenvs, caches, Codex/GitHub credentials or whole HOME trees.
No restoration, grant activation, cleanup or upload is performed by this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MAX_SELECTED_BYTES = 128 * 1024**2
CHUNK_BYTES = 9 * 1024**2


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def selected_files(root):
    if root.is_symlink():
        raise OSError(f"Refusing symbolic export root: {root}")
    if not root.exists():
        return []
    paths = [root] if root.is_file() else list(root.rglob("*"))
    result = []
    for path in paths:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise OSError(f"Refusing symbolic export entry: {path}")
        if stat.S_ISREG(info.st_mode):
            result.append(path)
        elif not stat.S_ISDIR(info.st_mode):
            raise OSError(f"Refusing special export entry: {path}")
    return result


def write_selected_zip(destination, selections, notice):
    rows = []
    for root, archive_prefix in selections:
        for source in selected_files(root):
            name = archive_prefix if root.is_file() else str(Path(archive_prefix) / source.relative_to(root))
            rows.append((source, name))
    if sum(source.stat().st_size for source, _ in rows) > MAX_SELECTED_BYTES:
        raise OSError("Selected recovery data exceeds 128 MiB; prepare a separate bounded migration")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("READ-BEFORE-RESTORING.txt", notice)
        for source, name in rows:
            archive.write(source, name)
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-app-state", action="store_true")
    parser.add_argument("--include-qa-capsules", action="store_true")
    args = parser.parse_args()
    if git("status", "--porcelain"):
        raise SystemExit("Commit/review the working tree before exporting; export never discards uncommitted files")
    destination = args.output.resolve()
    for key in ("DECKWELLNESS_PROC_ROOT", "DECKWELLNESS_SYS_ROOT"):
        os.environ.pop(key, None)
    from folego.core.tmpfs import read_mounts_checked
    from folego.safely.mounts import destination_verdict
    mounts, problem = read_mounts_checked()
    verdict = destination_verdict(destination, mounts=mounts)
    if problem or not verdict.ok:
        raise SystemExit(f"Persistent export destination required: {problem or verdict.reason}")
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    manifest = {"schema": 1, "commit": git("rev-parse", "HEAD"),
                "branch": git("branch", "--show-current"),
                "repository": "https://github.com/Misael-art/Folego",
                "lock_sha256": digest(ROOT / "uv.lock"), "files": [], "upload_files": []}
    source = destination / "folego-source.zip"
    subprocess.run(["git", "-C", str(ROOT), "archive", "--format=zip", "--prefix=Folego/",
                    "-o", str(source), "HEAD"], check=True)
    bundle = destination / "folego-history.bundle"
    subprocess.run(["git", "-C", str(ROOT), "-c", "pack.threads=2", "-c", "pack.windowMemory=64m",
                    "bundle", "create", str(bundle), "--all"], check=True)
    subprocess.run(["git", "-C", str(ROOT), "bundle", "verify", str(bundle)], check=True)
    payloads = [source, bundle]
    if args.include_app_state:
        home = Path.home()
        selections = [(home / name, "home/" + name) for name in
                      (".config/folego", ".local/state/folego", ".local/share/folego")]
        target = destination / "folego-private-app-state.zip"
        count = write_selected_zip(target, selections,
            "Private application archive. Extract into an inspection directory, not HOME.\n"
            "Do not activate old grants, replay plans, or overwrite current state.\n"
            "No Codex/GitHub credentials or browser profiles are included.\n")
        manifest["app_state_files"] = count
        payloads.append(target)
    if args.include_qa_capsules:
        evidence = ROOT / "docs/reviews/2026-10-18/desktop-validation"
        selections = []
        missing = []
        for report in sorted(evidence.glob("soak-*/report.json")):
            data = json.loads(report.read_text())
            state = Path(data["state"]).resolve()
            if not state.is_relative_to(ROOT / ".scratch") or not state.exists():
                missing.append(report.parent.name)
                continue
            for relative in ("home/.config/microsoft-edge/Local State",
                             "home/.local/state/folego", "home/.local/share/folego/backups",
                             "general/folego-jobs"):
                selections.append((state / relative, report.parent.name + "/" + relative))
        target = destination / "folego-historical-qa.zip"
        manifest["qa_files"] = write_selected_zip(target, selections,
            "Historical synthetic fixtures only. Reports remain in the source archive.\n"
            "Absolute paths, PIDs, boot IDs, plans and digests belong to the old host.\n"
            "Inspect read-only; never rewrite identities or execute/replay these plans.\n"
            "Interrupted attempts are not two-hour acceptance and cannot be added together.\n")
        manifest["qa_capsules_unavailable"] = missing
        location = evidence / "workspace-path.txt"
        if location.exists():
            qa_root = Path(location.read_text().strip()).resolve()
            wheel = qa_root / "final2-wheels/folego-0.1.0-py3-none-any.whl"
            if qa_root.is_relative_to(ROOT / ".scratch") and wheel.is_file() and not wheel.is_symlink():
                with zipfile.ZipFile(target, "a", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.write(wheel, "historical-tested-wheel/" + wheel.name)
                manifest["historical_wheel_sha256"] = digest(wheel)
        payloads.append(target)
    for path in payloads:
        row = {"name": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
        manifest["files"].append(row)
        if row["bytes"] <= CHUNK_BYTES:
            manifest["upload_files"].append(path.name)
            continue
        with path.open("rb") as stream:
            part = 0
            while chunk := stream.read(CHUNK_BYTES):
                part += 1
                split = destination / f"{path.name}.part{part:03d}"
                split.write_bytes(chunk)
                manifest["upload_files"].append(split.name)
                manifest["files"].append({"name": split.name, "bytes": len(chunk),
                                          "sha256": digest(split), "part_of": path.name})
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (destination / "SHA256SUMS").write_text("".join(
        f"{row['sha256']}  {row['name']}\n" for row in manifest["files"]))
    (destination / "RECOVER.txt").write_text(
        "Read the private recovery Page and verify SHA256SUMS before extracting.\n"
        "For split payloads: first verify existing parts using --ignore-missing, concatenate,\n"
        "then verify the original full payload hash before cloning/extracting.\n"
        "If split: cat folego-history.bundle.part* > folego-history.bundle\n"
        "git clone -b codex/portable-handoff-20261024 folego-history.bundle Folego\n"
        "cd Folego\n./dev setup --headless\n./dev test-headless\n"
        "See docs/NOVO-HOST.md for GUI/native packages and the agent handoff.\n"
        "Private app state and historical QA are for inspection; no automatic import.\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
