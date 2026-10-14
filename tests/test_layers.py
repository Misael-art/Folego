"""Boundary rules from the approved plan, enforced by static grep."""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "deck_wellness"

NO_QT = ["core", "safely", "actions", "process", "store", "paths.py"]
QT_RE = re.compile(r"\bPySide6\b")
PROC_DIRECT_RE = re.compile(r"open\(\s*[\"']/proc|procfs\.|sysfs\.|/mnt/")


def py_files(rel_dirs):
    for d in rel_dirs:
        base = SRC / d
        files = [base] if base.is_file() else (list(base.rglob("*.py")) if base.is_dir() else [])
        yield from files


def test_no_direct_io_in_non_ui_layers():
    offenders = []
    for f in py_files(["core", "safely", "actions", "process", "ui", "store"]):
        if f.name == "selftest.py":
            continue
        text = f.read_text()
        if "ui/" in str(f) or f.parent.name == "ui":
            # ui must not read /proc or sysfs or device mounts directly
            for m in PROC_DIRECT_RE.finditer(text):
                offenders.append(f"{f.relative_to(SRC)}: {m.group(0)!r}")
    assert offenders == []


def test_non_ui_layers_do_not_import_qt():
    offenders = []
    for f in py_files(NO_QT):
        if QT_RE.search(f.read_text()):
            offenders.append(str(f.relative_to(SRC)))
    assert offenders == []
