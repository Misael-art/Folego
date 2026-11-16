from folego.ui.options_tab import OptionsTab, options_argv


def test_care_option_uses_worker_persists_opt_out_and_stops_discovery_timer(qapp):
    class Jobs:
        in_flight = 0
        def __init__(self): self.calls = []
        def run(self, action, target, **kw): self.calls.append((action, kw))
        def shutdown(self): pass
    jobs = Jobs(); tab = OptionsTab(jobs=jobs)
    class Poller:
        _inflight = False
        calls = 0
        def request(self): self.calls += 1
        def stop(self): pass
        def pause(self): pass
    poller = Poller(); tab._care_poller = poller
    assert not tab.care_choice.isChecked()
    tab.show_agent_care({'enabled': True, 'state': 'applied', 'managed': 4})
    assert tab._care_timer.isActive()
    tab.sync_agent_care()
    assert poller.calls == 1 and not jobs.calls
    jobs.in_flight = 1
    tab.sync_agent_care()
    assert poller.calls == 1 and not jobs.calls
    jobs.in_flight = 0
    tab.care_choice.click()
    assert jobs.calls[-1][0] == 'agent-care-disable' and jobs.calls[-1][1]['confirm']
    assert not tab.care_choice.isEnabled()
    tab.show_agent_care({'enabled': False, 'state': 'restored'})
    assert not tab.care_choice.isChecked() and not tab._care_timer.isActive()
    tab._care_auto_done({'enabled': True, 'state': 'applied'})
    assert not tab.care_choice.isChecked()  # A result from before opt-out is stale.
    assert options_argv('agent-care-enable', '', True)[-4:] == ['ai', 'care-enable', '--json', '--confirmar']
    tab.show_agent_care({'enabled': True, 'state': 'pending', 'operation_id': 'pending'})
    assert not tab._care_timer.isActive() and 'pending' in tab.care_status.text()
    tab.stop(); tab.show_agent_care({'enabled': False})
    assert not tab._care_timer.isActive()
