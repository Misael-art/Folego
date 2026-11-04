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
    parser.add_argument('--console-themes',action='store_true',help='Select all console themes in owned mapped Qt windows')
    parser.add_argument('--background-transparency',action='store_true',help='Verify alpha at 0/50/100 percent in light/dark themes')
    parser.add_argument('--transparency-theme',choices=('snes-us','ps2'),help='Run one transparency palette within the existing QA time budget')
    parser.add_argument('--ai-quota-rings',action='store_true',help='Verify quota rings, animations and account gestures with synthetic observations')
    parser.add_argument('--dock-modes',action='store_true',help='Verify owned widget placement at both sides and top')
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
            if args.prompt_key or args.standard_shortcuts or args.console_themes or args.background_transparency or args.ai_quota_rings or args.dock_modes:
                script=root/'place-owned-widget.js'
                script.write_text('const w=workspace.windowList().find(w=>w.pid==='+str(os.getpid())+
                    ' && w.caption==="Fôlego — widget");if(w){const g=w.frameGeometry;w.frameGeometry={x:20,y:120,width:g.width,height:g.height};}')
                name='folego-qa-shortcuts-place-'+str(os.getpid())
                sid=call('qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.loadScript',str(script),name)
                try:call('qdbus6','org.kde.KWin','/Scripting/Script'+sid,'org.kde.kwin.Script.run')
                finally:call('qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.unloadScript',name)
                settle=time.monotonic()+.35;wait(lambda:time.monotonic()>=settle)
            if args.dock_modes:
                from folego.ui.compact import dock_geometry
                from folego.core import ai_sessions as ai
                window.ai_monitor.pause()
                wait(lambda: not window.ai_monitor.poller._inflight)
                now=time.time()
                items=[]
                for provider,remaining in (('codex',90),('web',None),('claude',69),('grok',None)):
                    item=ai.unknown(provider,label='Conta QA')
                    item.update(account_id=provider+'-dock-qa',default=True)
                    if remaining is not None:
                        item.update(observed_at=now,windows=[ai.quota_window('Sessão QA',100-remaining,now+3600,now)])
                    items.append(item)
                full_items=[]
                for provider,remaining in (('codex',90),('web',70),('claude',50),('grok',30)):
                    item=ai.unknown(provider,label='Conta QA')
                    item.update(account_id=provider+'-dock-full-qa',default=True,observed_at=now,
                                windows=[ai.quota_window('Sessão QA',100-remaining,now+3600,now)])
                    full_items.append(item)
                compact.ai_strip.set_items(items)
                compact.adjustSize();app.processEvents()
                def compositor_rect():
                    own=native('^Fôlego — widget$');assert len(own)==1
                    raw=call('kdotool','getwindowgeometry',own[0])
                    match=re.search(r'Position:\s*([-0-9.]+),([-0-9.]+)\s+Geometry:\s*([-0-9.]+)x([-0-9.]+)',raw)
                    assert match,raw
                    return tuple(round(float(value)) for value in match.groups())
                compact_origin=compositor_rect()
                for mode in ('right','left','top'):
                    if mode == 'left':apply_theme(app,'ps2')
                    handle=compact._handles[mode]
                    pointer_click(handle.mapToGlobal(handle.rect().center()),backend,compact)
                    wait(lambda:compact._dock_mode==mode and compact._dock_pending is None)
                    dock_target=dock_geometry(mode,compact.screen().availableGeometry())
                    actual=compositor_rect()
                    assert all(abs(a-b)<=1 for a,b in zip(actual,(dock_target.x(),dock_target.y(),dock_target.width(),dock_target.height()))),(mode,actual,dock_target)
                    compact.ai_strip.set_items(items)
                    assert compact.ai_strip.visible_providers == {'codex','claude'},(mode,compact.ai_strip.visible_providers)
                    wait(lambda: all(compact.ai_strip.arrival_animations[p].state()==
                                     compact.ai_strip.arrival_animations[p].State.Stopped
                                     for p in ('codex','claude')))
                    quota_positions=[(provider,compact.ai_strip.columns[provider].isVisible(),
                                      compact.ai_strip.columns[provider].mapTo(compact,QPoint(0,0)).y(),
                                      compact.ai_strip.columns[provider].height()) for provider in ('codex','claude')]
                    assert all(visible and 0<=y<compact.height() for _,visible,y,_ in quota_positions),(mode,quota_positions,compact.ai_strip.geometry().getRect(),compact.card.sizeHint().height())
                    if mode in ('left','right'):
                        assert all(y+height<=compact.dock_scroll.viewport().height()
                                   for _,_,y,height in quota_positions),(mode,quota_positions,compact.dock_scroll.viewport().height())
                        assert not compact.dock_scroll.verticalScrollBar().isVisible()
                    records.append(dict(case='quota positions',mode=mode,positions=quota_positions,
                                        strip=compact.ai_strip.mapTo(compact,QPoint(0,0)).y(),
                                        strip_size=[compact.ai_strip.width(),compact.ai_strip.height()],
                                        viewport_height=compact.dock_scroll.viewport().height()))
                    actions=[compact.shortcut_tabs.buttons[key] for key in ('select_all','delete_all','prompts','copy','paste','print')]
                    centers=[button.mapTo(compact,button.rect().center()) for button in actions]
                    assert all(button.isVisible() and 0<=center.x()<compact.width() and 0<=center.y()<compact.height()
                               for button,center in zip(actions,centers)),(mode,[(p.x(),p.y()) for p in centers])
                    if mode in ('left','right'):
                        assert compact.width()<=128 and all(centers[i].y()<centers[i+1].y() for i in range(5))
                        assert all(abs(center.x()-compact.width()/2)<17 for center in centers)
                        assert compact.gauge.width()>compact.ai_strip.buttons['codex'].iconSize().width()
                        assert compact._handles['back'].x()==(0 if mode=='left' else compact.width()-16)
                    else:
                        assert all(abs(centers[i].y()-centers[0].y())<3 for i in range(1,6))
                    image=compact.grab().toImage()
                    assert all(image.pixelColor(x,y).alpha()<32 for x,y in
                               ((0,0),(image.width()-1,0),(0,image.height()-1),
                                (image.width()-1,image.height()-1))),(mode,'square image corners')
                    image.save(str(root/('dock-'+mode+'.png')))
                    compact.ai_strip.grab().save(str(root/('dock-'+mode+'-quotas.png')))
                    records.append(dict(case='native dock placement',mode=mode,geometry=actual,
                                        available=list((compact.screen().availableGeometry().x(),compact.screen().availableGeometry().y(),
                                                        compact.screen().availableGeometry().width(),compact.screen().availableGeometry().height()))))
                    compact.ai_strip.set_deliveries([dict(provider=p,count=1,pending=[]) for p in ai.NAMES])
                    compact.ai_strip.set_items(full_items)
                    wait(lambda:compact.ai_strip.visible_providers==set(ai.NAMES))
                    wait(lambda:all(animation.state()==animation.State.Stopped for animation in
                                    compact.ai_strip.arrival_animations.values()))
                    scroll=compact.dock_scroll.verticalScrollBar()
                    scroll.setValue(scroll.maximum());app.processEvents()
                    last=compact.ai_strip.columns['grok']
                    last_y=last.mapTo(compact.dock_scroll.viewport(),QPoint(0,0)).y()
                    assert 0<=last_y and last_y+last.height()<=compact.dock_scroll.viewport().height(),(mode,last_y,last.height(),compact.dock_scroll.viewport().height(),scroll.maximum())
                    assert compact.dock_scroll.geometry().bottom()<compact.action_drawer.geometry().top()
                    compact.grab().save(str(root/('dock-'+mode+'-scrolled.png')))
                    records.append(dict(case='all quotas reachable',mode=mode,scroll_max=scroll.maximum(),
                                        last_quota_y=last_y,actions_top=compact.action_drawer.y()))
                    compact.ai_strip.set_deliveries([])
                    compact.ai_strip.set_items(items)
                    scroll.setValue(0);app.processEvents()
                    back=compact._handles['back']
                    assert back.geometry().bottom()<compact.action_drawer.y(),(mode,back.geometry().getRect(),compact.action_drawer.y())
                    back.hovered=True;back.update();app.processEvents()
                    compact.grab().save(str(root/('dock-'+mode+'-grip.png')))
                    pointer_click(back.mapToGlobal(back.rect().center()),backend,compact)
                    wait(lambda:compact._dock_mode=='compact' and compact._dock_pending is None)
                    assert compact.width()==280
                    returned=compositor_rect()
                    assert all(abs(a-b)<=1 for a,b in zip(returned[:3],compact_origin[:3])),(mode,returned,compact_origin)
                    assert returned[3]>=compact.card.sizeHint().height() and compact.action_drawer.maximumHeight()==0,(mode,returned,compact.card.sizeHint().height())
                compact.grab().save(str(root/'dock-return.png'))
                records.append(dict(case='native dock return',geometry=compositor_rect()))
                apply_theme(app,'snes-us')
            if args.ai_quota_rings:
                from folego.core import ai_sessions as ai
                from folego.ui.theme import TOKENS
                monitor=window.ai_monitor;monitor.pause()
                def drained():
                    monitor.poller.drain();monitor.delivery_poller.drain()
                    return not monitor.poller._inflight and not monitor.delivery_poller._inflight
                wait(drained)
                strip=compact.ai_strip;now=time.time();items=[]
                for provider,remaining in (('codex',31),('web',None),('claude',8),('grok',None)):
                    item=ai.unknown(provider,label='Conta QA')
                    item.update(account_id=provider+'-qa',default=True)
                    if remaining is not None:
                        item.update(observed_at=now,windows=[ai.quota_window('Sessão QA',100-remaining,now+3600,now)])
                    if provider=='codex':item['reset_credits']=dict(available=2,observed_at=now)
                    items.append(item)
                strip.set_items(items)
                strip.set_deliveries([dict(provider=p,count=2 if p=='codex' else 0,pending=[]) for p in ai.NAMES])
                requests=[];original_request=strip.opener.request
                strip.opener.request=lambda *values:requests.append(values)
                for key,transparency in (('snes-us',0),('ps2',0),('ps2',100)):
                    apply_theme(app,key,transparency=transparency)
                    settle=time.monotonic()+.2;wait(lambda:time.monotonic()>=settle)
                    prefix=key+'-'+str(transparency)
                    compact.grab().save(str(root/(prefix+'-rings-compact.png')))
                    strip.grab().save(str(root/(prefix+'-rings.png')))
                    assert [b.remaining for b in strip.buttons.values()]==[31,None,8,None]
                    assert [p for p in ai.NAMES if strip.columns[p].isVisible()]==['codex','claude']
                    assert all(b.width()>=b.sizeHint().width() for p,b in strip.buttons.items()
                               if strip.columns[p].isVisible())
                    records.append(dict(case='quota rings',theme=key,transparency=transparency,
                                        remaining=[31,None,8,None],width=compact.width()))
                apply_theme(app,'ps2',transparency=0)
                button=strip.buttons['codex']
                wait(lambda:button.halo>.9)
                strip.grab().save(str(root/'pulse-bright.png'))
                wait(lambda:button.halo<.1)
                strip.grab().save(str(root/'pulse-dim.png'))
                items[0]['windows'][0]['remaining']=68;strip.render()
                wait(lambda:31<button.displayed<68)
                strip.grab().save(str(root/'transition.png'))
                wait(lambda:button.displayed==68)
                # Hover and click still target the account represented by the visible ring.
                pointer_click(button.mapToGlobal(button.rect().center()),backend,compact,click=False)
                wait(lambda:strip.account_menu is not None and strip.account_menu.isVisible())
                assert strip.account_panel.selected=='codex-qa'
                strip.account_menu.grab().save(str(root/'rings-accounts.png'))
                strip.account_menu.close();app.processEvents()
                binary,wayland=backend._input();assert wayland
                subprocess.run([binary,'click','0xC0'],env=backend.env,check=True,capture_output=True)
                wait(lambda:bool(requests))
                assert requests==[('agent-open',('codex',[],'codex-qa'))],requests
                QTest.mouseClick(strip.reset_badges['codex'],Qt.MouseButton.LeftButton)
                wait(lambda:strip.account_menu is not None and strip.account_menu.isVisible())
                assert strip.account_panel.selected=='codex-qa'
                strip.account_menu.close();app.processEvents()
                items[0]['windows'][0]['resets_at']=now-1;strip.render()
                assert button.remaining is None and button.transition.state()==button.transition.State.Stopped
                assert not strip.columns['codex'].isVisible()
                strip.grab().save(str(root/'expired.png'))
                strip.details('codex',anchor=compact.control_button)
                wait(lambda:strip.account_menu is not None and strip.account_menu.isVisible())
                assert strip.account_panel.selected=='codex-qa'
                strip.account_menu.close();app.processEvents()
                items[0]['windows'][0]['resets_at']=now+3600
                items[0]['windows'][0]['remaining']=60
                strip.render()
                assert strip.columns['codex'].isVisible()
                assert strip.arrival_animations['codex'].state()==strip.arrival_animations['codex'].State.Running
                compact.hide();app.processEvents()
                assert strip.delivery_pulse.state()==strip.delivery_pulse.State.Stopped
                compact.show();wait(lambda:compact.windowHandle().isExposed())
                wait(lambda:strip.delivery_pulse.state()==strip.delivery_pulse.State.Running)
                strip._delivery_failed('QA incomplete')
                assert strip.delivery_pulse.state()==strip.delivery_pulse.State.Stopped
                strip.opener.request=original_request
                records.append(dict(case='quota animation and account gestures',transition=True,expiry_cancels=True,
                                    completion_pulse=True,hidden_stops=True,unknown_stops=True,
                                    input='native provider click and hover; Qt gift click',client_open='intercepted in memory'))
            if args.console_themes or args.background_transparency:
                from folego.ui.theme import THEMES,TOKENS,THEME_KEY
                from folego.ui.desktop_shortcuts import VirtualKeyboard
                from PySide6.QtCore import QSettings
                keyboard=VirtualKeyboard(compact.shortcut_tabs.controller)
                keyboard.resize(min(900,compact.screen().availableGeometry().width()),260)
                compact.shortcut_tabs.keyboard=keyboard
                QTest.mouseClick(compact.open_button,Qt.MouseButton.LeftButton)
                wait(lambda:window.isVisible() and window.windowHandle().isExposed())
                # Start from a different choice: selecting an already-current
                # default legitimately emits no currentIndexChanged signal.
                window.options.theme_choice.setCurrentIndex(window.options.theme_choice.findData('ps2'))
                profiles = ([(key,value) for key in ((args.transparency_theme,) if args.transparency_theme else ('snes-us','ps2')) for value in (0,50,100)]
                            if args.background_transparency else [(key,0) for key in THEMES])
                for key,transparency in profiles:
                    selected=THEMES[key]
                    combo=window.options.theme_choice
                    pointer_click(combo.mapToGlobal(combo.rect().center()),backend,window)
                    wait(lambda:combo.view().isVisible())
                    QTest.keyClick(combo.view(),Qt.Key.Key_Home)
                    for _ in range(combo.findData(key)):QTest.keyClick(combo.view(),Qt.Key.Key_Down)
                    QTest.keyClick(combo.view(),Qt.Key.Key_Enter)
                    wait(lambda:TOKENS.key==key and not combo.view().isVisible())
                    assert QSettings('folego','folego').value(THEME_KEY)==key
                    slider=window.options.background_slider
                    QTest.keyClick(slider,Qt.Key.Key_Home)
                    if transparency==100:QTest.keyClick(slider,Qt.Key.Key_End)
                    else:
                        for _ in range(transparency//10):QTest.keyClick(slider,Qt.Key.Key_PageUp)
                    wait(lambda:TOKENS.transparency==transparency)
                    prefix=key+('-'+str(transparency) if args.background_transparency else '')
                    settle=time.monotonic()+.15;wait(lambda:time.monotonic()>=settle)
                    window.grab().save(str(root/(prefix+'-central.png')))
                    QTest.mouseClick(window.back_button,Qt.MouseButton.LeftButton)
                    wait(lambda:compact.isVisible() and compact.windowHandle().isExposed())
                    compact._animate_actions(True)
                    wait(lambda:compact.drawer_animation.state()==compact.drawer_animation.State.Stopped)
                    compact.grab().save(str(root/(prefix+'-compact.png')))
                    tabs=compact.shortcut_tabs;tabs.show_prompts()
                    wait(lambda:tabs.prompt_menu is not None and tabs.prompt_menu.isVisible() and tabs.controller.future is None)
                    settle=time.monotonic()+.15;wait(lambda:time.monotonic()>=settle)
                    tabs.prompt_menu.grab().save(str(root/(prefix+'-prompts.png')))
                    tabs.prompt_menu.close()
                    if args.background_transparency:
                        from folego.core import ai_sessions as ai
                        now=time.time();items=[]
                        for identity,used in (('Principal',63),('Pesquisa',95),('Pessoal',15)):
                            item=ai.unknown('codex',label=identity)
                            item.update(account_id=identity,default=identity=='Principal',observed_at=now,
                                        windows=[ai.quota_window('Sessão (5 h)',used,now+3600,now),
                                                 ai.quota_window('Semana',used,now+86400,now)])
                            items.append(item)
                        compact.ai_strip.set_items(items);compact.ai_strip.details('codex')
                        wait(lambda:compact.ai_strip.account_menu is not None and compact.ai_strip.account_menu.isVisible())
                        panel=compact.ai_strip.account_panel
                        settle=time.monotonic()+.15;wait(lambda:time.monotonic()>=settle)
                        # Grab the actual native popup. QWidget.grab on an
                        # embedded panel adds a synthetic root palette fill.
                        image=compact.ai_strip.account_menu.grab().toImage();ratio=image.devicePixelRatio()
                        point=panel.mapTo(compact.ai_strip.account_menu,QPoint(4,100))
                        alpha=image.pixelColor(round(point.x()*ratio),round(point.y()*ratio)).alpha()
                        assert abs(alpha-round(255*(100-transparency)/100))<=1,(key,transparency,alpha)
                        compact.ai_strip.account_menu.grab().save(str(root/(prefix+'-accounts.png')))
                        compact.ai_strip.account_menu.close()
                    keyboard.show();wait(lambda:keyboard.windowHandle().isExposed())
                    keyboard.grab().save(str(root/(prefix+'-keyboard.png')))
                    from folego.ui.theme import background
                    assert background(selected.tokens.surface) in keyboard.styleSheet()
                    assert keyboard.windowOpacity()==window.windowOpacity()==1
                    keyboard.hide()
                    records.append(dict(case='background transparency' if args.background_transparency else 'console theme selection',
                                        theme=key,transparency=transparency,saved=True,
                                        surfaces=['central','compact','prompts','keyboard']+(['accounts'] if args.background_transparency else []),
                                        input='native dropdown click, Qt popup navigation and slider keys'))
                    QTest.mouseClick(compact.open_button,Qt.MouseButton.LeftButton)
                    wait(lambda:window.isVisible() and window.windowHandle().isExposed())
                QTest.mouseClick(window.back_button,Qt.MouseButton.LeftButton)
                wait(lambda:compact.isVisible() and compact.windowHandle().isExposed())
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
            compact._animate_actions(True)
            wait(lambda:compact.drawer_animation.state()==compact.drawer_animation.State.Stopped)
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
                c=window._compact;popup=QApplication.activePopupWidget();surface=native('^Fôlego — widget$')
                (root/'hover-failure.json').write_text(json.dumps(dict(height=c.action_drawer.maximumHeight(),
                    delay=c.drawer_delay.isActive(),under_mouse=c.underMouse(),
                    geometry=[c.x(),c.y(),c.width(),c.height()],
                    native=call('qdbus6','org.kde.KWin','/KWin','org.kde.KWin.getWindowInfo',surface[0]) if surface else None,
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
