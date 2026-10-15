"""Re-runnable live check for M3: the four tabs and the tray on this machine.

    PYTHONPATH=src .venv/bin/python tools/verify_m3.py | tee .scratch/m3-verify.log
    .venv/bin/python tools/verify_m3.py --sem-disco      # pula o walk dos caches

Nothing here clicks, writes or signals a process: the window is built offscreen
unless the session says otherwise, the disk numbers come from the same child
process the tab uses, and the tray only reports whether Plasma lets the icon in.

Every claim is reconciled against a path that does not go through the app: the
title's GB figures against a direct /proc/meminfo parse (taken just after the
collect, so the free figure carries a 0,3 GB drift tolerance while the total must
match exactly), the app's own RSS against /proc/self/status, and the thumbnails
measure against ``du``. An adverse snapshot is then replayed through the same
widgets to show the signal flipping 🔴 and back — that part is *simulated data*,
not pressure on this machine; a real memory stress run needs the owner's explicit
go-ahead.
"""
import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from deck_wellness.core.collector import MetricsCollector  # noqa: E402
from deck_wellness.core.snapshot import AppRSS, MemInfo, Pressure, Snapshot  # noqa: E402
from deck_wellness.ui.main_window import MainWindow  # noqa: E402

PROC_ROOT = Path(os.environ.get("DECKWELLNESS_PROC_ROOT", "/proc"))
DISK_DEADLINE_S = 150.0  # above the tab's 120 s child timeout; the walk took 54,7 s here
TITLE_NUMBERS = re.compile(r"DeckWellness (🟢|🟡|🔴|⚪) · ([\d,]+)/([\d,]+) GB "
                           r"livre ([\d,]+) · app (\d+) MB")
LEVELS = {"critico": 0, "alto": 1, "medio": 2}


