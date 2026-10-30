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
