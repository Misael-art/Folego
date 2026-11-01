"""Desktop options share the existing Fôlego QSettings authority."""
from PySide6.QtCore import QSettings

SHOW_IN_CAPTURE = 'capture/show_widget'
SOUNDS = 'alerts/enabled'
RAISE_VOLUME = 'alerts/raise_volume'


def enabled(key, store=None):
    value = (store or QSettings('folego', 'folego')).value(key, True)
    if type(value) is bool: return value
    if value == 'true': return True
    if value == 'false': return False
    raise ValueError('Preferência do desktop desconhecida; confira a aba opções')


def set_enabled(key, value):
    store = QSettings('folego', 'folego')
    store.setValue(key, bool(value)); store.sync()
    if store.status() != QSettings.Status.NoError:
        raise RuntimeError('Preferência não foi salva; confira as permissões da configuração')
