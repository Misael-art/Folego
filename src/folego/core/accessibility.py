"""Portable input observations. Enumeration never certifies physical usability."""
import hashlib
import re
import sys
import time

SCHEMA = 1
ACTION = "accessibility.enable-input"
STALE_SECONDS = 20


def observation_clock():
    """Linux elapsed time including suspension: old observations stay old."""
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def sample_age(report):
    clock = report.get("clock", "monotonic")
    if clock not in ("boottime", "monotonic"):
        return float("inf")
    now = observation_clock() if clock == "boottime" else time.monotonic()
    return now - report["mono"]
LABELS = {"keyboard": "⌨ Teclado físico", "pointer": "🖱 Mouse / ponteiro",
          "touchpad": "▣ Trackpads", "touch": "☝ Tela de toque",
          "gamepad": "🎮 Controles", "virtual-keyboard": "⌨ Teclado virtual",
          "audio": "♪ Saída de áudio", "microphone": "🎙 Microfone"}


def parse_devices(text):
    devices = []
    for block in text.split("\n\n"):
        values = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        handlers = values.get("H", "").removeprefix("Handlers=").split()
        event = next((item for item in handlers if re.fullmatch(r"event\d+", item)), "")
        if not event:
            continue
        name = values.get("N", "").removeprefix("Name=").strip('"')
        phys = values.get("P", "").removeprefix("Phys=")
        # Never retain serial numbers or raw keystrokes. Physical topology and
        # product identity survive event-number changes; ambiguity blocks repair.
        identity = "|".join((values.get("I", ""), phys, name))
        key = hashlib.sha256(identity.encode()).hexdigest()
        kinds = []
        key_line = next((line[7:] for line in block.splitlines() if line.startswith("B: KEY=")), "")
        bits = 64 if sys.maxsize > 2**32 else 32
        bitmap = sum(int(word, 16) << (index * bits) for index, word in enumerate(reversed(key_line.split())))
        if "kbd" in handlers and all(bitmap & (1 << key) for key in (30, 44, 57)):
            kinds.append("keyboard")
        if any(item.startswith("mouse") for item in handlers):
            kinds.append("pointer")
        if any(item.startswith("js") for item in handlers):
            kinds.append("gamepad")
        if re.search(r"touchpad|trackpad", name, re.IGNORECASE):
            kinds.append("touchpad")
        if re.search(r"touchscreen|FTS3528", name, re.IGNORECASE):
            kinds.append("touch")
        devices.append({"key": key, "event": event, "name": name,
                        "stable": bool(phys and name), "kinds": kinds,
                        "enabled": None, "repairable": False,
                        "deck_controller": "Vendor=28de" in values.get("I", "") and "Steam Deck" in name})
    counts = {}
    for device in devices:
        counts[device["key"]] = counts.get(device["key"], 0) + 1
    for device in devices:
        device["stable"] &= counts[device["key"]] == 1
    return devices


def device_cards(devices, *, kernel_known, deck=False):
    cards = []
    for kind in ("keyboard", "pointer", "touchpad", "touch", "gamepad"):
        found = [device for device in devices if kind in device["kinds"]]
        disabled = [device for device in found if device["enabled"] is False]
        state = ("unknown" if not kernel_known else "degraded" if disabled else
                 "observed" if found else "unavailable" if deck and kind == "touch" else "not-observed")
        detail = ("fonte indisponível" if not kernel_known else
                  f"{len(disabled)} dispositivo(s) desabilitado(s)" if disabled else
                  f"{len(found)} enumerado(s); funcionamento físico não testado" if found else
                  "não observado; sem autorização para reset de hardware")
        if kind == "touchpad" and deck and not found and kernel_known:
            pointer = [d for d in devices if d.get("deck_controller") and "pointer" in d["kinds"]]
            if pointer:
                state = "degraded" if any(d["enabled"] is False for d in pointer) else "observed"
                detail = "saída de ponteiro do Deck enumerada; trackpads/gestos físicos não testados"
        cards.append({"key": kind, "label": LABELS[kind], "state": state, "detail": detail})
    return cards
