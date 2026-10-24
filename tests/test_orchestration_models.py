"""F2.1: contratos independentes de Qt, versionados e validados na entrada.

O que estes testes protegem é a fronteira: um plano que chega deformado de outra
camada não é executado, uma identidade de processo sem ``start_ticks`` não
autoriza nada (reuso de PID), um grant é fechado por construção (parâmetro fora
do limite não passa) e um resultado carrega o vocabulário combinado — inclusive
"parcial" e "desconhecido", que não podem virar "sucesso" no caminho.
"""
import pytest
from dataclasses import replace

from folego.orchestration.models import (SCHEMA, ActionPlan, ActionResult, Grant,
                                         OperationState, OperationStatus, Outcome,
                                         ResourceIdentity, ValidationError)


def a_plan(**over):
    base = {"action": "tmpfs.release",
            "target": ResourceIdentity.path("/tmp/agente-1000", dev=8, ino=42),
            "params": {"bytes": 4096}}
    base.update(over)
    return ActionPlan(**base)


# ---------------------------------------------------------------- identidades

def test_a_path_identity_roundtrips_with_dev_and_ino():
    ident = ResourceIdentity.path("/tmp/x", dev=8, ino=99)

    back = ResourceIdentity.from_dict(ident.to_dict())

    assert back == ident and back.detail == {"dev": 8, "ino": 99}


def test_a_process_identity_needs_pid_and_start_ticks():
    ident = ResourceIdentity.process(4321, 555)
    assert ident.to_dict()["key"] == "4321:555"

    with pytest.raises(ValidationError, match="start_ticks"):
        ResourceIdentity("process", "4321:555", {"pid": 4321})

    with pytest.raises(ValidationError, match="pid"):
        ResourceIdentity("process", "0:555", {"pid": 0, "start_ticks": 555})


def test_an_unknown_kind_is_refused():
    with pytest.raises(ValidationError, match="kind"):
        ResourceIdentity("qualquer", "x")


# ---------------------------------------------------------------------- planos

def test_a_plan_roundtrips_and_keeps_its_digest():
    plan = a_plan()

    back = ActionPlan.from_dict(plan.to_dict())

    assert back == plan
    assert back.digest == plan.digest


def test_plan_snapshot_is_deeply_immutable_and_detached_from_inputs():
    inputs = {"nested": {"items": [1, {"value": "approved"}]}}
    plan = a_plan(params=inputs)
    approved = plan.digest
    inputs["nested"]["items"][1]["value"] = "changed"
    assert plan.digest == approved
    with pytest.raises(TypeError):
        plan.params["nested"]["items"][1]["value"] = "changed"
    with pytest.raises(TypeError):
        plan.target.detail["ino"] = 99
    exported = plan.to_dict()
    exported["params"]["nested"]["items"][1]["value"] = "other"
    assert plan.digest == approved


@pytest.mark.parametrize("field,value", [("expires_at", 3000.0),
                                         ("operation_id", "other"),
                                         ("created_at", 1100.0)])
def test_new_digest_covers_validity_and_operation_identity(field, value):
    plan = a_plan(created_at=1000.0, expires_at=2000.0)
    row = plan.to_dict()
    row[field] = value
    with pytest.raises(ValidationError, match="digest"):
        ActionPlan.from_dict(row)


def test_legacy_plan_keeps_historical_digest_and_serialization():
    plan = a_plan(plan_version=1)
    row = plan.to_dict()
    assert "plan_version" not in row
    assert ActionPlan.from_dict(row).to_dict() == row


def test_a_plan_tampered_on_the_way_is_refused_by_the_digest():
    row = a_plan().to_dict()
    row["params"]["bytes"] = 10 ** 9

    with pytest.raises(ValidationError, match="digest"):
        ActionPlan.from_dict(row)


def test_a_plan_without_operation_id_generates_one():
    assert len(a_plan().operation_id) == 32


def test_a_plan_knows_when_it_expired():
    plan = a_plan(created_at=1000.0, expires_at=2000.0)

    assert plan.expired(now=1999.0) is False
    assert plan.expired(now=2000.0) is True
    assert a_plan(created_at=1000.0).expires_at == 1300.0
    assert a_plan(created_at=1000.0).expired(now=10 ** 9) is True


def test_an_expiry_before_creation_is_invalid():
    with pytest.raises(ValidationError, match="expires_at"):
        a_plan(created_at=2000.0, expires_at=1000.0)


def test_a_plan_without_a_valid_action_is_refused():
    with pytest.raises(ValidationError, match="action"):
        a_plan(action="sem-ponto")


# ---------------------------------------------------------------------- grants

