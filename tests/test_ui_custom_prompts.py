import time

from folego.adapters.desktop_tools import DesktopTools
from folego.core.custom_prompts import CustomPrompts
from folego.ui.custom_prompts_tab import CustomPromptsTab
from folego.ui.desktop_shortcuts import DesktopController, ShortcutTabs


def wait(qapp, predicate):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        qapp.processEvents()
        if predicate(): return
        time.sleep(.01)
    raise AssertionError('UI task not completed')


def test_editor_creates_text_and_macro_without_executing_them(qapp, tmp_path, monkeypatch):
    env = dict(HOME=str(tmp_path))
    backend = DesktopTools(env=env)
    monkeypatch.setattr(backend, 'keys', lambda *_: (_ for _ in ()).throw(AssertionError('saving ran keys')))
    monkeypatch.setattr(backend, 'show_desktop', lambda: (_ for _ in ()).throw(AssertionError('saving ran macro')))
    controller = DesktopController(backend=backend)
    editor = CustomPromptsTab(controller=controller)
    assert not editor.initialized
    editor.show(); wait(qapp, lambda: editor.readable and not editor.busy)
    assert editor.text.toPlainText() == '123'
    editor.add_text.click(); editor.title.setText('Meu texto'); editor.text.setPlainText('Texto\ncom acentos')
    editor.save.click(); wait(qapp, lambda: not editor.busy and len(editor.entries) == 3)
    editor.add_macro.click(); editor.title.setText('Meu atalho'); editor.action.setCurrentIndex(1); editor.shortcut.setText('Ctrl+Alt+T')
    editor.save.click(); wait(qapp, lambda: not editor.busy and len(editor.entries) == 4)
    saved = CustomPrompts(env=env).read()
    assert saved['entries'][2]['text'] == 'Texto\ncom acentos'
    assert saved['entries'][3]['shortcut'] == 'Ctrl+Alt+T'
    editor.shutdown(); editor.close()


def test_custom_is_last_submenu_and_copy_is_literal_123(qapp, tmp_path, monkeypatch):
    class Clipboard:
        value = None
        def setText(self, value): self.value = value
    clipboard = Clipboard()
    monkeypatch.setattr('folego.ui.desktop_shortcuts.QGuiApplication.clipboard', lambda: clipboard)
    controller = DesktopController(backend=DesktopTools(env=dict(HOME=str(tmp_path))))
    tabs = ShortcutTabs(controller=controller)
    tabs.show_prompts()
    wait(qapp, lambda: tabs.custom_menu is not None and any(a.text() == '123' for a in tabs.custom_menu.actions()))
    assert list(tabs.prompt_panel.footer_buttons)[-1] == 'Custom'
    next(a for a in tabs.custom_menu.actions() if a.text() == '123').trigger()
    wait(qapp, lambda: clipboard.value is not None)
    assert clipboard.value == '123'
    requested = []
    tabs.customize_requested.connect(lambda: requested.append(True))
    tabs.show_prompts()
    wait(qapp, lambda: tabs.custom_menu is not None and any(a.text() == 'Editar textos e macros…' for a in tabs.custom_menu.actions()))
    next(a for a in tabs.custom_menu.actions() if a.text() == 'Editar textos e macros…').trigger()
    assert requested == [True]
    assert tabs.prompt_menu is None
    tabs.shutdown()


def test_bad_library_disables_editor_instead_of_overwriting(qapp, tmp_path):
    store = CustomPrompts(env=dict(HOME=str(tmp_path))); store.path.parent.mkdir(parents=True)
    store.path.write_text('{invalid')
    controller = DesktopController(backend=DesktopTools(env=dict(HOME=str(tmp_path))))
    editor = CustomPromptsTab(controller=controller); editor.show()
    wait(qapp, lambda: controller.future is None and 'preservado' in editor.status.text())
    assert not editor.readable and not editor.save.isEnabled()
    assert store.path.read_text() == '{invalid'
    editor.shutdown(); editor.close()


def test_standard_groups_are_always_available_and_click_dispatches_one_macro(qapp, tmp_path, monkeypatch):
    store = CustomPrompts(env=dict(HOME=str(tmp_path)))
    store.path.parent.mkdir(parents=True)
    store.path.write_text('{unknown}')
    backend = DesktopTools(env=dict(HOME=str(tmp_path)))
    calls = []
    monkeypatch.setattr(backend, 'keys', lambda codes: calls.append(codes) or 'sent')
    controller = DesktopController(backend=backend)
    tabs = ShortcutTabs(controller=controller)
    tabs.show_prompts()
    wait(qapp, lambda: controller.future is None)
    groups = tabs.prompt_panel.footer_menus
    assert list(groups) == ['Janelas', 'Edição', 'Terminal', 'Custom']
    assert [len(groups[name].actions()) for name in ('Janelas', 'Edição', 'Terminal')] == [4, 4, 2]
    assert calls == []  # opening menus never invokes a macro
    assert groups['Custom'].actions()[0].text() == 'Biblioteca indisponível'
    for name, total in (('Janelas', 4), ('Edição', 4), ('Terminal', 2)):
        for index in range(total):
            if tabs.prompt_menu is None:
                tabs.show_prompts()
                wait(qapp, lambda: controller.future is None)
            action = tabs.prompt_panel.footer_menus[name].actions()[index]
            assert action.shortcut().isEmpty() and '\t' in action.text()
            before = len(calls)
            action.trigger()
            wait(qapp, lambda: controller.future is None)
            assert len(calls) == before + 1
    assert calls == [[56, 15], [125, 17], [125, 105], [125, 106],
                     [29, 44], [29, 42, 44], [29, 31], [29, 33], [29, 42, 46], [29, 42, 47]]
    assert store.path.read_text() == '{unknown}'
    assert tabs.prompt_menu is None
    tabs.shutdown()


def test_compact_custom_editor_opens_the_standard_window_tab(qapp):
    from folego.ui.main_window import MainWindow
    window = MainWindow()
    window.show_compact()
    window._compact.shortcut_tabs.customize_requested.emit()
    assert window.isVisible() and not window._compact.isVisible()
    assert window.tabs.currentWidget() is window.custom_prompts
    wait(qapp, lambda: window.custom_prompts.initialized and window.custom_prompts.readable)
    assert window.custom_prompts.text.toPlainText() == '123'
    window.quit()
