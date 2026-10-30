"""Native Linux/KWin observations; optional peers never become dependencies."""
import json
import os
from pathlib import Path
import re
import shutil
import selectors
import signal
import subprocess
import time

from ..core.accessibility import SCHEMA, LABELS, parse_devices, device_cards, observation_clock
from ..core.sessions import read_boot_id

DEVICE_ROOT = "/org/kde/KWin/InputDevice"
DEVICE_IFACE = "org.kde.KWin.InputDevice"
PROPERTIES = "org.freedesktop.DBus.Properties"


class ProbeError(Exception):
    pass


def bounded_command(argv, *, timeout, **kwargs):
    """Bound both elapsed time and output, including a broken optional tool."""
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=kwargs.get("env"), start_new_session=True)
    deadline, buffers = observation_clock() + timeout, {"out": bytearray(), "err": bytearray()}
    completed = False
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ, "out")
            selector.register(proc.stderr, selectors.EVENT_READ, "err")
            while selector.get_map():
                remaining = deadline - observation_clock()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        buffers[key.data].extend(chunk)
                        if sum(map(len, buffers.values())) > 262144:
                            raise subprocess.SubprocessError("saída excede orçamento")
        code = proc.wait(timeout=max(.001, deadline - observation_clock()))
        completed = True
        return subprocess.CompletedProcess(argv, code, buffers["out"].decode(errors="replace"),
                                           buffers["err"].decode(errors="replace"))
    finally:
        if not completed:
            try:
                # Do not poll/reap first: even an exited leader reserves its PID
                # while descendants may still hold these pipes in our session.
                os.killpg(proc.pid, signal.SIGKILL)  # Only this disposable query's own session.
            except ProcessLookupError:
                pass
            proc.wait(timeout=2)
        proc.stdout.close()
        proc.stderr.close()


def bounded_read(path, limit=131072):
    with Path(path).open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ProbeError("fonte excede orçamento de leitura")
    return data.decode("utf-8")


def present(path):
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ProbeError("presença do registro não comprovada") from exc


