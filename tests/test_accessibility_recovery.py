"""Manual capabilities: immutable intent, scoped results and no blind retries."""
import copy
import json
import subprocess
from types import SimpleNamespace

import pytest

from folego.actions.accessibility_recovery import Recovery, ACTION, SAVE_ACTION, PEER_WAIT
from folego.adapters.accessibility_recovery import DesktopRecovery, UncertainEffect
from folego.orchestration.models import Outcome
from test_accessibility import supervisor, assert_intent, KEY


class Backend(DesktopRecovery):
    def __init__(self, native):
        super().__init__(native)
        self.owner = None
        self.effects = []
        self.loss = False
        self.active = False
        self.before = lambda: None

    def peer(self):
        return copy.deepcopy(self.owner)

    def audio_targets(self, scope):
        return {key: {"name": key} for key in scope if key in ("audio", "microphone")}

    def peer_idle(self, peer):
        if self.active:
            raise ValueError("jogo ativo")

    def delegate(self, peer, *, capture=False):
        self.before()
        self.effects.append("capture" if capture else "delegate")
        if self.loss:
            raise UncertainEffect("resposta perdida")
        self.native.report["devices"][0]["enabled"] = True
        return ""

    def enable_audio(self, key, target):
        self.before()
        self.effects.append(key)
        return True, "sem mute, padrão e ganho verificados"

    def open_keyboard(self, report):
        self.effects.append("virtual-keyboard")
        return True, "teclado visível"

    def repair_touch(self, peer):
        self.effects.append("touch")
        return False, "FTS ainda ausente"

    def gamepad(self, report):
        self.effects.append("gamepad")
        return False, "Steam solicitado, perfil não confirmado"


def controller(supervisor):
    return Recovery(supervisor, backend=Backend(supervisor.native))


def test_native_click_uses_exact_plan_after_intent_and_replays_without_effect(supervisor):
    recovery = controller(supervisor)
    plan = recovery.prepare("keyboard")
    supervisor.native.hook = lambda: assert_intent(supervisor, plan.operation_id)
    assert recovery.execute(plan).outcome == Outcome.REFUSED
    result = recovery.execute(plan, confirmed=True)
    assert result.outcome == Outcome.OK and result.operation_id == plan.operation_id
    assert result.effects["capabilities"][0]["ready"] is True
    assert result.effects["capabilities"][0]["physical_verified"] is False
    assert recovery.execute(plan, confirmed=True) == result
    assert len(supervisor.native.calls) == 1


def test_registered_active_observer_receives_manual_request_instead_of_waiting_forever(supervisor):
    recovery = controller(supervisor)
    recovery.backend.owner = {"name": "PhaseZero", "files": {"registered": "digest"}}
    supervisor.native.report["blockers"] = [PEER_WAIT]
    plan = recovery.prepare("keyboard")
    recovery.backend.before = lambda: assert_intent(supervisor, plan.operation_id)
    result = recovery.execute(plan, confirmed=True)
    assert result.outcome == Outcome.OK
    assert recovery.backend.effects == ["delegate"]
    assert supervisor.native.calls == [], "The registered owner remains responsible for its inputs"


@pytest.mark.parametrize("field", ["boot_id", "service_owner", "event"])
def test_changed_host_identity_refuses_before_effect(supervisor, field):
    recovery = controller(supervisor)
    plan = recovery.prepare("keyboard")
    if field == "event":
        supervisor.native.report["devices"][0][field] = "event99"
    else:
        supervisor.native.report[field] = "changed"
    assert recovery.execute(plan, confirmed=True).outcome == Outcome.REFUSED
    assert supervisor.native.calls == []


def test_owner_script_changed_after_plan_is_not_executed(supervisor):
    recovery = controller(supervisor)
    recovery.backend.owner = {"name": "PhaseZero", "files": {"registered": "before"}}
    plan = recovery.prepare("keyboard")
    recovery.backend.owner["files"]["registered"] = "after"
    assert recovery.execute(plan, confirmed=True).outcome == Outcome.REFUSED
    assert recovery.backend.effects == []


def test_all_reports_each_capability_and_continues_audio_after_known_input_conflict(supervisor):
    recovery = controller(supervisor)
    supervisor.native.report["blockers"] = ["outro responsável reparando"]
    plan = recovery.prepare("all")
    result = recovery.execute(plan, confirmed=True)
    rows = result.effects["capabilities"]
    assert result.outcome == Outcome.PARTIAL and len(rows) == 8
    assert [r["key"] for r in rows if r["ready"]] == ["audio", "microphone"]
    assert recovery.backend.effects == ["audio", "microphone"]
    assert supervisor.native.calls == []


