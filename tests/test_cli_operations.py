import json

from folego import cli
from folego.orchestration.models import ActionPlan, ActionResult, Outcome, ResourceIdentity
from folego.orchestration.journal import Journal


def test_operation_query_preserves_id_and_effects_without_new_records(fake_home, capsys):
    journal = Journal()
    plan = ActionPlan("tmpfs.release", ResourceIdentity.entry("managed"), {"bytes": 4})
    journal.append_intent(plan)
    journal.append_result(ActionResult(plan.action, Outcome.OK, plan.operation_id,
                                       target_key=plan.target.key, effects={"bytes": 4}))
    before = journal.path.read_bytes()
    assert cli.main(["operation", plan.operation_id, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation_id"] == plan.operation_id
    assert payload["state"]["result"]["effects"] == {"bytes": 4}
    assert journal.path.read_bytes() == before


def test_pending_operation_query_is_unknown_and_does_not_reconcile_blindly(fake_home, capsys):
    journal = Journal()
    plan = ActionPlan("tmpfs.release", ResourceIdentity.entry("managed"), {"bytes": 4})
    journal.append_intent(plan)
    before = journal.path.read_bytes()
    assert cli.main(["operation", plan.operation_id, "--json"]) == 5
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "desconhecido"
    assert "não repetir" in payload["reason"]
    assert journal.path.read_bytes() == before


def test_query_missing_id_does_not_create_history(fake_home, capsys):
    journal = Journal()
    assert cli.main(["operation", "missing", "--json"]) == 5
    assert json.loads(capsys.readouterr().out)["state"] is None
    assert not journal.path.exists()


def test_accessibility_cli_refuses_plan_from_other_command(fake_home, capsys):
    plan = ActionPlan("accessibility.activate", ResourceIdentity.entry("all"), {})
    assert cli.main(["accessibility", "save-profile", "--plan", json.dumps(plan.to_dict()),
                     "--confirmar", "--json"]) != 0
    payload = json.loads(capsys.readouterr().out)
    assert "não corresponde" in payload["reason"]
    assert not Journal().path.exists()
