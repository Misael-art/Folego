"""Performance mode closers: ask the app to leave through its own channel.

No signal is sent from here. `tray_quit` clicks the app's own quit entry in its
StatusNotifierItem menu (dbusmenu), found only among tray items whose bus owner
is a member of the reviewed group. `unit_stop` asks the user's systemd manager
to stop the app's unit, which is how the session itself ends a launched app.
Each returns what was *requested*; whether the app left is the executor's
follow-up, never assumed here.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

QUIT_LABELS = ("exit", "quit", "sair", "encerrar", "fechar")
UNIT_NAME = re.compile(r"^[A-Za-z0-9:_.\\@-]+\.(service|scope)$")
WATCHER = ("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher")
TIMEOUT_S = 5


@dataclass(frozen=True)
class Request:
    sent: bool
    channel: str
    detail: str


def _busctl(run, *args):
    done = run(["busctl", "--user", "--json=short", *args], capture_output=True, text=True,
               timeout=TIMEOUT_S, check=False)
    if done.returncode != 0:
        raise OSError((done.stderr or "busctl falhou").strip())
    return json.loads(done.stdout)["data"] if done.stdout.strip() else None


def _owner_pid(run, name):
    data = _busctl(run, "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                   "org.freedesktop.DBus", "GetConnectionUnixProcessID", "s", name)
    return int(data[0])


def _quit_item(layout):
    _root, _props, children = layout
    for child in children:
        item_id, props, _kids = child["data"]
        label = str(props.get("label", {}).get("data", "")).replace("_", "").replace("&", "")
        if props.get("enabled", {}).get("data", True) is False:
            continue
        if label.strip().lower().startswith(QUIT_LABELS):
            return item_id, label.strip()
    return None


def tray_quit(pids, *, run=subprocess.run) -> Request:
    members = set(pids)
    try:
        items = _busctl(run, "get-property", *WATCHER, "org.kde.StatusNotifierWatcher",
                        "RegisteredStatusNotifierItems")
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        return Request(False, "bandeja", f"bandeja ilegível: {exc}")
    for entry in items or ():
        name, _, path = entry.partition("/")
        path = "/" + path
        try:
            if _owner_pid(run, name) not in members:
                continue
            menu = _busctl(run, "get-property", name, path, "org.kde.StatusNotifierItem", "Menu")
            layout = _busctl(run, "call", name, menu, "com.canonical.dbusmenu", "GetLayout",
                             "iias", "--", "0", "1", "0")[1]
            found = _quit_item(layout)
            if found is None:
                return Request(False, "bandeja", "menu da bandeja sem item de saída")
            item_id, label = found
            _busctl(run, "call", name, menu, "com.canonical.dbusmenu", "Event", "isvu",
                    "--", str(item_id), "clicked", "s", "", "0")
            return Request(True, "bandeja", f"'{label}' acionado no menu do próprio app")
        except (OSError, ValueError, KeyError, IndexError, TypeError,
                subprocess.TimeoutExpired) as exc:
            return Request(False, "bandeja", f"menu da bandeja não acionado: {exc}")
    return Request(False, "bandeja", "nenhum ícone de bandeja pertence ao grupo")


def unit_stop(unit: str, *, run=subprocess.run) -> Request:
    if not UNIT_NAME.match(unit):
        return Request(False, "unit", f"nome de unit recusado: {unit!r}")
    try:
        done = run(["systemctl", "--user", "stop", "--no-block", "--", unit],
                   capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return Request(False, "unit", f"systemctl não respondeu: {exc}")
    if done.returncode != 0:
        return Request(False, "unit", (done.stderr or "systemctl recusou").strip())
    return Request(True, "unit", f"parada de {unit} pedida ao systemd do usuário")


CLOSERS = {"tray": tray_quit, "unit": unit_stop}
