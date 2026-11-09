from folego.core.ai_alerts import AlertTracker
from folego.core.ai_sessions import quota_window
from folego.core.notification_tones import pcm, SCORES


def item(left, at, reset=10000, account='a', provider='codex'):
    return dict(provider=provider, account_id=account, observed_at=at,
                windows=[quota_window('Sessão', 100-left, reset, at)])


def test_quota_threshold_empty_and_confirmed_recovery_only_once():
    tracker = AlertTracker()
    assert tracker.quota_changes([item(50, 100)], now=100) == []
    assert tracker.quota_changes([item(20, 101)], now=101) == ['low']
    assert tracker.quota_changes([item(19, 102)], now=102) == []
    assert tracker.quota_changes([item(0, 103)], now=103) == ['empty']
    assert tracker.quota_changes([item(0, 104)], now=104) == []
    assert tracker.quota_changes([item(100, 105, reset=20000)], now=105) == ['restored']
    assert tracker.quota_changes([item(100, 105, reset=20000)], now=105) == []
    assert tracker.quota_changes([item(20, 101)], now=106) == []  # delayed response


def test_stale_or_expired_quota_is_not_a_replenishment_or_loss():
    tracker = AlertTracker()
    tracker.quota_changes([item(0, 100)], now=100)
    assert tracker.quota_changes([item(100, 101)], now=15000) == []
    assert tracker.quota_changes([item(0, 15001, reset=14000)], now=15001) == []
    assert tracker.quota_changes([item(100, 15002, reset=20000)], now=15002) == ['restored']


def test_all_accounts_and_providers_are_independent():
    tracker = AlertTracker()
    tracker.quota_changes([item(90, 100), item(40, 100, account='b')], now=100)
    assert tracker.quota_changes([item(90, 101), item(20, 101, account='b')], now=101) == ['low']
    assert tracker.quota_changes([item(20, 102)], now=102) == ['low']


def test_delivery_identity_survives_acknowledgment_and_partial_reads():
    tracker = AlertTracker(now=100)
    def rows(provider, *events, count=1):
        return [dict(provider=provider, count=count,
                     pending=[dict(event=e, at=99 if e.startswith('old') else 101) for e in events])]
    assert tracker.delivery_changes(rows('codex', 'old')) == {}
    assert tracker.delivery_changes(rows('codex', 'new', 'old', 'old-delayed')) == {'codex': 1}
    assert tracker.delivery_changes(rows('codex', count=None)) == {}
    assert tracker.delivery_changes(rows('codex', 'new')) == {}
    assert tracker.delivery_changes(rows('codex', 'next', 'another')) == {'codex': 2}
    for provider in ('web', 'claude', 'grok'):
        assert tracker.delivery_changes(rows(provider, count=0)) == {}
        assert tracker.delivery_changes(rows(provider, 'new')) == {provider: 1}


def test_original_cues_are_distinct_short_and_faded():
    tracks = [pcm(key) for key in SCORES]
    assert len(set(tracks)) == len(SCORES)
    assert all(0 < len(t) < 48000*2 for t in tracks)
    assert all(t[:2] == b'\0\0' for t in tracks)


def test_first_delivery_after_startup_is_audible_even_if_provider_was_unavailable():
    tracker=AlertTracker(now=100)
    assert tracker.delivery_changes([dict(provider='grok',count=None,pending=[])],now=101)=={}
    new=dict(provider='grok',count=1,pending=[dict(event='first',at=105)])
    assert tracker.delivery_changes([new],now=106)=={'grok': 1}
    assert tracker.delivery_changes([new],now=107)=={}
    restarted=AlertTracker(now=200)
    assert restarted.delivery_changes([new],now=201)=={}


def test_reported_web_mcp_failure_does_not_play_success_completion_cue():
    tracker = AlertTracker(now=100)
    failure = dict(provider='web', count=1, pending=[dict(
        event='failed', at=101, reported_web_mcp_error=True)])
    assert tracker.delivery_changes([failure], now=102) == {}
    assert tracker.delivery_changes([failure], now=103) == {}
    success = dict(provider='web', count=2, pending=[*failure['pending'], dict(event='ok', at=104)])
    assert tracker.delivery_changes([success], now=105) == {'web': 1}


def test_native_capacity_error_never_plays_success_cue():
    tracker = AlertTracker(now=100)
    failed = dict(provider='web', count=1, pending=[dict(event='capacity', at=101, web_capacity_error=True)])
    assert tracker.delivery_changes([failed], now=102) == {}
    assert tracker.delivery_changes([failed], now=103) == {}


def test_structured_generic_failure_is_excluded_from_delivery_notice():
    tracker = AlertTracker(now=100)
    rows = [dict(provider='codex', count=2, pending=[
        dict(event='failed', at=101, delivery_failed=True),
        dict(event='finished', at=101),
    ])]
    assert tracker.delivery_changes(rows, now=102) == {'codex': 1}
    assert tracker.delivery_changes(rows, now=103) == {}
