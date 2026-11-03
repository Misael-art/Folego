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
    assert "nada é fechado" in tab.notice.text()
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
