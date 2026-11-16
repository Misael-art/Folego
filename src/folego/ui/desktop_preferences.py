"""Desktop options share the existing Fôlego QSettings authority."""
from PySide6.QtCore import QSettings

SHOW_IN_CAPTURE = 'capture/show_widget'
SOUNDS = 'alerts/enabled'
RAISE_VOLUME = 'alerts/raise_volume'
STARTUP_VIEW = 'widget/startup_view'
WIDGET_VIEWS = (
    ('mini', 'Mini horizontal'),
    ('compact', 'Widget flutuante'),
    ('left', 'Lateral esquerda'),
    ('right', 'Lateral direita'),
    ('top', 'Barra superior'),
)
STARTUP_VIEWS = (('central', 'Central do Fôlego'), *WIDGET_VIEWS)


def startup_view():
    value = QSettings('folego', 'folego').value(STARTUP_VIEW, 'central')
    return value if isinstance(value, str) and value in dict(STARTUP_VIEWS) else 'central'


def set_startup_view(mode):
    if mode not in dict(STARTUP_VIEWS):
        raise ValueError('Modo de abertura desconhecido')
    _save(STARTUP_VIEW, mode)


def enabled(key, store=None):
    value = (store or QSettings('folego', 'folego')).value(key, True)
    if type(value) is bool: return value
    if value == 'true': return True
    if value == 'false': return False
    raise ValueError('Preferência do desktop desconhecida; confira a aba opções')


def set_enabled(key, value):
    _save(key, bool(value))


def _save(key, value):
    store = QSettings('folego', 'folego')
    store.setValue(key, value)
    store.sync()
    if store.status() != QSettings.Status.NoError:
        raise RuntimeError('Preferência não foi salva; confira as permissões da configuração')