def test_active_game_is_never_stopped_and_cannot_be_made_green(supervisor):
    recovery = controller(supervisor)
    recovery.backend.owner = {"name": "PhaseZero", "files": {}}
    recovery.backend.active = True
    plan = recovery.prepare("keyboard")
    result = recovery.execute(plan, confirmed=True)
    assert result.outcome == Outcome.PARTIAL
    assert not result.effects["capabilities"][0]["ready"]
    assert recovery.backend.effects == []


def test_lost_delegate_response_blocks_next_operation_and_reconciliation_does_not_reapply(supervisor):
    recovery = controller(supervisor)
    recovery.backend.owner = {"name": "PhaseZero", "files": {}}
    recovery.backend.loss = True
    plan = recovery.prepare("keyboard")
    assert recovery.execute(plan, confirmed=True).outcome == Outcome.UNKNOWN
    assert recovery.reconcile(plan.operation_id).outcome == Outcome.UNKNOWN
    assert recovery.execute(recovery.prepare("audio"), confirmed=True).outcome == Outcome.REFUSED
    assert recovery.backend.effects == ["delegate"]
    assert plan.operation_id in supervisor.inspect()["pending_operations"]


def test_emergency_keyboard_remains_possible_without_repeating_pending_hardware(supervisor):
    recovery = controller(supervisor)
    recovery.backend.owner = {"name":"PhaseZero", "files":{}}
    recovery.backend.loss = True
    plan = recovery.prepare("touch")
    assert recovery.execute(plan, confirmed=True).outcome == Outcome.UNKNOWN
    result = recovery.execute(recovery.prepare("virtual-keyboard"), confirmed=True)
    assert result.outcome == Outcome.OK
    assert recovery.backend.effects == ["delegate", "virtual-keyboard"]
    assert plan.operation_id in supervisor.inspect()["pending_operations"]


def test_save_uses_healthy_baseline_and_preserves_input_grants(supervisor):
    recovery = controller(supervisor)
    supervisor.native.report["devices"][0]["enabled"] = True
    plan = recovery.prepare("all", save=True)
    result = recovery.execute(plan, confirmed=True)
    policy = supervisor.store.read()
    assert result.outcome == Outcome.OK
    assert plan.action == SAVE_ACTION and KEY in policy["baseline"]
    assert policy["enabled"] is False, "Saving is not permission to run a new automatic executor"


def test_save_never_learns_disabled_input_as_healthy(supervisor):
    recovery = controller(supervisor)
    result = recovery.execute(recovery.prepare("all", save=True), confirmed=True)
    assert result.outcome == Outcome.REFUSED
    assert supervisor.store.read()["baseline"] == {}


def test_keyboard_force_open_restores_visibility_mode_even_after_failure():
    class Native:
        qdbus = "qdbus"
        clock = staticmethod(lambda: 0)
        mode, visible = "1", False
        calls = []
        def props(self, *args):
            return {"available":"true", "mode":self.mode, "visible":"true" if self.visible else "false"}
        def call(self, args):
            self.calls.append(args)
            if args[-2] == "mode": self.mode = args[-1]
            elif args[-1].endswith("forceActivate"): self.visible = True
    native = Native()
    ready, detail = DesktopRecovery(native).open_keyboard({"backend":"kwin", "service_owner":":1.2"})
    assert ready and native.mode == "1" and native.visible
    assert native.calls[-1][-2:] == ["mode", "1"]


def test_audio_enables_only_reviewed_default_and_does_not_amplify_existing_volume():
    node = {"name":"alsa_output.test", "mute":True, "volume":{"left":{"value":32768}},
            "active_port":"speaker", "ports":[{"name":"speaker", "available":"yes"}]}
    effects = []
    def run(args, **kwargs):
        if args[1:4] == ["-f", "json", "list"]: out = json.dumps([node])
        elif args[1] == "get-default-sink": out = node["name"]
        else:
            effects.append(args)
            if args[1] == "set-sink-mute": node["mute"] = False
            out = ""
        return subprocess.CompletedProcess(args, 0, out, "")
    backend = DesktopRecovery(None, runner=run, which=lambda _: "pactl")
    targets = backend.audio_targets(["audio"])
    assert backend.enable_audio("audio", targets["audio"])[0]
    assert not any(args[1] == "set-sink-volume" for args in effects)
    assert all(node["name"] in args for args in effects)


def test_invalid_registration_does_not_execute_and_audio_stays_independent(supervisor):
    recovery = controller(supervisor)
    def bad(): raise ValueError("schema externo desconhecido")
    recovery.backend.peer = bad
    assert recovery.execute(recovery.prepare("audio"), confirmed=True).outcome == Outcome.OK
    result = recovery.execute(recovery.prepare("all"), confirmed=True)
    assert result.outcome == Outcome.PARTIAL
    assert [r["key"] for r in result.effects["capabilities"] if r["ready"]] == ["audio", "microphone"]


