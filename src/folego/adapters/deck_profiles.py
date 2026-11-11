"""Bounded, native observations of the Deck desktop's Steam and audio profiles.

The Steam CEF interface is private to the installed client. Unknown responses
remain unknown; this module never starts Steam or changes a game profile.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import subprocess
import time
import urllib.parse
import urllib.request
import configparser

from .accessibility import bounded_command, ProbeError
from .. import paths
from .audio_recovery import AudioRecoveryError, WirePlumberRecovery

DESKTOP_APP = 413080
DESKTOP_URL = "template://retrofe_steamdeck_desktop.vdf"
GAMEPAD_URL = "template://retrofe_steamdeck_gamepad.vdf"
MIC_PROFILE = "HiFi (Mic, Speaker)"
MIC_CARD_SUFFIX = "-platform-acp5x_mach.0"


class ProfileUnknown(RuntimeError):
    pass


class SteamClient:
    """One local CEF request at a time, with finite replies and deadlines."""

    def __init__(self, *, port=8080):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ProfileUnknown("porta Steam inválida")
        try:
            listener = subprocess.run(["ss", "-H", "-lptn", f"( sport = :{port} )"],
                                      capture_output=True, text=True, timeout=1, check=False)
            matches = re.findall(r'users:\(\("steamwebhelper",pid=(\d+),fd=\d+\)\)', listener.stdout)
            if (listener.returncode or len(matches) != 1 or
                    (Path("/proc") / matches[0]).stat().st_uid != os.getuid()):
                raise ProfileUnknown("API local não pertence ao Steam deste usuário")
            self.owner_pid = int(matches[0])
            self.owner_start = self._owner_start()
        except (OSError, TimeoutError, subprocess.SubprocessError) as exc:
            raise ProfileUnknown("identidade da API local da Steam não comprovada") from exc
        self.port = port
        self.sock = None
        self.buffer = b""
        self.sequence = 0
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(f"http://127.0.0.1:{port}/json", timeout=2) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise ProfileUnknown("inventário Steam excede limite")
            pages = json.loads(raw)
            if not isinstance(pages, list) or len(pages) > 64:
                raise ProfileUnknown("inventário Steam desconhecido")
            matches = [p for p in pages if isinstance(p, dict) and p.get("title") == "SharedJSContext"]
            if len(matches) != 1:
                raise ProfileUnknown("contexto Steam ausente ou ambíguo")
            url = urllib.parse.urlsplit(matches[0]["webSocketDebuggerUrl"])
            if (url.scheme != "ws" or url.hostname not in ("127.0.0.1", "localhost", "::1")
                    or url.port != port or not url.path.startswith("/devtools/page/")):
                raise ProfileUnknown("Steam retornou endpoint fora do contexto local")
            self.sock = socket.create_connection(("127.0.0.1", port), timeout=2)
            self.sock.settimeout(3)
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            path = url.path + ("?" + url.query if url.query else "")
            self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
            header = b""
            while b"\r\n\r\n" not in header and len(header) <= 16384:
                part = self.sock.recv(4096)
                if not part:
                    raise ProfileUnknown("Steam encerrou o handshake")
                header += part
            if len(header) > 16384 or b"\r\n\r\n" not in header:
                raise ProfileUnknown("handshake Steam incompleto")
            expected = base64.b64encode(hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
            head, self.buffer = header.split(b"\r\n\r\n", 1)
            if b" 101 " not in head.split(b"\r\n", 1)[0] or expected not in head:
                raise ProfileUnknown("Steam recusou conexão local")
        except (OSError, ValueError, KeyError, TypeError, TimeoutError) as exc:
            self.close()
            raise ProfileUnknown("API local da Steam indisponível") from exc
        except ProfileUnknown:
            self.close()
            raise

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def _owner_start(self):
        proc = Path("/proc") / str(self.owner_pid)
        try:
            executable = proc.joinpath("exe").resolve(strict=True)
            expected = paths._env_dir("XDG_DATA_HOME", Path.home() / ".local/share") / "Steam/ubuntu12_64/steamwebhelper"
            if executable != expected.resolve(strict=True):
                raise ProfileUnknown("executável Steam local mudou")
            return proc.joinpath("stat").read_text().rsplit(")", 1)[1].split()[19]
        except (OSError, ValueError, IndexError) as exc:
            raise ProfileUnknown("processo Steam local não comprovado") from exc

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _read(self, size):
        while len(self.buffer) < size:
            part = self.sock.recv(min(4096, size - len(self.buffer)))
            if not part:
                raise ProfileUnknown("Steam encerrou conexão local")
            self.buffer += part
        result, self.buffer = self.buffer[:size], self.buffer[size:]
        return result

    def evaluate(self, expression):
        self.sequence += 1
        payload = json.dumps({"id": self.sequence, "method": "Runtime.evaluate", "params": {
            "expression": expression, "awaitPromise": True, "returnByValue": True,
            "userGesture": True, "timeout": 3000}}).encode()
        mask = os.urandom(4)
        header = b"\x81" + (bytes([0x80 | len(payload)]) if len(payload) < 126 else
                             b"\xfe" + struct.pack("!H", len(payload)))
        self.sock.sendall(header + mask + bytes(value ^ mask[i % 4] for i, value in enumerate(payload)))
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            self.sock.settimeout(max(.1, deadline - time.monotonic()))
            first, second = self._read(2)
            length = second & 127
            if length == 126:
                length = struct.unpack("!H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read(8))[0]
            if length > 262144:
                raise ProfileUnknown("resposta Steam excede limite")
            mask = self._read(4) if second & 128 else None
            body = self._read(length)
            if mask:
                body = bytes(value ^ mask[i % 4] for i, value in enumerate(body))
            if first & 15 == 8:
                raise ProfileUnknown("Steam fechou a conexão")
            if first & 15 == 9:
                continue
            if first & 15 != 1 or not first & 0x80:
                raise ProfileUnknown("quadro Steam desconhecido")
            try:
                row = json.loads(body)
                if row.get("id") != self.sequence:
                    continue
                if row.get("error") or row.get("result", {}).get("exceptionDetails"):
                    raise ProfileUnknown("Steam recusou consulta/seleção")
                return row["result"]["result"].get("value")
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise ProfileUnknown("resposta Steam ilegível") from exc
        raise ProfileUnknown("Steam não respondeu no prazo")

    def controllers(self):
        rows = self.evaluate("""Promise.all(Array.from({length:16}, async (_,index) => {
            try { const c=await SteamClient.Input.GetConfigForAppAndController(413080,index);
                if (!c || !c.bConfigurationEnabled) return null;
                return {index:c.unControllerIndex,type:c.nControllerType,url:c.URL || '',
                    title:c.Title || '',gamepad:!!c.bUsesGamepad,keyboard:!!c.bUsesKeyboard,
                    mouse:!!c.bUsesMouse}; } catch (_) { return null; }
        }))""")
        if not isinstance(rows, list) or len(rows) != 16:
            raise ProfileUnknown("lista de controles Steam desconhecida")
        result = [r for r in rows if r is not None and isinstance(r, dict) and r.get("type") == 4]
        if len(result) != 1:
            raise ProfileUnknown("controle Steam Deck ausente ou ambíguo")
        row = result[0]
        if (type(row.get("index")) is not int or not 0 <= row["index"] < 16
                or any(type(row.get(k)) is not bool for k in ("mouse", "keyboard", "gamepad"))
                or not isinstance(row.get("url"), str) or len(row["url"]) > 512
                or not isinstance(row.get("title"), str) or len(row["title"]) > 128):
            raise ProfileUnknown("perfil Steam desconhecido")
        return row

    def select_desktop(self, index):
        if type(index) is not int or not 0 <= index < 16:
            raise ProfileUnknown("índice de controle Steam inválido")
        if self._owner_start() != self.owner_start:
            raise ProfileUnknown("processo Steam mudou antes da seleção")
        current = self.controllers()
        if (current["index"] != index or current["url"] != GAMEPAD_URL
                or current["mouse"] or current["keyboard"]):
            raise ProfileUnknown("perfil Steam mudou antes da seleção")
        self.evaluate("Promise.resolve(SteamClient.Input.SetSelectedConfigForApp(413080,"
                      f"{index},{json.dumps(DESKTOP_URL)},false,1)).then(()=>true)")


class DeckProfiles:
    def __init__(self, *, steam_factory=SteamClient, runner=bounded_command,
                 data_home=None, state_home=None, model_path=Path("/sys/class/dmi/id/product_name"),
                 audio_recovery=None):
        self.steam_factory, self.runner = steam_factory, runner
        self.data_home = Path(data_home) if data_home else paths._env_dir(
            "XDG_DATA_HOME", Path.home() / ".local/share")
        self.state_home = Path(state_home) if state_home else paths._env_dir(
            "XDG_STATE_HOME", Path.home() / ".local/state")
        self.model_path = Path(model_path)
        self.audio_recovery = audio_recovery or WirePlumberRecovery(runner=runner, state_home=self.state_home)

    def supported(self):
        try:
            return self.model_path.read_text().strip() in ("Jupiter", "Galileo")
        except OSError:
            return False

    def template_digest(self):
        file = self.data_home / "Steam/controller_base/templates/retrofe_steamdeck_desktop.vdf"
        try:
            info = file.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or not 1024 <= info.st_size <= 65536:
                raise ProfileUnknown("template Desktop não comprovado")
            return hashlib.sha256(file.read_bytes()).hexdigest()
        except OSError as exc:
            raise ProfileUnknown("template Desktop ausente ou ilegível") from exc

    def steam(self):
        try:
            with self.steam_factory() as client:
                row = client.controllers()
            digest = self.template_digest()
            identity = {"index": row["index"], "type": row["type"], "url": row["url"],
                        "template_sha256": digest}
            if row["url"] == DESKTOP_URL and row["mouse"] and row["keyboard"]:
                state, detail = "healthy", "Steam: perfil Desktop com mouse e teclado habilitados; gesto físico não testado"
            elif row["url"] == GAMEPAD_URL and not row["mouse"] and not row["keyboard"]:
                state, detail = "fault", "Steam deixou o perfil Gamepad no desktop; mouse e teclado desabilitados"
            else:
                state, detail = "unknown", "perfil Steam diferente ou saídas inconsistentes; escolha preservada"
            return {"state": state, "detail": detail, "identity": identity}
        except (ProfileUnknown, OSError, ValueError, TimeoutError) as exc:
            return {"state": "unknown", "detail": str(exc)[:180], "identity": None}

    def _pactl(self, *args):
        try:
            answer = self.runner(["pactl", *args], timeout=2, env={**os.environ, "LC_ALL": "C"})
            if answer.returncode or len(answer.stdout) > 262144:
                raise ProfileUnknown("resposta PipeWire incompleta")
            return answer.stdout
        except (OSError, TimeoutError, ValueError, subprocess.SubprocessError) as exc:
            raise ProfileUnknown("PipeWire indisponível") from exc

    def microphone(self):
        try:
            cards = json.loads(self._pactl("-f", "json", "list", "cards"))
            sources = json.loads(self._pactl("-f", "json", "list", "sources"))
            if not isinstance(cards, list) or not isinstance(sources, list) or len(cards) > 32 or len(sources) > 128:
                raise ProfileUnknown("grafo de áudio desconhecido")
            if not all(isinstance(row, dict) for row in (*cards, *sources)):
                raise ProfileUnknown('grafo de áudio incompleto')
            matches = [c for c in cards if isinstance(c, dict) and
                       isinstance(c.get("name"), str) and c["name"].endswith(MIC_CARD_SUFFIX)]
            if len(matches) != 1:
                raise ProfileUnknown("placa interna ausente ou ambígua")
            card = matches[0]
            default = self._pactl("get-default-source").strip()
            if not default or len(default) > 256:
                raise ProfileUnknown("entrada padrão não comprovada")
            profiles = card.get("profiles")
            target = profiles.get(MIC_PROFILE) if isinstance(profiles, dict) else None
            active = card.get('active_profile')
            if (target is None and isinstance(profiles, dict) and active == 'off'
                    and default == 'mic-biglinux' and self.supported()):
                virtual = [source for source in sources if source.get('name') == default]
                if len(virtual) != 1 or virtual[0].get('mute') is not False:
                    raise ProfileUnknown('microfone virtual silenciado ou sem identidade comprovada')
                owner = self.audio_recovery.probe(card, cards, sources, MIC_PROFILE)
                return {'state': 'fault', 'code': 'audio-enumeration-incomplete',
                        'detail': 'Placa interna desligada após enumeração incompleta; reenumerar WirePlumber',
                        'identity': {'card': card['name'], 'active': active, 'target': MIC_PROFILE,
                                     'default': default, 'recovery': 'wireplumber-reprobe', 'owner': owner}}
            if not isinstance(target, dict) or target.get("available") is not True or target.get("sources", 0) < 1:
                raise ProfileUnknown("perfil de microfone interno indisponível")
            active = card.get("active_profile")
            if not isinstance(active, str):
                raise ProfileUnknown("perfil ativo desconhecido")
            physical = [s for s in sources if isinstance(s, dict) and
                        isinstance(s.get("name"), str) and s["name"].startswith("alsa_input.") and
                        isinstance(s.get("properties"), dict) and
                        s["properties"].get("device.name") == card["name"]]
            virtual = [s for s in sources if isinstance(s, dict) and s.get("name") == "mic-biglinux"]
            identity = {"card": card["name"], "active": active, "target": MIC_PROFILE,
                        "default": default}
            if default != "mic-biglinux" and (len(physical) != 1 or default != physical[0]["name"]):
                return {"state": "unknown", "detail": "outra entrada padrão em uso; escolha preservada",
                        "identity": identity}
            if default == "mic-biglinux" and (len(virtual) != 1 or
                    type(virtual[0].get("mute")) is not bool or virtual[0]["mute"]):
                return {"state": "unknown", "detail": "entrada BigLinux ausente ou silenciada; revisar sem alterar mute",
                        "identity": identity}
            if active == MIC_PROFILE:
                if len(physical) != 1 or type(physical[0].get("mute")) is not bool:
                    state, detail = "unknown", "perfil interno ativo, mas captura física não comprovada"
                elif physical[0]["mute"]:
                    state, detail = "unknown", "microfone interno silenciado; escolha preservada para revisão manual"
                elif default == 'mic-biglinux' and not self._capture_linked(physical[0], sources):
                    state, detail = 'unknown', 'cadeia física → echo-cancel → mic-biglinux sem ligação comprovada'
                else:
                    state, detail = "healthy", "perfil do microfone interno e fonte física habilitados; voz não testada"
            elif active == "pro-audio":
                state, detail = "fault", "perfil Pro Audio não aplica o caminho UCM do microfone interno"
            elif active.startswith("HiFi (Headset") and profiles.get(active, {}).get("available") is False:
                state, detail = "fault", "perfil de headset ausente impede o microfone interno"
            else:
                state, detail = "unknown", "outro perfil de áudio ativo; escolha preservada"
            return {"state": state, "detail": detail, "identity": identity}
        except (ProfileUnknown, ProbeError, AudioRecoveryError, configparser.Error, OSError, ValueError,
                TypeError, KeyError, AttributeError, IndexError) as exc:
            return {"state": "unknown", "detail": str(exc)[:180], "identity": None}

    def _capture_linked(self, physical, sources):
        outputs = json.loads(self._pactl('-f', 'json', 'list', 'source-outputs'))
        if not isinstance(outputs, list) or len(outputs) > 128:
            return False
        echo = [row for row in sources if row.get('name') == 'echo-cancel-source']
        if len(echo) != 1:
            return False
        for name, source in (('echo-cancel-capture', physical), ('mic-biglinux-capture', echo[0])):
            index = source.get('index')
            matches = [row for row in outputs if isinstance(row, dict)
                       and isinstance(row.get('properties'), dict)
                       and row['properties'].get('node.name') == name]
            if (type(index) is not int or index < 0 or len(matches) != 1
                    or matches[0].get('source') != index or matches[0].get('mute') is not False):
                return False
        return True

    def observe(self):
        if not self.supported():
            return {}
        return {"touchpad": self.steam(), "microphone": self.microphone()}

    def restore(self, key, before):
        """Caller must have recorded intent, checked ownership and reobserved."""
        if key == "microphone":
            if before['identity'].get('recovery') == 'wireplumber-reprobe':
                self.audio_recovery.restart(before['identity']['owner'])
                return
            if before["identity"]["active"] not in ("pro-audio", "HiFi (Headset, Speaker)"):
                raise ProfileUnknown("outro perfil de microfone preservado")
            self._pactl("set-card-profile", before["identity"]["card"], MIC_PROFILE)
        elif key == "touchpad":
            with self.steam_factory() as client:
                client.select_desktop(before["identity"]["index"])
        else:
            raise ValueError("perfil desconhecido")
