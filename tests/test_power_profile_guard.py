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
    with pytest.raises(PowerProfileError, match="ausente"):
        PowerProfileGuard(path=tmp_path / "none.json", command=daemon).status()  # conftest hides the tool
    limited = Daemon(listing="* performance:\n  balanced:\n")
    g2 = guard(tmp_path / "limited", limited)
    g2.observe("critical"); g2.observe("critical")
    assert limited.sets == []
    g.path.write_text("{broken", encoding="utf-8")
    with pytest.raises(PowerProfileError, match="ilegível"):
        g.observe("critical")
    with pytest.raises(ValueError):
        g.perform("reset")


def test_window_forwards_sag_and_charger_edges_and_reports_changes(qapp):
    from folego.core.snapshot import BatteryInfo
    from folego.ui.main_window import MainWindow
    window = MainWindow(collector_factory=None, startup_defaults=False)
    try:
        calls, notices = [], []
        window._power_controller.request = lambda action, value=None: calls.append((action, value)) or True
        window.tray.show_power_profile = notices.append
        def battery(volts, status='Discharging'):
            return BatteryInfo(80, status, 3600, voltage_uv=volts, voltage_min_design_uv=7_700_000)
        window._observe_power_profile(battery(7_650_000))   # stable: nothing to ask
        window._observe_power_profile(battery(7_000_000))
        window._observe_power_profile(battery(7_000_000))   # paced, not every sample
        window._power_asked_at -= 20
        window._observe_power_profile(battery(6_500_000))
        window._observe_power_profile(battery(8_300_000, 'Charging'))
        window._observe_power_profile(battery(8_300_000, 'Charging'))
        window._observe_power_profile(None)                  # unknown reading asks for nothing new
        assert calls == [('observe', 'attention'), ('observe', 'critical'),
                         ('observe', 'external'), ('observe', None)]
        window.options.build_desktop_options()
        change = {'from': 'performance', 'to': 'balanced', 'restore': False, 'level': 'attention'}
        window._power_result({'guard': True, 'enabled': True, 'message': 'Ativo.', 'changed': change})
        assert notices == [change] and window.options.power_guard_choice.isChecked()
        assert window.options.power_guard_choice.isEnabled()
        window._power_error('powerprofilesctl ausente')
        assert not window.options.power_guard_choice.isEnabled()
        assert 'ausente' in window.options.power_guard_status.text()
        emitted = []
        window.options.power_guard_requested.connect(emitted.append)
        window._power_result({'guard': True, 'enabled': True, 'message': 'Ativo.'})
        window.options.power_guard_choice.click()
        assert emitted == ['disable']
    finally:
        window.close()
