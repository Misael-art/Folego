from folego.ui.options_tab import OptionsTab, options_argv
from folego.ui.tune_jobs import MUTATING


def test_basic_session_worker_controls_default_and_uncertain_result(qapp):
    class Jobs:
        def __init__(self): self.calls = []
        def run(self, action, target, **kw): self.calls.append((action, kw))
        def shutdown(self): pass
    jobs = Jobs()
    tab = OptionsTab(jobs=jobs)
    assert tab.basic_choice.isChecked()
    tab.basic_choice.click()
    assert jobs.calls[-1][0] == 'startup-basic-disable'
    assert jobs.calls[-1][1]['confirm'] is True
    assert not tab.basic_choice.isEnabled()
    tab.show_basic_session({'enabled': False, 'state': 'restored', 'message': 'Restaurado'})
    assert not tab.basic_choice.isChecked() and tab.basic_choice.isEnabled()
    tab.show_basic_session({'enabled': True, 'state': 'intended', 'operation_id': 'same-id',
                            'message': 'Pendente'})
    assert 'same-id' in tab.basic_status.text()
    tab.basic_verify.click()
    assert jobs.calls[-1][0] == 'startup-basic-reconcile'
    tab.show_basic_session({'enabled': True, 'state': 'conflict', 'message': 'Mudou'})
    assert not tab.basic_choice.isEnabled()
    tab.show_basic_session(None)
    assert 'desconhecida' in tab.basic_status.text().lower()
    assert options_argv('startup-basic-disable', '', True)[-4:] == [
        'startup', 'basic-disable', '--json', '--confirmar']
    assert 'startup-basic-enable' in MUTATING and 'startup-basic-reconcile' in MUTATING
    tab.close()


def test_startup_sync_uses_its_final_basic_response_without_a_racing_status(qapp):
    class Jobs:
        def __init__(self): self.calls = []
        def run(self, action, target, **kw): self.calls.append((action, kw))
        def shutdown(self): pass
    jobs = Jobs(); tab = OptionsTab(jobs=jobs)
    tab.start(sync=True)
    assert 'startup-basic-status' not in [c[0] for c in jobs.calls]
    assert not tab.basic_choice.isEnabled()
    tab.done({'enabled': True, 'outcome': 'sucesso', 'basic_session': {
        'enabled': True, 'state': 'applied', 'message': 'Configurado',
        'targets': ['steam-input.desktop'], 'preserved': ['unknown.desktop']}})
    assert tab.basic_choice.isEnabled()
    assert 'steam-input.desktop' in tab.basic_status.text()
    assert 'unknown.desktop' in tab.basic_status.text()
    tab.close()
