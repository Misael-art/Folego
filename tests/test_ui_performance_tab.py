from folego.core import agents, perf_model
from folego.ui.performance_tab import PerformanceTab


def view():
    act = agents.AgentActivity(frozenset({1}), frozenset({1}), frozenset({"/p"}), agents.IDLE, 0.0)
    groups = (perf_model.AppGroup("app-edge.scope", "edge", (5, 6), 900_000, 2.0,
                                  perf_model.OBSERVED, "sem agente"),
              perf_model.AppGroup("x.scope", "tiny", (7,), 10, None, perf_model.PROTECTED, "classe"))
    return perf_model.PerfView(groups, act, None, 4_000_000, 16_000_000)


def test_tab_polls_only_while_visible_and_never_acts(qapp):
    calls = []
    tab = PerformanceTab(observe_factory=lambda: (lambda: calls.append(1) or view()), interval_s=60)
    assert tab._poller is None
    tab.show(); qapp.processEvents()
    assert tab._poller is not None
    tab.show_view(view())
    assert tab.table.rowCount() == 1 and tab.table.item(0, 1).text() == "edge"
    assert "nada é fechado" in tab.notice.text() and "indisponível" in tab.summary.text()
    tab.hide(); qapp.processEvents()
    assert not tab._poller._timer.isActive()
    tab.shutdown()
    assert tab._poller is None
