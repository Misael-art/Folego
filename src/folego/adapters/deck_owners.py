"""Read-only evidence published by optional Deck input managers."""
import os
from pathlib import Path
import re
import stat

from .. import paths


def emuatlas_pending():
    state = paths._env_dir("XDG_STATE_HOME", Path.home() / ".local/state")
    try:
        directory = state / "retrofe/input-session"
        for parent in (directory.parent, directory):
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                return "EmuAtlas/RetroFE: diretório de recuperação sem identidade confirmada."
        for name in ("steam-desktop-session.json", "kde-global-shortcut-guard.json", "desktop-environment.json"):
            try:
                (directory / name).lstat()
            except FileNotFoundError:
                continue
            return "EmuAtlas/RetroFE: aguardando o término da sessão ou da restauração do desktop."
    except FileNotFoundError:
        pass
    except OSError:
        return "EmuAtlas/RetroFE: estado da recuperação ilegível."
    return ""


def phasezero_controller(native):
    # The official controller-desktop installer registers this user unit. The
    # running supervisor is also recognized by argv for nonstandard installations.
    from .accessibility import ProbeError, present
    unit = "phasezero-controller-desktop.service"
    try:
        if not present(paths.xdg_config_home() / "systemd/user" / unit):
            return ""
        systemctl = native.which("systemctl")
        if systemctl:
            state = native.call([systemctl, "--user", "show", unit, "-p", "LoadState",
                                 "-p", "ActiveState", "-p", "SubState"])
            props = dict(line.split("=", 1) for line in state.splitlines())
            if (props.get("LoadState") in {"loaded", "masked", "not-found"}
                    and props.get("ActiveState") == "inactive" and props.get("SubState") == "dead"):
                return ""
            if props.get("ActiveState") == "active":
                return "PhaseZero está gerindo o controle de desktop."
    except (ProbeError, OSError, ValueError):
        pass
    return "Aguardando confirmação do serviço de controle do PhaseZero."


def controller_command(argv):
    """Inspect only the invoked script and its subcommand, never a child's arguments."""
    if not argv:
        return ""
    script, *args = [os.fsdecode(arg) for arg in argv]
    if Path(script).name in {"bash", "sh"} or re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", Path(script).name):
        if not args:
            return ""
        script, *args = args
    if Path(script).name == "scc-daemon":
        return "Controle reservado pelo mapeador sc-controller."
    if script.endswith("/linux/steamdeck/controller-desktop.sh") and args[:1] == ["supervise"]:
        return "PhaseZero está gerindo o controle de desktop."
    if (script.endswith("/linux/steamdeck/desktop_session.py") and args
            and args[0] in {"watch", "reconcile", "reconcile-input", "recover-touch", "persist-touch"}):
        return "PhaseZero está supervisionando ou restaurando a entrada do desktop."
    if script.endswith("/Tools/launchers/retrofe/input-session.py") and args[:1] == ["guard"]:
        return "EmuAtlas/RetroFE está protegendo ou restaurando os atalhos."
    if script.endswith(("/Tools/launchers/retrofe/launch-retrofe.sh", "/Tools/launchers/retrofe/run-retrofe.sh")):
        return "EmuAtlas/RetroFE está iniciando ou usando o front-end."
    if script.endswith("/Tools/launchers/retrofe/steam-input.py"):
        if args[:1] == ["--root"]:
            args = args[2:]
        elif args and args[0].startswith("--root="):
            args = args[1:]
        if args and args[0] in {"ensure", "session-run", "session-prepare", "session-acquire", "session-release",
                                "session-attach", "session-watch", "session-recover", "controller-prepare"}:
            return "EmuAtlas/RetroFE está gerindo a sessão de controle."
    return ""
