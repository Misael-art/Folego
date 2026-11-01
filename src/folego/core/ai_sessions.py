"""Read-only AI quota observations. No Qt, account manager or token renewal.

Provider data is deliberately asymmetric: Codex reports rate limits, Claude
has a first-party usage endpoint, Web/Grok do not supply a quota here. A reset
in the past invalidates an observation; it never creates a full allowance.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import math
import os
from pathlib import Path
import time
import urllib.request

MAX_AGE = 900
MAX_FILE = 512 * 1024
MAX_TAIL = 64 * 1024
NAMES = {"codex": "Codex", "web": "Codex Web", "claude": "Claude", "grok": "Grok"}


def read_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise ValueError("documento acima do orçamento")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("objeto esperado")
    return value


def timestamp(value):
    try:
        if isinstance(value, str):
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.timestamp() if parsed.tzinfo else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return float(value) if value > 0 else None
    except (ValueError, OverflowError, OSError):
        pass
    return None


def unknown(provider, reason="Ainda não consultado", label=None):
    return dict(provider=provider, label=label or NAMES[provider], windows=[],
                remaining=None, observed_at=None, reason=reason, plan=None,
                paid_until=None, access="não verificado", renewal="não verificada")


def quota_window(name, used, reset, now):
    if (isinstance(used, bool) or not isinstance(used, (int, float))
            or not math.isfinite(used) or not 0 <= used <= 100):
        return None
    reset = timestamp(reset)
    return dict(name=name, used=round(used), remaining=round(100 - used), resets_at=reset,
                valid=reset is not None and reset > now)


def effective(item, now=None):
    """Re-evaluate freshness at display time, even without a collector response."""
    now = time.time() if now is None else now
    seen = item.get("observed_at")
    windows = item.get("windows", [])
    if (not seen or not 0 <= now - seen <= MAX_AGE or not windows
            or any(not w.get("valid") or not w.get("resets_at") or w["resets_at"] <= now
                   for w in windows)):
        return None
    return min(w["remaining"] for w in windows)


def band(remaining):
    return "unknown" if remaining is None else "green" if remaining > 60 else "yellow" if remaining > 20 else "red"


def _rollouts(home):
    """Bound both directory enumeration and bytes read, not just result count."""
    import itertools
    paths = [home / "sessions"]
    for _ in range(3):
        following = []
        for path in paths:
            try:
                with os.scandir(path) as entries:
                    names = list(itertools.islice(entries, 129))
                if len(names) > 128:
                    raise ValueError("inventário de sessões excede orçamento")
                following.extend(Path(e.path) for e in names if e.is_dir(follow_symlinks=False))
            except FileNotFoundError:
                continue
        paths = sorted(following, reverse=True)[:32]
    files = []
    for path in paths:
        with os.scandir(path) as entries:
            names = list(itertools.islice(entries, 257))
        if len(names) > 256:
            raise ValueError("inventário de rollouts excede orçamento")
        files.extend(Path(e.path) for e in names if e.name.startswith("rollout-")
                     and e.name.endswith(".jsonl") and e.is_file(follow_symlinks=False))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:40]


def _tail(path):
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(max(0, size - MAX_TAIL))
        if size > MAX_TAIL:
            stream.readline()  # discard the partial first record
        raw = stream.read(MAX_TAIL)
    # A torn final record is not a completed provider observation.
    return raw[:raw.rfind(b"\n") + 1].splitlines()


def _claims(auth):
    token = auth.get("tokens", {}).get("id_token")
    if not isinstance(token, str) or token.count(".") != 2:
        return {}
    try:
        body = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        value = claims.get("https://api.openai.com/auth", {})
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError, AttributeError):
        return {}


def codex(home, now, *, provider="codex", label=None):
    result = unknown(provider, "Sem observação recente da conta", label)
    home = Path(home)
    auth = None
    try:
        auth = read_json(home / "auth.json")
        claims = _claims(auth)
        result.update(plan=claims.get("chatgpt_plan_type"),
                      paid_until=timestamp(claims.get("chatgpt_subscription_active_until")))
        tokens = auth.get("tokens") or {}
        if isinstance(tokens.get("refresh_token"), str) and tokens["refresh_token"]:
            result["renewal"] = "token presente; validade remota não verificada"
        # JWT claims are metadata, not proof that a server accepts a credential.
        result["access"] = "metadados locais; aceitação remota não verificada"
        auth_changed = (home / "auth.json").stat().st_mtime
    except FileNotFoundError:
        auth_changed = 0
    if provider == "web":
        result["reason"] = "Codex Web não fornece percentual de cota nesta fonte"
        return result
    best = None
    for path in _rollouts(home):
        for line in _tail(path):
            if b'"rate_limits"' not in line:
                continue
            try:
                record = json.loads(line)
                limits = record.get("payload", {}).get("rate_limits")
                seen = timestamp(record.get("timestamp"))
                if (isinstance(limits, dict) and limits.get("limit_id") == "codex"
                        and seen and (best is None or seen > best[0])):
                    best = seen, limits
            except (ValueError, AttributeError):
                continue
    if best:
        seen, limits = best
        if seen < auth_changed:
            result["reason"] = "Conta/credencial alterada após a observação; use a conta para atualizar"
            return result
        result["observed_at"] = seen
        result["plan"] = result["plan"] or limits.get("plan_type")
        for key, name in (("primary", "Sessão"), ("secondary", "Semana")):
            data = limits.get(key)
            if isinstance(data, dict):
                value = quota_window(name, data.get("used_percent"), data.get("resets_at"), now)
                if value:
                    result["windows"].append(value)
                else:
                    result["reason"] = "Janela de cota inválida"
                    result["windows"] = []
                    return result
        result["remaining"] = effective(result, now)
        result["reason"] = "" if result["remaining"] is not None else "Observação vencida/incompleta; aguardando o provedor"
    if auth is not None and read_json(home / "auth.json") != auth:
        return unknown(provider, "Conta alterada durante a leitura", label)
    return result


def http_json(url, headers):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError("redirecionamento recusado")
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.build_opener(NoRedirect).open(request, timeout=5) as response:
        raw = response.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        raise ValueError("resposta acima do orçamento")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("resposta inválida")
    return value


def claude(config, now, fetch):
    result = unknown("claude", "Login do Claude não encontrado")
    credentials = read_json(Path(config) / ".credentials.json")
    oauth = credentials.get("claudeAiOauth")
    if not isinstance(oauth, dict) or not isinstance(oauth.get("accessToken"), str):
        return result
    expiry = timestamp(oauth.get("expiresAt", 0) / 1000) if isinstance(oauth.get("expiresAt"), (int, float)) else None
    if not expiry or expiry <= now:
        result["reason"] = "Login expirado/sem validade comprovada; renove no Claude"
        return result
    # Never refresh, transfer or persist credentials. Only this first-party URL.
    headers = {"Authorization": "Bearer " + oauth["accessToken"],
               "anthropic-beta": "oauth-2025-04-20", "User-Agent": "Folego/0.2"}
    payload = fetch("https://api.anthropic.com/api/oauth/usage", headers)
    # A credential/account rotation during HTTP invalidates that response.
    if read_json(Path(config) / ".credentials.json") != credentials:
        result["reason"] = "Conta alterada durante a consulta; aguardando nova observação"
        return result
    for key, name in (("five_hour", "Sessão"), ("seven_day", "Semana"),
                      ("seven_day_opus", "Semana Opus"), ("seven_day_sonnet", "Semana Sonnet")):
        data = payload.get(key)
        if isinstance(data, dict):
            value = quota_window(name, data.get("utilization"), data.get("resets_at"), now)
            if value is None:
                result["reason"] = "Resposta parcial: janela inválida"
                return result
            result["windows"].append(value)
    result.update(observed_at=now, plan=oauth.get("subscriptionType"),
                  access="aceito pelo provedor nesta observação", reason="")
    result["renewal"] = "token presente; validade futura não verificada" if oauth.get("refreshToken") else "não informada"
    result["remaining"] = effective(result, now)
    return result


def collect(env=None, *, now=None, fetch=http_json):
    env = dict(os.environ if env is None else env)
    now = time.time() if now is None else now
    home = Path(env.get("HOME") or Path.home())
    config_root = Path(env.get("XDG_CONFIG_HOME") or home / ".config")
    config_path = config_root / "folego/ai-sessions.json"
    settings = {}
    if config_path.exists():
        try:
            settings = read_json(config_path)
            if settings.get("schema") != 1:
                raise ValueError("schema desconhecido")
        except (OSError, ValueError):
            return [unknown(p, "Configuração de IAs ilegível/schema desconhecido") for p in NAMES]
    roots = settings.get("accounts", [])
    if not isinstance(roots, list) or len(roots) > 16:
        return [unknown(p, "Inventário de contas inválido/acima do orçamento") for p in NAMES]
    accounts = [dict(provider="codex", path=env.get("CODEX_HOME") or str(home / ".codex"))]
    web_default = home / ".local/share/codex-web-gpt/codex-home"
    accounts.append(dict(provider="web", path=str(web_default)))
    accounts.extend(roots)
    result = []
    for account in accounts:
        if not isinstance(account, dict) or account.get("provider") not in ("codex", "web"):
            return [unknown(p, "Configuração de conta inválida") for p in NAMES]
        provider = account["provider"]
        try:
            path = Path(account["path"]).expanduser()
            if not path.is_absolute():
                raise ValueError("caminho não absoluto")
            result.append(codex(path, now, provider=provider, label=account.get("label")))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            result.append(unknown(provider, "Fonte ausente, ilegível ou fora do orçamento"))
    try:
        result.append(claude(env.get("CLAUDE_CONFIG_DIR") or home / ".claude", now, fetch))
    except (OSError, ValueError, TypeError, AttributeError):
        result.append(unknown("claude", "Uso indisponível; verifique o login no Claude"))
    grok = unknown("grok", "O provedor não informa o percentual de cota nesta fonte")
    grok["paid_until"] = timestamp(settings.get("grok_paid_until"))
    grok["plan"] = "data informada pelo usuário" if grok["paid_until"] else None
    result.append(grok)
    return result


def describe(item, now=None):
    now = time.time() if now is None else now
    left = effective(item, now)
    lines = [item["label"], "Cota não confirmada" if left is None else f"{left}% disponível"]
    def date(value):
        return dt.datetime.fromtimestamp(value).astimezone().strftime("%d/%m/%Y %H:%M")
    for window in item.get("windows", []):
        lines.append(f"{window['name']}: {window['used']}% usado" + (" (observação vencida)" if left is None else ""))
        if window.get("resets_at"):
            lines.append("Reposição: " + date(window["resets_at"]))
    if item.get("plan"):
        lines.append("Plano: " + str(item["plan"]))
    if item.get("paid_until"):
        lines.append("Assinatura até: " + date(item["paid_until"]) + " (metadado; confira no provedor)")
    lines.extend(["Acesso: " + item.get("access", "não verificado"),
                  "Renovação: " + item.get("renewal", "não verificada"),
                  "Cupons/créditos: não informados pelo provedor"])
    if item.get("observed_at"):
        lines.append("Observado: " + date(item["observed_at"]))
    if item.get("reason"):
        lines.append(item["reason"])
    return "\n".join(lines)
