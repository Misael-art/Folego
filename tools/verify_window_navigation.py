#!/usr/bin/env python3
"""Owned KDE/Wayland navigation proof, without credentials or resource effects."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--standard-shortcuts',action='store_true',help='Native menu clicks into an owned text field')
    parser.add_argument('--prompt-key',help='Verify native prompt selection with clipboard intercepted in memory')
    args=parser.parse_args()
    root=args.state.resolve();root.mkdir(mode=0o700,parents=True,exist_ok=False)
    for key,folder in (('HOME','home'),('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),
                       ('XDG_STATE_HOME','state'),('XDG_CACHE_HOME','cache'),('TMPDIR','tmp')):
        p=root/folder;p.mkdir(mode=0o700);os.environ[key]=str(p)
    for key in ('CODEX_HOME','CLAUDE_CONFIG_DIR','GROK_HOME'):os.environ.pop(key,None)
    os.environ['PULSE_SERVER']='unix:'+str(root/'no-audio')
    from PySide6.QtCore import QTimer,Qt,QCoreApplication,QEvent,QObject,Slot,ClassInfo,QPoint
    from PySide6.QtDBus import QDBusConnection
    from PySide6.QtWidgets import QApplication,QLineEdit
    from PySide6.QtGui import QShortcut,QKeySequence
    from PySide6.QtTest import QTest
    from folego.ui.main_window import MainWindow
    from folego.ui.workers import Poller
    from folego.ui.theme import apply_theme
    app=QApplication([]);app.setApplicationName('folego');app.setDesktopFileName('folego')
    app.setQuitOnLastWindowClosed(False);apply_theme(app)
    window=MainWindow(startup_defaults=False)
    window.ai_monitor.poller._collect=lambda:[]
    window.ai_monitor.delivery_poller._collect=lambda:[]
    window._poller=Poller(lambda:None,offload=True,parent=window)
    window._poller.start()
    errors=[];records=[];menu_events=[];target=None
    measured={}
    @ClassInfo(**{'D-Bus Interface':'org.folego.QANavigation'})
    class Geometry(QObject):
        @Slot(str)
        def report(self,raw): measured.update(json.loads(raw))
    geometry=Geometry();bus=QDBusConnection.sessionBus()
    service='org.folego.QANavigation.p'+str(os.getpid())
    assert bus.registerService(service)
    assert bus.registerObject('/geometry',geometry,QDBusConnection.RegisterOption.ExportAllSlots)
    def wait(predicate):
        end=time.monotonic()+8
        while time.monotonic()<end:
            app.processEvents()
            if predicate():return
            time.sleep(.02)
        raise AssertionError('Owned navigation QA deadline')
    def call(*args):return subprocess.check_output(args,text=True,timeout=3).strip()
    def native(caption):
        result=subprocess.run(['kdotool','search','--all','--pid',str(os.getpid()),'--name',caption],capture_output=True,text=True,timeout=3)
        return result.stdout.strip().splitlines()
    def pointer_click(point,backend,widget):
        binary,wayland=backend._input();assert wayland
        windows=native('^Fôlego — widget$');assert len(windows)==1
        raw=call('qdbus6','org.kde.KWin','/KWin','org.kde.KWin.getWindowInfo',windows[0])
        x=float(re.search(r'(?m)^x:\s*([-0-9.]+)',raw)[1]);y=float(re.search(r'(?m)^y:\s*([-0-9.]+)',raw)[1])
        origin=widget.mapToGlobal(QPoint(0,0))
        desired=(point.x()+x-origin.x(),point.y()+y-origin.y())
        call('kdotool','windowraise',windows[0])
        factors=[widget.devicePixelRatioF()]*2
        def cursor():
            raw=call('kdotool','getmouselocation')
            found=re.search(r'x[:=]\s*([-0-9.]+).*y[:=]\s*([-0-9.]+)',raw);assert found,raw
            return float(found[1]),float(found[2])
        for _ in range(12):
            before=cursor();delta=[desired[i]-before[i] for i in range(2)]
            if max(map(abs,delta))<=1:break
            amounts=[round(delta[i]*factors[i]) for i in range(2)]
            subprocess.run([binary,'mousemove','--',*map(str,amounts)],env=backend.env,check=True,capture_output=True)
            time.sleep(.06);app.processEvents();after=cursor()
            for i in range(2):
                moved=after[i]-before[i]
                if abs(moved)>1 and amounts[i]:factors[i]=max(.2,min(4,abs(amounts[i]/moved)))
        assert max(abs(cursor()[i]-desired[i]) for i in range(2))<=1,(desired,cursor(),raw,origin,point)
        surface=re.search(r'window[:=]\s*(\{[0-9a-fA-F-]+\})',call('kdotool','getmouselocation'))
        assert surface and call('kdotool','getwindowpid',surface[1])==str(os.getpid()),'pointer outside owned QA window'
        subprocess.run([binary,'click','0xC0'],env=backend.env,check=True,capture_output=True)
    def scenario():
        nonlocal target
        try:
            window.show()
            wait(lambda:window.windowHandle().isExposed() and len(native('^Fôlego ·'))==1)
            script=root/'read-owned-geometry.js'
            script.write_text('const w=workspace.windowList().find(w=>w.pid==='+str(os.getpid())+' && w.caption.startsWith("Fôlego ·"));if(w){const f=w.frameGeometry,c=w.clientGeometry;callDBus('+json.dumps(service)+',"/geometry","org.folego.QANavigation","report",JSON.stringify({frame:[f.x,f.y,f.width,f.height],client:[c.x,c.y,c.width,c.height]}));}')
            name='folego-qa-navigation-'+str(os.getpid())
            sid=call('qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.loadScript',str(script),name)
            try:
                call('qdbus6','org.kde.KWin','/Scripting/Script'+sid,'org.kde.kwin.Script.run')
                wait(lambda:bool(measured))
            finally:call('qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.unloadScript',name)
            assert all(abs(f-c)<=1 for f,c in zip(measured['frame'],measured['client'])),measured
            assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
            assert window.back_button.isVisible()
            window.tabs.setCurrentWidget(window.options);app.processEvents()
            window.grab().save(str(root/'central.png'))
            area=window.screen().availableGeometry()
            records.append(dict(case='frameless central',native_frame_equals_client=True,
                                compositor_geometry=measured,
                                client_size=[window.width(),window.height()],available=[area.width(),area.height()]))
            QTest.mouseClick(window.back_button,Qt.MouseButton.LeftButton)
            wait(lambda:not window.isVisible() and window._compact.isVisible() and window._compact.windowHandle().isExposed())
            assert not window._poller._stop.is_set()
            compact=window._compact
            assert not hasattr(compact,'hide_button') and not hasattr(compact,'quit_button')
            compact.grab().save(str(root/'compact.png'))
            records.append(dict(case='back to widget without tray',workers_active=True))
            QTest.mouseClick(compact.open_button,Qt.MouseButton.LeftButton)
            wait(lambda:window.isVisible() and window.windowHandle().isExposed() and not compact.isVisible())
            assert window.tabs.currentWidget() is window.options and not window._poller._stop.is_set()
            records.append(dict(case='return to previous central tab',tab='opções',workers_active=True))
            QTest.mouseClick(window.back_button,Qt.MouseButton.LeftButton)
            wait(lambda:compact.isVisible() and compact.windowHandle().isExposed() and not window.isVisible())
            backend=compact.shortcut_tabs.controller.backend
            if args.prompt_key or args.standard_shortcuts:
                script=root/'place-owned-widget.js'
                script.write_text('const w=workspace.windowList().find(w=>w.pid==='+str(os.getpid())+
                    ' && w.caption==="Fôlego — widget");if(w){const g=w.frameGeometry;w.frameGeometry={x:20,y:120,width:g.width,height:g.height};}')
                name='folego-qa-shortcuts-place-'+str(os.getpid())
                sid=call('qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.loadScript',str(script),name)
                try:call('qdbus6','org.kde.KWin','/Scripting/Script'+sid,'org.kde.kwin.Script.run')
                finally:call('qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.unloadScript',name)
                settle=time.monotonic()+.35;wait(lambda:time.monotonic()>=settle)
            if args.prompt_key:
                from folego.core.development_prompts import PROMPTS,text
                selected=next(p for p in PROMPTS if p.key==args.prompt_key)
                tabs=compact.shortcut_tabs;copied=[]
                tabs._copy_text=copied.append  # no physical clipboard fixture
                pointer_click(tabs.buttons['prompts'].mapToGlobal(tabs.buttons['prompts'].rect().center()),backend,compact)
                wait(lambda:tabs.prompt_menu is not None and tabs.prompt_menu.isVisible())
                settle=time.monotonic()+.35;wait(lambda:time.monotonic()>=settle)
                menu=tabs.prompt_menu
                action=next(a for a in menu.actions() if a.text()==selected.title)
                menu.grab().save(str(root/'prompts.png'))
                pointer_click(menu.mapToGlobal(menu.actionGeometry(action).center()),backend,compact)
                wait(lambda:copied==[text(selected.key)] and tabs.prompt_menu is None)
                records.append(dict(case='native prompt selection',key=selected.key,clipboard='intercepted in memory'))
            if args.standard_shortcuts:
                target=QLineEdit('123');target.setWindowTitle('Fôlego QA — atalhos padrão')
                target.resize(450,80);target.show()
                observed=[];bindings=[]
                for key,chord in (('save','Ctrl+S'),('find','Ctrl+F'),
                                  ('terminal-copy','Ctrl+Shift+C'),('terminal-paste','Ctrl+Shift+V')):
                    binding=QShortcut(QKeySequence(chord),target)
                    binding.activated.connect(lambda identity=key:observed.append(identity));bindings.append(binding)
                wait(lambda:target.windowHandle().isExposed() and len(native('^Fôlego QA — atalhos padrão$'))==1)
                def focus_target():
                    script=root/'focus-owned-text.js'
                    script.write_text('const w=workspace.windowList().find(w=>w.pid==='+str(os.getpid())+
                        ' && w.caption==="Fôlego QA — atalhos padrão");if(w)workspace.activeWindow=w;')
                    name='folego-qa-shortcuts-'+str(os.getpid())
                    sid=call('qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.loadScript',str(script),name)
                    try:call('qdbus6','org.kde.KWin','/Scripting/Script'+sid,'org.kde.kwin.Script.run')
                    finally:call('qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.unloadScript',name)
                    target.setFocus();wait(lambda:target.isActiveWindow() and target.hasFocus())
                focus_target();target.insert('abc');assert target.text()=='123abc'
                for group,key in (('Edição','undo'),('Edição','redo'),('Edição','save'),('Edição','find'),
                                  ('Terminal','terminal-copy'),('Terminal','terminal-paste')):
                    focus_target()
                    tabs=compact.shortcut_tabs
                    pointer_click(tabs.buttons['prompts'].mapToGlobal(tabs.buttons['prompts'].rect().center()),backend,compact)
                    wait(lambda:tabs.prompt_menu is not None and tabs.prompt_menu.isVisible() and tabs.controller.future is None)
                    menu=tabs.prompt_menu
                    assert [a.text() for a in menu.actions() if a.menu()]==['Janelas','Edição','Terminal','Custom']
                    submenu=next(a.menu() for a in menu.actions() if a.text()==group)
                    menu.setActiveAction(submenu.menuAction())
                    submenu.popup(menu.mapToGlobal(menu.actionGeometry(submenu.menuAction()).topRight()))
                    wait(lambda:submenu.isVisible() and submenu.windowHandle().isExposed())
                    if key in ('undo','terminal-copy'):
                        settle=time.monotonic()+.35;wait(lambda:time.monotonic()>=settle)
                        submenu.grab().save(str(root/(group+'.png')))
                    action=next(a for a in submenu.actions() if a.data()==key)
                    pointer_click(submenu.mapToGlobal(submenu.actionGeometry(action).center()),backend,compact)
                    wait(lambda:tabs.controller.future is None and tabs.prompt_menu is None)
                    if key=='undo':wait(lambda:target.text()=='123')
                    elif key=='redo':wait(lambda:target.text()=='123abc')
                    else:wait(lambda:key in observed)
                    assert target.hasFocus() and target.isActiveWindow()
                    records.append(dict(case='native standard macro',macro=key,owned_target=True,
                                        result='text edit' if key in ('undo','redo') else 'native key delivery; no file or clipboard effect'))
                target.close()
            compact.control_button.pressed.connect(lambda:menu_events.append('pressed'))
            compact.control_menu.aboutToShow.connect(lambda:menu_events.append('show'))
            compact.control_menu.aboutToHide.connect(lambda:menu_events.append('hide'))
            pointer_click(compact.control_button.mapToGlobal(compact.control_button.rect().center()),backend,compact)
            wait(compact.control_menu.isVisible)
            compact.control_menu.grab().save(str(root/'controls.png'))
            point=compact.control_menu.mapToGlobal(compact.control_menu.actionGeometry(compact.quit_action).center())
            pointer_click(point,backend,compact)
            wait(lambda:window._quitting)
            assert window._poller._stop.is_set() and window.ai_monitor.poller._stop.is_set()
            records.append(dict(case='explicit exit in controls',workers_stopped=True))
        except Exception as exc:
            import traceback
            (root/'failure.txt').write_text(traceback.format_exc())
            if args.prompt_key and 'copied' in locals():
                import hashlib
                (root/'prompt-failure.json').write_text(json.dumps(dict(
                    received=[hashlib.sha256(value.encode()).hexdigest() for value in copied],
                    expected=hashlib.sha256(text(args.prompt_key).encode()).hexdigest(),
                    menu_open=compact.shortcut_tabs.prompt_menu is not None),indent=2))
            errors.append(repr(exc)+' menu events: '+repr(menu_events));window.quit();app.exit(1)
    QTimer.singleShot(0,scenario)
    QTimer.singleShot(45000,lambda:(errors.append('watchdog'),window.quit(),app.exit(2)))
    code=app.exec()
    bus.unregisterObject('/geometry');bus.unregisterService(service)
    result=dict(passed=not errors and code==0,platform=app.platformName(),cases=records,errors=errors,
                scope='owned Qt windows and compositor metadata; private HOME/XDG/Pulse; no user text or resource effects')
    (root/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    window.quit()
    if window._compact is not None:
        backend=window._compact.shortcut_tabs.controller.backend
        wait(lambda:backend.daemon is None)
    if target is not None:target.close()
    for widget in list(app.topLevelWidgets()):widget.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
    assert result['passed']


if __name__=='__main__':main()
