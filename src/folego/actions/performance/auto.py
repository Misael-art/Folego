"""Performance mode, automatic runner: one cycle, the watch loop and the optional unit.

A cycle observes, plans, asks `core.perf_auto.decide` and, when a close is
chosen, runs the same executor as the assisted path with the automatic trigger
(intent, revalidation, follow-up). Announcements go out as a desktop
notification before the grace period; the GUI shows the same state and offers
"Adiar" and "Proteger sempre". Only one watcher runs at a time.
"""
from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ... import paths
from ...core import perf_auto, perf_model, perf_rules, procfs
from ...core.sessions import read_boot_id
from . import executor

UNIT = "folego-performance.service"
MARKER = "# X-Folego-Managed=performance-v1"


def state_store() -> perf_auto.AutoStore:
    return perf_auto.AutoStore(paths.state_dir() / "performance-auto.json")


def notify(item, *, run=subprocess.run) -> None:
    binary = shutil.which("notify-send")
    if not binary:
        return
    run([binary, "--app-name=Fôlego", "--icon=folego", "Fôlego · Modo Desempenho",
         f"{item.title}: {item.label} será fechado em {perf_auto.GRACE_S:.0f} s. "
         "Abra a aba desempenho para adiar ou proteger."],
        capture_output=True, timeout=5, check=False)


def cycle(*, collector, tracker, store, rules_path, protected_fn=None, notify_fn=notify,
          execute=executor.execute, boot_id_fn=read_boot_id, now=time.time) -> dict:
    snapshot = collector.collect()
    view = perf_model.observe(snapshot, protected_fn=protected_fn() if protected_fn else None)
    try:
        modes = perf_rules.load_modes(rules_path)
    except perf_rules.PolicyError as exc:
        return {"ok": False, "reason": f"regras ilegíveis: {exc}"}
    suggestions = perf_rules.plan(view, snapshot.procs, modes, tracker, time.monotonic())
    boot = boot_id_fn()
    try:
        with store.update() as state:
            decision = perf_auto.decide(suggestions, view, state, now=now(), boot=boot)
            state.last = {"ts": now(), "trigger": decision.trigger,
                          "waiting": [{"rule": s.rule, "unit": s.unit, "label": s.label, "why": why}
                                      for s, why in decision.waiting]}
    except perf_auto.AutoStateError as exc:
        return {"ok": False, "reason": f"automático desligado: {exc}"}
    for item in decision.announce:
        notify_fn(item)
    report = {"ok": True, "trigger": decision.trigger, "announced": len(decision.announce),
              "waiting": len(decision.waiting)}
    item = decision.close
    if item is None:
        return report
    plan = executor.plan_for(item, snapshot.procs, boot_id=boot, trigger=executor.AUTO)
    root = Path(paths.proc_root())

    def observe():
        time.sleep(1.0)
        fresh = collector.collect()
        return (perf_model.observe(fresh, protected_fn=protected_fn() if protected_fn else None),
                fresh.procs, perf_rules.load_modes(rules_path))

    verdict = execute(plan, observe=observe, read_proc=lambda pid: procfs.read_proc(root, pid),
                      confirm=True)
    outcome = str(verdict.outcome)
    try:
        with store.update() as state:
            state.record(ts=now(), boot=boot, rule=item.rule, unit=item.unit, label=item.label,
                         outcome=outcome)
    except perf_auto.AutoStateError as exc:
        report["record_error"] = str(exc)
    report.update(closed=item.label, outcome=outcome, reason=verdict.reason,
                  operation_id=verdict.operation_id)
    return report


def watch(*, interval=10.0, cycles=None, log=sys.stdout) -> dict:
    from ...core.collector import MetricsCollector
    from ...core.process_protection import snapshot_checker
    store = state_store()
    lock = paths.state_dir() / "performance-watch.lock"
    lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"ok": False, "reason": "já existe um executor do Modo Desempenho"}
        collector = MetricsCollector()
        collector.collect()  # CPU fractions need a previous sample
        tracker = perf_rules.ConditionTracker()
        count = 0
        while cycles is None or count < cycles:
            started = time.monotonic()
            try:
                report = cycle(collector=collector, tracker=tracker, store=store,
                               rules_path=paths.performance_rules_path(),
                               protected_fn=snapshot_checker)
            except Exception as exc:  # a bad cycle stops effects, never the watcher
                report = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
            if report.get("closed") or not report.get("ok"):
                log.write(f"{time.strftime('%H:%M:%S')} {report}\n")
                log.flush()
            count += 1
            if cycles is None or count < cycles:
                time.sleep(max(1.0, interval - (time.monotonic() - started)))
        return {"ok": True, "cycles": count}
    finally:
        os.close(fd)


def unit_text(executable=None) -> str:
    executable = executable or sys.executable
    if "\n" in executable or "\r" in executable:
        raise ValueError("executável inválido")
    quoted = '"' + executable.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
    return (MARKER + "\n[Unit]\nDescription=Fôlego performance mode\n"
            "PartOf=graphical-session.target\nAfter=graphical-session.target\n"
            "[Service]\nType=simple\nExecStart=" + quoted + " -m folego performance watch\n"
            "Environment=PYTHONPATH=" + str(Path(__file__).resolve().parents[3]) + "\n"
            "UMask=0077\nRestart=on-failure\nRestartSec=30\n"
            "[Install]\nWantedBy=graphical-session.target\n")


def _unit_path() -> Path:
    return paths.xdg_config_home() / "systemd/user" / UNIT


def install(*, confirmed=False, run=subprocess.run) -> dict:
    if not confirmed:
        raise ValueError("instalar o executor do Modo Desempenho exige confirmação")
    binary = shutil.which("systemctl")
    if not binary:
        raise ValueError("systemd de usuário indisponível; use folego performance watch no terminal")
    path = _unit_path()
    if path.exists() and not path.read_text().startswith(MARKER + "\n"):
        raise ValueError("unit pessoal com o mesmo nome preservada")
    from ...safely.atomicfile import write_atomic
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_atomic(path, unit_text().encode(), mode=0o600)
    for args in (("daemon-reload",), ("enable", "--now", UNIT)):
        result = run([binary, "--user", *args], stdin=subprocess.DEVNULL, capture_output=True,
                     text=True, timeout=8, check=False)
        if result.returncode:
            raise ValueError("unit gravada, mas ativação não comprovada; consulte "
                             f"systemctl --user status {UNIT}")
    return {"ok": True, "unit": UNIT, "path": str(path)}


def uninstall(*, confirmed=False, run=subprocess.run) -> dict:
    if not confirmed:
        raise ValueError("remover o executor exige confirmação")
    path = _unit_path()
    if path.exists() and not path.read_text().startswith(MARKER + "\n"):
        raise ValueError("unit pessoal com o mesmo nome preservada")
    binary = shutil.which("systemctl")
    if binary:
        run([binary, "--user", "disable", "--now", UNIT], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=8, check=False)
    if path.exists():
        path.unlink()
    return {"ok": True, "unit": UNIT}
