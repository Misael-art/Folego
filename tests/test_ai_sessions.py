"""AI observations stay read-only, bounded, account-scoped and secret-free."""
import datetime as dt
import json
import os

import pytest

from folego.core import ai_sessions as ai

NOW = 1_793_534_400.0


def env(home):
    return {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")}


def rollout(home, used=72, *, reset=NOW + 3600, seen=NOW, secondary=43):
    root = home / ".codex/sessions/2026/11/01"
    root.mkdir(parents=True, exist_ok=True)
    limits = dict(limit_id="codex", plan_type="plus",
                  primary=dict(used_percent=used, resets_at=reset),
                  secondary=dict(used_percent=secondary, resets_at=NOW + 86400))
    row = dict(timestamp=dt.datetime.fromtimestamp(seen, dt.timezone.utc).isoformat(),
               payload=dict(rate_limits=limits))
    (root / "rollout-test.jsonl").write_text(json.dumps(row) + "\n")
    return root / "rollout-test.jsonl"


def test_tightest_window_and_display_expiry(tmp_path):
    rollout(tmp_path)
    item = ai.collect(env(tmp_path), now=NOW)[0]
    assert item["remaining"] == 28
    assert ai.effective(item, NOW + 901) is None
    assert ai.effective(item, NOW - 1) is None
    assert ai.effective(item, NOW + 100) == 28


@pytest.mark.parametrize("used", [-1, 101, True, float("nan"), "72"])
def test_invalid_window_protects_whole_meter(tmp_path, used):
    rollout(tmp_path, used)
    assert ai.collect(env(tmp_path), now=NOW)[0]["remaining"] is None


def test_elapsed_reset_never_creates_full_quota(tmp_path):
    rollout(tmp_path, reset=NOW - 1)
    item = ai.collect(env(tmp_path), now=NOW)[0]
    assert item["remaining"] is None
    assert "vencida" in ai.describe(item, NOW)


def test_old_auth_account_cannot_reuse_recent_rollout(tmp_path):
    rollout(tmp_path)
    auth = tmp_path / ".codex/auth.json"
    auth.write_text('{}')
    os.utime(auth, (NOW + 1, NOW + 1))
    item = ai.collect(env(tmp_path), now=NOW)[0]
    assert item["remaining"] is None and "alterada" in item["reason"]


def test_torn_record_and_foreign_limit_do_not_become_measurements(tmp_path):
    path = rollout(tmp_path)
    raw = path.read_text()
    path.write_text(raw.replace('"codex"', '"premium"') + raw.rstrip())
    assert ai.collect(env(tmp_path), now=NOW)[0]["remaining"] is None


def test_unknown_schema_blocks_instead_of_using_default_accounts(tmp_path):
    config = tmp_path / ".config/folego"
    config.mkdir(parents=True)
    (config / "ai-sessions.json").write_text('{"schema":99}')
    rollout(tmp_path)
    assert all(item["remaining"] is None for item in ai.collect(env(tmp_path), now=NOW))


def credentials(home):
    config = home / ".claude"
    config.mkdir()
    path = config / ".credentials.json"
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": "private-test-token",
                    "refreshToken": "private-renewal-token", "expiresAt": (NOW + 100) * 1000}}))
    return config, path


def test_claude_usage_is_confirmed_but_renewal_is_not_invented(tmp_path):
    config, path = credentials(tmp_path)
    before = path.read_bytes()
    payload = dict(five_hour=dict(utilization=18, resets_at=NOW + 1000),
                   seven_day=dict(utilization=60, resets_at=NOW + 2000))
    seen = []
    def fetch(url, headers):
        seen.append((url, headers["Authorization"]))
        return payload
    item = ai.claude(config, NOW, fetch)
    assert item["remaining"] == 40
    assert "aceito" in item["access"] and "não verificada" in item["renewal"]
    assert "private-" not in json.dumps(item)
    assert path.read_bytes() == before
    assert seen[0][0] == "https://api.anthropic.com/api/oauth/usage"


def test_claude_response_from_previous_account_is_discarded(tmp_path):
    config, path = credentials(tmp_path)
    def fetch(url, headers):
        path.write_text('{}')
        return dict(five_hour=dict(utilization=10, resets_at=NOW + 1000))
    item = ai.claude(config, NOW, fetch)
    assert item["remaining"] is None and "alterada" in item["reason"]


def test_expired_credentials_never_make_network_request(tmp_path):
    config, path = credentials(tmp_path)
    value = json.loads(path.read_text())
    value["claudeAiOauth"]["expiresAt"] = (NOW - 1) * 1000
    path.write_text(json.dumps(value))
    def fetch(*args):
        pytest.fail("expired credential was used")
    assert ai.claude(config, NOW, fetch)["remaining"] is None


def test_web_grok_and_missing_accounts_are_unknown(tmp_path):
    items = ai.collect(env(tmp_path), now=NOW)
    assert [i["provider"] for i in items] == ["codex", "web", "claude", "grok"]
    assert all(i["remaining"] is None for i in items)
    assert ai.band(None) == "unknown"
    assert [ai.band(x) for x in (0, 20, 21, 60, 61)] == ["red", "red", "yellow", "yellow", "green"]


def test_cli_ai_status_is_headless_and_uses_same_data(tmp_path, monkeypatch, capsys):
    from folego import cli
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert cli.main(["ai", "status", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["meters"]) == 4