class NativeInput:
    def __init__(self, *, runner=bounded_command, which=shutil.which, clock=observation_clock,
                 proc_root="/proc", sys_root="/sys", budget=8):
        self.runner, self.which, self.clock = runner, which, clock
        self.proc_root, self.sys_root, self.budget = Path(proc_root), Path(sys_root), budget
        self.deadline = 0
        self.qdbus = ""

    def call(self, argv):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise ProbeError("prazo total de coleta excedido")
        try:
            result = self.runner(argv, capture_output=True, text=True,
                                 stdin=subprocess.DEVNULL, timeout=min(remaining, 1.0),
                                 env={**os.environ, "LC_ALL": "C"}, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProbeError(f"{Path(argv[0]).name}: consulta indisponível") from exc
        if result.returncode or len(result.stdout) > 262144:
            raise ProbeError(f"{Path(argv[0]).name}: resposta incompleta/ilegível")
        return result.stdout

    def props(self, service, path, interface):
        text = self.call([self.qdbus, service, path, PROPERTIES + ".GetAll", interface])
        return dict(line.split(": ", 1) for line in text.splitlines() if ": " in line)

    def collect(self):
        began = self.clock()
        self.deadline = began + self.budget
        report = {"schema": SCHEMA, "sampled_at": time.time(), "mono": began, "clock": "boottime",
                  "boot_id": read_boot_id(self.proc_root), "backend": "observe-only",
                  "service_owner": "", "devices": [], "cards": [], "providers": [],
                  "blockers": [], "errors": []}
        known = False
        try:
            report["devices"] = parse_devices(bounded_read(self.proc_root / "bus/input/devices"))
            known = True
        except (OSError, ValueError, ProbeError):
            report["errors"].append("inventário de entrada indisponível ou incompleto")
        try:
            model = bounded_read(self.sys_root / "class/dmi/id/product_name", 256).strip()
        except (OSError, ValueError, ProbeError):
            model = ""
        self.qdbus = self.which("qdbus6") or self.which("qdbus") or ""
        if self.qdbus and os.environ.get("XDG_SESSION_TYPE") == "wayland":
            try:
                service = self.call([self.qdbus, "org.freedesktop.DBus", "/org/freedesktop/DBus",
                                     "org.freedesktop.DBus.GetNameOwner", "org.kde.KWin"]).strip()
                if not re.fullmatch(r":\d+\.\d+", service):
                    raise ProbeError("proprietário do compositor desconhecido")
                uid = self.call([self.qdbus, "org.freedesktop.DBus", "/org/freedesktop/DBus",
                                 "org.freedesktop.DBus.GetConnectionUnixUser", service]).strip()
                if not uid.isdigit() or int(uid) != os.getuid():
                    raise ProbeError("compositor não pertence ao usuário corrente")
                events = self.call([self.qdbus, service, DEVICE_ROOT, PROPERTIES + ".Get",
                                   DEVICE_IFACE + "Manager", "devicesSysNames"]).splitlines()
                if len(events) > 64 or any(not re.fullmatch(r"event\d+", event) for event in events):
                    raise ProbeError("inventário do compositor excede limite ou schema")
                by_event = {device["event"]: device for device in report["devices"]}
                for event in events:
                    props = self.props(service, DEVICE_ROOT + "/" + event, DEVICE_IFACE)
                    device = by_event.get(event)
                    if device is None:
                        raise ProbeError("kernel e compositor divergiram; reenumerar")
                    if props.get("sysName") != event or props.get("name") != device["name"]:
                        raise ProbeError("identidade do dispositivo mudou durante a leitura")
                    if props.get("enabled") not in ("true", "false"):
                        raise ProbeError("estado habilitado desconhecido")
                    device["enabled"] = props["enabled"] == "true"
                    device["kinds"] = [kind for kind in ("keyboard", "pointer", "touch", "touchpad")
                                       if props.get(kind) == "true" and
                                       (kind != "keyboard" or props.get("alphaNumericKeyboard") == "true")]
                    device["repairable"] = (bool(device["kinds"]) and device["stable"] and props.get("supportsDisableEvents") == "true"
                                             and props.get("isVirtual") == "false")
                report.update(backend="kwin", service_owner=service)
            except ProbeError as exc:
                report["errors"].append(str(exc))
                for device in report["devices"]:
                    device["repairable"] = False
        report["cards"] = device_cards(report["devices"], kernel_known=known,
                                        deck=model in ("Jupiter", "Galileo"))
        self._optional_cards(report)
        self._external_writers(report)
        if not report["boot_id"]:
            report["errors"].append("boot não comprovado")
        report["blockers"].extend(report["errors"])
        report["duration_s"] = self.clock() - began
        # Age is measured from the beginning: a slow probe never launders old data.
        return report

    def _optional_cards(self, report):
        state, detail = "unsupported", "backend do teclado virtual não disponível neste desktop"
        if report["backend"] == "kwin":
            try:
                props = self.props(report["service_owner"], "/VirtualKeyboard", "org.kde.kwin.VirtualKeyboard")
                state = "observed" if props.get("available") == "true" else "unavailable"
                detail = f"modo {props.get('mode', 'desconhecido')}; abertura/digitação não testadas"
            except ProbeError:
                state, detail = "unknown", "consulta do teclado virtual indisponível"
        report["cards"].append({"key": "virtual-keyboard", "label": LABELS["virtual-keyboard"],
                                "state": state, "detail": detail})
        for kind, plural in (("audio", "sinks"), ("microphone", "sources")):
            state, detail = "unsupported", "Pulse/PipeWire não disponível; sem alteração de áudio"
            binary = self.which("pactl")
            if binary:
                try:
                    rows = json.loads(self.call([binary, "-f", "json", "list", plural]))
                    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                        raise ValueError("schema")
                    if plural == "sources":
                        rows = [row for row in rows if not str(row.get("name", "")).endswith(".monitor")]
                    state, detail = ("observed" if rows else "not-observed"), f"{len(rows)} endpoint(s); áudio físico não testado"
                except (ProbeError, ValueError):
                    state, detail = "unknown", "grafo de áudio indisponível"
            report["cards"].append({"key": kind, "label": LABELS[kind], "state": state, "detail": detail})

    def _external_writers(self, report):
        # Legacy integrations are optional. We never execute a registered path
        # or copy its repair policy. Unknown live state protects the resource.
        from .. import paths
        marker = paths.xdg_config_home() / "phasezero/desktop-session.json"
        try:
            registered = present(marker)
        except ProbeError:
            report["blockers"].append("registro externo não comprovado")
            registered = False
        if registered:
            binary = self.which("systemctl")
            try:
                if marker.is_symlink():
                    raise ProbeError("registro simbólico")
                registration = json.loads(bounded_read(marker, 16384))
                if (not isinstance(registration, dict) or type(registration.get("schema_version")) is not int
                        or registration.get("schema_version") != 1
                        or registration.get("managed_by") != "phasezero-input"
                        or not isinstance(registration.get("command"), list)
                        or len(registration["command"]) != 2
                        or not all(isinstance(item, str) and Path(item).is_absolute() for item in registration["command"])):
                    raise ProbeError("registro desconhecido")
                if not binary:
                    raise ProbeError("gerenciador de serviços indisponível")
                text = self.call([binary, "--user", "show", "phasezero-input-restore.service",
                                  "--property=ActiveState", "--value"]).strip()
                if text not in ("inactive", "failed"):
                    report["blockers"].append("PhaseZero ativo ou sem estado comprovado; aguardando executor existente")
                report["providers"].append({"name": "PhaseZero", "state": text or "unknown"})
            except (ProbeError, OSError, ValueError):
                report["blockers"].append("registro PhaseZero presente; propriedade desconhecida")
        state = paths._env_dir("XDG_STATE_HOME", Path.home() / ".local/state") / "retrofe/input-session"
        for name in ("steam-desktop-session.json", "kde-global-shortcut-guard.json"):
            path = state / name
            try:
                pending = present(path)
            except ProbeError:
                report["blockers"].append("recuperação externa ilegível")
                pending = False
            if pending:
                report["providers"].append({"name": "RetroFE", "state": "pending"})
                report["blockers"].append("sessão/recuperação RetroFE pendente; aguardando o proprietário")
        for engine in ("docker", "podman"):
            binary = self.which(engine)
            if not binary:
                continue
            try:
                ids = self.call([binary, "ps", "-q", "--no-trunc"]).split()
                if len(ids) > 32 or any(not re.fullmatch(r"[a-f0-9]{12,64}", key) for key in ids):
                    raise ProbeError("inventário de containers incompleto")
                for key in ids:
                    # Select only device exposure; never request environment or secrets.
                    text = self.call([binary, "inspect", "--format",
                        '{"privileged":{{json .HostConfig.Privileged}},"devices":{{json .HostConfig.Devices}},"mounts":{{json .Mounts}}}', key])
                    try:
                        data = json.loads(text)
                        if (not isinstance(data, dict) or set(data) != {"privileged", "devices", "mounts"}
                                or type(data["privileged"]) is not bool
                                or not isinstance(data["devices"], (list, type(None)))
                                or not isinstance(data["mounts"], list)):
                            raise ValueError("schema")
                        sources = []
                        for device in data["devices"] or []:
                            sources.append(device["PathOnHost"])
                        for mount in data["mounts"]:
                            if mount.get("Type") != "tmpfs":
                                sources.append(mount["Source"])
                        if not all(isinstance(source, str) and source.startswith("/") for source in sources):
                            raise ValueError("caminho desconhecido")
                    except (ValueError, KeyError, TypeError, AttributeError) as exc:
                        raise ProbeError("mapeamentos de dispositivos desconhecidos") from exc
                    if data["privileged"] or any(source == "/" or source == "/dev" or
                            source.startswith(("/dev/input", "/dev/hidraw")) for source in sources):
                        report["blockers"].append(f"{engine} {key[:12]} expõe dispositivos; coordene com o dono")
            except ProbeError:
                report["blockers"].append(f"{engine}: acesso a dispositivos não comprovado")
