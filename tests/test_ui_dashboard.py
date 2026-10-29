"""M3 dashboard: the same numbers the title bar shows, plus what to do about them.

The panel receives plain data and a jump callback — it never measures, never
reads /proc and never mutates. That boundary is the test: a suggestion click
only changes which tab is visible.
"""
import pytest

from PySide6.QtCore import QCoreApplication, QEvent

from folego.core.snapshot import AppRSS, MemInfo, Pressure, Snapshot
from folego.ui.dashboard_tab import DashboardTab

pytest.importorskip("PySide6")


def snap(*, available_kb=5_000_000, total_kb=14_374_304, psi10=0.0,
         swap_used_kb=0, swap_total_kb=7_208_724, self_rss_kb=96_000,
         apps=(AppRSS("edge", 3 * 1024 * 1024, 21),), errors=(),
         tmpfs=(), sources=()):
    return Snapshot(ts=0.0, mem=MemInfo(total_kb, available_kb),
                    swap_used_kb=swap_used_kb, swap_total_kb=swap_total_kb,
                    pressure_memory=Pressure(psi10, psi10, psi10, 0),
                    pressure_io=None, pressure_cpu=None, load=None,
                    apps=apps, self_rss_kb=self_rss_kb, errors=errors,
                    tmpfs=tmpfs, sources=sources)


@pytest.fixture
def panel(qapp):
    jumps = []
    return DashboardTab(on_jump=jumps.append), jumps


def test_the_headline_repeats_the_title_signal(panel):
    view, jumps = panel
    view.show_snapshot(snap(psi10=14.0))
    assert "🔴" in view.headline.text()


def test_suggestions_land_in_order_with_their_own_jump_target(panel):
    view, jumps = panel
    view.show_snapshot(snap(psi10=14.0, available_kb=900_000), orphan_count=2)
    assert [row.target for row in view.rows] == ["memoria", "memoria", "ajustes",
                                                 "orfaos"]


def test_the_overview_names_each_resource_and_the_collection_quality(panel):
    from folego.core.snapshot import OK, PARTIAL, SourceQuality
    from folego.core.tmpfs import TmpfsVolume
    view, _ = panel
    view.show_snapshot(snap(
        tmpfs=(TmpfsVolume("/tmp", "tmpfs", 8 * 1024 ** 3, 7 * 1024 ** 3,
                          1024 ** 3),),
        sources=(SourceQuality("meminfo", OK, ""),
                 SourceQuality("processes", PARTIAL, "varredura limitada"))))

    text = view.resources.text()
    assert "memória: ok" in text
    assert "tmpfs /tmp: 88% usado" in text
    assert "coleta: ok 1, partial 1" in text
    assert "warning" not in text.lower()


def test_the_last_operation_is_shown_verbatim_and_never_invented(panel):
    view, _ = panel
    view.show_snapshot(snap(), last_operation="17/10 12:00:00 · disk.quarantine · sucesso")
    assert "disk.quarantine · sucesso" in view.last_operation.text()
    assert view.last_operation.text().startswith("última operação:")


def test_clicking_a_suggestion_only_asks_to_change_tab(panel):
    view, jumps = panel
    view.show_snapshot(snap(apps=(AppRSS("edge", 3 * 1024 * 1024, 21),)))
    view.rows[0].jump_button.click()
    assert jumps == ["ajustes"]


def test_a_calm_machine_is_reported_calm_instead_of_left_blank(panel):
    view, _ = panel
    view.show_snapshot(snap(apps=(), psi10=0.0, available_kb=8_000_000))
    assert view.rows == []
    assert "nada" in view.status.text().lower()


def test_full_runtime_recommends_the_temporaries_tab(panel):
    from folego.core.tmpfs import TmpfsVolume
    view, jumps = panel
    view.show_snapshot(snap(apps=(), tmpfs=(TmpfsVolume(
        "/run/user/1000", "tmpfs", 1000, 1000, 0, is_runtime=True),)))
    assert view.gauge.verdict == "Crítico"
    assert view.rows[0].target == "tmpfs"
    view.primary_button.click()
    assert jumps == ["tmpfs"]
    assert "dentro do orçamento" not in view.primary_button.text()


def test_missing_or_stale_memory_never_gets_a_healthy_empty_state(panel):
    from dataclasses import replace
    from folego.core.snapshot import SourceQuality
    view, _ = panel
    for sample in (replace(snap(apps=()), mem=None),
                   replace(snap(apps=()), mono=1, sources=(SourceQuality("meminfo", "ok"),))):
        view.show_snapshot(sample)
        assert view.gauge.verdict == "Desconhecido"
        assert "dentro do orçamento" not in view.no_recommendations.text()
        assert "dados válidos" in view.primary_button.text()


