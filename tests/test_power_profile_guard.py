"""Voltage-driven power profile guard: fakes only, never the host daemon."""
import pytest

from folego.actions.power_profile_guard import PowerProfileGuard, PowerProfileError

LISTING = "* performance:\n    CpuDriver:\tx\n\n  balanced:\n    CpuDriver:\tx\n\n  power-saver:\n"


class Daemon:
    def __init__(self, profile="performance", *, obey=True, listing=LISTING):
        self.profile, self.obey, self.listing, self.sets = profile, obey, listing, []

    def __call__(self, argv):
        if argv[1] == "get":
            return self.profile + "\n"
        if argv[1] == "list":
            return self.listing
        self.sets.append(argv[2])
        if self.obey:
            self.profile = argv[2]
        return ""


class Audit:
    def __init__(self): self.rows = []
    def append(self, **row): self.rows.append(row)


def guard(tmp_path, daemon, **kw):
    return PowerProfileGuard(path=tmp_path / "state" / "guard.json", command=daemon,
                             tool="powerprofilesctl", audit=kw.pop("audit", Audit()), **kw)


def test_sustained_sag_lowers_the_profile_and_the_charger_restores_it(tmp_path):
    daemon, audit = Daemon(), Audit()
    g = guard(tmp_path, daemon, audit=audit)
    assert g.observe("attention") == {"guard": True, "idle": True}  # one sample is not sustained
    result = g.observe("attention")
    assert daemon.profile == "balanced" and result["managed"]
    assert result["changed"] == {"from": "performance", "to": "balanced",
                                 "restore": False, "level": "attention"}
    g.observe("critical"); g.observe("critical")
    assert daemon.profile == "power-saver"
    assert g.observe(None) == {"guard": True, "idle": True}  # recovery in discharge keeps it
    assert daemon.profile == "power-saver"
    result = g.observe("external")
    assert daemon.profile == "performance" and result["changed"]["restore"]
    assert not result["managed"] and daemon.sets == ["balanced", "power-saver", "performance"]
    assert [row["outcome"] for row in audit.rows] == ["applied", "applied", "restored"]
    assert g.observe("external") == {"guard": True, "idle": True}


def test_never_raises_the_profile_and_respects_a_user_choice(tmp_path):
    daemon = Daemon("power-saver")
    g = guard(tmp_path, daemon)
    g.observe("attention"); g.observe("attention")
    assert daemon.sets == []
    daemon.profile = "performance"
    g.observe("critical"); g.observe("critical")
    daemon.profile = "balanced"  # the user picked another profile while discharging
    g.observe("external")
    assert daemon.profile == "balanced" and daemon.sets == ["power-saver"]
    assert not g.status()["managed"]


def test_unconfirmed_request_stops_automation_until_the_user_reviews(tmp_path):
    daemon = Daemon(obey=False)
    g = guard(tmp_path, daemon)
    g.observe("critical")
    result = g.observe("critical")
    assert result["failed"] and result["blocked"]
    for _ in range(4):
        g.observe("critical")
    assert daemon.sets == ["power-saver"]  # no blind retry
    assert "sem confirmação" in g.status()["message"]
    daemon.obey = True
    assert not g.perform("enable")["blocked"]
    g.observe("critical"); g.observe("critical")
    assert daemon.profile == "power-saver"


def test_disabled_guard_does_nothing_but_still_gives_back_its_own_change(tmp_path):
    daemon = Daemon()
    g = guard(tmp_path, daemon)
    g.observe("critical"); g.observe("critical")
    assert not g.perform("disable")["enabled"]
    daemon.sets.clear()
    g.observe("external")
    assert daemon.profile == "performance"
    for _ in range(3):
        g.observe("critical")
    assert daemon.sets == ["performance"]
    assert not PowerProfileGuard(path=g.path, command=daemon, tool="x").status()["enabled"]


def test_interrupted_intention_is_reconciled_by_reading_the_profile(tmp_path):
    daemon = Daemon()
    g = guard(tmp_path, daemon)
    g.observe("attention"); g.observe("attention")
    state = g._load(); state["receipt"]["state"] = "intended"; g._save(state)
    again = guard(tmp_path, daemon)
    assert again.status()["managed"]  # profile equals the target: the effect happened
    again.observe("external")
    assert daemon.profile == "performance"


