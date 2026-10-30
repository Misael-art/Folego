"""One default-on preference for session startup, independent of effect grants."""
import os
from pathlib import Path
import shutil
import subprocess

from . import paths, shortcuts
from .actions.accessibility import read_object, save_object, private_path
from .actions.accessibility_service import install, UNIT, MARKER
from .adapters.accessibility import bounded_command


def preference():
    value = read_object(paths.config_dir() / "startup.json")
    if value is None:
        return {"schema": 1, "enabled": True}
    if type(value.get("enabled")) is not bool:
        raise ValueError("preferência de inicialização desconhecida; preservada")
    return value


def _managed_entry(path):
    private_path(path)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_uid != os.getuid() or path.stat().st_size > 16384:
        raise ValueError("autostart não é arquivo próprio regular; preservado")
    text = path.read_text()
    if shortcuts.MARKER not in text.splitlines():
        raise ValueError("autostart pessoal preservado")
    return text


def service_status():
    binary = shutil.which("systemctl")
    if not binary:
        return {"state": "unsupported", "reason": "systemd de usuário indisponível"}
    try:
        result = bounded_command([binary, "--user", "show", UNIT,
                                  "--property=FragmentPath,ActiveState,UnitFileState"], timeout=2)
    except (OSError, subprocess.SubprocessError):
        return {"state": "unknown", "reason": "consulta do serviço excedeu prazo ou falhou"}
    if result.returncode:
        return {"state": "unknown", "reason": "estado do serviço não comprovado"}
    props = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    return {"state": props.get("ActiveState", "unknown"),
            "enabled": props.get("UnitFileState") == "enabled",
            "path": props.get("FragmentPath", "")}


def status():
    policy = preference()
    try:
        entry = _managed_entry(paths.autostart_path())
        problem = ""
    except (OSError, ValueError) as exc:
        entry, problem = None, str(exc)
    return {"schema": 1, "enabled": policy["enabled"], "default_enabled": True,
            "ok": not problem, "reason": problem,
            "configured": entry is not None, "effective": None if problem else entry is not None and "Hidden=true" not in entry.splitlines(),
            "path": str(paths.autostart_path()), "service": service_status(),
            "effects_authorized": False}


def configure(enabled=None, *, confirmed=False, manage_service=True):
    if enabled is not None and (not confirmed or type(enabled) is not bool):
        raise ValueError("alteração de início automático exige confirmação e booleano")
    from .orchestration import Coordinator
    with Coordinator().lock(wait=.2):
        policy = preference()
        path = paths.autostart_path()
        old = _managed_entry(path)
        # Respect an explicit desktop-level opt-out as well as the saved option.
        if enabled is None and old and "Hidden=true" in old.splitlines() and policy["enabled"]:
            policy["enabled"] = False
        if enabled is not None:
            policy["enabled"] = enabled
        executable = shortcuts.launcher_executable()
        if executable is None:
            raise ValueError("launcher executável não encontrado")
        text = shortcuts.entry_text(executable) + "Hidden=" + ("false" if policy["enabled"] else "true") + "\n"
        save_object(paths.config_dir() / "startup.json", policy)  # Durable choice before effect.
        private_path(path, create=True)
        from .safely.atomicfile import write_atomic
        write_atomic(path, text.encode(), mode=0o600)
    errors = []
    if manage_service:
        try:
            if policy["enabled"]:
                install(confirmed=True)
            else:
                unit = paths.xdg_config_home() / "systemd/user" / UNIT
                private_path(unit)
                if unit.exists():
                    if not unit.read_text().startswith(MARKER + "\n"):
                        raise ValueError("unit pessoal preservada")
                    current = service_status()
                    if current.get("path") != str(unit):
                        raise ValueError("unit carregada de outro destino; preservada")
                    result = bounded_command([shutil.which("systemctl"), "--user", "disable", UNIT], timeout=3)
                    if result.returncode:
                        raise ValueError("desativação do serviço no próximo login não comprovada")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            errors.append(str(exc))
    return {"ok": not errors, "enabled": policy["enabled"], "errors": errors,
            "outcome": "parcial" if errors else "sucesso",
            "reason": "; ".join(errors) or "início com a sessão atualizado; permissões de reparo preservadas"}