def fmt1(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def raw_meminfo() -> tuple[int, int]:
    """MemTotal, MemAvailable in kB, read here so the check is not the app's own."""
    values = {}
    for line in (PROC_ROOT / "meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        if key.strip() in ("MemTotal", "MemAvailable"):
            values[key.strip()] = int(rest.strip().split()[0])
    return values["MemTotal"], values["MemAvailable"]


def raw_self_rss_kb() -> int:
    for line in (PROC_ROOT / "self" / "status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return 0


def drive(app, until, deadline_s: float) -> bool:
    """Spin the event loop until ``until()`` holds: QProcess answers asynchronously."""
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        app.processEvents()
        if until():
            return True
        time.sleep(0.05)
    return until()


def check_title(win, problems) -> None:
    match = TITLE_NUMBERS.match(win.windowTitle())
    if match is None:
        problems.append(f"título fora do formato: {win.windowTitle()!r}")
        return
    used, total, livre = (float(g.replace(",", ".")) for g in match.group(2, 3, 4))
    total_kb, avail_kb = raw_meminfo()
    direct_total = total_kb / 1024 / 1024
    direct_livre = avail_kb / 1024 / 1024
    print(f"titulo={match.group(0)}")
    print(f"meminfo_direto={fmt1(direct_total)} GB total, {fmt1(direct_livre)} GB livre "
          f"(lido logo depois da coleta)")
    if abs((used + livre) - total) > 0.11:
        problems.append(f"o título não fecha: {used}+{livre} != {total}")
    if abs(total - direct_total) > 0.06:
        problems.append(f"total do título ({total}) ≠ /proc/meminfo ({fmt1(direct_total)})")
    if abs(livre - direct_livre) > 0.3:
        problems.append(f"livre do título ({livre}) ≠ /proc/meminfo "
                        f"({fmt1(direct_livre)}) — {abs(livre - direct_livre):.1f} GB de gap")
    rss_kb = raw_self_rss_kb()
    print(f"app_mb_titulo={match.group(5)} app_mb_vmrss={rss_kb // 1024} "
          f"delta={rss_kb // 1024 - int(match.group(5))} MB")
    if abs(int(match.group(5)) - rss_kb // 1024) > 32:
        problems.append(f"RSS do app diverge do /proc/self/status "
                        f"({match.group(5)} MB vs {rss_kb // 1024} MB)")


def check_dashboard(win, snapshot, problems) -> None:
    ids = [row.suggestion.id for row in win.dashboard.rows]
    groups = [(a.group, a.rss_kb // 1024) for a in snapshot.apps[:6]]
    print(f"apps={groups}")
    print(f"sugestoes={ids or 'nenhuma'}")
    print(f"detalhes={win.dashboard.details.text()}")
    print(f"estado={win.dashboard.status.text()}")
    edge = next((a for a in snapshot.apps if a.group == "edge"), None)
    heavy = edge is not None and edge.rss_kb > 2 * 1024 * 1024
    if heavy and "edge" not in ids:
        problems.append(f"Edge com {edge.rss_kb // 1024} MB e o dashboard mudo")
    if "edge" in ids and not heavy:
        problems.append("sugestão de Edge sem Edge pesado na coleta")


def check_disk(win, app, problems) -> None:
    win.disk.refresh()
    landed = drive(app, lambda: bool(win.disk.rows) or
                   win.disk.summary.text() == "sem plano", DISK_DEADLINE_S)
    if not landed:
        problems.append(f"o filho do plano não respondeu em {DISK_DEADLINE_S:g} s "
                        f"(resumo: {win.disk.summary.text()!r})")
        return
    print(f"disco_resumo={win.disk.summary.text()}")
    print(f"disco_estado={win.disk.status.text()}")
    for row in win.disk.rows[:6]:
        print(f"  · {row['size']:>9} · {row['path']} · {row['state']}")
    if len(win.disk.rows) > 6:
        print(f"  · … {len(win.disk.rows) - 6} item(ns) além dos 6 maiores")
    free = [r for r in win.disk.rows if r["reclaimable"]]
    refused = [r for r in win.disk.rows if r["reason"].startswith("refused")]
    young = [r for r in win.disk.rows if r["state"].startswith("intacto")]
    empty = [r for r in win.disk.rows if r["state"] == "vazio"]
    others = len(win.disk.rows) - len(free) - len(refused) - len(young) - len(empty)
    print(f"itens={len(win.disk.rows)} recuperáveis={len(free)} recusados={len(refused)} "
          f"intactos={len(young)} vazios={len(empty)} outros={others}")
    if others:
        problems.append(f"{others} item(ns) sem estado classificado")

    thumb = next((r for r in win.disk.rows if r["label"] == "Miniaturas"), None)
    if thumb is None:
        print("miniaturas=fora do plano (nada a reconciliar)")
        return
    du = subprocess.run(["du", "-sb", thumb["path"]], capture_output=True,
                        text=True, timeout=60)
    if du.returncode != 0:
        problems.append(f"du falhou em {thumb['path']}: {du.stderr.strip()[:80]}")
        return
    measured = int(du.stdout.split()[0])
    drift = abs(thumb["bytes"] - measured) / max(measured, 1)
    print(f"miniaturas_app={fmt1(thumb['bytes'] / 1024 ** 3)} GiB "
          f"du={fmt1(measured / 1024 ** 3)} GiB desvio={drift * 100:.1f}%")
    print(f"thumbnails_kb={win.disk.thumbnails_kb}")
    if drift > 0.15:
        problems.append(f"miniaturas divergem do du em {drift * 100:.0f}%")


def check_tray(win, problems) -> None:
    installed = win.tray.install()
    print(f"bandeja={'instalada' if installed else 'indisponível'}")
    print(f"fallback={win.tray.fallback or '—'}")
    if not installed:
        return
    match = TITLE_NUMBERS.match(win.windowTitle())
    win.tray.show_snapshot(MetricsCollector().collect())
    tooltip = win.tray.tray.toolTip()
    print(f"tooltip={tooltip!r}")
    if match and match.group(1) not in tooltip:
        problems.append(f"o tooltip não traz o emoji do título ({match.group(1)})")


def check_adverse(win, problems) -> None:
    """Simulated pressure through the same widgets: the signal must flip and return."""
    total, _ = raw_meminfo()
    adverse = Snapshot(ts=0.0, mem=MemInfo(total, int(total * 0.05)),
                       swap_used_kb=int(total * 0.9), swap_total_kb=total,
                       pressure_memory=Pressure(22.0, 20.0, 18.0, 0),
                       pressure_io=None, pressure_cpu=None, load=None,
                       apps=(AppRSS("edge", 3 * 1024 * 1024, 21),), self_rss_kb=90_000)
    win.apply_snapshot(adverse)
    ids = [row.suggestion.id for row in win.dashboard.rows]
    print(f"simulado_titulo={win.windowTitle()}")
    print(f"simulado_sugestoes={ids}")
    print(f"simulado_alvos={[row.target for row in win.dashboard.rows]}")
    if "🔴" not in win.windowTitle():
        problems.append("pressão simulada não acendeu o vermelho")
    for expected_id in ("pressao", "memoria", "zram", "edge"):
        if expected_id not in ids:
            problems.append(f"a regra {expected_id} não disparou sob pressão simulada")
    order = [row.suggestion.level for row in win.dashboard.rows]
    if order != sorted(order, key=LEVELS.get):
        problems.append(f"sugestões fora de ordem de gravidade: {order}")

    win.apply_snapshot(MetricsCollector().collect())
    print(f"volta_titulo={win.windowTitle()}")
    if "🔴" in win.windowTitle():
        problems.append("o vermelho não voltou com a leitura real")


def main(argv=None) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sem-disco", action="store_true",
                        help="pula o plano de disco (o walk dos caches é o passo lento)")
    args = parser.parse_args(argv)

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    collector = MetricsCollector()
    snapshot = collector.collect()
    win = MainWindow(collector_factory=lambda: collector)
    win.apply_snapshot(snapshot)

    problems: list[str] = []
    check_title(win, problems)
    check_dashboard(win, snapshot, problems)
    check_tray(win, problems)
    if not args.sem_disco:
        check_disk(win, app, problems)
    check_adverse(win, problems)

    for line in problems:
        print(f"FALHA: {line}")
    print(f"plataforma={os.environ['QT_QPA_PLATFORM']} "
          f"veredicto={'FALHOU' if problems else 'OK'} problemas={len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
