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
    hover_events=[]
    class HoverProbe(QObject):
        def eventFilter(self,obj,event):
            if event.type() in (QEvent.Type.Enter,QEvent.Type.Leave):
                hover_events.append([type(obj).__name__,obj.objectName(),str(event.type()),
                                     obj.windowTitle() if hasattr(obj,'windowTitle') else ''])
            return False
    hover_probe=HoverProbe();app.installEventFilter(hover_probe)
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
    def pointer_click(point,backend,widget,click=True):
        binary,wayland=backend._input();assert wayland
        if not click:
            subprocess.run([binary,'mousemove','--','4','0'],env=backend.env,check=True,capture_output=True)
            app.processEvents()
        windows=native('^'+re.escape(widget.windowTitle())+'$');assert len(windows)==1
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
        # First enter the outputs' common vertical span, then cross horizontally.
        # A diagonal through the void below a short output is constrained by KWin
        # and is not a usable sample for calibrating relative input.
        # Recheck Y after crossing outputs: KWin can remap it at a scale boundary.
        for axis in (1,0,1):
            for _ in range(20):
                before=cursor();delta=desired[axis]-before[axis]
                if abs(delta)<=1:break
                amounts=[0,0];amounts[axis]=max(-200,min(200,round(delta*factors[axis])))
                subprocess.run([binary,'mousemove','--',*map(str,amounts)],env=backend.env,check=True,capture_output=True)
                time.sleep(.06);app.processEvents();after=cursor()
                moved=after[axis]-before[axis]
                if abs(moved)>1 and amounts[axis]:factors[axis]=max(.2,min(4,abs(amounts[axis]/moved)))
        assert max(abs(cursor()[i]-desired[i]) for i in range(2))<=1,(desired,cursor(),raw,origin,point)
        surface=re.search(r'window[:=]\s*(\{[0-9a-fA-F-]+\})',call('kdotool','getmouselocation'))
        assert surface and call('kdotool','getwindowpid',surface[1])==str(os.getpid()),('pointer outside owned QA window',raw,origin,point,desired,call('kdotool','getmouselocation'))
        if widget.windowTitle()!='Fôlego — widget':
            assert call('kdotool','getwindowname',surface[1])==widget.windowTitle(),'pointer outside intended owned target'
        if click:subprocess.run([binary,'click','0xC0'],env=backend.env,check=True,capture_output=True)
    def reveal(compact,backend):
        pointer_click(compact.mapToGlobal(QPoint(45,80)),backend,compact,click=False)
        wait(lambda:compact.action_drawer.maximumHeight()>0 and
             compact.drawer_animation.state()==compact.drawer_animation.State.Stopped)
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
            from folego.core.snapshot import Snapshot,MemInfo
            from folego.core.tmpfs import TmpfsVolume
            compact.show_snapshot(Snapshot(ts=time.time(),mono=time.monotonic(),mem=MemInfo(16*1024**2,6*1024**2),
                swap_used_kb=1024,swap_total_kb=8192,pressure_memory=None,pressure_io=None,pressure_cpu=None,
                load=None,apps=(),self_rss_kb=0,cpu_busy_frac=.52,temperature_c=61,temperature_sensor='demonstração',
                tmpfs=(TmpfsVolume('/qa/runtime','tmpfs',100,81,19,is_runtime=True),)))
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
                reveal(compact,backend)
                pointer_click(tabs.buttons['prompts'].mapToGlobal(tabs.buttons['prompts'].rect().center()),backend,compact)
                wait(lambda:tabs.prompt_menu is not None and tabs.prompt_menu.isVisible())
                settle=time.monotonic()+.35;wait(lambda:time.monotonic()>=settle)
                menu=tabs.prompt_menu;panel=tabs.prompt_panel
                menu.grab().save(str(root/'prompts-top.png'))
                button=panel.buttons[selected.key]
                panel.scroll.ensureWidgetVisible(button,0,8)
                settle=time.monotonic()+.35;wait(lambda:time.monotonic()>=settle)
                pointer_click(button.mapToGlobal(button.rect().center()),backend,compact,click=False)
                settle=time.monotonic()+.15;wait(lambda:time.monotonic()>=settle)
                menu.grab().save(str(root/'prompts.png'))
                pointer_click(button.mapToGlobal(button.rect().center()),backend,compact)
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
                        ' && w.caption==="Fôlego QA — atalhos padrão");if(w){w.frameGeometry={x:420,y:30,width:450,height:100};workspace.activeWindow=w;}')
                    name='folego-qa-shortcuts-'+str(os.getpid())
                    sid=call('qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.loadScript',str(script),name)
                    try:call('qdbus6','org.kde.KWin','/Scripting/Script'+sid,'org.kde.kwin.Script.run')
                    finally:call('qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.unloadScript',name)
                    target.setFocus();wait(lambda:target.isActiveWindow() and target.hasFocus())
                    settle=time.monotonic()+.35;wait(lambda:time.monotonic()>=settle)
                focus_target();target.insert('abc');assert target.text()=='123abc'
                pointer_click(target.mapToGlobal(target.rect().center()),backend,target,click=False)
                wait(lambda:compact.action_drawer.maximumHeight()==0)
                compact.grab().save(str(root/'compact-collapsed.png'))
                reveal(compact,backend)
                compact.grab().save(str(root/'compact-expanded.png'))
                records.append(dict(case='hover actions',collapsed=True,expanded=True,temperature='61 °C demo',
                                    focus_preserved=target.hasFocus()))
                for group,key in (('Edição','undo'),('Edição','redo'),('Edição','save'),('Edição','find'),
                                  ('Terminal','terminal-copy'),('Terminal','terminal-paste')):
                    focus_target()
                    tabs=compact.shortcut_tabs
                    reveal(compact,backend)
                    pointer_click(tabs.buttons['prompts'].mapToGlobal(tabs.buttons['prompts'].rect().center()),backend,compact)
                    wait(lambda:tabs.prompt_menu is not None and tabs.prompt_menu.isVisible() and tabs.controller.future is None)
                    menu=tabs.prompt_menu;panel=tabs.prompt_panel
                    assert list(panel.footer_menus)==['Janelas','Edição','Terminal','Custom']
                    submenu=panel.footer_menus[group]
                    footer=panel.footer_buttons[group]
                    pointer_click(footer.mapToGlobal(footer.rect().center()),backend,compact)
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
            (root/'hover-events.json').write_text(json.dumps(hover_events,indent=2))
            if window._compact is not None:
                c=window._compact;popup=QApplication.activePopupWidget()
                (root/'hover-failure.json').write_text(json.dumps(dict(height=c.action_drawer.maximumHeight(),
                    delay=c.drawer_delay.isActive(),under_mouse=c.underMouse(),
                    geometry=[c.x(),c.y(),c.width(),c.height()],
                    native=call('qdbus6','org.kde.KWin','/KWin','org.kde.KWin.getWindowInfo',native('^Fôlego — widget$')[0]),
                    popup=popup.windowTitle() if popup else None,
                    popup_visible=popup.isVisible() if popup else None,
                    pointer=call('kdotool','getmouselocation')),indent=2))
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
