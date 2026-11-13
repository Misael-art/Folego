"""The desktop guard restores only a known profile after a durable intent."""
import copy
import pytest

from folego.actions.accessibility import Store, Supervisor
from folego.actions.deck_profile_guard import DeckProfileGuard
from folego.adapters.deck_profiles import DESKTOP_URL, GAMEPAD_URL, MIC_PROFILE, DeckProfiles, SteamClient, ProfileUnknown
from folego.orchestration import Coordinator
from folego.orchestration.journal import Journal
from folego.orchestration.models import ActionPlan, ResourceIdentity
from test_accessibility import Native


class Profiles:
    def __init__(self):
        self.rows = {
            "touchpad": {"state": "healthy", "detail": "desktop", "identity": {
                "index": 15, "type": 4, "url": DESKTOP_URL, "template_sha256": "a" * 64}},
            "microphone": {"state": "healthy", "detail": "microfone interno", "identity": {
                "card": "alsa_card.pci-0000_04_00.5-platform-acp5x_mach.0",
                "active": MIC_PROFILE, "target": MIC_PROFILE, "default": "mic-biglinux"}},
        }
        self.effects = []
        self.before = lambda: None
        self.fail = False

    def observe(self):
        return copy.deepcopy(self.rows)

    def steam(self):
        return copy.deepcopy(self.rows["touchpad"])

    def microphone(self):
        return copy.deepcopy(self.rows["microphone"])

    def restore(self, key, before):
        self.before()
        self.effects.append(key)
        if self.fail:
            raise RuntimeError("resposta perdida")
        self.rows[key]["state"] = "healthy"
        self.rows[key]["identity"]["url" if key == "touchpad" else "active"] = (
            DESKTOP_URL if key == "touchpad" else MIC_PROFILE)


def guard(tmp_path, monkeypatch):
    store = Store(tmp_path / "state")
    coordinator = Coordinator(journal=Journal(tmp_path / "journal"), lock_path=tmp_path / "lock")
    profiles = Profiles()
    instance = DeckProfileGuard(profiles=profiles, store=store, coordinator=coordinator)
    monkeypatch.setattr(DeckProfileGuard, "_game_blocker", staticmethod(lambda: ""))
    monkeypatch.setattr(DeckProfileGuard, "_phasezero_audio_blocker", staticmethod(lambda card: ""))
    supervisor = Supervisor(native=Native(True), store=store, coordinator=coordinator,
                            profile_guard=instance)
    supervisor.native.report["cards"] = [
        {"key": key, "state": "observed", "detail": "enumerado"} for key in ("touchpad", "microphone")]
    supervisor.configure(enabled=True)
    return supervisor, profiles


def test_learns_healthy_profiles_and_repairs_only_confirmed_gamepad(tmp_path, monkeypatch):
    supervisor, profiles = guard(tmp_path, monkeypatch)
    assert supervisor.tick()["state"] == "observing"
    assert not supervisor.store.read()["profile_baseline"]
    supervisor.tick()
    assert set(supervisor.store.read()["profile_baseline"]) == {"touchpad", "microphone"}
    profiles.rows["touchpad"]["state"] = "fault"
    profiles.rows["touchpad"]["identity"]["url"] = GAMEPAD_URL
    profiles.before = lambda: assert_intent(supervisor)
    assert supervisor.tick()["state"] == "observing"  # One observation does not act.
    outcome = supervisor.tick()
    assert outcome["state"] == "repaired" and outcome["profile"] == "touchpad"
    assert profiles.effects == ["touchpad"]
    assert supervisor.store.read()["profile_attempts"][0]["key"] == "touchpad"


def assert_intent(supervisor):
    rows = supervisor.coordinator.journal.records()
    assert rows[-1].kind == "intent" and rows[-1].plan.action == "accessibility.restore-desktop-profile"


def test_old_unknown_touch_does_not_block_microphone(tmp_path, monkeypatch):
    supervisor, profiles = guard(tmp_path, monkeypatch)
    supervisor.tick()
    supervisor.tick()
    old = ActionPlan("accessibility.activate", ResourceIdentity.entry("touch"),
                     {"capabilities": ["touch"], "peer": {"registered": True}})
    supervisor.coordinator.journal.append_intent(old)
    profiles.rows["microphone"]["state"] = "fault"
    profiles.rows["microphone"]["identity"]["active"] = "pro-audio"
    supervisor.tick()
    result = supervisor.tick()
    assert result["state"] == "repaired" and result["profile"] == "microphone"
    assert profiles.effects == ["microphone"]