def test_budget_unknown_profile_missing_tool_and_bad_state_fail_closed(tmp_path):
    daemon = Daemon()
    g = guard(tmp_path, daemon, clock=lambda: 10.0)
    for _ in range(6):
        g.observe("attention"); g.observe("attention")
        daemon.profile = "performance"
    assert len(daemon.sets) == 4
    odd = guard(tmp_path / "odd", Daemon("turbo"))
    with pytest.raises(PowerProfileError, match="desconhecido"):
        odd.observe("critical")
    missing = PowerProfileGuard(path=tmp_path / "none.json", command=daemon).status()
    assert missing['unavailable'] and missing['enabled']
    assert 'ausente' in missing['message']
    limited = Daemon(listing="* performance:\n  balanced:\n")
    g2 = guard(tmp_path / "limited", limited)
    g2.observe("critical"); g2.observe("critical")
    assert limited.sets == []
    g.path.write_text("{broken", encoding="utf-8")
    with pytest.raises(PowerProfileError, match="ilegível"):
        g.observe("critical")
    with pytest.raises(ValueError):
        g.perform("reset")


def test_read_only_status_preserves_receipt_and_disabled_choice_on_daemon_failure(tmp_path):
    daemon = Daemon()
    g = guard(tmp_path, daemon)
    g.observe('attention'); g.observe('attention')
    state = g._load()
    state['receipt']['state'] = 'intended'
    g._save(state)
    before = g.path.read_bytes()
    assert not g.status(reconcile=False)['managed']
    assert g.path.read_bytes() == before
    assert g.status()['managed']
    g.perform('disable')
    before = g.path.read_bytes()

    def unavailable(argv):
        raise PowerProfileError('Serviço mascarado')

    g.command = unavailable
    status = g.status(reconcile=False)
    assert status['unavailable'] and status['enabled'] is False
    assert status['profile'] is None and 'mascarado' in status['message']
    assert g.path.read_bytes() == before


def test_budget_survives_restarts_review_and_clock_regression(tmp_path):
    daemon = Daemon()
    for _ in range(4):
        g = guard(tmp_path, daemon, clock=lambda: 100.0)
        g.observe('attention'); g.observe('attention')
        daemon.profile = 'performance'
    g = guard(tmp_path, daemon, clock=lambda: 100.0)
    g.perform('disable'); g.perform('enable')
    g.observe('attention')
    assert 'Limite' in g.observe('attention')['message']
    assert len(daemon.sets) == 4
    backwards = guard(tmp_path, daemon, clock=lambda: 99.0)
    backwards.observe('attention')
    assert 'regressou' in backwards.observe('attention')['message']
    assert len(daemon.sets) == 4


def test_restoration_has_its_own_durable_intent_and_lost_result_is_not_retried(tmp_path):
    daemon = Daemon()
    g = guard(tmp_path, daemon)
    g.observe('attention'); g.observe('attention')
    applied_id = g._load()['receipt']['id']
    def interrupted(argv):
        if argv[1] == 'set':
            receipt = g._load()['receipt']
            assert receipt['state'] == 'intended' and receipt['restore']
            assert receipt['parent_id'] == applied_id and receipt['id'] != applied_id
            raise SystemExit('simulated loss after intent')
        return daemon(argv)
    g.command = interrupted
    with pytest.raises(SystemExit):
        g.observe('external')
    again = guard(tmp_path, daemon)
    assert again.status()['blocked']
    again.observe('external'); again.observe('critical')
    assert daemon.sets == ['balanced']


def test_completed_restoration_is_reconciled_without_reapplying(tmp_path):
    daemon = Daemon()
    g = guard(tmp_path, daemon)
    g.observe('attention'); g.observe('attention')
    original_save = g._save
    def lose_final_receipt(state):
        if state['receipt'] is None:
            raise SystemExit('simulated loss after effect')
        original_save(state)
    g._save = lose_final_receipt
    with pytest.raises(SystemExit):
        g.observe('external')
    again = guard(tmp_path, daemon)
    assert not again.status()['managed'] and again._load()['receipt'] is None
    again.observe('external')
    assert daemon.sets == ['balanced', 'performance']


def test_competing_writers_cannot_reuse_budget_or_change_the_profile(tmp_path):
    from folego.orchestration import Coordinator
    daemon = Daemon()
    g = guard(tmp_path, daemon)
    rival = Coordinator(lock_path=g.path.with_suffix('.lock'))
    with rival.lock():
        with pytest.raises(PowerProfileError, match='andamento'):
            g.observe('critical')
    assert not daemon.sets


@pytest.mark.parametrize('value', [False, [], {'schema': 1, 'enabled': 'yes'},
                                  {'schema': 1, 'enabled': True, 'receipt': {}}])
def test_incomplete_state_never_becomes_an_empty_healthy_receipt(tmp_path, value):
    from folego.safely.persist import write_json_atomic
    g = guard(tmp_path, Daemon())
    write_json_atomic(g.path, value)
    with pytest.raises(PowerProfileError):
        g.observe('critical')
