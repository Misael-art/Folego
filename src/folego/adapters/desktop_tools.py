"""Explicit desktop shortcuts. All subprocess and compositor I/O is off Qt.

Wayland input uses an app-owned, transient ydotoold only if uinput is already
accessible. No package install, privilege, shared daemon, shell or autostart.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
import uuid

from .. import paths


class DesktopTools:
    def __init__(self, *, env=None, run=subprocess.run):
        self.env = dict(os.environ if env is None else env)
        self.run = run
        self.daemon = None
        self.directory = None
        self.socket = None
        self.position_directory = None
        self.socket_directory = None
        self.capture = None

    def _call(self, argv, timeout=5):
        result = self.run(argv, env=self.env, capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError("O desktop não confirmou a solicitação; não houve repetição")
        return result.stdout.decode(errors="replace").strip()

    def _input(self):
        if self.env.get("XDG_SESSION_TYPE") != "wayland":
            binary = shutil.which("xdotool")
            if not binary or not self.env.get("DISPLAY"):
                raise RuntimeError("Entrada indisponível: requer X11/xdotool ou Wayland/uinput")
            return binary, False
        binary, daemon = shutil.which("ydotool"), shutil.which("ydotoold")
        if not binary or not daemon or not os.access("/dev/uinput", os.W_OK):
            raise RuntimeError("Entrada indisponível: ydotool/ydotoold e acesso existente a /dev/uinput são necessários")
        if self.daemon is not None and self.daemon.poll() is not None:
            self.close()
            raise RuntimeError("A entrada encerrou; clique novamente para reconectar")
        if self.daemon is None:
            from ..safely.jobtemp import prepare_job_environment
            prepared = prepare_job_environment(self.env, root=paths.data_dir() / "desktop-input")
            self.directory = Path(prepared["TMPDIR"])
            # Unix socket addresses are limited to ~108 bytes. Keep only this
            # short IPC endpoint in XDG_RUNTIME_DIR; all payloads/TMPDIR stay on
            # persistent disk. Never use a shared daemon or a user's socket.
            runtime = Path(self.env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
            info = runtime.stat()
            if runtime.is_symlink() or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise RuntimeError("Diretório de comunicação privado indisponível")
            self.socket_directory = Path(tempfile.mkdtemp(prefix="folego-input-", dir=runtime))
            self.socket = self.socket_directory / "input.sock"
            if len(os.fsencode(self.socket)) >= 104:
                raise RuntimeError("Caminho de comunicação excede o limite do sistema")
            self.env.update(TMPDIR=str(self.directory), YDOTOOL_SOCKET=str(self.socket))
            self.daemon = subprocess.Popen([daemon, "--socket-path", str(self.socket),
                                             "--socket-perm", "0600"], env=self.env,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            end = time.monotonic() + 4
            while time.monotonic() < end:
                if self.daemon.poll() is not None:
                    raise RuntimeError("Não foi possível preparar a entrada virtual")
                try:
                    if stat.S_ISSOCK(self.socket.stat().st_mode):
                        time.sleep(1)  # udev/compositor enumeration is asynchronous
                        return binary, True
                except FileNotFoundError:
                    pass
                time.sleep(.03)
            raise RuntimeError("Entrada não ficou pronta no prazo; solicitação não enviada")
        return binary, True

    def keys(self, codes):
        if (not codes or len(codes) > 8 or any(type(k) is not int or not 1 <= k <= 127 for k in codes)):
            raise ValueError("combinação inválida")
        binary, wayland = self._input()
        if wayland:
            args = [f"{key}:1" for key in codes] + [f"{key}:0" for key in reversed(codes)]
            self._call([binary, "key", "--key-delay", "5", *args])
        else:
            symbols = {29: "ctrl", 42: "shift", 15: "Tab", 57: "space", 14: "BackSpace", 28: "Return", 110: "Insert"}
            for text, values in (("1234567890", range(2, 12)), ("qwertyuiop", range(16, 26)),
                                 ("asdfghjkl", range(30, 39)), ("zxcvbnm", range(44, 51))):
                symbols.update(zip(values, text))
            if any(code not in symbols for code in codes):
                raise ValueError("tecla não suportada no backend X11")
            self._call([binary, "key", "--delay", "5", "+".join(symbols[c] for c in codes)])
        return "Solicitação de tecla enviada ao aplicativo em foco"

    def perform(self, action, value=None):
        if action in ('select_all', 'delete_all'):
            from .editable_text import edit_focused
            return edit_focused(action, env=self.env)
        if action == "copy":
            # Standard alternate editing keys: Ctrl+C in a terminal can signal
            # its foreground job. Copy must never turn into an interrupt.
            return self.keys([29, 110])
        if action == "paste":
            return self.keys([42, 110])
        if action == "key":
            return self.keys(value)
        if action == "print":
            if self.capture is not None and self.capture.poll() is None:
                return "A captura já está aberta; conclua ou cancele na ferramenta de captura"
            binary = shutil.which("spectacle")
            if not binary:
                raise RuntimeError("Captura indisponível: Spectacle não encontrado")
            # Hand off to its native interactive selection; no disk path or
            # capture is silently chosen. Never report an image was saved.
            self.capture = subprocess.Popen([binary, "--new-instance", "--region"], env=self.env,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             start_new_session=True)
            return "Selecione a região na ferramenta de captura"
        if action == "position":
            return self.position(*value)
        raise ValueError("atalho desconhecido")

    def position(self, caption, geometry, service=None, confirmation=None):
        """KWin can move only this process's uniquely titled keyboard window."""
        binary = shutil.which("qdbus6")
        if not binary:
            raise RuntimeError("Posicionamento Wayland não confirmado: qdbus6/KWin ausente")
        from ..safely.jobtemp import prepare_job_environment
        if self.position_directory is None:
            env = prepare_job_environment(self.env, root=paths.data_dir() / "desktop-placement")
            self.position_directory = Path(env["TMPDIR"])
        source = self.position_directory / "position.js"
        x, y, width, height = (int(n) for n in geometry)
        name = "folego-keyboard-" + uuid.uuid4().hex
        source.write_text("const matches = workspace.windowList().filter(w => w.pid === "
                          + str(os.getpid()) + " && w.caption === " + json.dumps(caption) + ");\n"
                          + "if (matches.length === 1) { const w = matches[0]; w.keepAbove = true;"
                          + ("function report(){ const g=w.frameGeometry; callDBus(" + json.dumps(service)
                             + ', "/keyboard", "org.folego.Keyboard", "placed", '
                             + json.dumps(caption) + ", JSON.stringify([g.x,g.y,g.width,g.height])); }"
                             + "w.frameGeometryChanged.connect(report);" if service else "")
                          + f" w.frameGeometry = {{x:{x},y:{y},width:{width},height:{height}}}; "
                          + ("report();" if service else "")
                          + " }\n")
        script = self._call([binary, "org.kde.KWin", "/Scripting",
                             "org.kde.kwin.Scripting.loadScript", str(source), name])
        if not script.isdigit():
            raise RuntimeError("KWin não confirmou o script próprio")
        try:
            self._call([binary, "org.kde.KWin", "/Scripting/Script" + script,
                        "org.kde.kwin.Script.run"])
            if confirmation is None or not confirmation.wait(3):
                raise RuntimeError("O compositor não confirmou a posição do teclado")
        finally:
            self._call([binary, "org.kde.KWin", "/Scripting",
                        "org.kde.kwin.Scripting.unloadScript", name])
        return ""

    def close(self):
        if self.daemon is not None:
            if self.daemon.poll() is None:
                self.daemon.terminate()  # only the Popen child this instance created
                try:
                    self.daemon.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    # No forced kill and no second daemon while ownership is live.
                    return False
            self.daemon = None
        if self.socket_directory is not None:
            # Only our endpoint, after the exact Popen child has been reaped.
            if self.socket is not None and self.socket.exists():
                self.socket.unlink()
            try:
                self.socket_directory.rmdir()
            except OSError:
                pass  # unexpected files are preserved
            self.socket_directory = None
        return True