def test_freshness_timer_invalidates_gauge_cards_and_empty_state(panel):
    from folego.ui.title_signal import TitleSignal
    view, _ = panel
    view.show_snapshot(snap(apps=()))
    view.invalidate_health(TitleSignal("unknown", "⚪", "amostra antiga"))
    assert view.gauge.value is None and view.gauge.verdict == "Desconhecido"
    assert all(card.value.text() == "—" for card in view.cards.values())
    assert "dentro do orçamento" not in view.no_recommendations.text()


def test_the_panel_shows_what_the_collector_could_not_read(panel):
    view, _ = panel
    view.show_snapshot(snap(errors=("meminfo: No space left on device",)))
    assert "No space left" in view.status.text()


def test_pressure_and_zram_get_their_own_numbers(panel):
    view, _ = panel
    view.show_snapshot(snap(psi10=12.0, swap_used_kb=6 * 1024 * 1024))
    text = view.details.text()
    assert "psi" in text.lower() and "12,0" in text
    assert "zram" in text.lower() and "6,0 GB" in text


def test_the_details_name_the_heaviest_apps(panel):
    """M1's body text listed them; the dashboard must not lose that."""
    view, _ = panel
    view.show_snapshot(snap(apps=(AppRSS("chrome", 900 * 1024, 9),
                                 AppRSS("codex", 120 * 1024, 3))))
    assert "chrome 900 MB" in view.details.text()
    assert "codex 120 MB" in view.details.text()


def test_a_repeated_poll_updates_suggestion_rows_in_place(panel):
    """Um poll igual não pode recriar os botões: foco e seleção ficam onde estão."""
    view, _ = panel
    view.show_snapshot(snap(psi10=14.0))
    first = view.rows[0]

    view.show_snapshot(snap(psi10=14.0))

    assert view.rows[0] is first
    assert first.text_label.text().startswith("🔴")


def test_a_new_suggestion_set_reuses_matching_rows_and_removes_the_rest(panel):
    view, _ = panel
    view.show_snapshot(snap(psi10=14.0, self_rss_kb=350_000))
    by_id = {row.suggestion.id: row for row in view.rows}

    view.show_snapshot(snap(psi10=14.0))

    assert view.rows[0] is by_id["pressao"]
    assert all(row.suggestion.id != "app" for row in view.rows)


def test_a_removed_suggestion_row_returns_hidden_to_the_pool(panel, qapp):
    """Ensaio F8: destruir a linha com `deleteLater` derrubava o processo quando
    haviam conexões Python pendentes. A linha sai do layout, fica oculta e volta
    no próximo poll — nada de C++/Python é destruído em pleno loop."""
    view, _ = panel
    view.show_snapshot(snap(psi10=14.0, apps=()))
    row = view.rows[0]
    before = view.list_box.count()

    view.show_snapshot(snap(psi10=0.0, apps=()))

    assert view.rows == []
    assert view.list_box.count() == before - 1
    assert row.parent() is not None and row.isHidden()
    assert view._hidden_rows == [row]

    view.show_snapshot(snap(psi10=14.0, apps=()))
    assert view.rows[0] is row
    assert view._hidden_rows == []
    assert not row.isHidden(), "a linha do pool volta visível, sem recriação"

    for _ in range(5):
        view.show_snapshot(snap(psi10=14.0, apps=()))
        view.show_snapshot(snap(psi10=0.0, apps=()))
    assert view.list_box.count() == 0
    assert len(view._hidden_rows) == 1, "o pool não pode crescer a cada ciclo"


def test_reused_row_updates_content_and_callback_without_replacing_focused_button(panel, qapp):
    view, jumps = panel
    view.show()
    view.show_snapshot(snap(psi10=14.0, apps=()))
    row = view.rows[0]
    view.show_snapshot(snap(psi10=0.0, apps=()))
    view.show_snapshot(snap(psi10=0.0, apps=(AppRSS("edge", 3 * 1024 * 1024, 21),)))
    assert view.rows[0] is row and row.target == "ajustes"
    assert "ajustes" in row.jump_button.text()
    row.jump_button.setFocus()
    qapp.processEvents()
    assert row.jump_button.hasFocus()
    view.show_snapshot(snap(psi10=0.0, apps=(AppRSS("edge", 3 * 1024 * 1024, 21),)))
    assert row.jump_button.hasFocus()
    row.jump_button.click()
    assert jumps == ["ajustes"]
    view.close()


