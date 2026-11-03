import time
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


def test_actions_reveal_collapse_and_header_keyboard_stays_available(qapp):
    view,_=make(qapp);view.show();qapp.processEvents()
    view._animate_actions(False);wait(qapp,lambda:view.action_drawer.maximumHeight()==0)
    small=view.height()
    QApplication.sendEvent(view,QEnterEvent(QPointF(),QPointF(),QPointF()))
    wait(qapp,lambda:view.action_drawer.maximumHeight()>0 and view.drawer_animation.state()==view.drawer_animation.State.Stopped)
    assert view.height()>small
    sizes=[view.shortcut_tabs.buttons[k].size() for k in ('select_all','delete_all','prompts','copy','paste','print')]
    assert max(s.width() for s in sizes)-min(s.width() for s in sizes)<=1
    assert len({s.height() for s in sizes})==1
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
