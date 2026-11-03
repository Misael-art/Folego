"""Live theme coverage: existing/hidden/new surfaces, persistence and contrast."""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QLabel, QMenu, QFrame

from folego.ui import theme
from folego.ui.palettes import THEMES, DEFAULT_THEME, contrast, on_color
from folego.ui.options_tab import OptionsTab
from folego.ui.prompt_panel import PromptPanel
from folego.ui.ai_account_panel import AccountPanel
from folego.ui.desktop_shortcuts import VirtualKeyboard
from test_ui_compact import make, snap


@pytest.fixture
def restore_theme(qapp):
    previous = theme.TOKENS.key
    yield
    theme.apply_theme(qapp, previous)


@pytest.mark.parametrize('key', THEMES)
def test_console_text_focus_and_action_contrast(key):
    t = THEMES[key].tokens
    surfaces = (t.background, t.surface, t.surface_alt)
    for color in (t.text, t.muted, t.accent, t.ok, t.warning, t.danger, *t.categories):
        assert min(contrast(color, s) for s in surfaces) >= 4.5
    assert min(contrast(t.focus, s) for s in surfaces) >= 3
    for color in t.actions:
        assert contrast(on_color(color), color) >= 4.5


def test_live_theme_covers_existing_hidden_and_new_surfaces(qapp, restore_theme):
    view, _ = make(qapp)
    view.show_snapshot(snap())
    panel = PromptPanel()
    accounts = AccountPanel('codex', [])
    keyboard = VirtualKeyboard(view.shortcut_tabs.controller)
    menu = QMenu()
    before = panel.buttons['design-mockups'].label.text()
    role = view.gauge._color_role
    try:
        # None need to be visible for the new theme to reach them.
        for key, selected in THEMES.items():
            theme.apply_theme(qapp, key)
            menu.ensurePolished()
            qapp.processEvents()
            t = selected.tokens
            assert theme.TOKENS.surface == t.surface
            for widget in (view, panel, accounts, keyboard):
                assert t.surface in widget.styleSheet()
            assert view.gauge.color == getattr(t, role)
            assert getattr(t, role) in view.status_label.styleSheet()
            assert t.actions[0] in view.shortcut_tabs.buttons['select_all'].styleSheet()
            assert t.actions[5] in view.shortcut_tabs.buttons['print'].styleSheet()
            assert t.categories[4] in panel.findChild(QFrame, 'promptStripe_design').styleSheet()
            assert menu.palette().color(QPalette.ColorRole.WindowText).name() == t.text.lower()
            assert all(t.muted in label.styleSheet() or t.text in label.styleSheet()
                       for label in accounts.details.findChildren(QLabel))
            fresh = PromptPanel()
            assert t.surface in fresh.styleSheet()
            fresh.deleteLater()
        assert panel.buttons['design-mockups'].label.text() == before
    finally:
        keyboard.close()
        view.force_close()


def test_choice_persists_and_unknown_saved_theme_is_reported(qapp, tmp_path, restore_theme):
    store = QSettings(str(tmp_path / 'theme.ini'), QSettings.Format.IniFormat)
    theme.choose_theme('ps2', store=store)
    theme.apply_theme(qapp, 'nes')
    theme.apply_theme(qapp, store=QSettings(str(tmp_path / 'theme.ini'), QSettings.Format.IniFormat))
    assert theme.TOKENS.key == 'ps2'
    store.setValue(theme.THEME_KEY, 'future-unknown-theme');store.sync()
    theme.apply_theme(qapp, store=store)
    assert theme.TOKENS.key == DEFAULT_THEME
    assert 'desconhecido' in qapp.property('folego_theme_error')
    assert store.value(theme.THEME_KEY) == 'future-unknown-theme'
    qapp.setProperty('folego_theme_error', '')


def test_failed_or_invalid_choice_keeps_current_theme(qapp, restore_theme):
    class ReadOnly:
        def setValue(self, *args): pass
        def sync(self): pass
        def status(self): return QSettings.Status.AccessError
    theme.apply_theme(qapp, 'snes-us')
    with pytest.raises(RuntimeError): theme.choose_theme('ps2', store=ReadOnly())
    assert theme.TOKENS.key == 'snes-us'
    with pytest.raises(ValueError): theme.choose_theme('unknown', store=ReadOnly())
    assert theme.TOKENS.key == 'snes-us'


def test_options_updates_all_views_and_reports_save_failure(qapp, monkeypatch, tmp_path, restore_theme):
    class Jobs:
        def shutdown(self): pass
    from folego.ui import options_tab
    store = QSettings(str(tmp_path / 'theme.ini'), QSettings.Format.IniFormat)
    monkeypatch.setattr(options_tab, 'choose_theme', lambda key: theme.choose_theme(key, store=store))
    first = OptionsTab(jobs=Jobs());second = OptionsTab(jobs=Jobs())
    first.theme_choice.setCurrentIndex(first.theme_choice.findData('pc-engine'))
    assert theme.TOKENS.key == 'pc-engine'
    assert second.theme_choice.currentData() == 'pc-engine'
    assert store.value(theme.THEME_KEY) == 'pc-engine'
    def fail(_key): raise RuntimeError('Não foi salvo')
    monkeypatch.setattr(options_tab, 'choose_theme', fail)
    first.theme_choice.setCurrentIndex(first.theme_choice.findData('ps2'))
    assert theme.TOKENS.key == 'pc-engine'
    assert first.theme_choice.currentData() == 'pc-engine'
    assert 'Não foi salvo' in first.theme_status.text()
