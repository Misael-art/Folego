import pytest

from folego.adapters.editable_text import edit_focused


class Bridge:
    def __init__(self, count=42, selections=0):
        self.count, self.selections = count, selections
        self.calls = []
        self.closed = False
    def focused(self, pid): return 'object', 'text', 'editable'
    def states(self, obj): return True
    def call(self, name, *args, **kwargs):
        self.calls.append((name, args))
        if name == 'text_get_character_count': return self.count
        if name == 'text_get_n_selections': return self.selections
        if name == 'editable_text_delete_text': self.count = 0
        return True
    def close(self): self.closed = True


@pytest.mark.parametrize('selections', [0, 1])
def test_selection_targets_the_editable_object_without_keys_or_text_reads(selections):
    api = Bridge(selections=selections)
    edit_focused('select_all', bridge=lambda: api, focus=lambda env: ('window', (123, 1, 10)))
    method = 'text_set_selection' if selections else 'text_add_selection'
    assert any(name == method for name, _ in api.calls)
    assert not any('get_text' in name or 'delete' in name for name, _ in api.calls)
    assert api.closed


def test_delete_removes_only_explicit_field_and_never_reads_or_copies_contents():
    api = Bridge()
    edit_focused('delete_all', bridge=lambda: api, focus=lambda env: ('window', (123, 1, 10)))
    assert ('editable_text_delete_text', ('editable', 0, 42)) in api.calls
    assert not any('selection' in name or 'get_text' in name for name, _ in api.calls)
    assert api.closed


def test_focus_change_refuses_effect_instead_of_global_shortcut_fallback():
    api = Bridge()
    focus = iter([('window', (123, 1, 10)), ('other-window', (124, 1, 11))])
    with pytest.raises(RuntimeError, match='foco mudou'):
        edit_focused('delete_all', bridge=lambda: api, focus=lambda env: next(focus))
    assert api.closed and not any('delete' in name for name, _ in api.calls)


def test_missing_editable_surface_never_deletes_or_sends_terminal_shortcuts():
    api = Bridge()
    def unavailable(pid): raise RuntimeError('campo não acessível')
    api.focused = unavailable
    with pytest.raises(RuntimeError):
        edit_focused('delete_all', bridge=lambda: api, focus=lambda env: ('window', (123, 1, 10)))
    assert api.closed and not api.calls


@pytest.mark.parametrize('selected', [0, 1])
def test_chromium_without_editabletext_selects_exact_field_then_sends_one_backspace(selected):
    api = Bridge(selections=selected)
    api.focused = lambda pid: ('object', 'text', None)
    selected_ranges = iter([None, (0, 42)])
    api.selection = lambda text: next(selected_ranges)
    sent = []
    def key(codes): sent.append(codes); api.count = 0
    result = edit_focused('delete_all', bridge=lambda: api, focus=lambda env: ('window', (123, 1, 10)), send_key=key)
    assert sent == [[14]] and 'apagado' in result
    assert not any('get_text' in name for name, _ in api.calls)


def test_chromium_focus_change_after_selection_does_not_send_backspace():
    api = Bridge(); api.focused = lambda pid: ('object', 'text', None)
    api.selection = lambda text: (0, 42)
    positions = iter([('window', (123, 1, 10)), ('window', (123, 1, 10)), ('other', (124, 1, 12))])
    with pytest.raises(RuntimeError, match='foco mudou'):
        edit_focused('delete_all', bridge=lambda: api, focus=lambda env: next(positions), send_key=lambda _: pytest.fail('wrong focus'))