def test_automation_is_read_only_and_separates_mode_from_grants(panel):
    view, _ = panel
    view.show_automation(mode="manual", preset="conservador", paused=False,
                         active_grants=0)
    text = view.automation_status.text()
    assert "modo manual" in text and "preset conservador" in text
    assert "nenhum grant ativo" in text
    assert "execução real desligada" in text

    view.show_automation(mode="assistido", preset="foco", paused=True,
                         active_grants=2)
    text = view.automation_status.text()
    assert "modo assistido" in text and "pausada" in text
    assert "2 grant(s) ativo(s)" in text


def test_an_illegible_automation_state_fails_closed_in_the_ui(panel):
    view, _ = panel
    view.show_automation(mode="manual", preset="equilibrado", paused=False,
                         active_grants=0, error="registro ilegível")
    text = view.automation_status.text()
    assert "ilegível" in text and "fail-closed" in text
    assert "execução desligada" in text
    assert "modo manual" not in text


def test_the_diagnostic_copy_includes_automation_state(panel):
    view, _ = panel
    view.show_automation(mode="manual", preset="equilibrado", paused=False,
                         active_grants=0)
    assert "automação: modo manual" in view.diagnostic_text()


def test_a_snapshot_without_memory_leaves_the_title_alone(panel):
    view, _ = panel
    empty = Snapshot(ts=0.0, mem=None, swap_used_kb=0, swap_total_kb=0,
                     pressure_memory=None, pressure_io=None, pressure_cpu=None,
                     load=None, apps=(), self_rss_kb=0)
    view.show_snapshot(empty)
    assert "indisponível" in view.headline.text()


def test_headroom_is_the_smallest_free_share_and_unknown_without_data():
    from folego.core.tmpfs import TmpfsVolume
    from folego.ui.dashboard_tab import headroom_pct
    runtime = TmpfsVolume("/run/user/1000", "tmpfs", 100, 95, 5, is_runtime=True)
    assert headroom_pct(snap(available_kb=7_187_152, swap_used_kb=0)) == 50
    assert headroom_pct(snap(swap_used_kb=6_487_852)) == 10
    assert headroom_pct(snap(tmpfs=(runtime,))) == 5
    broken = TmpfsVolume("/tmp", "tmpfs", 0, 0, 0, quality="error", error="x")
    empty = Snapshot(ts=0.0, mem=None, swap_used_kb=0, swap_total_kb=0, pressure_memory=None,
                     pressure_io=None, pressure_cpu=None, load=None, apps=(), self_rss_kb=0,
                     errors=(), tmpfs=(broken,), sources=())
    assert headroom_pct(empty) is None


def test_gauge_and_cards_say_the_level_in_words(panel):
    tab, _ = panel
    tab.show_snapshot(snap(available_kb=1_000_000, swap_used_kb=6_800_000))
    assert tab.gauge.verdict == "Crítico"
    assert "Crítico" in tab.gauge.accessibleDescription() and "folga" in tab.gauge.accessibleDescription()
    memory = tab.cards["memoria"]
    assert memory.value.text() == "93%" and memory.detail.text().startswith("crítico")
    assert memory.property("level") == "danger"
    assert tab.cards["swap"].detail.text().startswith("crítico")
    assert tab.cards["cpu"].value.text() == "—"
    assert "menor folga" in tab.verdict_line.text()


def test_primary_action_jumps_to_the_most_urgent_recommendation_only(panel):
    tab, jumps = panel
    tab.show_snapshot(snap(apps=()))
    assert not tab.primary_button.isEnabled() and tab.no_recommendations.isVisibleTo(tab)
    tab.show_snapshot(snap(available_kb=1_000_000))
    assert tab.primary_button.isEnabled() and not tab.no_recommendations.isVisibleTo(tab)
    tab.primary_button.click()
    assert jumps == [tab.rows[0].target]


def test_widget_button_exists_only_with_a_handler_and_calls_it(qapp):
    calls = []
    with_handler = DashboardTab(on_widget=lambda: calls.append(1))
    with_handler.show()
    assert with_handler.widget_button.isVisible()
    with_handler.widget_button.click()
    assert calls == [1]
    assert not DashboardTab().widget_button.isVisibleTo(DashboardTab())
