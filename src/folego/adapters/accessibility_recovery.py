"""Explicit desktop recovery through native APIs and an optional registered owner.

Only a user-requested action may execute the registered PhaseZero backend.
Observation and the automatic input supervisor never execute third-party paths.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import time

from .accessibility import bounded_command, bounded_read, ProbeError, DEVICE_ROOT, DEVICE_IFACE, PROPERTIES
from .. import paths


class UncertainEffect(RuntimeError):
    pass


class DesktopRecovery:
    def __init__(self, native, *, runner=bounded_command, which=shutil.which):
        self.native, self.runner, self.which = native, runner, which

    def command(self, argv, *, effect=False, timeout=5):
        try:
            result = self.runner(argv, timeout=timeout, env={**os.environ, "LC_ALL": "C"})
        except (OSError, subprocess.SubprocessError) as exc:
            if effect:
                raise UncertainEffect("resposta perdida; verificar a mesma operação, sem repetir") from exc
            raise ProbeError("consulta indisponível: " + Path(argv[0]).name) from exc
        return result

    @staticmethod
    def _owned_file(path, *, system=False):
        path = Path(path)
        # Interpreters may be distro symlinks; scripts and registration may not.
        if system:
            path = path.resolve(strict=True)
        elif path.is_symlink() or any(p.is_symlink() for p in path.parents):
            raise ValueError("backend simbólico; preservado")
        info = path.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != (0 if system else os.getuid())
                or info.st_mode & 0o022 or info.st_size > 262144):
            raise ValueError("backend sem propriedade/permissões comprovadas")
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def peer(self):
        marker = paths.xdg_config_home() / "phasezero/desktop-session.json"
        try:
            marker.lstat()
        except FileNotFoundError:
            return None
        self._owned_file(marker)
        value = json.loads(bounded_read(marker, 16384))
        if not isinstance(value, dict):
            raise ValueError("registro do responsável não é objeto; preservado")
        command = value.get("command") if isinstance(value, dict) else None
        if (value.get("schema_version") != 1 or type(value.get("schema_version")) is not int
                or value.get("managed_by") != "phasezero-input" or not isinstance(command, list)
                or len(command) != 2 or not all(isinstance(v, str) and Path(v).is_absolute() for v in command)
                or Path(command[1]).name != "desktop_session.py"):
            raise ValueError("contrato do responsável externo desconhecido; nenhuma execução autorizada")
        executable = Path(command[0]).resolve(strict=True)
        if executable.name not in ("python3", "python3.13", "python3.14", "python3.15"):
            raise ValueError("interpretador do responsável não reconhecido")
        # The interpreter is a root-owned executable, not a script from state.
        info = executable.stat()
        if info.st_uid != 0 or info.st_mode & 0o022 or not os.access(executable, os.X_OK):
            raise ValueError("interpretador externo não é executável protegido do sistema")
        script = Path(command[1])
        files = {str(script): self._owned_file(script)}
        helper = script.parent.parent / "repairs/reparo-entrada.sh"
        if helper.exists():
            files[str(helper)] = self._owned_file(helper)
        # Pin all shell code the registered backend may use for keyboard repair.
        for source in (script.parent / "input-actions.sh", script.parent.parent / "lib/common.sh"):
            if source.exists():
                files[str(source)] = self._owned_file(source)
        for source in (helper.parent / "80-phasezero-touchscreen.rules",
                       helper.parent / "phasezero-touchscreen-recovery.service"):
            if source.exists():
                files[str(source)] = self._owned_file(source)
        return {"name": "PhaseZero", "command": command, "files": files,
                "touch_helper": str(helper) if str(helper) in files else ""}

    def peer_idle(self, peer):
        if not peer:
            return
        answer = self.command([*peer["command"], "lease"], timeout=4)
        try:
            value = json.loads(answer.stdout)
            if (answer.returncode or not isinstance(value, dict)
                    or type(value.get("active")) is not bool
                    or type(value.get("externalGameActive")) is not bool
                    or not isinstance(value.get("pending"), list)):
                raise ValueError("estado do responsável não comprovado")
            if value["active"] or value["externalGameActive"] or value["pending"]:
                raise ValueError("jogo, frontend ou recuperação pendente; responsável preservado")
        except (ValueError, TypeError) as exc:
            raise ValueError(str(exc) or "estado do responsável desconhecido") from exc

    def delegate(self, peer, *, capture=False):
        result = self.command([*peer["command"], "capture" if capture else "reconcile-input"], effect=True, timeout=25)
        if result.returncode:
            return "Responsável respondeu com reparo incompleto: " + result.stderr.strip()[:240]
        try:
            value = json.loads(result.stdout)
        except ValueError as exc:
            raise UncertainEffect("responsável terminou sem resultado legível") from exc
        if capture and value is None:
            return ""  # The registered capture command returns JSON null on completion.
        if not isinstance(value, dict) or type(value.get("ok")) is not bool:
            raise UncertainEffect("contrato de resultado do responsável desconhecido")
        if not capture and (value.get("scope") != "input" or value.get("schema_version") != 1):
            raise UncertainEffect("responsável não confirmou escopo restrito a entradas")
        if value.get("ok") is False:
            return "; ".join(str(v) for v in value.get("errors", []))[:240]
        return ""

    def audio_targets(self, scope):
        result = {}
        binary = self.which("pactl")
        for key, singular in (("audio", "sink"), ("microphone", "source")):
            if key not in scope:
                continue
            try:
                if not binary:
                    raise ProbeError("Pulse/PipeWire não disponível")
                answer = self.command([binary, "get-default-" + singular])
                if answer.returncode:
                    raise ProbeError("endpoint padrão não comprovado")
                default = answer.stdout.strip()
                rows = self._audio_nodes(binary, singular)
                eligible = [r for r in rows if not r["name"].endswith(".monitor") and self._port_available(r)]
                target = next((r for r in eligible if r["name"] == default), None)
                if target is None and len(eligible) == 1:
                    target = eligible[0]
                result[key] = self._audio_identity(target) if target else {"error": "saída/entrada ausente ou ambígua"}
            except (OSError, ValueError, ProbeError) as exc:
                result[key] = {"error": str(exc)}
        return result

    @staticmethod
    def _audio_identity(node):
        properties = node.get("properties", {})
        stable = {key: properties.get(key) for key in ("device.name", "device.bus_path", "alsa.card_name", "device.serial")}
        return {"name": node["name"], "index": node.get("index"),
                "identity": hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()}

    @staticmethod
    def _port_available(row):
        active = row.get("active_port")
        ports = row.get("ports", [])
        if isinstance(ports, dict):
            ports = list(ports.values())
        if isinstance(active, str):
            active = next((p for p in ports if isinstance(p, dict) and p.get("name") == active), {})
        return not isinstance(active, dict) or active.get("available") not in ("not available", "no")

    def _audio_nodes(self, binary, singular):
        answer = self.command([binary, "-f", "json", "list", singular + "s"])
        rows = json.loads(answer.stdout)
        if (answer.returncode or not isinstance(rows, list) or len(rows) > 64
                or any(not isinstance(r, dict) or not isinstance(r.get("name"), str) or not r["name"]
                       or r["name"].startswith("-") or len(r["name"]) > 512
                       or not isinstance(r.get("properties", {}), dict)
                       or type(r.get("mute")) is not bool or not isinstance(r.get("volume"), dict)
                       or not 1 <= len(r["volume"]) <= 32
                       or any(not isinstance(v, dict) or type(v.get("value")) is not int or v["value"] < 0
                              for v in r["volume"].values()) for r in rows)):
            raise ProbeError("grafo de áudio incompleto/desconhecido")
        return rows

    def enable_audio(self, key, target):
        binary = self.which("pactl")
        if not binary or not target or target.get("error"):
            return False, (target or {}).get("error", "backend de áudio indisponível")
        name = target["name"]
        singular = "sink" if key == "audio" else "source"
        rows = self._audio_nodes(binary, singular)
        node = next((r for r in rows if r["name"] == name and not name.endswith(".monitor")), None)
        if node is None:
            return False, "endpoint revisado desapareceu; verificar antes de nova tentativa"
        if self._audio_identity(node) != dict(target):
            return False, "identidade do endpoint mudou; nenhuma configuração aplicada"
        values = [v.get("value") for v in node["volume"].values() if isinstance(v, dict)]
        if not values or any(type(v) is not int or v < 0 for v in values):
            return False, "volume desconhecido; configuração preservada"
        commands = [[binary, "set-default-" + singular, name],
                    [binary, "set-" + singular + "-mute", name, "0"]]
        if max(values) == 0:
            commands.append([binary, "set-" + singular + "-volume", name, "25%"])
        for command in commands:
            response = self.command(command, effect=True)
            if response.returncode:
                return False, "configuração de áudio incompleta; resultado atual deve ser verificado"
        after = next((r for r in self._audio_nodes(binary, singular) if r["name"] == name), None)
        default = self.command([binary, "get-default-" + singular])
        ready = (after is not None and self._audio_identity(after) == dict(target)
                 and after["mute"] is False and default.returncode == 0
                 and default.stdout.strip() == name and any(v.get("value", 0) > 0 for v in after["volume"].values()))
        return ready, "padrão habilitado, sem mute e com volume; teste físico pendente" if ready else "áudio não confirmado"

    def open_keyboard(self, report):
        if report["backend"] != "kwin":
            return False, "abertura direta exige backend do compositor; nenhum teclado foi instalado"
        native = self.native
        native.deadline = native.clock() + 4
        props = native.props(report["service_owner"], "/VirtualKeyboard", "org.kde.kwin.VirtualKeyboard")
        mode = props.get("mode")
        if props.get("available") != "true" or mode not in ("0", "1", "2"):
            return False, "provedor de teclado indisponível; configuração atual preservada"
        changed = mode != "2"
        restore_mode = "1" if mode == "0" else mode
        try:
            if changed:
                native.call([native.qdbus, report["service_owner"], "/VirtualKeyboard", PROPERTIES + ".Set",
                             "org.kde.kwin.VirtualKeyboard", "mode", "2"])
            native.call([native.qdbus, report["service_owner"], "/VirtualKeyboard", "org.kde.kwin.VirtualKeyboard.forceActivate"])
            visible = False
            for _ in range(6):
                current = native.props(report["service_owner"], "/VirtualKeyboard", "org.kde.kwin.VirtualKeyboard")
                if current.get("visible") == "true":
                    visible = True
                    break
                time.sleep(.1)
        finally:
            if changed:
                native.deadline = native.clock() + 2
                native.call([native.qdbus, report["service_owner"], "/VirtualKeyboard", PROPERTIES + ".Set",
                             "org.kde.kwin.VirtualKeyboard", "mode", restore_mode])
        current = native.props(report["service_owner"], "/VirtualKeyboard", "org.kde.kwin.VirtualKeyboard")
        if current.get("mode") != restore_mode:
            raise UncertainEffect("modo anterior do teclado não confirmado; não repetir")
        visible = visible and current.get("visible") == "true"
        return visible, "teclado visível; abertura automática por toque preservada" if visible else "KWin não exibiu o teclado; confirme provedor e aplicativo com campo de texto"

    def enable_devices(self, key, report, *, delegated=False):
        kinds = {key}
        devices = [d for d in report["devices"] if kinds.intersection(d["kinds"])]
        if key == "touchpad" and not devices:
            devices = [d for d in report["devices"] if d.get("deck_controller") and "pointer" in d["kinds"]]
        if not devices:
            return False, "dispositivo não enumerado; diagnóstico de hardware necessário"
        if any(not d["stable"] or d["enabled"] is None for d in devices):
            return False, "identidade/estado desconhecido; nenhuma entrada foi desabilitada"
        if not delegated:
            for device in devices:
                current = self.native.collect()
                matching = next((d for d in current["devices"] if d["key"] == device["key"]), None)
                if (current["errors"] or current["blockers"] or current["boot_id"] != report["boot_id"]
                        or current["service_owner"] != report["service_owner"] or matching is None
                        or any(matching[k] != device[k] for k in ("key", "event", "name", "stable"))):
                    return False, "identidade/sessão/propriedade mudou antes do efeito; entrada preservada"
                device = matching
                if device["enabled"] is True:
                    continue
                if not device["repairable"]:
                    return False, "compositor não autoriza reabilitar este dispositivo"
                self.native.deadline = self.native.clock() + 2
                self.native.call([self.native.qdbus, report["service_owner"], DEVICE_ROOT + "/" + device["event"],
                    PROPERTIES + ".Set", DEVICE_IFACE, "enabled", "true"])
        after = self.native.collect()
        found = {d["key"]: d for d in after["devices"]}
        ready = (not after["errors"] and after["service_owner"] == report["service_owner"]
                 and after["boot_id"] == report["boot_id"] and all(found.get(d["key"], {}).get("enabled") is True for d in devices))
        return ready, "habilitado e verificado no compositor; teste físico pendente" if ready else "habilitação não confirmada pelo compositor"

    def repair_touch(self, peer):
        helper = (peer or {}).get("touch_helper")
        if not helper:
            return False, "driver ausente; não há reparador FTS registrado neste host"
        # The owner's bounded helper verifies Jupiter, the dedicated I²C adapter,
        # other clients and users before rebinding. USB/Valve HID are not targets.
        ready, detail = self._touch_request(peer, "recover-touch")
        if not ready:
            return ready, detail
        report = self.native.collect()
        return self.enable_devices("touch", report, delegated=True)

    def persist_touch(self, peer):
        helper = (peer or {}).get("touch_helper")
        if not helper:
            return False, "persistência FTS não suportada por responsável registrado"
        return self._touch_request(peer, "persist-touch")

    def _touch_request(self, peer, action):
        result = self.command([*peer["command"], action], effect=True, timeout=125)
        try:
            value = json.loads(result.stdout)
            if (not isinstance(value, dict) or value.get("schema_version") != 1
                    or value.get("scope") != "touch" or type(value.get("ok")) is not bool
                    or not isinstance(value.get("errors"), list)):
                raise ValueError("contrato de autenticação desconhecido")
        except (ValueError, TypeError) as exc:
            raise UncertainEffect("responsável não comprovou término da recuperação autenticada") from exc
        return value["ok"], "; ".join(map(str, value["errors"]))[:800]

    def gamepad(self, report):
        found = [d for d in report["devices"] if "gamepad" in d["kinds"]]
        if not found:
            return False, "controle não enumerado; nenhum perfil foi trocado às cegas"
        binary = self.which("steam")
        if binary:
            # The public URI asks the existing client to open its controller UI;
            # never bootstrap CEF, close Steam, or replace its Desktop mapping.
            subprocess.Popen([binary, "steam://open/bigpicture"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return False, "modo controle solicitado ao Steam; perfil ainda não confirmado. Steam e o perfil Desktop foram preservados"
        return True, "controle enumerado pelo sistema; teste físico dos botões pendente"