def test_owner_incomplete_repair_is_reported_without_claiming_success(supervisor):
    recovery = controller(supervisor)
    recovery.backend.owner = {"name": "PhaseZero", "files": {}}
    recovery.backend.delegate = lambda *args, **kwargs: "entrada não reabilitada"
    result = recovery.execute(recovery.prepare("keyboard"), confirmed=True)
    assert result.outcome == Outcome.PARTIAL
    assert "entrada não reabilitada" in result.reason
    assert not supervisor.native.calls


def test_owner_changed_between_capabilities_stops_input_effect(supervisor):
    recovery = controller(supervisor)
    recovery.backend.owner = {"name": "PhaseZero", "files": {}}
    def open_keyboard(report):
        recovery.backend.owner["files"]["script"] = "changed"
        return True, "visível"
    recovery.backend.open_keyboard = open_keyboard
    result = recovery.execute(recovery.prepare("all"), confirmed=True)
    rows = {r["key"]: r for r in result.effects["capabilities"]}
    assert not rows["touch"]["ready"] and "mudou" in rows["touch"]["reason"]
    assert rows["audio"]["ready"], "Independent audio does not acquire input ownership"


def test_audio_does_not_guess_after_failed_default_query_or_changed_identity():
    node = {"name":"source", "index":3, "properties":{"device.serial":"first"},
            "mute":True, "volume":{"mono":{"value":0}}}
    effects = []
    failure = False
    def run(args, **kwargs):
        if args[1] == "get-default-source":
            return subprocess.CompletedProcess(args, int(failure), "source", "")
        if args[1:4] == ["-f", "json", "list"]:
            return subprocess.CompletedProcess(args, 0, json.dumps([node]), "")
        effects.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")
    backend = DesktopRecovery(None, runner=run, which=lambda _: "pactl")
    target = backend.audio_targets(["microphone"])["microphone"]
    node["properties"]["device.serial"] = "replacement"
    assert not backend.enable_audio("microphone", target)[0]
    assert effects == []
    failure = True
    assert "error" in backend.audio_targets(["microphone"])["microphone"]


def test_zero_audio_gain_uses_bounded_initial_volume_and_verifies():
    node = {"name":"sink", "mute":True, "volume":{"mono":{"value":0}}}
    effects = []
    def run(args, **kwargs):
        if args[1:4] == ["-f", "json", "list"]: out = json.dumps([node])
        elif args[1] == "get-default-sink": out = "sink"
        else:
            effects.append(args)
            if args[1] == "set-sink-mute": node["mute"] = False
            if args[1] == "set-sink-volume": node["volume"]["mono"]["value"] = 16384
            out = ""
        return subprocess.CompletedProcess(args, 0, out, "")
    backend = DesktopRecovery(None, runner=run, which=lambda _: "pactl")
    target = backend.audio_targets(["audio"])["audio"]
    assert backend.enable_audio("audio", target)[0]
    assert ["pactl", "set-sink-volume", "sink", "25%"] in effects


def test_touch_helper_persistence_is_explicit_and_timeout_is_uncertain():
    effects = []
    def run(args, **kwargs):
        effects.append(args)
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])
    backend = DesktopRecovery(None, runner=run, which=lambda _: "bash")
    assert backend.persist_touch(None)[0] is False and not effects
    with pytest.raises(UncertainEffect):
        backend.persist_touch({"touch_helper":"/owner/reparo-entrada.sh", "command":["python3","/owner/desktop_session.py"]})
    assert effects == [["python3", "/owner/desktop_session.py", "persist-touch"]]


def test_touch_hardware_attempt_is_budgeted_before_effect_and_cannot_loop(supervisor):
    recovery = controller(supervisor)
    def repair(peer):
        assert supervisor.store.read()["attempts"][-1]["operation_id"] == plan.operation_id
        recovery.backend.effects.append("touch")
        return False, "FTS ausente"
    recovery.backend.repair_touch = repair
    plan = recovery.prepare("touch")
    assert recovery.execute(plan, confirmed=True).outcome == Outcome.PARTIAL
    again = recovery.execute(recovery.prepare("touch"), confirmed=True)
    assert again.outcome == Outcome.PARTIAL and "orçamento" in again.reason
    assert recovery.backend.effects == ["touch"]


def test_gamepad_requests_public_mode_without_stopping_steam(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kwargs: calls.append(argv))
    backend = DesktopRecovery(None, which=lambda _: "steam")
    ready, detail = backend.gamepad({"devices":[{"kinds":["gamepad"]}]})
    assert ready is False and "não confirmado" in detail
    assert calls == [["steam", "steam://open/bigpicture"]]
