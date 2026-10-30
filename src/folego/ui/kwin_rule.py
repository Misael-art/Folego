"""Optional KWin window rule that keeps the Fôlego widget above other windows on Plasma.

Wayland gives an application no way to stay on top or pick its position; on Plasma
the compositor does it through window rules. This module writes one rule, owned by
Fôlego and matched by app id + exact widget title, with the official
kwriteconfig6/kreadconfig6 tools, then asks KWin to reload. It only runs after an
explicit confirmation, keeps every other rule untouched and can be removed again.
"""
import shutil
import subprocess

GROUP = "folego-widget"
FILE = "kwinrulesrc"
APP_ID = "folego"


def rule_keys(title: str, x: int, y: int) -> dict:
    """Force keep-above/no focus/out of taskbar; the corner position applies only initially."""
    return {
        "Description": "Fôlego — widget flutuante (criado pelo Fôlego)",
        "wmclass": APP_ID, "wmclassmatch": "1",
        "title": title, "titlematch": "1",
        "above": "true", "aboverule": "2",
        "noborder": "true", "noborderrule": "2",
        "skiptaskbar": "true", "skiptaskbarrule": "2",
        "skipswitcher": "true", "skipswitcherrule": "2",
        "skippager": "true", "skippagerrule": "2",
        "acceptfocus": "false", "acceptfocusrule": "2",
        "position": f"{int(x)},{int(y)}", "positionrule": "3",
    }


def _tools(which=shutil.which):
    write, read = which("kwriteconfig6"), which("kreadconfig6")
    if not write or not read:
        raise RuntimeError("kwriteconfig6/kreadconfig6 ausentes: regra do KWin indisponível nesta sessão")
    return write, read


def _rules(read, run) -> list:
    result = run([read, "--file", FILE, "--group", "General", "--key", "rules"],
                 capture_output=True, text=True, check=False, timeout=5)
    if result.returncode:
        raise RuntimeError("não foi possível ler as regras do KWin; configuração preservada")
    return [item for item in (result.stdout or "").strip().split(",") if item]


def _reload(run, which=shutil.which) -> bool:
    for tool in ("qdbus6", "qdbus"):
        path = which(tool)
        if path and run([path, "org.kde.KWin", "/KWin", "reconfigure"],
                        capture_output=True, check=False).returncode == 0:
            return True
    path = which("dbus-send")
    return bool(path) and run([path, "--session", "--type=method_call", "--dest=org.kde.KWin", "/KWin",
                               "org.kde.KWin.reconfigure"], capture_output=True, check=False).returncode == 0


def installed(*, run=subprocess.run, which=shutil.which) -> bool:
    try:
        _write, read = _tools(which)
    except RuntimeError:
        return False
    return GROUP in _rules(read, run)


def install(title: str, x: int, y: int, *, confirmed: bool, run=subprocess.run, which=shutil.which) -> dict:
    if not confirmed:
        raise ValueError("criar a regra do KWin exige confirmação explícita")
    write, read = _tools(which)
    rules = _rules(read, run)
    for key, value in rule_keys(title, x, y).items():
        run([write, "--file", FILE, "--group", GROUP, "--key", key, value], check=True)
    if GROUP not in rules:
        rules.append(GROUP)
        run([write, "--file", FILE, "--group", "General", "--key", "rules", ",".join(rules)], check=True)
        run([write, "--file", FILE, "--group", "General", "--key", "count", str(len(rules))], check=True)
    return {"group": GROUP, "rules": rules, "reloaded": _reload(run, which)}


def remove(*, run=subprocess.run, which=shutil.which) -> dict:
    write, read = _tools(which)
    rules = [item for item in _rules(read, run) if item != GROUP]
    run([write, "--file", FILE, "--group", "General", "--key", "rules", ",".join(rules)], check=True)
    run([write, "--file", FILE, "--group", "General", "--key", "count", str(len(rules))], check=True)
    run([write, "--file", FILE, "--group", GROUP, "--key", "Description", "--delete"], check=True)
    for key in rule_keys("", 0, 0):
        run([write, "--file", FILE, "--group", GROUP, "--key", key, "--delete"], check=True)
    return {"group": GROUP, "rules": rules, "reloaded": _reload(run, which)}
