import time

from folego.ui.compact import CompactWindow
from folego.ui.desktop_preferences import enabled, set_enabled, SHOW_IN_CAPTURE, SOUNDS, RAISE_VOLUME
from folego.ui.options_tab import OptionsTab


def wait(qapp, predicate):
    end=time.monotonic()+4
    while time.monotonic()<end:
        qapp.processEvents()
        if predicate(): return
        time.sleep(.02)
    raise AssertionError('UI request did not complete')


class Host:
    def raise_to_user(self): pass
    def toggle_pause(self): return False
    def quit(self): pass


def view_with_capture(monkeypatch, include, fail=False):
    class Store:
        def value(self,key,default=None): return include if key==SHOW_IN_CAPTURE else default
        def setValue(self,*args): pass
        def sync(self): pass
    class Capture:
        active=True
        calls=[]
        visible_at_start=None
        def perform(self,action,value=None):
            self.calls.append(action)
            if action=='print':
                self.visible_at_start=view.isVisible()
                if fail: raise RuntimeError('Spectacle indisponível')
                return 'Selecione a região'
            return dict(operation='capture-status',active=self.active)
        def close(self): return True
    backend=Capture()
    monkeypatch.setattr('folego.ui.desktop_shortcuts.DesktopTools',lambda **_:backend)
    view=CompactWindow(Host(),store=Store())
    return view,backend


def test_capture_hides_before_launch_and_restores_after_tool_exit(qapp,monkeypatch):
    view,backend=view_with_capture(monkeypatch,False)
    view.show_compact();qapp.processEvents()
    view.shortcut_tabs.buttons['print'].click()
    wait(qapp,lambda:'print' in backend.calls)
    assert backend.visible_at_start is False and not view.isVisible()
    view.shortcut_tabs.activate('print')
    assert backend.calls.count('print')==1
    backend.active=False
    wait(qapp,lambda:view.isVisible() and not view._capture_waiting)
    view.force_close()


def test_capture_default_includes_widget_and_launch_failure_restores(qapp,monkeypatch):
    view,backend=view_with_capture(monkeypatch,True)
    view.show_compact();view.shortcut_tabs.activate('print')
    wait(qapp,lambda:'print' in backend.calls)
    assert backend.visible_at_start is True
    backend.active=False;wait(qapp,lambda:not view._capture_waiting);view.force_close()
    view,backend=view_with_capture(monkeypatch,False,fail=True)
    view.show_compact();view.shortcut_tabs.activate('print')
    wait(qapp,lambda:'print' in backend.calls and view.isVisible() and not view._capture_waiting)
    view.force_close()


