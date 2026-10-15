"""Re-runnable live check for M4: what would the app offer, and does a click kill.

    python tools/verify_orphans.py            # read-only census of the real host
    python tools/verify_orphans.py --decoy    # end-to-end on processes this script owns

The census never signals anything and prints every process the orphan rule and
the group rule would offer, so the protected pre-list can be certified against
the machine instead of against imagination.

--decoy spawns two of its own processes (an adopted leftover and a "msedge"
family member), drives the real window and the real Reaper against them, and
proves the PIDs are gone. Anything outside its own decoys is reported and never
touched.
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from deck_wellness.core.collector import MetricsCollector  # noqa: E402
from deck_wellness.core.orphans import (OrphanTracker,  # noqa: E402
                                        group_targets, is_adopted, is_tooling,
                                        under_automation_control)

DECOY_BIN = Path("/dev/shm/dw-orphan-decoy")
ORPHAN = "dw-orphan"   # comm is truncated to 15 chars by the kernel: keep names short
EDGE = "dw-msedge"
DECOYS = {DECOY_BIN / ORPHAN, DECOY_BIN / EDGE}


def census() -> int:
    snapshot = MetricsCollector().collect()
    found = OrphanTracker(min_idle_s=0.0).observe(snapshot)
    by_pid = {p.pid: p for p in snapshot.procs}
    print(f"procs_lidos={len(snapshot.procs)} candidatos_estruturais={len(found)}")
    for c in found:
        proc = by_pid[c.pid]
        print(f"  órfão  pid={c.pid:<7} {c.comm:<22} {c.rss_kb // 1024:>5} MB  "
              f"pai={proc.ppid} adotado={is_adopted(proc, by_pid.get(proc.ppid))}  "
              f"{' '.join(c.cmdline)[:80]}")
    for target in group_targets(snapshot.procs):
        print(f"  grupo  {target.label}: {len(target.members)} processo(s) · "
              f"{sum(m.rss_kb for m in target.members) // 1024} MB · "
              f"pids={[m.pid for m in target.members]}")
    vetoed = [p for p in snapshot.procs
              if p.uid == os.getuid() and (is_tooling(p) or under_automation_control(p))]
    print(f"  recusados_por_ser_ferramenta={len(vetoed)} (drivers, shells de automação)")
    return 0


def mine(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/exe").resolve() in DECOYS
    except OSError:
        return False


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def cleanup(pids: set[int]) -> None:
    for pid in pids:
        if mine(pid):
            os.kill(pid, int(signal.SIGKILL))
    shutil.rmtree(DECOY_BIN, ignore_errors=True)


def decoy_pids() -> set[int]:
    out = subprocess.run(["pgrep", "-x", ORPHAN], capture_output=True, text=True).stdout
    out += subprocess.run(["pgrep", "-x", EDGE], capture_output=True, text=True).stdout
    return {int(x) for x in out.split()}


def end_to_end() -> int:
    from PySide6.QtWidgets import QApplication

    from deck_wellness.ui.main_window import MainWindow

    DECOY_BIN.mkdir(parents=True, exist_ok=True)
    for name in (ORPHAN, EDGE):
        shutil.copy("/bin/sleep", DECOY_BIN / name)
    # background children of a dying shell: adopted by the session supervisor,
    # keeping the launcher's pgid/session — exactly what a real leftover looks like
    subprocess.run(["bash", "-c", f"{DECOY_BIN}/{ORPHAN} 600 &"], check=True)
    subprocess.run(["bash", "-c", f"{DECOY_BIN}/{EDGE} 600 &"], check=True)
    time.sleep(0.6)
    created = decoy_pids()
    print(f"decoys_criados={sorted(created)}")

    app = QApplication(sys.argv)
    asked: list[str] = []
    win = MainWindow(collector_factory=MetricsCollector,
                     tracker=OrphanTracker(min_idle_s=2.0),
                     confirm_fn=lambda text: asked.append(text) or True)
    win.apply_snapshot(MetricsCollector().collect())
    time.sleep(2.5)
    win.apply_snapshot(MetricsCollector().collect())

    rows = [(index, int(r["pid"])) for index, r in enumerate(win.orphans.rows())]
    offered = {pid for _, pid in rows}
    targets = [t for t in group_targets(MetricsCollector().collect().procs)
               if t.group == "edge"]
    grouped = {m.pid for t in targets for m in t.members}
    foreign_group = {m.pid for t in targets for m in t.members if not mine(m.pid)}
    print(f"oferecidos_orfaos={sorted(offered)}  "
          f"oferecidos_grupos={[sorted(m.pid for m in t.members) for t in targets]}")
    print(f"estranhos_apenas_informados={sorted(p for p in offered if not mine(p))}")

    scope = {p for p in offered | grouped if mine(p)}
    if foreign_group:
        print(f"ABORTADO: o grupo offer contém alheios {sorted(foreign_group)}")
        cleanup(created)
        return 1
    if not scope:
        print("FALHA: o app não ofereceu os próprios decoys")
        cleanup(created)
        return 1

    # the two acts cover disjoint decoys on purpose: the single-orphan click
    # clears what the group does not own, the group click clears the family.
    # killing the family member first would only prove the reaper refuses a dead pid.
    lone = [index for index, pid in rows if mine(pid) and pid not in grouped]
    for index in lone:
        win.orphans.select(index)
        win.orphans.terminate_clicked()
    if grouped and win.orphans.group_button.isEnabled():
        win.orphans.choose_group(win.orphans.group_options().index("Microsoft Edge"))
        win.orphans.group_clicked()

    for text in asked:
        print("  confirmação: " + text.replace("\n", " / ")[:150])
    print(f"status_final={win.orphans.status()}")
    time.sleep(0.8)
    deaths = {pid: not alive(pid) for pid in sorted(scope)}
    print(f"mortes_comprovadas={deaths}")
    survivors = {pid for pid, dead in deaths.items() if not dead}
    cleanup(created | survivors)
    print("tudo encerrado pelo próprio app." if not survivors
          else f"FALHA: seguem vivos {sorted(survivors)}")
    return 1 if survivors else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoy", action="store_true",
                        help="encerrar processos criados por este script (não toca em nada alheio)")
    args = parser.parse_args()
    return end_to_end() if args.decoy else census()


if __name__ == "__main__":
    raise SystemExit(main())
