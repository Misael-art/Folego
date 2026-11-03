"""Diagnóstico isolado do caso runtime/pytest. Não limpa o runtime real.

Executa operações somente em TemporaryDirectory sob .scratch. O reparo externo
é importado como referência; repair(), configure() e scanners reais não rodam.
"""
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "src"))

from folego.actions.tmpfs.holders import holder_index
from folego.actions.tmpfs.inventory import TmpfsEntry
from folego.actions.tmpfs.policy import Policy, classify
from folego.core.health import HealthEngine
from folego.core.snapshot import MemInfo, Pressure, Snapshot
from folego.core.tmpfs import TmpfsVolume, watched_volumes


def run(base):
    result = {}
    runtime_item = TmpfsEntry(
        "/run/user/1000/codex-desktop/tmp/pytest-of-user/pytest-1",
        "pytest-1", "/run/user/1000", "dir", os.getuid(), 128, 1, 4.0)
    decision = classify(runtime_item, Policy())
    result["fixture_runtime_na_politica_atual"] = {
        "eligible": decision.ok, "reason": decision.reason}

    volume = TmpfsVolume("/run/user/1000", "tmpfs", 1000, 100, 900,
                         inodes_total=100, inodes_used=100, inodes_avail=0)
    snap = Snapshot(
        ts=1000, mono=100, mem=MemInfo(10000000, 5000000),
        swap_used_kb=0, swap_total_kb=0,
        pressure_memory=Pressure(0, 0, 0, 0), pressure_io=None,
        pressure_cpu=None, load=None, apps=(), self_rss_kb=10000,
        tmpfs=(volume,))
    health = HealthEngine().evaluate(snap, now_mono=100)
    result["inodes_esgotados_com_bytes_livres"] = {
        "level": health.level, "reasons": health.codes()}

    consulted = []

    def stat_unexpected(path):
        consulted.append(path)
        raise AssertionError("Unexpected statvfs call")

    volumes = watched_volumes(mounts=(("/run/user/1001", "tmpfs"),),
                              statvfs_fn=stat_unexpected)
    result["runtime_outro_uid_na_watchlist_padrao"] = {
        "volumes": len(volumes), "paths_consulted": consulted}

    def stat_denied(path):
        raise PermissionError(errno.EACCES, "injected statvfs denied")

    volumes = watched_volumes(mounts=(("/run/user/1000", "tmpfs"),),
                              statvfs_fn=stat_denied)
    result["statvfs_recusado"] = {"volumes": len(volumes),
                                  "error_propagated": False}

    fake_proc = base / "proc"
    fd = fake_proc / "123/fd"
    fd.mkdir(parents=True)
    (fd / "7").touch()

    def readlink_denied(path):
        raise PermissionError(errno.EACCES, "injected fd denied")

    holders = holder_index(proc_root=str(fake_proc),
                           readlink_fn=readlink_denied)
    result["fd_individual_ilegivel"] = {
        "state": holders.state, "refs": holders.refs, "errors": holders.errors}

    repair_path = Path("/mnt/sdcard/Projects/pz-ashyterm-repair/linux/repairs/terminal.py")
    if not repair_path.exists():
        result["reparo_externo"] = {"skipped": "arquivo não disponível"}
        return result
    spec = importlib.util.spec_from_file_location("review_terminal", repair_path)
    terminal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(terminal)
    fixtures = base / "fixtures"
    candidate = fixtures / "pytest-1"
    current_target = fixtures / "pytest-2"
    candidate.mkdir(parents=True)
    current_target.mkdir()
    (candidate / "data").write_text("synthetic fixture only")
    old = time.time() - 7200
    for path in [candidate / "data", candidate, current_target]:
        os.utime(path, (old, old))
    current = fixtures / "pytest-current"
    current.symlink_to(current_target)
    selected = terminal.candidates(fixtures, set())
    tree = next(tree for path, tree in selected if path == candidate)
    current.unlink()
    current.symlink_to(candidate)
    destination = base / "backup"
    destination.mkdir()
    # Ausência de referências é deliberadamente simulada: o teste isola a
    # revalidação de pytest-current, sem executar varredura real de processos.
    with patch.object(terminal, "references", return_value=set()):
        terminal.archive(candidate, tree, destination)
    result["pytest_current_mudou_apos_selecao"] = {
        "source": str(repair_path),
        "source_sha256": hashlib.sha256(repair_path.read_bytes()).hexdigest(),
        "fixture_original_exists": candidate.exists(),
        "current_is_symlink": current.is_symlink(),
        "current_target_exists": current.exists(),
        "backup_exists": (destination / "pytest-1/data").exists()}
    return result


if __name__ == "__main__":
    (ROOT / ".scratch").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="runtime-review-", dir=ROOT / ".scratch") as path:
        print(json.dumps(run(Path(path)), ensure_ascii=False, indent=2))