def test_game_owner_and_changed_template_block_effect(tmp_path, monkeypatch):
    supervisor, profiles = guard(tmp_path, monkeypatch)
    supervisor.tick()
    supervisor.tick()
    profiles.rows["touchpad"]["state"] = "fault"
    profiles.rows["touchpad"]["identity"]["url"] = GAMEPAD_URL
    monkeypatch.setattr(DeckProfileGuard, "_game_blocker", staticmethod(lambda: "jogo ativo"))
    supervisor.tick()
    supervisor.tick()
    assert profiles.effects == []
    monkeypatch.setattr(DeckProfileGuard, "_game_blocker", staticmethod(lambda: ""))
    profiles.rows["touchpad"]["identity"]["template_sha256"] = "b" * 64
    supervisor.tick()
    assert profiles.effects == []


def test_external_audio_preference_blocks_profile_fight(tmp_path, monkeypatch):
    supervisor, profiles = guard(tmp_path, monkeypatch)
    supervisor.tick()
    supervisor.tick()
    profiles.rows["microphone"]["state"] = "fault"
    profiles.rows["microphone"]["identity"]["active"] = "pro-audio"
    monkeypatch.setattr(DeckProfileGuard, "_phasezero_audio_blocker",
                        staticmethod(lambda card: "preferência do responsável externo diverge"))
    supervisor.tick()
    report = supervisor.inspect()
    assert "preferência do responsável externo diverge" in next(
        card["detail"] for card in report["cards"] if card["key"] == "microphone")
    supervisor.tick()
    assert profiles.effects == []


def test_phasezero_stale_headset_reference_is_not_treated_as_agreement(tmp_path, monkeypatch):
    import json
    from folego import paths
    config = tmp_path / "config"
    state = tmp_path / "state"
    marker = config / "phasezero/desktop-session.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}")
    marker.chmod(0o600)
    preference = state / "phasezero/desktop-session/preferences.json"
    preference.parent.mkdir(parents=True)
    card = "alsa_card.pci-0000_04_00.5-platform-acp5x_mach.0"
    preference.write_text(json.dumps({"schema_version": 1, "audio": {
        "profiles": {card: MIC_PROFILE}, "defaults": {"source": "mic-biglinux"},
        "endpoints": {"sources": {
            "alsa_input.pci-0000_04_00.5-platform-acp5x_mach.0.HiFi__Headset__source": {}}}}}))
    preference.chmod(0o600)
    monkeypatch.setattr(paths, "xdg_config_home", lambda: config)
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    assert "fone" in DeckProfileGuard._phasezero_audio_blocker({"card": card, "default": "mic-biglinux"})


def test_lost_result_opens_circuit_without_retry(tmp_path, monkeypatch):
    supervisor, profiles = guard(tmp_path, monkeypatch)
    supervisor.tick()
    supervisor.tick()
    profiles.rows["touchpad"]["state"] = "fault"
    profiles.rows["touchpad"]["identity"]["url"] = GAMEPAD_URL
    profiles.fail = True
    supervisor.tick()
    result = supervisor.tick()
    assert result["state"] == "waiting"
    assert supervisor.store.read()["profile_circuit"]["touchpad"]
    supervisor.tick()
    supervisor.tick()
    assert profiles.effects == ["touchpad"]
    operation = result["operation_id"]
    profiles.rows["touchpad"]["state"] = "healthy"
    profiles.rows["touchpad"]["identity"]["url"] = DESKTOP_URL
    assert supervisor.reconcile(operation).outcome.value == "sucesso"
    assert supervisor.profile_guard.rearm("touchpad", confirmed=True)["ok"]
    assert not supervisor.store.read()["profile_circuit"]


