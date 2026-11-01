"""Explicit whole-field editing via native AT-SPI, without text or clipboard reads.

Only the focused editable object of the compositor's current local application
can be changed. No Ctrl+A/Backspace fallback can accidentally affect files,
terminal jobs, or another application after a focus change.
"""
import ctypes as C
from ctypes.util import find_library
import os
import shutil
import subprocess
import time

from ..core.agent_deliveries import identity


class Atspi:
    def __init__(self):
        self.owned = []
        try:
            self.lib = C.CDLL(find_library('atspi') or 'libatspi.so.0')
            self.glib = C.CDLL(find_library('glib-2.0') or 'libglib-2.0.so.0')
            self.objects = C.CDLL(find_library('gobject-2.0') or 'libgobject-2.0.so.0')
        except OSError:
            raise RuntimeError('Edição indisponível: acessibilidade AT-SPI não encontrada') from None
        P, I, E = C.c_void_p, C.c_int, C.POINTER(C.c_void_p)
        signatures = {
            'init': (I, []), 'set_timeout': (None, [I, I]),
            'get_desktop': (P, [I]), 'accessible_clear_cache': (None, [P]),
            'accessible_get_child_count': (I, [P, E]),
            'accessible_get_child_at_index': (P, [P, I, E]),
            'accessible_get_process_id': (C.c_uint, [P, E]),
            'accessible_get_role_name': (P, [P, E]),
            'accessible_get_state_set': (P, [P]),
            'state_set_contains': (I, [P, I]),
            'accessible_get_text_iface': (P, [P]),
            'accessible_get_editable_text_iface': (P, [P]),
            'text_get_character_count': (I, [P, E]),
            'text_get_n_selections': (I, [P, E]),
            'text_add_selection': (I, [P, I, I, E]),
            'text_set_selection': (I, [P, I, I, I, E]),
            'editable_text_delete_text': (I, [P, I, I, E]),
        }
        for name, (result, args) in signatures.items():
            fn = getattr(self.lib, 'atspi_' + name)
            fn.restype, fn.argtypes = result, args
        self.objects.g_object_unref.argtypes = [P]
        self.glib.g_error_free.argtypes = [P]
        self.glib.g_free.argtypes = [P]
        if self.lib.atspi_init() not in (0, 1):
            raise RuntimeError('Acessibilidade indisponível; texto preservado')
        self.lib.atspi_set_timeout(250, 250)

    def call(self, name, *args, error=True, own=False):
        problem = C.c_void_p()
        fn = getattr(self.lib, 'atspi_' + name)
        value = fn(*args, C.byref(problem)) if error else fn(*args)
        if problem.value:
            self.glib.g_error_free(problem)
            raise RuntimeError('O aplicativo não confirmou a edição; não houve repetição')
        if own and value: self.owned.append(value)
        return value

    def states(self, obj):
        self.call('accessible_clear_cache', obj, error=False)
        states = self.call('accessible_get_state_set', obj, error=False, own=True)
        if not states: return False
        # Stable AT-SPI 2 enums: editable, enabled, focused, showing.
        return all(self.call('state_set_contains', states, state, error=False) for state in (7, 8, 12, 25))

    def focused(self, pid):
        desktop = self.call('get_desktop', 0, error=False, own=True)
        if not desktop: raise RuntimeError('Desktop acessível não encontrado; texto preservado')
        deadline = time.monotonic() + 3
        apps = self.call('accessible_get_child_count', desktop)
        if not 0 <= apps <= 128: raise RuntimeError('Inventário de acessibilidade não verificado')
        target = None
        for i in range(apps):
            if time.monotonic() > deadline: break
            app = self.call('accessible_get_child_at_index', desktop, i, own=True)
            if not app: continue
            if self.call('accessible_get_process_id', app) == pid:
                target = app
                break
        if not target: raise RuntimeError('O aplicativo não expõe um campo editável; clique no campo de texto')
        queue = [target]
        for obj in queue:
            if not obj: continue
            if time.monotonic() > deadline: break
            if self.states(obj):
                ptr = self.call('accessible_get_role_name', obj)
                try: role = C.string_at(ptr).decode() if ptr else ''
                finally:
                    if ptr: self.glib.g_free(ptr)
                if role == 'terminal': raise RuntimeError('O terminal não expõe um campo de texto editável')
                text = self.call('accessible_get_text_iface', obj, error=False, own=True)
                editable = self.call('accessible_get_editable_text_iface', obj, error=False, own=True)
                if text and editable: return obj, text, editable
            count = self.call('accessible_get_child_count', obj)
            if count < 0 or len(queue) + count > 1024: break
            queue.extend(self.call('accessible_get_child_at_index', obj, i, own=True) for i in range(count))
        raise RuntimeError('Clique no campo de texto editável e tente novamente; nada foi apagado')

    def close(self):
        for obj in reversed(self.owned): self.objects.g_object_unref(obj)
        self.owned.clear()


def foreground(env):
    binary = shutil.which('kdotool' if env.get('XDG_SESSION_TYPE') == 'wayland' else 'xdotool')
    if not binary: raise RuntimeError('Não foi possível verificar o aplicativo em foco')
    def call(*args):
        result = subprocess.run([binary, *args], env=env, capture_output=True, text=True, timeout=2)
        if result.returncode: raise RuntimeError('Foco não confirmado; nenhuma edição enviada')
        return result.stdout.strip()
    window = call('getactivewindow')
    pid = call('getwindowpid', window)
    owner = identity(int(pid)) if pid.isdigit() else None
    if not owner: raise RuntimeError('Aplicativo em foco sem proprietário local confirmado')
    return window, owner


def edit_focused(action, *, env=None, bridge=Atspi, focus=foreground):
    if action not in ('select_all', 'delete_all'): raise ValueError('edição desconhecida')
    env = dict(os.environ if env is None else env)
    before = focus(env)
    api = bridge()
    try:
        obj, text, editable = api.focused(before[1][0])
        count = api.call('text_get_character_count', text)
        if not 0 <= count <= 1_000_000: raise RuntimeError('Tamanho do campo não verificado; texto preservado')
        selections = api.call('text_get_n_selections', text) if action == 'select_all' else 0
        if focus(env) != before or not api.states(obj):
            raise RuntimeError('O foco mudou; nenhuma edição enviada')
        if count == 0: return 'O campo de texto já está vazio'
        if api.call('text_get_character_count', text) != count:
            raise RuntimeError('O campo mudou; nenhuma edição enviada')
        if action == 'select_all':
            ok = api.call('text_set_selection', text, 0, 0, count) if selections else api.call('text_add_selection', text, 0, count)
        else:
            ok = api.call('editable_text_delete_text', editable, 0, count)
        if not ok: raise RuntimeError('O campo não confirmou a edição; não houve repetição')
        if action == 'delete_all' and api.call('text_get_character_count', text) != 0:
            return 'Edição enviada; o campo mudou novamente. Confira o texto, sem repetição automática'
        return 'Todo o texto do campo selecionado' if action == 'select_all' else 'Todo o texto do campo apagado'
    finally:
        api.close()
