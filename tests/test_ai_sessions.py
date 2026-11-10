"""AI observations stay read-only, bounded, account-scoped and secret-free."""
import datetime as dt
import json
import os

import pytest

from folego.core import ai_sessions as ai

NOW = 1_793_534_400.0


@pytest.mark.parametrize('session_used,week_used,minutes,expected', (
    (100, 40, 300, NOW + 600),
    (100, 100, 300, None),
    (40, 100, 300, None),
    (40, 40, 300, None),
    (100, 40, None, None),
    (100, 40, 60, None),
))
def test_only_confirmed_exhausted_five_hour_windows_offer_a_countdown(
        session_used, week_used, minutes, expected):
    session = ai.quota_window('Sessão', session_used, NOW + 600, NOW, minutes)
    weekly = ai.quota_window('Semana', week_used, NOW + 86400, NOW, 10080)
    item = dict(observed_at=NOW, windows=[session, weekly])
    assert ai.session_reset_at(item, NOW) == expected
    assert ai.session_reset_at(item, NOW + 600) is None
    assert ai.session_reset_at(item, NOW - 1) is None
    assert ai.session_reset_at(dict(item, observed_at=NOW - 901), NOW) is None
    if minutes is not None:
        assert session['duration_minutes'] == minutes


def test_legacy_confirmed_five_hour_window_remains_readable():
    window = ai.quota_window('Sessão (5 h)', 100, NOW + 600, NOW)
    assert ai.session_reset_at(dict(observed_at=NOW, windows=[window]), NOW) == NOW + 600


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
    assert item['windows'][0]['duration_minutes'] == 300
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


def test_web_instance_count_uses_codex_profile_processes_once_and_expires(tmp_path):
    root = tmp_path / 'web-profile'
    root.mkdir()
    (root / 'config.toml').write_text('model = "chatgpt-web/gpt-6-sol"\n')
    calls = []
    def discover():
        calls.append(True)
        return [dict(provider='codex', roots=dict(CODEX_HOME=str(root)), identity=(1, 10, 20)),
                dict(provider='codex', roots=dict(CODEX_HOME=str(root)), identity=(1, 10, 20)),
                dict(provider='codex', roots={}, identity=(1, 11, 21))]
    items = ai.collect(env(tmp_path), now=NOW, discover=discover)
    web = next(item for item in items if item['provider'] == 'web' and item.get('account_id')
               and item['label'] == 'Conta 2')
    assert calls == [True]
    assert ai.web_instances(web, NOW) == 1
    assert ai.web_instances(web, NOW + 121) is None
    assert ai.web_instances(next(item for item in items if item['provider'] == 'web'
                                 and item is not web), NOW) == 0


def test_web_instance_absence_is_unknown_without_process_inventory(tmp_path):
    web = next(item for item in ai.collect(env(tmp_path), now=NOW) if item['provider'] == 'web')
    assert ai.web_instances(web, NOW) is None