def test_desktop_options_persist_and_preview_only_on_explicit_click(qapp,tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    class Jobs:
        def run(self,*args,**kwargs): pass
        def shutdown(self): pass
    tab=OptionsTab(jobs=Jobs());assert not tab._desktop_options
    tab.show();qapp.processEvents()
    assert tab.capture_choice.isChecked() and tab.sound_choice.isChecked() and tab.volume_choice.isChecked()
    for control in (tab.capture_choice,tab.sound_choice,tab.volume_choice,tab.sound_kind):
        assert control.height() >= control.fontMetrics().height()
    tab.capture_choice.click();tab.sound_choice.click();tab.volume_choice.click()
    assert not enabled(SHOW_IN_CAPTURE) and not enabled(SOUNDS) and not enabled(RAISE_VOLUME)
    played=[];tab.sound_preview.connect(played.append)
    assert tab.sound_kind.count()==12 and not played
    tab.sound_kind.setCurrentIndex(4);tab.test_sound.click();assert played==['low']
    tab.stop();tab.close()


def test_shared_monitor_keeps_collecting_when_widget_is_hidden(qapp):
    from folego.ui.ai_monitor import AIMonitor
    from folego.ui.ai_strip import AIStrip
    class Deliveries:
        def collect(self): return []
    class Alerts:
        seen=[]
        def observe(self,kind,rows): self.seen.append(kind)
        def start(self): pass
        def shutdown(self): pass
    alerts=Alerts();monitor=AIMonitor(collect_fn=lambda:[],deliveries=Deliveries(),alerts=alerts)
    monitor.start();wait(qapp,lambda:len(alerts.seen)>=2)
    strip=AIStrip(monitor=monitor);strip.show();qapp.processEvents();strip.hide();qapp.processEvents()
    assert monitor.poller._timer.isActive() and monitor.delivery_poller._timer.isActive()
    strip.shutdown();monitor.shutdown()


def test_completion_to_audio_pipeline_respects_mute_and_does_not_replay(qapp,tmp_path,monkeypatch):
    from folego.ui.alert_sounds import AlertSounds
    from folego.ui.desktop_shortcuts import DesktopController
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    # Qt caches its native settings location within the shared QApplication.
    # Establish this test's preference explicitly after the persistence case.
    set_enabled(SOUNDS,True);set_enabled(RAISE_VOLUME,True)
    class Backend:
        calls=[]
        def perform(self,action,value=None): self.calls.append((action,value));return ''
        def close(self): return True
    backend=Backend();controller=DesktopController(backend=backend)
    sounds=AlertSounds(controller=controller)
    deliveries = []
    sounds.deliveries_observed.connect(deliveries.append)
    def rows(*events):
        return [dict(provider='codex', count=len(events),
                     pending=[dict(event=e, at=time.time()) for e in events])]
    sounds.observe('deliveries',rows())
    sounds.observe('deliveries',rows('one'))
    wait(qapp,lambda:controller.future is None and len(backend.calls)==1)
    assert backend.calls[0]==('alert-play',dict(tone='codex',raise_volume=True))
    set_enabled(SOUNDS,False);sounds.observe('deliveries',rows('one','two'))
    assert len(backend.calls)==1
    assert deliveries == [{'codex': 1}, {'codex': 1}]
    set_enabled(SOUNDS,True);sounds.observe('deliveries',rows('two'))
    assert len(backend.calls)==1
    sounds.observe('deliveries',rows('three'))
    wait(qapp,lambda:controller.future is None and len(backend.calls)==2)
    assert deliveries == [{'codex': 1}, {'codex': 1}, {'codex': 1}]
    resets = []
    sounds.accounts_observed.connect(resets.append)
    def ticket(count):
        return [dict(provider='claude', account_id='a', label='Principal', windows=[], observed_at=time.time(),
                     reset_credits=dict(available=count, expires_at=None, observed_at=time.time()))]
    set_enabled(SOUNDS, False); sounds.observe('quotas', ticket(0)); sounds.observe('quotas', ticket(1))
    assert [e['kind'] for e in resets[0]] == ['available'] and len(backend.calls) == 2
    set_enabled(SOUNDS, True); sounds.observe('quotas', ticket(2))
    wait(qapp, lambda: controller.future is None and len(backend.calls) == 3)
    assert backend.calls[2] == ('alert-play', dict(tone='reset', raise_volume=True))
    sounds.shutdown()


def test_battery_cue_uses_existing_audio_worker_and_sound_preference(qapp, monkeypatch):
    from folego.ui.alert_sounds import AlertSounds
    from folego.ui.desktop_shortcuts import DesktopController
    monkeypatch.setattr('folego.ui.alert_sounds.enabled', lambda key: key == SOUNDS)
    class Backend:
        calls = []
        def perform(self, action, value=None):
            self.calls.append((action, value))
            return ''
        def close(self): return True
    backend = Backend()
    sounds = AlertSounds(controller=DesktopController(backend=backend))
    sounds.battery_cue('battery-25')
    wait(qapp, lambda: sounds.controller.future is None and len(backend.calls) == 1)
    assert backend.calls == [('alert-play', {'tone': 'battery-25', 'raise_volume': False})]
    sounds.shutdown()
