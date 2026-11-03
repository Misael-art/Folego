import json

from folego.core import agents, perf_model, perf_rules
from folego.ui.performance_tab import Observation, PerformanceTab


def view():
    act = agents.AgentActivity(frozenset({1}), frozenset({1}), frozenset({"/p"}), agents.IDLE, 0.0)
    groups = (perf_model.AppGroup("app-edge.scope", "edge", (5, 6), 900_000, 2.0,
                                  perf_model.OBSERVED, "sem agente"),
              perf_model.AppGroup("x.scope", "tiny", (7,), 10, None, perf_model.PROTECTED, "classe"))
    return perf_model.PerfView(groups, act, None, 4_000_000, 16_000_000)


def test_tab_polls_only_while_visible_and_never_acts(qapp, tmp_path):
    calls = []
    tab = PerformanceTab(observe_factory=lambda _path: (lambda: calls.append(1) or Observation(view())),
                         interval_s=60, rules_path=tmp_path / "rules.json")
    assert tab._poller is None
    tab.show(); qapp.processEvents()
    assert tab._poller is not None
    tab.show_view(view())
    assert tab.table.rowCount() == 1 and tab.table.item(0, 1).text() == "edge"
    assert "indisponível" in tab.summary.text()
    tab.show_observation(Observation(view()))
    assert "Assistido pede o seu clique" in tab.notice.text()
    tab.hide(); qapp.processEvents()
    assert not tab._poller._timer.isActive()
    tab.shutdown()
    assert tab._poller is None


def suggestion(ready):
    return perf_rules.Suggestion("steam-idle", "Steam aberto sem jogo", perf_rules.CLOSE, "u", "steam",
                                 500_000, "CPU 0%", "Sair pela bandeja", ready, 30.0, 600.0)


def test_cards_and_modes_persist_and_bad_file_disables(qapp, tmp_path):
    path = tmp_path / "rules.json"
    tab = PerformanceTab(observe_factory=lambda _p: (lambda: Observation(view())), rules_path=path)
    tab.show_suggestions((suggestion(False), suggestion(True)))
    texts = [tab.cards.itemAt(i).widget().detail.text() for i in range(tab.cards.count())]
    assert "observando 30/600 s" in texts[0] and "pronta" in texts[1]
    choice = tab.mode_choices["steam-idle"]
    choice.setCurrentIndex(choice.findData("off"))
    assert json.loads(path.read_text())["modes"]["steam-idle"] == "off"
    tab.show_observation(Observation(view(), (), "versão não suportada"))
    assert "desligado" in tab.notice.text() and tab.suggestions == ()
    path.write_text("{")
    bad = PerformanceTab(observe_factory=lambda _p: (lambda: Observation(view())), rules_path=path)
    assert not bad.mode_choices["steam-idle"].isEnabled() and "desligado" in bad.notice.text()


class Jobs:
    def __init__(self):
        self.calls = []
        self.review_calls = []

    def run(self, acao, target, *, confirm, done):
        self.calls.append((acao, target, confirm))
        self.done = done

    def review_and_run(self, action, target, *, title, text, confirm_fn, done, expected_scope):
        self.review_calls.append((action, target, expected_scope))
        self.review_confirm = confirm_fn
        self.done = done


def test_assisted_ready_card_closes_only_after_confirmation(qapp, tmp_path):
    jobs = Jobs()
    answers = []
    tab = PerformanceTab(observe_factory=lambda _p: (lambda: Observation(view())),
                         rules_path=tmp_path / "r.json", jobs=jobs,
                         confirm_fn=lambda title, text: answers.pop(0))
    item = perf_rules.Suggestion("steam-idle", "Steam", perf_rules.CLOSE, "app-steam.service", "steam",
                                 500_000, "CPU 0%", "Sair", True, 600.0, 600.0, perf_rules.ASSISTED,
                                 "tray", (5,))
    tab.show_suggestions((item, suggestion(True)))
    card = tab.cards.itemAt(0).widget()
    assert card.close_button is not None and tab.cards.itemAt(1).widget().close_button is None
    card.close_button.click()
    assert jobs.review_calls == [("performance-close", "steam-idle\tapp-steam.service",
                                  [{"key": "app-steam.service"}])]
    assert jobs.calls == [] and answers == []  # no dialog before the same plan/ID exists
    assert tab.closing == "steam" and tab.cards.itemAt(0).widget().close_button is None
    tab.request_close(item)
    assert len(jobs.review_calls) == 1  # repeated click cannot create a second review
    answers.append(False)
    assert not jobs.review_confirm("Fechar?", "Operação fixture")
    jobs.done({"outcome": "cancelamento", "reason": "nenhum efeito"})
    assert tab.closing == ""
    tab.request_close(item)
    answers.append(True)
    assert jobs.review_confirm("Fechar?", "Operação fixture")
    jobs.done({"outcome": "sucesso", "reason": "todos saíram"})
    assert tab.closing == "" and "sucesso" in tab.notice.text()


