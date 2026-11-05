import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from folego.core.development_prompts import PROMPTS, PROMPT_CATEGORIES, text
from folego.ui.desktop_shortcuts import ShortcutTabs
from folego.ui.prompt_panel import PromptPanel
from folego.ui.theme import STYLESHEET


def wait(qapp, predicate):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        qapp.processEvents()
        if predicate(): return
        time.sleep(.01)
    raise AssertionError('Prompt picker deadline')


def test_every_grouped_choice_copies_full_text_once_and_closes(qapp, monkeypatch):
    copied = []
    tabs = ShortcutTabs()
    monkeypatch.setattr(tabs, '_copy_text', copied.append)
    for prompt in PROMPTS:
        tabs.show_prompts()
        panel = tabs.prompt_panel
        assert panel.count.text() == '13 modelos'
        assert [h.text() for h in panel.headings.values()] == [title for _, title, _ in PROMPT_CATEGORIES]
        assert set(panel.buttons) == {p.key for p in PROMPTS}
        button = panel.buttons[prompt.key]
        assert button.accessibleName() == prompt.title and button.label.text() == prompt.title
        button.click()
        assert tabs.prompt_menu is None and tabs.prompt_panel is None
        assert copied == [text(p.key) for p in PROMPTS[:len(copied)]]
    assert len(copied) == 13
    tabs.shutdown()


def test_picker_keyboard_navigation_copies_and_escape_closes(qapp, monkeypatch):
    copied = []
    tabs = ShortcutTabs()
    monkeypatch.setattr(tabs, '_copy_text', copied.append)
    tabs.show_prompts()
    menu, panel = tabs.prompt_menu, tabs.prompt_panel
    QTest.keyClick(menu, Qt.Key.Key_Home)
    assert panel.buttons['diagnose'].hasFocus()
    QTest.keyClick(panel.buttons['diagnose'], Qt.Key.Key_Down)
    assert panel.buttons['implant'].hasFocus()
    QTest.keyClick(panel.buttons['implant'], Qt.Key.Key_Return)
    assert copied == [text('implant')] and tabs.prompt_menu is None
    tabs.show_prompts()
    QTest.keyClick(tabs.prompt_menu, Qt.Key.Key_Escape)
    assert tabs.prompt_menu is None
    tabs.shutdown()


def test_product_theme_keeps_popup_size_and_thin_group_dividers(qapp):
    from PySide6.QtWidgets import QFrame
    tabs = ShortcutTabs()
    tabs.setStyleSheet(STYLESHEET)
    tabs.show_prompts()
    qapp.processEvents()
    assert tabs.prompt_menu.width() == 480 and tabs.prompt_menu.height() == 540
    lines = [f for f in tabs.prompt_panel.findChildren(QFrame) if f.maximumHeight() == 1]
    assert len(lines) == 7 and all(f.height() == 1 for f in lines)
    tabs.shutdown()


def test_scrolling_and_wrapping_preserve_footer_and_readable_choices(qapp):
    panel = PromptPanel()
    panel.setStyleSheet(STYLESHEET + panel.styleSheet())
    panel.setFixedSize(340, 320)
    panel.show()
    wait(qapp, lambda: panel.scroll.verticalScrollBar().maximum() > 0)
    footer_y = panel.footer_buttons['Custom'].mapTo(panel, panel.footer_buttons['Custom'].rect().topLeft()).y()
    button = panel.buttons['delivery']
    panel.scroll.ensureWidgetVisible(button, 0, 8)
    qapp.processEvents()
    assert panel.scroll.horizontalScrollBar().maximum() == 0
    assert button.label.height() >= button.label.heightForWidth(button.label.width())
    assert panel.footer_buttons['Custom'].mapTo(panel, panel.footer_buttons['Custom'].rect().topLeft()).y() == footer_y
    for footer in panel.footer_buttons.values():
        assert panel.rect().contains(footer.mapTo(panel, footer.rect().bottomRight()))
    panel.close()
