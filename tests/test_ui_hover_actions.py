import time
import pytest
from PySide6.QtCore import QEvent
from PySide6.QtGui import QEnterEvent, QWindow
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF
from test_ui_compact import make


def wait(qapp, condition):
    end=time.monotonic()+2
    while time.monotonic()<end:
        qapp.processEvents()
        if condition():return
        time.sleep(.01)
    assert condition()


def test_actions_reveal_collapse_and_header_keyboard_stays_available(qapp, monkeypatch):
    view,_=make(qapp);view.show();qapp.processEvents()
    view._animate_actions(False);wait(qapp,lambda:view.action_drawer.maximumHeight()==0)
    small=view.height()
    QApplication.sendEvent(view,QEnterEvent(QPointF(),QPointF(),QPointF()))
    wait(qapp,lambda:view.action_drawer.maximumHeight()>0 and view.drawer_animation.state()==view.drawer_animation.State.Stopped)
    assert view.height()>small
    sizes=[view.shortcut_tabs.buttons[k].size() for k in ('select_all','delete_all','prompts','copy','paste','print')]
    assert max(s.width() for s in sizes)-min(s.width() for s in sizes)<=1
    assert len({s.height() for s in sizes})==1
    assert sizes[0].height() == 22
    delete_all = view.shortcut_tabs.buttons['delete_all']
    assert delete_all.text() == 'Apagar tudo'
    assert delete_all.fontMetrics().horizontalAdvance(delete_all.text()) + 4 <= delete_all.width()
    desktop = view.shortcut_tabs.buttons['show-desktop']
    assert desktop.isVisible() and desktop.height() == 46
    requests = []
    monkeypatch.setattr(view.shortcut_tabs.controller, 'request', lambda action: requests.append(action))
    desktop.click()
    assert requests == ['show-desktop']
    QApplication.sendEvent(view,QEvent(QEvent.Type.Leave))
    wait(qapp,lambda:view.action_drawer.maximumHeight()==0)
    assert view.shortcut_tabs.buttons['keyboard'].isVisible() and view.shortcut_tabs.top_button.isVisible()
    view.force_close()


def test_entering_another_surface_reconciles_popup_synthetic_enter(qapp):
    view,_=make(qapp);view.show();qapp.processEvents()
    QApplication.sendEvent(view,QEnterEvent(QPointF(),QPointF(),QPointF()))
    wait(qapp,lambda:view.action_drawer.maximumHeight()>0)
    other=QWindow()
    QApplication.sendEvent(other,QEnterEvent(QPointF(),QPointF(),QPointF()))
    wait(qapp,lambda:view.action_drawer.maximumHeight()==0)
    other.destroy();view.force_close()


def test_mini_reveals_a_short_horizontal_drawer_at_the_right(qapp, monkeypatch):
    from PySide6.QtTest import QTest

    view, _ = make(qapp)
    view.show_compact(desired_mode='mini')
    # Geometry assertions require the final frame, even when timer delivery is delayed.
    wait(qapp, lambda: hasattr(view, 'dock_animation'))
    view.dock_animation.setCurrentTime(view.dock_animation.duration())
    qapp.processEvents()
    wait(qapp, lambda: not view.mini_fit_timer.isActive())
    closed = view.size()
    bottom = view._screen_area().bottom()
    view.move(20, bottom + 1 - closed.height())
    assert view.action_drawer.maximumHeight() == 0
    assert not view.control_button.isVisible()
    enter = QEnterEvent(QPointF(), QPointF(), QPointF())
    QApplication.sendEvent(view, enter)
    assert view.action_drawer.maximumHeight() == 0
    QApplication.sendEvent(view.mini_actions_handle, enter)
    qapp.processEvents()
    keys = ('show-desktop', 'copy', 'paste', 'prompts')
    buttons = [view.control_button, *(view.shortcut_tabs.buttons[key] for key in keys)]
    assert all(button.isVisible() and button.height() == 24 for button in buttons)
    assert [button.x() for button in buttons] == sorted({button.x() for button in buttons})
    assert view.shortcut_tabs.width() < view.width() * 0.75
    assert view.shortcut_tabs.x() > 0 and view.width() == closed.width()
    assert view.height() > closed.height()
    assert view.geometry().bottom() <= bottom
    assert view.shortcut_tabs.buttons['delete_all'].isHidden()
    assert view.open_button.isVisible() and view.mini_drag.isVisible()
    requests = []
    monkeypatch.setattr(view.shortcut_tabs.controller, 'request', lambda *args: requests.append(args) or True)
    for key in keys[:-1]:
        view.shortcut_tabs.buttons[key].click()
    assert requests == [(key,) for key in keys[:-1]]
    view.control_button.click()
    assert view.control_menu.isVisible()
    view._collapse_actions()
    assert view.height() > closed.height()
    view.control_menu.close()
    QApplication.sendEvent(view, QEvent(QEvent.Type.Leave))
    wait(qapp, lambda: view.size() == closed)
    assert not view.control_button.isVisible()
    view.set_dock_mode('compact')
    QTest.qWait(350)
    assert view.control_button.parentWidget() is view.navigation_group
    view.force_close()


@pytest.mark.parametrize('mode', ('left', 'right', 'top'))
def test_dock_actions_reveal_on_hover_and_retract_after_leave(qapp, mode):
    from PySide6.QtCore import QRect
    from PySide6.QtTest import QTest
    view,_=make(qapp)
    view._screen_area=lambda:QRect(0,0,948,593)
    view.show_compact()
    view.set_dock_mode(mode)
    QTest.qWait(450)
    assert view._dock_mode==mode and view.action_drawer.maximumHeight()==0
    size=view.size()
    back_rect=view._handles['back'].geometry()
    QApplication.sendEvent(view,QEnterEvent(QPointF(),QPointF(),QPointF()))
    wait(qapp,lambda:view.action_drawer.maximumHeight()==view.shortcut_tabs.sizeHint().height())
    assert all(view.shortcut_tabs.buttons[key].isVisible() for key in
               ('select_all','delete_all','prompts','copy','paste','print'))
    assert view.shortcut_tabs.buttons['show-desktop'].isHidden()
    assert view.size()==size
    if mode=='top': assert view._handles['back'].geometry()==back_rect
    assert view.dock_scroll.geometry().bottom()<view.action_drawer.geometry().top()
    QApplication.sendEvent(view,QEvent(QEvent.Type.Leave))
    wait(qapp,lambda:view.action_drawer.maximumHeight()==0)
    assert view.size()==size
    if mode=='top': assert view._handles['back'].geometry()==back_rect
    assert view.keyboard_group.isVisible() and view.navigation_group.isVisible()
    view.force_close()