def test_changed_healthy_template_requires_manual_capture(tmp_path, monkeypatch):
    supervisor, profiles = guard(tmp_path, monkeypatch)
    supervisor.tick()
    supervisor.tick()
    profiles.rows["touchpad"]["identity"]["template_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="confirmação"):
        supervisor.profile_guard.capture("touchpad", confirmed=False)
    result = supervisor.profile_guard.capture("touchpad", confirmed=True)
    assert result["ok"] and result["baseline"]["template_sha256"] == "b" * 64
    assert profiles.effects == []


def test_status_keeps_enabled_when_old_journal_read_is_still_pending(tmp_path, monkeypatch):
    supervisor, _ = guard(tmp_path, monkeypatch)
    monkeypatch.setattr(supervisor._pending_reader, "ids", lambda: (_ for _ in ()).throw(ValueError("leitura em andamento")))
    report = supervisor.inspect()
    assert report["policy"]["enabled"] is True
    assert "leitura em andamento" in report["blockers"]


def test_deck_profile_probe_recognizes_wrong_audio_profile_and_stays_read_only(tmp_path):
    import json
    from subprocess import CompletedProcess
    model = tmp_path / "model"
    model.write_text("Jupiter")
    card = "alsa_card.pci-0000_04_00.5-platform-acp5x_mach.0"
    calls = []
    def runner(argv, **_):
        calls.append(argv)
        if argv[-1] == "cards":
            payload = [{"name": card, "active_profile": "pro-audio", "profiles": {
                MIC_PROFILE: {"available": True, "sources": 1}, "pro-audio": {"available": True, "sources": 1}}}]
        elif argv[-1] == "get-default-source":
            return CompletedProcess(argv, 0, "mic-biglinux\n", "")
        else:
            payload = [{"name": "mic-biglinux", "mute": False}]
        return CompletedProcess(argv, 0, json.dumps(payload), "")
    probe = DeckProfiles(runner=runner, data_home=tmp_path, model_path=model)
    assert probe.microphone()["state"] == "fault"
    assert all("set-" not in " ".join(command) for command in calls)


def test_deck_profile_probe_requires_exact_wrong_steam_map(tmp_path):
    model = tmp_path / "model"
    model.write_text("Jupiter")
    template = tmp_path / "Steam/controller_base/templates/retrofe_steamdeck_desktop.vdf"
    template.parent.mkdir(parents=True)
    template.write_bytes(b"desktop" * 200)
    class Client:
        url = GAMEPAD_URL
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def controllers(self):
            return {"index": 15, "type": 4, "url": self.url, "title": "RetroFE Steam Deck Gamepad",
                    "gamepad": True, "mouse": False, "keyboard": False}
    probe = DeckProfiles(steam_factory=Client, data_home=tmp_path, model_path=model)
    assert probe.steam()["state"] == "fault"
    Client.url = "template://other.vdf"
    assert probe.steam()["state"] == "unknown"


def test_microphone_mute_is_preserved_even_with_expected_profile(tmp_path):
    import json
    from subprocess import CompletedProcess
    model = tmp_path / "model"
    model.write_text("Jupiter")
    card = "alsa_card.pci-0000_04_00.5-platform-acp5x_mach.0"
    commands = []
    def runner(argv, **_):
        commands.append(argv)
        if argv[-1] == "get-default-source":
            return CompletedProcess(argv, 0, "mic-biglinux\n", "")
        if argv[-1] == "cards":
            payload = [{"name": card, "active_profile": MIC_PROFILE,
                        "profiles": {MIC_PROFILE: {"available": True, "sources": 1}}}]
        else:
            payload = [{"name": "mic-biglinux", "mute": False},
                       {"name": "alsa_input.internal", "mute": True,
                        "properties": {"device.name": card}}]
        return CompletedProcess(argv, 0, json.dumps(payload), "")
    probe = DeckProfiles(runner=runner, model_path=model)
    assert probe.microphone()["state"] == "unknown"
    assert all("set-source-mute" not in argv for argv in commands)


def test_steam_selection_rechecks_controller_before_private_api_write():
    client = object.__new__(SteamClient)
    client.owner_start = "123"
    client._owner_start = lambda: "123"
    commands = []
    client.evaluate = lambda expression: commands.append(expression)
    client.controllers = lambda: {"index": 15, "url": DESKTOP_URL, "mouse": True, "keyboard": True}
    with pytest.raises(ProfileUnknown, match="mudou"):
        client.select_desktop(15)
    assert commands == []
    client.controllers = lambda: {"index": 15, "url": GAMEPAD_URL, "mouse": False, "keyboard": False}
    client.select_desktop(15)
    assert "SetSelectedConfigForApp(413080,15" in commands[0]


def test_microphone_restore_changes_profile_only():
    calls = []
    probe = DeckProfiles()
    probe._pactl = lambda *args: calls.append(args)
    probe.restore("microphone", {"identity": {"active": "pro-audio", "card": "alsa_card.acp5x"}})
    assert calls == [("set-card-profile", "alsa_card.acp5x", MIC_PROFILE)]
    with pytest.raises(ProfileUnknown):
        probe.restore("microphone", {"identity": {"active": MIC_PROFILE, "card": "alsa_card.acp5x"}})


def reprobe_fault(profiles):
    row = profiles.rows['microphone']
    row.update(state='fault', code='audio-enumeration-incomplete')
    row['identity'].update(active='off', recovery='wireplumber-reprobe', owner={'pid': 123})


@pytest.mark.parametrize('active', ['off', MIC_PROFILE])
def test_reprobe_requires_opt_in_and_ignores_unrelated_kwin_failure(tmp_path, monkeypatch, active):
    supervisor, profiles = guard(tmp_path, monkeypatch)
    supervisor.tick(); supervisor.tick()
    reprobe_fault(profiles)
    profiles.rows['microphone']['identity']['active'] = active
    if active == MIC_PROFILE:
        profiles.rows['microphone']['code'] = 'audio-nodes-missing-after-busy'
        profiles.rows['microphone']['identity']['busy_evidence'] = {'pipewire': {'pid': 124}}
    supervisor.native.report['errors'] = ['KWin indisponível']
    supervisor.native.report['backend'] = 'unknown'
    supervisor.tick(); supervisor.tick()
    assert not profiles.effects
    supervisor.configure(audio_reprobe=True)
    profiles.before = lambda: assert_intent(supervisor)
    assert supervisor.tick()['state'] == 'repaired'
    assert profiles.effects == ['microphone']


def test_repeated_or_stale_observation_cannot_trigger_repair(tmp_path, monkeypatch):
    supervisor, profiles = guard(tmp_path, monkeypatch)
    supervisor.tick(); supervisor.tick()
    reprobe_fault(profiles)
    supervisor.configure(audio_reprobe=True)
    report = supervisor.native.collect()
    supervisor.profile_guard.annotate(report)
    for _ in range(4):
        assert supervisor.profile_guard.tick(report) is None
    assert not profiles.effects
    report['mono'] -= 60
    assert supervisor.profile_guard.tick(report) is None
    supervisor.tick()
    assert not profiles.effects
    assert supervisor.tick()['state'] == 'repaired'


def test_unknown_legacy_scope_and_clock_regression_preserve_protection(tmp_path, monkeypatch):
    supervisor, profiles = guard(tmp_path, monkeypatch)
    supervisor.tick(); supervisor.tick()
    old = ActionPlan('accessibility.activate', ResourceIdentity.entry('touch'), {'legacy': True})
    supervisor.coordinator.journal.append_intent(old)
    reprobe_fault(profiles)
    supervisor.configure(audio_reprobe=True)
    supervisor.tick(); supervisor.tick()
    assert not profiles.effects
    from folego.orchestration.models import ActionResult, Outcome
    supervisor.coordinator.journal.append_result(ActionResult(old.action, Outcome.REFUSED, old.operation_id,
                                                             target_key='touch'))
    policy = supervisor.store.read()
    policy['profile_attempts'] = [{'key': 'microphone', 'ts': supervisor.now() + 600, 'operation_id': 'future'}]
    supervisor.store.save(policy)
    before = len(supervisor.coordinator.journal.records())
    supervisor.tick(); supervisor.tick()
    assert not profiles.effects
    assert len(supervisor.coordinator.journal.records()) == before


def test_manual_reprobe_uses_parent_intent_and_saved_preference_without_learning_fault(tmp_path, monkeypatch):
    from folego.actions.accessibility_recovery import Recovery
    from test_accessibility_recovery import Backend
    supervisor, profiles = guard(tmp_path, monkeypatch)
    reprobe_fault(profiles)
    recovery = Recovery(supervisor, backend=Backend(supervisor.native))
    plan = recovery.prepare('microphone')
    profiles.before = lambda: assert_parent_intent(supervisor, plan)
    assert recovery.execute(plan, confirmed=True).outcome.value == 'sucesso'
    assert profiles.effects == ['microphone']
    assert not supervisor.store.read()['profile_baseline']


def assert_parent_intent(supervisor, plan):
    assert supervisor.coordinator.journal.state_of(plan.operation_id).intent == plan


def test_unknown_manual_reprobe_can_be_queried_then_rearmed_without_retry(tmp_path, monkeypatch):
    from folego.actions.accessibility_recovery import Recovery
    from test_accessibility_recovery import Backend
    supervisor, profiles = guard(tmp_path, monkeypatch)
    supervisor.tick(); supervisor.tick()
    reprobe_fault(profiles)
    recovery = Recovery(supervisor, backend=Backend(supervisor.native))
    plan = recovery.prepare('microphone')
    profiles.fail = True
    assert recovery.execute(plan, confirmed=True).outcome.value == 'desconhecido'
    from folego.actions.accessibility import unresolved
    assert unresolved(supervisor.coordinator.journal, capabilities=['audio']) == [plan.operation_id]
    assert unresolved(supervisor.coordinator.journal, capabilities=['keyboard']) == []
    assert supervisor.reconcile(plan.operation_id).outcome.value == 'desconhecido'
    profiles.rows['microphone']['state'] = 'healthy'
    profiles.rows['microphone']['identity']['active'] = MIC_PROFILE
    monkeypatch.setattr('folego.actions.accessibility_recovery._alive', lambda owner: False)
    assert supervisor.reconcile(plan.operation_id).outcome.value == 'sucesso'
    report = supervisor.inspect()
    card = next(row for row in report['cards'] if row['key'] == 'microphone')
    assert 'reparo suspenso' in card['detail']
    assert supervisor.profile_guard.rearm('microphone', confirmed=True)['ok']
    assert profiles.effects == ['microphone']
