"""Provas isoladas da revisão; não limpa nem sinaliza processos do host.

Execute na raiz: rtk proxy .venv/bin/python docs/reviews/2026-10-17/evidencias/reproduzir.py
As imagens são widgets reais com dados sintéticos, renderizados offscreen.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from folego.actions.disk import tmpclean
from folego.actions.disk.measure import TreeStat
from folego.actions.disk.planner import DiskTarget, build_plan
from folego.actions.tmpfs.holders import holder_index
from folego.actions.tmpfs.inventory import entry_at
from folego.actions.tmpfs.policy import Policy, classify
from folego.actions.tmpfs.ledger import Ledger
from folego.core.orphans import GroupTarget, GroupMember, OrphanCandidate
from folego.core.snapshot import Snapshot, MemInfo, Pressure, AppRSS
from folego.core.tmpfs import TmpfsVolume
from folego.ui.main_window import MainWindow
from folego.ui.orphans_panel import OrphansPanel
from folego.ui.tune_jobs import TuneJobs

app = QApplication.instance() or QApplication([])
results = {"scope": "fixtures isoladas; nenhuma limpeza ou sinal no host"}


def spin(seconds):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        app.processEvents()
        time.sleep(.005)


with tempfile.TemporaryDirectory(prefix="review-", dir=ROOT / ".scratch") as temp:
    base = Path(temp)
    tree = base / "tmp" / "sessao"
    tree.mkdir(parents=True)
    (tree / "ativo.txt").write_text("arquivo recém-escrito")
    now = time.time()
    os.utime(tree, (now - 5 * 86400, now - 5 * 86400))
    plan = tmpclean.plan_tmp(tree.parent, now=now)
    results["legacy_tmp_recent_descendant"] = {
        "fresh_child_selected_for_deletion": str(tree) in [i.path for i in plan.items],
        "executed_deletion": False,
    }
    holder = holder_index(proc_root=str(base / "proc-inexistente"), prefixes=(str(tree),))
    entry = entry_at(tree, (), holder, volume=str(tree.parent), now=now)
    verdict = classify(entry, Policy(allow_patterns=(str(tree),), min_age_days=0,
                                     volumes=(str(tree.parent),)))
    results["unknown_holders"] = {"proc_count": holder.proc_count,
                                   "eligible": verdict.ok, "reason": verdict.reason}
    target = DiskTarget("probe", "Probe", str(tree), mode="self", stale_days=None)
    incomplete = build_plan((target,), home=base, allowed_roots=[base],
        measure=lambda p, **kw: TreeStat(str(p), 100, 1, 0, ("permission denied",), True))
    results["incomplete_disk_walk"] = {
        "reclaimable": incomplete.items[0].reclaimable,
        "truncated": incomplete.items[0].truncated,
        "errors": incomplete.items[0].errors,
    }
    ledger = Ledger(base / "ledger.jsonl")
    row = dict(src=str(tree), volume=str(tree.parent), stored=str(base / "copy"),
               bytes=100, sha256="fixture", age_days=5, matched_pattern=str(tree),
               holder_pids=(), action_id="fixture", audit_event_id="fixture")
    ledger.append(entry_id="old", state="restored", **row)
    ledger.append(entry_id="new", state="released", **row)
    results["ledger_path_lookup"] = {"returned_id": ledger.find(str(tree)).entry_id,
                                     "active_ids": [r.entry_id for r in ledger.retained()]}

    panel = OrphansPanel()
    a = GroupTarget("edge", "Edge", (GroupMember(501, "msedge", 100, 1, 1),))
    b = GroupTarget("chrome", "Chrome", (GroupMember(502, "chrome", 100, 2, 1),))
    panel.show_groups((a, b))
    panel.choose_group(1)
    try:
        panel.show_groups((a,))
        results["group_disappears"] = {"exception": None}
    except Exception as exc:
        results["group_disappears"] = {"exception": type(exc).__name__, "message": str(exc)}

    callbacks = []
    jobs = TuneJobs(timeout_ms=30,
                    argv_factory=lambda *args: [str(base / "no-such-executable")])
    jobs.run("apply", "fixture", done=callbacks.append)
    spin(.15)
    results["worker_failed_to_start"] = {"callbacks": len(callbacks),
                                          "in_flight": jobs.in_flight,
                                          "pending_jobs": len(jobs._jobs)}
    jobs.shutdown()

    class FakeJobs:
        def run(self, *args, **kwargs):
            raise AssertionError("A renderização não deve executar ações")
        def shutdown(self):
            pass

    fake = FakeJobs()
    win = MainWindow(jobs=fake, disk_jobs=fake, tmpfs_jobs=fake)
    win.resize(1100, 740)
    win.show()

    def capture(index, name):
        win.tabs.setCurrentIndex(index)
        app.processEvents()
        assert win.grab().save(str(OUT / name))

    capture(1, "01-ajustes-inicial.png")
    capture(3, "02-disco-inicial.png")
    snap = Snapshot(ts=now, mem=MemInfo(16*1024**2, 1500*1024),
        swap_used_kb=3*1024**2, swap_total_kb=8*1024**2,
        pressure_memory=Pressure(12, 8, 3, 0), pressure_io=None,
        pressure_cpu=None, load=None,
        apps=(AppRSS("edge", 3*1024**2, 12), AppRSS("codex", 800*1024, 4)),
        self_rss_kb=95000,
        tmpfs=(TmpfsVolume("/tmp", "tmpfs", 8*1024**3, 7*1024**3, 1024**3),))
    win.apply_snapshot(snap)
    capture(0, "03-memoria-simulada.png")
    win.orphans.show_candidates((OrphanCandidate(12345, "node", "S", os.getuid(),
        350000, 0, 1234, 420, 1, ("node", "preview.js")),))
    win.orphans.show_groups((a, b))
    capture(2, "04-processos-simulados.png")
    win.tmpfs.show_plan({"reclaimable": [], "protected": [{
        "path": "/tmp/playwright_fixture", "bytes": 10*1024**2, "age_days": 4,
        "holder_pids": [12345], "ok": False, "reason": "refused: arquivo em uso",
        "item_id": "fixture"}], "total_bytes": 0, "scanned_entries": 1,
        "digest": "fixture-only"})
    win.tmpfs.show_ledger({"records": [], "budget": {"oldest_days": 0,
        "retained_bytes": 0, "retained_count": 0, "freed_bytes": 0,
        "slack_bytes": 3*1024**3, "max_bytes": 3*1024**3, "days": 14}})
    results["protected_item_button"] = {"enabled": win.tmpfs.release_buttons[0].isEnabled()}
    capture(4, "05-temporarios-simulados.png")
    win.close()

(OUT / "resultados.json").write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
print(json.dumps(results, indent=2, ensure_ascii=False))
