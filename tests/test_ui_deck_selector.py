import pytest
pytest.importorskip('PySide6')
from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QEnterEvent
from PySide6.QtTest import QTest
from folego.ui.deck_selector import DeckButton, DeckPicker


class Backend:
    def __init__(self):
        self.choices = []

    def perform(self, action, value):
        if action == 'select':
            self.choices.append(value)
        return {'choice': self.choices[-1] if self.choices else 'steam', 'message': 'observação'}

    def close(self):
        pass


@pytest.mark.parametrize('width', [480, 948])
def test_map_preview_and_options_never_overlap(qapp, width):
    backend = Backend()
    button = DeckButton(backend=backend)
    button.show()
    picker = DeckPicker(button, QRect(0, 0, width, 580), button.controller)
    picker.show()
    picker.loaded(backend.perform('status', None))
    picker.busy(False)
    option = picker.options['phasezero']
    option.setFocus()
    qapp.sendEvent(option, QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    qapp.processEvents()
    assert picker.preview == 'phasezero' and not backend.choices
    from PySide6.QtCore import QPoint
    bounds = QRect(option.mapTo(picker, QPoint()), option.size())
    assert not bounds.intersects(picker.scroll.geometry())
    assert picker.scroll.widget().accessibleName().endswith('PhaseZero')
    picker.apply.click()
    QTest.qWait(70)
    assert backend.choices == ['phasezero']
    QTest.keyClick(picker, Qt.Key.Key_Escape)
    button.close()