def test_automatic_card_offers_snooze_protect_and_breaker_resume(qapp, tmp_path):
    jobs = Jobs()
    tab = PerformanceTab(observe_factory=lambda _p: (lambda: Observation(view())),
                         rules_path=tmp_path / "r.json", jobs=jobs, confirm_fn=lambda t, x: True)
    item = perf_rules.Suggestion("steam-idle", "Steam", perf_rules.CLOSE, "app-steam.service", "steam",
                                 500_000, "CPU 0%", "Sair", True, 600.0, 600.0, perf_rules.AUTOMATIC,
                                 "tray", (5,))
    state = {"breaker": "2 falhas", "history": [], "last": {"trigger": "", "waiting": [
        {"rule": "steam-idle", "unit": "app-steam.service", "label": "steam", "why": "carência: 30 s"}]}}
    tab.show_observation(Observation(view(), (item,), auto=state))
    card = tab.cards.itemAt(0).widget()
    assert "carência" in card.waiting.text() and not tab.resume_button.isHidden()
    assert "disjuntor" in tab.auto_status.text()
    card.snooze_button.click()
    assert jobs.calls[-1] == ("performance-snooze", "steam-idle\tapp-steam.service", False)
    jobs.done({"outcome": "sucesso", "reason": "adiado"})
    tab.cards.itemAt(0).widget().protect_button.click()
    assert jobs.calls[-1] == ("performance-protect", "steam-idle\tapp-steam.service", True)
    jobs.done({"outcome": "sucesso"})
    tab.resume_button.click()
    assert jobs.calls[-1][0] == "performance-resume"
    tab.show_auto(None, "versão")
    assert "desligado" in tab.auto_status.text() and tab.resume_button.isHidden()


def test_top_switch_turns_automatic_off_without_dialog_and_on_with_one(qapp, tmp_path):
    jobs = Jobs()
    asked = []
    tab = PerformanceTab(observe_factory=lambda _p: (lambda: Observation(view())),
                         rules_path=tmp_path / "r.json", jobs=jobs,
                         confirm_fn=lambda t, x: asked.append(t) or True)
    assert not tab.auto_switch.isEnabled()
    tab.show_observation(Observation(view(), auto={"paused": False, "history": [], "last": {}}))
    assert tab.auto_switch.isChecked() and "ligado" in tab.auto_switch.text()
    tab.auto_switch.click()
    assert jobs.calls[-1][0] == "performance-auto-off" and asked == []
    jobs.done({"outcome": "sucesso", "reason": "automático desligado: nada será fechado sozinho"})
    assert not tab.auto_switch.isChecked() and "desligado pelo usuário" in tab.auto_status.text()
    tab.auto_switch.click()
    assert jobs.calls[-1][0] == "performance-auto-on" and asked == ["Ligar automático?"]
    tab.show_auto(None, "ilegível")
    assert not tab.auto_switch.isEnabled()


def test_bridges_section_offers_finalize_only_when_safe(qapp, tmp_path):
    from folego.core import mcp_bridges as mb
    from folego.core.snapshot import ProcInfo
    jobs = Jobs()
    tab = PerformanceTab(observe_factory=lambda _p: (lambda: Observation(view())),
                         rules_path=tmp_path / "r.json", jobs=jobs, confirm_fn=lambda t, x: True)
    member = ProcInfo(12, "npm", "S", 1, 12, 12, 0, 0, 5, 1, 0, 1000, ())
    a = mb.Bridge(12, 5, (member,), "http://127.0.0.1:1/mcp", 10, "claude-desktop", True, 900, 0.0, mb.DUPLICATE)
    b = mb.Bridge(22, 9, (member,), "http://127.0.0.1:1/mcp", 10, "claude-desktop", True, 900, 0.0, mb.DUPLICATE)
    tab.show_observation(Observation(view(), bridges=(a, b)))
    assert tab.bridge_buttons[12].isEnabled() and tab.bridge_buttons[22].isEnabled()
    first = tab.bridge_rows.itemAt(0).widget().findChild(type(tab.summary))
    assert "recomendada" in first.text()
    tab.bridge_buttons[12].click()
    assert jobs.calls[-1] == ("performance-bridge-stop", "12", True)
    assert not tab.bridge_buttons[22].isEnabled()  # one action at a time
    jobs.done({"outcome": "sucesso", "reason": "ponte finalizada; MCP OK: 1 ponte conectada ao cliente"})
    assert "MCP OK" in tab.notice.text()
    single = mb.Bridge(**{**b.__dict__, "status": mb.SINGLE})
    tab.show_bridges((single,))
    assert not tab.bridge_buttons[22].isEnabled()