def a_grant(**over):
    base = {"grant_id": "g-1", "action": "tmpfs.release",
            "resources": (a_plan().target,), "limits": {"bytes": 4096}, "issued_at": 1000.0,
            "expires_at": 5000.0}
    base.update(over)
    return Grant(**base)


def test_an_active_grant_is_covered_by_limits():
    covered, why = a_grant().covers(a_plan())

    assert covered is True and why == "coberto"


def test_a_grant_refuses_a_parameter_over_the_ceiling():
    covered, why = a_grant().covers(a_plan(params={"bytes": 4097, "volume": "/tmp"}))

    assert covered is False and "excede" in why


def test_a_grant_refuses_a_parameter_outside_its_list():
    grant = a_grant(limits={"volume": ["/tmp", "/run"]})
    covered, why = grant.covers(a_plan(params={"volume": "/home"}))

    assert covered is False and "lista" in why


def test_a_grant_refuses_a_missing_parameter():
    grant = a_grant(limits={"bytes": 4096, "volume": "/tmp"})
    covered, why = grant.covers(a_plan(params={"bytes": 1}))

    assert covered is False and "ausente" in why


def test_a_grant_refuses_another_action():
    covered, why = a_grant().covers(a_plan(action="tunings.apply"))

    assert covered is False and "fora do grant" in why


def test_grant_never_covers_empty_extra_or_negative_limits():
    assert not a_grant(limits={}).covers(a_plan())[0]
    assert not a_grant().covers(a_plan(params={"bytes": 1, "unapproved": True}))[0]
    assert not a_grant(limits={"bytes": -1}).covers(a_plan(params={"bytes": -2}))[0]
    assert not a_grant().covers(a_plan(params={"bytes": -1}))[0]


def test_grant_requires_exact_resource_identity_and_legacy_scope_stays_inactive():
    grant = a_grant()
    assert not grant.covers(a_plan(target=ResourceIdentity.path("/tmp/other", dev=8, ino=42)))[0]
    assert not grant.covers(a_plan(target=ResourceIdentity.path("/tmp/agente-1000", dev=8, ino=43)))[0]
    row = grant.to_dict()
    row.pop("resources")
    legacy = Grant.from_dict(row)
    assert not legacy.active(now=1100)
    assert not legacy.covers(a_plan())[0]


def test_a_revoked_or_expired_grant_is_inactive():
    assert a_grant(expires_at=1500.0).active(now=1600.0) is False
    assert a_grant(revoked_at=1200.0).active(now=1300.0) is False
    assert a_grant().active(now=1100.0) is True
    assert a_grant(expires_at=1500.0).active(now=1400.0) is True


def test_a_grant_roundtrips():
    grant = a_grant(expires_at=2000.0, source="preset")

    assert Grant.from_dict(grant.to_dict()) == grant


# -------------------------------------------------------------------- results

def test_the_outcome_vocabulary_is_the_agreed_one():
    assert {str(o) for o in Outcome} == {"sucesso", "parcial", "recusa", "falha",
                                         "cancelamento", "desconhecido"}


def test_a_result_roundtrips_with_effects_and_errors():
    result = ActionResult(action="tmpfs.release", outcome=Outcome.PARTIAL,
                          operation_id="op-1", reason="clone feito, origem não removida",
                          target_key="/tmp/x", started_at=1.0, finished_at=2.0,
                          effects={"bytes_transferred": 4096, "bytes_freed": 0},
                          errors=("origem não pôde ser removida",))

    back = ActionResult.from_dict(result.to_dict())

    assert back == result
    assert back.ok is False and back.partial is True


def test_an_unknown_outcome_is_refused():
    with pytest.raises(ValidationError, match="outcome"):
        ActionResult(action="tmpfs.release", outcome="mais ou menos")


def test_a_result_without_a_valid_action_is_refused():
    with pytest.raises(ValidationError, match="action"):
        ActionResult(action="", outcome=Outcome.OK)


# --------------------------------------------------------------------- estado

def test_operation_state_roundtrips():
    state = OperationState("op-1", OperationStatus.COMPLETED, intent=a_plan(),
                           result=ActionResult("tmpfs.release", Outcome.OK, "op-1"),
                           intent_seq=1, result_seq=2)

    assert OperationState.from_dict(state.to_dict()) == state


def test_an_unknown_operation_state_is_named_not_guessed():
    state = OperationState.unknown("op-9")

    assert state.status is OperationStatus.UNKNOWN
    assert state.intent is None and state.result is None


def test_a_future_schema_is_refused_on_every_contract():
    for model in (ResourceIdentity, ActionPlan, Grant, ActionResult, OperationState):
        row = {"schema": SCHEMA + 1}
        with pytest.raises(ValidationError, match="schema"):
            model.from_dict(row)
