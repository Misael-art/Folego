#!/usr/bin/env python3
"""Owned Wayland alpha probe over an owned backdrop, safe to crop for QA."""
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
    parser.add_argument('--hold-for-capture',action='store_true')
    args=parser.parse_args()
    root=args.state.resolve();root.mkdir(mode=0o700,parents=True,exist_ok=False)
    for key,name in (('HOME','home'),('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),
                     ('XDG_STATE_HOME','state'),('XDG_CACHE_HOME','cache'),('TMPDIR','tmp')):
        folder=root/name;folder.mkdir(mode=0o700);os.environ[key]=str(folder)
    for key in ('CODEX_HOME','CLAUDE_CONFIG_DIR','GROK_HOME'):os.environ.pop(key,None)
    from PySide6.QtCore import Qt,QTimer,QCoreApplication,QEvent
    from PySide6.QtGui import QPainter,QColor
    from PySide6.QtWidgets import QApplication,QWidget
    from folego.ui.theme import apply_theme,prepare_surface
    from folego.ui.ai_account_panel import AccountPanel
    from folego.core import ai_sessions as ai
    app=QApplication([]);app.setApplicationName('folego-qa-alpha')
    app.setQuitOnLastWindowClosed(False);apply_theme(app,'ps2',transparency=50)
    class Backdrop(QWidget):
        def paintEvent(self,event):
            painter=QPainter(self)
            for y in range(0,self.height(),40):
                for x in range(0,self.width(),40):
                    painter.fillRect(x,y,40,40,QColor('#273541' if (x//40+y//40)%2 else '#495766'))
            painter.end()
    backdrop=Backdrop(None,Qt.WindowType.Window|Qt.WindowType.FramelessWindowHint)
    backdrop.setWindowTitle('Fôlego QA — fundo controlado');backdrop.resize(900,570)
    now=time.time();rows=[]
    for label,used in (('Demonstração',63),('Pesquisa',95),('Pessoal',15)):
        row=ai.unknown('codex',label=label)
        row.update(account_id=label,default=label=='Demonstração',observed_at=now,
                   windows=[ai.quota_window('Sessão (5 h)',used,now+3600,now),
                            ai.quota_window('Semana',used,now+86400,now)])
        rows.append(row)
    panel=AccountPanel('codex',rows,backdrop)
    panel.setWindowFlags(Qt.WindowType.Tool|Qt.WindowType.FramelessWindowHint)
    prepare_surface(panel);panel.setWindowTitle('Fôlego QA — superfície translúcida');panel.resize(560,470)
    def call(*argv):return subprocess.check_output(argv,text=True,timeout=5).strip()
    def wait(predicate):
        end=time.monotonic()+8
        while time.monotonic()<end:
            app.processEvents()
            if predicate():return
            time.sleep(.02)
        raise AssertionError('Owned alpha probe deadline')
    def native(widget):
        return call('kdotool','search','--all','--pid',str(os.getpid()),'--name','^'+re.escape(widget.windowTitle())+'$').splitlines()
    result=dict(passed=False,platform=app.platformName(),pid=os.getpid(),cases=[],scope='owned panel and opaque checkerboard; private HOME/XDG; no user data or native input')
    try:
        assert app.platformName()=='wayland'
        backdrop.show();panel.show()
        wait(lambda:backdrop.windowHandle().isExposed() and panel.windowHandle().isExposed())
        script=root/'place-owned-alpha.js'
        script.write_text('const ws=workspace.windowList().filter(w=>w.pid==='+str(os.getpid())+');'
            'for(const w of ws){if(w.caption==="Fôlego QA — fundo controlado"){w.frameGeometry={x:20,y:0,width:900,height:570};w.keepAbove=true;}}'
            'for(const w of ws){if(w.caption==="Fôlego QA — superfície translúcida"){w.frameGeometry={x:200,y:50,width:560,height:470};w.keepAbove=true;}}')
        name='folego-owned-alpha-'+str(os.getpid())
        sid=call('qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.loadScript',str(script),name)
        try:call('qdbus6','org.kde.KWin','/Scripting/Script'+sid,'org.kde.kwin.Script.run')
        finally:call('qdbus6','org.kde.KWin','/Scripting','org.kde.kwin.Scripting.unloadScript',name)
        settle=time.monotonic()+.35;wait(lambda:time.monotonic()>=settle)
        geometry={}
        for key,widget in (('backdrop',backdrop),('panel',panel)):
            ids=native(widget);assert len(ids)==1
            raw=call('qdbus6','org.kde.KWin','/KWin','org.kde.KWin.getWindowInfo',ids[0])
            assert re.search(r'(?m)^pid:\s*'+str(os.getpid())+'$',raw)
            geometry[key]={name:float(re.search(r'(?m)^'+name+r':\s*([-0-9.]+)',raw)[1]) for name in ('x','y','width','height')}
        outer,inner=geometry['backdrop'],geometry['panel']
        assert outer['x']<inner['x'] and outer['y']<inner['y']
        assert inner['x']+inner['width']<outer['x']+outer['width'] and inner['y']+inner['height']<outer['y']+outer['height']
        assert panel.windowHandle().format().alphaBufferSize()>=8
        result['geometry']=geometry
        for value in (0,50,100):
            apply_theme(app,'ps2',transparency=value)
            app.processEvents();image=panel.grab().toImage();ratio=image.devicePixelRatio()
            alpha=image.pixelColor(round(4*ratio),round(100*ratio)).alpha()
            assert abs(alpha-round(255*(100-value)/100))<=1,(value,alpha)
            assert panel.windowOpacity()==1
            image.save(str(root/('panel-'+str(value)+'.png')))
            result['cases'].append(dict(transparency=value,background_alpha=alpha,window_opacity=1,alpha_buffer=panel.windowHandle().format().alphaBufferSize()))
        apply_theme(app,'ps2',transparency=50);app.processEvents()
        ready=dict(pid=os.getpid(),title=backdrop.windowTitle(),geometry=geometry,marker=str(root/'captured'),scope=result['scope'])
        (root/'ready.json').write_text(json.dumps(ready,indent=2))
        if args.hold_for_capture:
            deadline=time.monotonic()+90
            timer=QTimer()
            def finish():
                if (root/'captured').exists() or time.monotonic()>deadline:app.quit()
            timer.timeout.connect(finish);timer.start(100);app.exec();timer.stop()
            result['capture_ack']=(root/'captured').exists()
            assert result['capture_ack'],'Compositor capture confirmation deadline'
        result['passed']=True
    except Exception as exc:
        import traceback
        (root/'failure.txt').write_text(traceback.format_exc());result['error']=repr(exc)
    finally:
        panel.hide();backdrop.close()
        for widget in list(app.topLevelWidgets()):widget.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    (root/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    assert result['passed']


if __name__=='__main__':main()
