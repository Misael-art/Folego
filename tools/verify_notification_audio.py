#!/usr/bin/env python3
"""Play all cues on an owned PipeWire null sink, with physical audio hidden."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--child', action='store_true')
    args = parser.parse_args(); root = args.state.resolve()
    if not args.child:
        root.mkdir(mode=0o700, parents=True, exist_ok=False)
        env = dict(os.environ)
        for key, folder in (('HOME','home'),('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),
                            ('XDG_STATE_HOME','state'),('XDG_CACHE_HOME','cache'),('XDG_RUNTIME_DIR','runtime'),('TMPDIR','tmp')):
            path=root/folder;path.mkdir(mode=0o700);env[key]=str(path)
        for key in ('DBUS_SESSION_BUS_ADDRESS','DBUS_STARTER_ADDRESS','AT_SPI_BUS_ADDRESS','WAYLAND_DISPLAY',
                    'DISPLAY','PIPEWIRE_REMOTE','PULSE_SINK','PULSE_SOURCE','PULSE_RUNTIME_PATH','PIPEWIRE_CONFIG_DIR'):
            env.pop(key,None)
        env.update(PULSE_SERVER='unix:'+str(root/'runtime/pulse/native'), PIPEWIRE_RUNTIME_DIR=str(root/'runtime'),
                   PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(Path(__file__).resolve().parents[1]/'src'))
        command=['bwrap','--ro-bind','/','/','--dev','/dev','--proc','/proc','--unshare-pid','--unshare-net','--new-session',
            '--tmpfs',f'/run/user/{os.getuid()}','--tmpfs','/run/dbus','--bind',str(root),str(root),'--bind',str(root/'tmp'),'/tmp',
            'dbus-run-session','--',sys.executable,str(Path(__file__).resolve()),'--state',str(root),'--child']
        with (root/'session.log').open('w') as log:
            subprocess.run(command,env=env,stdout=log,stderr=log,timeout=60,check=True)
        print((root/'result.json').read_text());return
    assert Path(os.environ['XDG_RUNTIME_DIR']).is_relative_to(root)
    assert not Path('/dev/snd').exists()
    from folego.adapters.notification_audio import NotificationAudio, LOUD
    from folego.core.notification_tones import SCORES
    children=[]
    def call(*argv): return subprocess.check_output(argv,text=True,timeout=4).strip()
    def wait(path):
        end=time.monotonic()+8
        while not path.exists() and time.monotonic()<end: time.sleep(.05)
        assert path.exists(),str(path)
    def sink(): return next(n for n in json.loads(call('pactl','-f','json','list','sinks')) if n['name']=='folego_qa')
    proofs=[]
    def run(argv,**kwargs):
        if Path(argv[0]).name=='paplay':
            node=sink()
            proofs.append(dict(volumes=[v['value'] for v in node['volume'].values()],mute=node['mute'],pcm_bytes=len(kwargs['input'])))
            assert all(v>=LOUD for v in proofs[-1]['volumes']) and not node['mute']
        return subprocess.run(argv,**kwargs)
    try:
        for binary,ready in (('pipewire',root/'runtime/pipewire-0'),('wireplumber',None),('pipewire-pulse',root/'runtime/pulse/native')):
            with (root/(binary+'.log')).open('w') as log:
                children.append(subprocess.Popen([binary],stdout=log,stderr=log))
            if ready is not None: wait(ready)
        call('pactl','load-module','module-null-sink','sink_name=folego_qa','channel_map=front-left,front-right')
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            result = subprocess.run(['pactl', 'get-default-sink'], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip() == 'folego_qa': break
            time.sleep(.1)
        else: raise AssertionError('Private session policy did not select the owned null sink')
        call('pactl','set-sink-volume','folego_qa','35%','45%')
        call('pactl','set-sink-mute','folego_qa','1')
        before=sink(); expected=[v['value'] for v in before['volume'].values()]
        backend=NotificationAudio(run=run)
        for tone in SCORES:
            backend.perform('alert-play',dict(tone=tone,raise_volume=True))
            after=sink(); assert [v['value'] for v in after['volume'].values()]==expected and after['mute']
        receipt=json.loads(backend.path.read_text());assert receipt['status']=='restored'
        result=dict(passed=True,tones=list(SCORES),during_playback=proofs,restored_channels=expected,restored_mute=True,
                    scope='owned PipeWire/Pulse/WirePlumber and null sink, PID/network namespaces, physical runtime and sound devices hidden')
        (root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    finally:
        for child in reversed(children):
            if child.poll() is None: child.terminate();child.wait(timeout=8)


if __name__=='__main__':main()