def test_cli_ai_status_is_headless_and_uses_same_data(tmp_path, monkeypatch, capsys):
    from folego import cli
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert cli.main(["ai", "status", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["meters"]) == 4


def codex_auth(home):
    import base64
    root = home / '.codex'
    root.mkdir(exist_ok=True)
    encoded = base64.urlsafe_b64encode(json.dumps(dict(exp=NOW + 3600)).encode()).decode().rstrip('=')
    path = root / 'auth.json'
    path.write_text(json.dumps(dict(tokens=dict(access_token='test.' + encoded + '.fixture', account_id='account-fixture'))))
    return root, path


def test_live_codex_reads_quota_tickets_and_balance_without_redeeming(tmp_path):
    root, path = codex_auth(tmp_path)
    original = path.read_bytes()
    urls = []
    def fetch(url, headers):
        urls.append(url)
        if url.endswith('/usage'):
            return dict(account_id='account-fixture', plan_type='pro',
                rate_limit=dict(primary_window=dict(used_percent=72, reset_at=NOW + 3600, limit_window_seconds=604800)),
                rate_limit_reset_credits=dict(available_count=2), credits=dict(balance='9.99'))
        return dict(available_count=2, credits=[dict(status='available', expires_at=NOW + 86400)])
    item = ai.codex(root, NOW, fetch=fetch)
    assert item['remaining'] == 28 and item['windows'][0]['name'] == 'Semana'
    assert item['reset_credits']['available'] == 2 and item['extra_credits'] == '9.99'
    description = ai.describe(item, NOW)
    assert 'Tickets de reposição: 2' in description and 'Renovação mensal: data não informada' in description
    assert all('/consume' not in url for url in urls)
    assert 'fixture' not in json.dumps(item) and path.read_bytes() == original
    assert 'consulta vencida' in ai.describe(item, NOW + 901)


def test_live_codex_rotation_never_reuses_previous_account_response(tmp_path):
    root, path = codex_auth(tmp_path)
    def fetch(url, headers):
        path.write_text('{}')
        return dict(rate_limit=dict(primary_window=dict(used_percent=10, reset_at=NOW + 3600)))
    item = ai.codex(root, NOW, fetch=fetch)
    assert item['remaining'] is None and 'alterada' in item['reason']


def test_failed_ticket_details_preserve_summary_without_inventing_validity(tmp_path):
    root, _ = codex_auth(tmp_path)
    def fetch(url, headers):
        if url.endswith('/usage'): return dict(rate_limit_reset_credits=dict(available_count=1))
        raise OSError('unavailable')
    item = ai.codex(root, NOW, fetch=fetch)
    assert item['reset_credits']['available'] == 1
    assert 'validade: não informada' in ai.describe(item, NOW)


def test_available_resets_are_independent_of_quota_and_expire_without_collection():
    item = ai.unknown('codex')
    item['reset_credits'] = ai.reset_credits(dict(available_count=2, credits=[
        dict(status='available', expires_at=NOW + 10),
        dict(status='available', expires_at=NOW + 100)]), NOW)
    assert ai.effective(item, NOW) is None
    assert ai.available_resets(item, NOW) == 2
    assert ai.available_resets(item, NOW + 10) is None  # no guessed decrement
    assert 'consulta vencida' in ai.describe(item, NOW + 10)
    item['reset_credits'] = ai.reset_credits(dict(available_count=2), NOW)
    assert ai.available_resets(item, NOW) == 2  # provider confirms count, not expiry
    assert ai.available_resets(item, NOW + ai.MAX_AGE + 1) is None
    assert ai.available_resets(item, NOW - 1) is None


def test_already_expired_reset_details_never_lose_their_validity_boundary():
    item = dict(reset_credits=ai.reset_credits(dict(available_count=1,
        credits=[dict(status='available', expires_at=NOW - 1)]), NOW))
    assert ai.available_resets(item, NOW) is None


def test_unknown_or_malformed_ticket_counts_never_become_available():
    assert ai.available_resets({}, NOW) is None
    for count in (None, True, -1, '2', 2.5):
        assert ai.available_resets(dict(reset_credits=dict(available=count, observed_at=NOW)), NOW) is None
    for observed in (None, True, 'invalid', float('nan'), NOW + 1):
        assert ai.available_resets(dict(reset_credits=dict(available=2, observed_at=observed)), NOW) is None
    for expiry in (True, 0, 'invalid', float('inf'), NOW):
        assert ai.available_resets(dict(reset_credits=dict(available=2, observed_at=NOW, expires_at=expiry)), NOW) is None
    assert ai.available_resets(dict(reset_credits=dict(available=0, observed_at=NOW)), NOW) == 0


def test_claude_profile_and_extra_usage_have_separate_monthly_meaning(tmp_path):
    root, _ = credentials(tmp_path)
    def fetch(url, headers):
        if url.endswith('/profile'):
            return dict(organization=dict(subscription_status='active', subscription_created_at='2026-10-31T12:00:00Z'))
        return dict(five_hour=dict(utilization=18, resets_at=NOW + 1000),
                    extra_usage=dict(is_enabled=True, monthly_limit=2000, used_credits=500, utilization=25))
    item = ai.claude(root, NOW, fetch)
    assert item['billing_day'] == 31 and item['extra_usage']['utilization'] == 25
    text = ai.describe(item, NOW)
    assert 'estimativa' in text and '25% do limite mensal' in text


def test_billing_reference_preserves_configuration_and_unknown_schema(tmp_path):
    configuration = tmp_path / '.config/folego/ai-sessions.json'
    configuration.parent.mkdir(parents=True)
    original = dict(schema=1, accounts=[], grok_paid_until='2026-12-01T00:00:00Z')
    configuration.write_text(json.dumps(original))
    ai.set_billing_day('grok', 31, env=env(tmp_path))
    settings = json.loads(configuration.read_text())
    assert settings['grok_paid_until'] == original['grok_paid_until']
    assert next(i for i in ai.collect(env(tmp_path), now=NOW) if i['provider']=='grok')['billing_day'] == 31
    assert ai.next_monthly(31, dt.datetime(2027, 2, 1, tzinfo=dt.timezone.utc).timestamp()) == '28/02/2027'
    configuration.write_text('{"schema":99}')
    with pytest.raises(ValueError): ai.set_billing_day('grok', 10, env=env(tmp_path))
    assert configuration.read_text() == '{"schema":99}'


def test_native_account_discovery_is_deduplicated_and_private_home_scoped(tmp_path):
    from folego.core.ai_accounts import inventory
    root = tmp_path / 'profile'
    root.mkdir()
    (root/'config.toml').write_text('model="chatgpt-web/test"')
    found = lambda: [dict(provider='codex', roots=dict(CODEX_HOME=str(root)))] * 2
    accounts = inventory(env(tmp_path), discover=found)
    assert len([a for a in accounts if a['path'] == str(root)]) == 1
    assert next(a for a in accounts if a['path'] == str(root))['provider'] == 'web'
    assert not any(a['path'] == str(root) for a in inventory(env(tmp_path/'private-home'), discover=found))


def test_claude_rate_limit_reuses_only_fresh_same_account_and_honors_backoff(tmp_path):
    from urllib.error import HTTPError
    root, path = credentials(tmp_path)
    credentials_value = json.loads(path.read_text())
    credentials_value['claudeAiOauth']['expiresAt'] = (NOW + 10000) * 1000
    path.write_text(json.dumps(credentials_value))
    cache = {}
    def success(url, headers):
        if url.endswith('/profile'): return {}
        return dict(five_hour=dict(utilization=18, resets_at=NOW + 1000))
    first = ai.claude(root, NOW, success, cache=cache)
    calls = []
    def limited(url, headers):
        calls.append(url)
        raise HTTPError(url, 429, 'Limited', {'Retry-After': '300'}, None)
    result = ai.claude(root, NOW + 301, limited, cache=cache)
    assert result['remaining'] == first['remaining'] and result['observed_at'] == NOW
    assert 'limitada' in result['reason'] and len(calls) == 1
    ai.claude(root, NOW + 302, limited, cache=cache)
    assert len(calls) == 1
    result = ai.claude(root, NOW + 902, limited, cache=cache)
    assert result['remaining'] is None and '429' in result['reason']
    changed = json.loads(path.read_text())
    changed['claudeAiOauth']['accessToken'] = 'another-account-fixture'
    path.write_text(json.dumps(changed))
    assert ai.claude(root, NOW + 1, limited, cache=cache)['remaining'] is None
    assert 'private-' not in str(cache) and 'another-account' not in str(cache)


def test_cached_claude_reset_revalidates_remaining_without_new_network(tmp_path):
    root, _ = credentials(tmp_path)
    cache = {}
    def success(url, headers):
        return {} if url.endswith('/profile') else dict(five_hour=dict(utilization=18, resets_at=NOW + 30))
    ai.claude(root, NOW, success, cache=cache)
    def no_request(*args): pytest.fail('fresh cache triggered a new network request')
    assert ai.claude(root, NOW + 31, no_request, cache=cache)['remaining'] is None


def test_claude_retry_after_is_not_shortened_to_one_hour(tmp_path):
    from urllib.error import HTTPError
    root, _ = credentials(tmp_path)
    cache = {}
    calls = []
    def limited(url, headers):
        calls.append(url)
        raise HTTPError(url, 429, 'Limited', {'Retry-After': '7200'}, None)
    ai.claude(root, NOW, limited, cache=cache)
    ai.claude(root, NOW + 61, limited, cache=cache)
    assert len(calls) == 1 and next(iter(cache.values()))['retry_at'] == NOW + 7200


def test_claude_account_organization_change_invalidates_usage_and_profile(tmp_path):
    root, credentials_path = credentials(tmp_path)
    before = credentials_path.read_bytes()
    metadata = root.with_suffix('.json')
    metadata.write_text(json.dumps(dict(oauthAccount=dict(accountUuid='fixture-account', organizationUuid='org-A'))))
    cache, calls = {}, []
    def fetch(url, headers):
        calls.append(url)
        account = json.loads(metadata.read_text())['oauthAccount']['organizationUuid']
        if url.endswith('/profile'):
            return dict(organization=dict(subscription_status='active', subscription_created_at=
                '2026-10-15T00:00:00Z' if account == 'org-A' else '2026-10-20T00:00:00Z'))
        return dict(five_hour=dict(utilization=10 if account == 'org-A' else 60, resets_at=NOW + 1000))
    first = ai.claude(root, NOW, fetch, cache=cache)
    metadata.write_text(json.dumps(dict(oauthAccount=dict(accountUuid='fixture-account', organizationUuid='org-B'))))
    second = ai.claude(root, NOW + 1, fetch, cache=cache)
    assert (first['remaining'], second['remaining']) == (90, 40)
    assert (first['billing_day'], second['billing_day']) == (15, 20)
    assert len(calls) == 4 and len(cache) == 1
    assert credentials_path.read_bytes() == before
    assert 'org-A' not in str(cache) and 'org-B' not in str(cache)


def test_claude_context_change_during_http_discards_response(tmp_path):
    root, _ = credentials(tmp_path)
    metadata = root.with_suffix('.json')
    metadata.write_text(json.dumps(dict(oauthAccount=dict(organizationUuid='org-A'))))
    def fetch(url, headers):
        metadata.write_text(json.dumps(dict(oauthAccount=dict(organizationUuid='org-B'))))
        return dict(five_hour=dict(utilization=10, resets_at=NOW + 1000))
    result = ai.claude(root, NOW, fetch, cache={})
    assert result['remaining'] is None and 'alterada' in result['reason']


def test_malformed_claude_account_metadata_does_not_reuse_cache(tmp_path):
    root, _ = credentials(tmp_path)
    cache = {}
    def fetch(url, headers):
        return {} if url.endswith('/profile') else dict(five_hour=dict(utilization=10, resets_at=NOW + 1000))
    ai.claude(root, NOW, fetch, cache=cache)
    root.with_suffix('.json').write_text('{')
    with pytest.raises(ValueError): ai.claude(root, NOW + 1, fetch, cache=cache)


def test_claude_context_change_keeps_retry_after_for_the_same_token(tmp_path):
    from urllib.error import HTTPError
    root, _ = credentials(tmp_path)
    metadata = root.with_suffix('.json')
    metadata.write_text(json.dumps(dict(oauthAccount=dict(organizationUuid='org-A'))))
    cache, calls = {}, []
    def limited(url, headers):
        calls.append(url)
        raise HTTPError(url, 429, 'Limited', {'Retry-After': '7200'}, None)
    ai.claude(root, NOW, limited, cache=cache)
    metadata.write_text(json.dumps(dict(oauthAccount=dict(organizationUuid='org-B'))))
    result = ai.claude(root, NOW + 1, limited, cache=cache)
    assert result['remaining'] is None and len(calls) == 1
    assert next(iter(cache.values()))['retry_at'] == NOW + 7200
    metadata.write_text(json.dumps(dict(oauthAccount=dict(organizationUuid='org-A'))))
    ai.claude(root, NOW + 2, limited, cache=cache)
    ai.claude(root, NOW + 3, limited, cache=cache)
    assert len(calls) == 1 and next(iter(cache.values()))['retry_at'] == NOW + 7200


def web_root(home, plan='pro_200', events=(), since=1):
    root = home / 'chatgpt-web/codex-home'
    root.mkdir(parents=True)
    key = 'a' * 64
    account = dict(plan=plan, initializedAt=None if plan == 'unsupported' else int(since * 1000), checkedAt=0,
                   events=[dict(id=str(i), model=m, at=int(at * 1000)) for i, (m, at) in enumerate(events)])
    (home / 'chatgpt-web/launcher-data').mkdir()
    (home / 'chatgpt-web/launcher-data/limits.json').write_text(
        json.dumps(dict(version=1, activeAccountKey=key, accounts={key: account})))
    return root


def test_web_reads_launcher_pro_limits_not_the_root_codex_quota(tmp_path):
    root = web_root(tmp_path, events=[('gpt-5.6-pro', NOW - 3600)] * 85 + [('gpt-6-pro', NOW - 3 * 86400), ('other', NOW - 10)])
    codex_auth(tmp_path)  # a Codex login in the root must not be used
    item = ai.codex(root, NOW, provider='web', fetch=lambda *a: pytest.fail('Codex quota used for Web'))
    assert item['remaining'] is None and item['windows'] == []
    assert item['local_usage']['counts'] == {'gpt-6-pro': 1, 'gpt-5.6-pro': 85, 'pro-unknown': 0}
    assert 'não inclui outros clientes' in item['source']
    assert 'não informados' in item['reason']


@pytest.mark.parametrize('plan', ['unsupported', 'unknown'])
def test_web_without_confirmed_pro_tracker_is_unknown(tmp_path, plan):
    item = ai.codex(web_root(tmp_path, plan=plan), NOW, provider='web')
    assert item['remaining'] is None and item['local_usage'] is None
    assert 'não suportado ou não confirmado' in item['reason']
    assert item['limits_action'] is False


def test_web_marks_local_tracking_start_without_inventing_a_reset(tmp_path):
    item = ai.codex(web_root(tmp_path, events=[('gpt-6-pro', NOW - 60)], since=NOW - 86400), NOW, provider='web')
    assert item['local_usage']['since'] == NOW - 86400
    assert item['local_usage']['counts']['gpt-6-pro'] == 1
    assert item['windows'] == [] and item['remaining'] is None


def test_web_rejects_events_before_tracking_or_missing_start(tmp_path):
    root = web_root(tmp_path, events=[('gpt-6-pro', NOW - 7200)], since=NOW - 3600)
    assert ai.codex(root, NOW, provider='web')['local_usage'] is None
    path = tmp_path / 'chatgpt-web/launcher-data/limits.json'
    state = json.loads(path.read_text())
    state['accounts']['a' * 64].update(initializedAt=None, events=[])
    path.write_text(json.dumps(state))
    assert 'início do rastreamento' in ai.codex(root, NOW, provider='web')['reason']


def test_web_missing_tracker_is_unknown(tmp_path):
    root = tmp_path / 'codex-home'
    root.mkdir()
    assert 'histórico local' in ai.codex(root, NOW, provider='web')['reason']


def test_claude_stale_access_token_is_not_reported_as_expired_login(tmp_path):
    config, path = credentials(tmp_path)
    value = json.loads(path.read_text())
    value['claudeAiOauth'].update(expiresAt=(NOW - 1) * 1000, refreshTokenExpiresAt=(NOW + 86400) * 1000,
                                  subscriptionType='pro')
    path.write_text(json.dumps(value))
    def fetch(*args):
        pytest.fail('stale access token was used')
    item = ai.claude(config, NOW, fetch)
    assert item['remaining'] is None and 'Token de acesso vencido' in item['reason']
    assert item['plan'] == 'pro' and item['renewal'].startswith('renovação local')
    value['claudeAiOauth']['refreshTokenExpiresAt'] = (NOW - 1) * 1000
    path.write_text(json.dumps(value))
    assert 'Login expirado' in ai.claude(config, NOW, fetch)['reason']


def grok_home(home):
    root = home / '.grok'
    root.mkdir()
    (root / 'auth.json').write_text('{"fixture": true}')
    return root


def billing(used, end=NOW + 86400, kind='USAGE_PERIOD_TYPE_WEEKLY'):
    period = dict(type=kind, start='2026-10-31T00:00:00+00:00',
                  end=dt.datetime.fromtimestamp(end, dt.timezone.utc).isoformat())
    return dict(config=dict(creditUsagePercent=used, currentPeriod=period), subscription_tier='SuperGrok')


def test_grok_billing_becomes_weekly_meter_and_is_cached(tmp_path):
    root, calls = grok_home(tmp_path), []
    def query(home):
        calls.append(home)
        return billing(37.5)
    cache = {}
    item = ai.grok(root, NOW, query, cache=cache)
    assert item['remaining'] == 62 and item['windows'][0]['name'] == 'Semana' and item['plan'] == 'SuperGrok'
    assert ai.grok(root, NOW + 60, query, cache=cache)['remaining'] == 62 and len(calls) == 1
    ai.grok(root, NOW + 301, query, cache=cache)
    assert len(calls) == 2


@pytest.mark.parametrize('payload', [dict(), dict(config=dict(creditUsagePercent=120, currentPeriod=dict(end='2026-11-07T00:00:00Z'))),
                                     billing(10, end=NOW - 1)])
def test_grok_invalid_or_elapsed_billing_is_unknown(tmp_path, payload):
    item = ai.grok(grok_home(tmp_path), NOW, lambda home: payload, cache={})
    assert item['remaining'] is None


def test_grok_account_change_during_query_discards_response(tmp_path):
    root = grok_home(tmp_path)
    def query(home):
        (root / 'auth.json').write_text('{"other": true}')
        return billing(10)
    assert 'alterada' in ai.grok(root, NOW, query, cache={})['reason']


def test_collect_uses_injected_grok_query(tmp_path):
    grok_home(tmp_path)
    items = ai.collect(env(tmp_path), now=NOW, grok_query=lambda home: billing(100))
    assert next(i for i in items if i['provider'] == 'grok')['remaining'] == 0


def stale_claude(home):
    config, path = credentials(home)
    value = json.loads(path.read_text())
    value['claudeAiOauth'].update(expiresAt=(NOW - 1) * 1000, refreshTokenExpiresAt=(NOW + 86400) * 1000)
    path.write_text(json.dumps(value))
    return config, path, value


def test_stale_claude_asks_client_once_then_reads_renewed_quota(tmp_path):
    config, path, value = stale_claude(tmp_path)
    calls, attempts = [], {}
    def renew(target):
        calls.append(target)
        value['claudeAiOauth']['expiresAt'] = (NOW + 3600) * 1000
        path.write_text(json.dumps(value))
    fetch = lambda url, headers: dict(five_hour=dict(utilization=26, resets_at=NOW + 1000)) if url.endswith('/usage') else {}
    item = ai.claude_with_renewal(config, NOW, fetch, renew, cache={}, attempts=attempts)
    assert item['remaining'] == 74 and calls == [config]


def test_failed_claude_renewal_is_rate_limited_and_stays_unknown(tmp_path):
    config, _, _ = stale_claude(tmp_path)
    calls, attempts = [], {}
    fetch = lambda *a: pytest.fail('stale token used')
    for offset in (0, 60, 601):
        item = ai.claude_with_renewal(config, NOW + offset, fetch, calls.append, cache={}, attempts=attempts)
        assert item['remaining'] is None and item['reason'] == ai.STALE_CLAUDE
    assert len(calls) == 2


def test_test_environment_never_runs_claude_client(tmp_path):
    stale_claude(tmp_path)
    item = next(i for i in ai.collect(env(tmp_path), now=NOW) if i['provider'] == 'claude')
    assert item['reason'] == ai.STALE_CLAUDE


def test_web_unsupported_check_does_not_claim_unlimited_or_broken_client(tmp_path):
    root = web_root(tmp_path, plan='unsupported')
    item = ai.codex(root, NOW, provider='web')
    text = ai.describe(item, NOW)
    assert not item['limits_action'] and item['remaining'] is None
    assert 'não suportado ou não confirmado' in text
    assert 'atualização' not in text and 'ilimitado' not in text


def test_claude_model_scoped_weekly_limit_is_a_window_of_its_own(tmp_path):
    config, _ = credentials(tmp_path)
    scoped = dict(kind='weekly_scoped', percent=54, resets_at=NOW + 2000,
                  scope=dict(model=dict(id=None, display_name='Fable'), surface=None))
    payload = dict(five_hour=dict(utilization=10, resets_at=NOW + 1000),
                   seven_day=dict(utilization=45, resets_at=NOW + 2000),
                   limits=[dict(kind='session', percent=10, resets_at=NOW + 1000),
                           dict(kind='weekly_all', percent=45, resets_at=NOW + 2000), scoped])
    item = ai.claude(config, NOW, lambda url, headers: payload)
    assert [w['name'] for w in item['windows']] == ['Sessão (5 h)', 'Semana', 'Semana Fable']
    assert item['remaining'] == 46
    assert 'Semana Fable: 54% usado / 46% livre' in ai.describe(item, NOW)
    assert 'não expostos por esta fonte' in ai.describe(item, NOW)
    payload['limits'][2] = dict(scoped, percent=None)
    partial = ai.claude(config, NOW, lambda url, headers: payload)
    assert partial['remaining'] is None and 'parcial' in partial['reason']
