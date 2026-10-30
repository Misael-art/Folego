import copy
import time

from folego.ui.accessibility_tab import AccessibilityTab, access_argv
from folego.orchestration.models import ActionPlan, ResourceIdentity


def sample():
    plan = ActionPlan("accessibility.enable-input", ResourceIdentity.entry("device"),
                      {"name": "USB Keyboard"}).to_dict()
    return {"schema": 1, "mono": time.monotonic(), "backend": "kwin", "policy": {"enabled": False},
            "cards": [{"key": "keyboard", "state": "degraded", "detail": "desabilitado"}],
            "plans": [plan], "pending_operations": [], "blockers": []}


class Jobs:
    def __init__(self, response=None):
        self.calls = []
        self.response = response
    def run(self, action, target, *, confirm=False, done):
        self.calls.append((action, target, confirm))
        if self.response is not None:
            done(self.response)
    def shutdown(self):
        pass


def test_panel_explains_capabilities_and_unknown_sources_without_green_defaults(qapp):
    view = AccessibilityTab(jobs=Jobs())
    view.show_report(sample())
    assert "Revisão necessária" in view.cards["keyboard"].text()
    assert "Desconhecido" in view.cards["touch"].text()
    view.show_error("compositor absent")
    assert not view.repair_button.isEnabled()
    assert all("Desconhecido" in label.text() for label in view.cards.values())


def test_parent_retains_plan_id_after_timeout_and_refresh_cannot_allow_repeat(qapp):
    jobs = Jobs({"outcome": "desconhecido", "reason": "timeout"})
    value = sample()
    view = AccessibilityTab(jobs=jobs, inspect_fn=lambda: value, confirm_fn=lambda *a: True)
    view.show_report(value)
    view.repair_selected()
    assert view._pending == value["plans"][0]["operation_id"]
    assert "não repetir" in view.status.text()
    view.show_report(value)
    assert not view.repair_button.isEnabled() and view.reconcile_button.isEnabled()
    view.repair_selected()
    assert len(jobs.calls) == 1
    view.stop()


def test_stale_cards_invalidate_repair_and_keep_last_result_visible(qapp):
    jobs = Jobs()
    view = AccessibilityTab(jobs=jobs, confirm_fn=lambda *a: True)
    value = sample(); value["mono"] -= 30
    view.show_report(value)
    view.repair_selected()
    assert not jobs.calls and "antiga" in view.status.text()
    assert not view.repair_button.isEnabled()


def test_manual_cancel_and_waiting_owner_never_issue_mutation(qapp):
    jobs = Jobs()
    view = AccessibilityTab(jobs=jobs, confirm_fn=lambda *a: False)
    view.show_report(sample()); view.repair_selected()
    assert not jobs.calls
    value = sample(); value.update(plans=[], blockers=["Other app repairing"])
    view.show_report(value)
    assert not view.repair_button.isEnabled() and "Other app" in view.providers.text()


def test_reconciliation_uses_same_id_and_explicit_settings_are_separate(qapp):
    jobs = Jobs()
    view = AccessibilityTab(jobs=jobs, confirm_fn=lambda *a: True)
    view._pending = "original"
    view.reconcile()
    assert jobs.calls == [("accessibility-reconcile", "original", False)]
    assert access_argv("accessibility-repair", '{"operation_id":"original"}', True)[-3:] == [
        "--plan", '{"operation_id":"original"}', "--confirmar"]


def test_unknown_protocol_or_wrong_operation_never_clears_pending_id(qapp):
    view = AccessibilityTab(jobs=Jobs())
    view._pending = "original"
    view.completed({"operation_id": "other", "outcome": "sucesso"})
    assert view._pending == "original" and "desconhecido" in view.status.text()
    view.completed({"unexpected": "legacy"})
    assert view._pending == "original"


def test_cards_are_buttons_and_primary_action_stays_available_with_observer(qapp):
    from PySide6.QtWidgets import QPushButton
    jobs = Jobs()
    view = AccessibilityTab(jobs=jobs)
    value = sample(); value.update(plans=[], blockers=["PhaseZero ativo"])
    view.show_report(value)
    assert all(isinstance(card, QPushButton) for card in view.cards.values())
    assert view.enable_all_button.isEnabled()
    assert not view.native_controls.isVisible(), "No unusable repair selector in the default flow"
    view.cards["touch"].click()
    assert jobs.calls[0][0] == "accessibility-activation-plan"
    assert '"touch"' in jobs.calls[0][1]
    assert view.cards["touch"].property("recovery") != "ready"


def test_click_does_not_turn_green_and_only_matching_verified_result_does(qapp):
    import json
    jobs = Jobs()
    view = AccessibilityTab(jobs=jobs)
    plan = ActionPlan("accessibility.activate", ResourceIdentity.entry("keyboard"),
                      {"capabilities":["keyboard"]}).to_dict()
    view.activate("keyboard")
    view.activation_planned("keyboard", False, {"plan":plan})
    assert view.cards["keyboard"].property("recovery") == "busy"
    view.completed({"operation_id":"wrong", "outcome":"sucesso"})
    assert view._pending == plan["operation_id"]
    assert view.cards["keyboard"].property("recovery") == "attention"
    view.completed({"operation_id":plan["operation_id"], "outcome":"sucesso", "reason":"verificado",
        "effects":{"boot_id":"boot", "service_owner":":1.2", "capabilities":[{
            "key":"keyboard", "ready":True, "outcome":"sucesso", "reason":"habilitado"}]}})
    assert view.cards["keyboard"].property("recovery") == "ready"
    assert not view._pending
    view.stop()


def test_verify_has_immediate_and_completed_summary_outside_scrolling(qapp):
    view = AccessibilityTab(jobs=Jobs(), inspect_fn=sample)
    view.refresh()
    assert "Verificando" in view.status.text()
    view.show_report(sample())
    assert "Verificado às" in view.status.text()
    assert not view.scroll.isAncestorOf(view.status)
    assert not view.scroll.isAncestorOf(view.enable_all_button)
    assert not view.scroll.isAncestorOf(view.capture_button)
    view.stop()


def test_pending_hardware_does_not_disable_keyboard_escape_or_lose_original_id(qapp):
    view = AccessibilityTab(jobs=Jobs())
    value=sample(); value["pending_operations"]=["hardware-id"]
    view.show_report(value)
    assert not view.cards["touch"].isEnabled()
    assert view.cards["virtual-keyboard"].isEnabled()
    view.activate("virtual-keyboard")
    assert view.keyboard_test.isVisibleTo(view) and view._emergency_previous=="hardware-id"
    plan=ActionPlan("accessibility.activate",ResourceIdentity.entry("virtual-keyboard"),{}).to_dict()
    view.activation_planned("virtual-keyboard",False,{"plan":plan})
    view.completed({"operation_id":plan["operation_id"],"outcome":"parcial","reason":"teclado"})
    assert view._pending=="hardware-id" and view.cards["virtual-keyboard"].isEnabled()
    view.stop()
