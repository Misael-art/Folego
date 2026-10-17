"""M2 engine, part 1: what is a tuning right now, and what would change write?

Detection has to separate three states that look alike in a file listing: the key
is present and already economical, the key is present and costs RAM, and the key
is absent because the browser is deciding by itself (a signed-in Edge turns
Startup boost on without ever writing the key). Only the third and second can be
planned; the first has nothing to do.

A file that does not parse, or does not exist, is never "repaired" here: writing
a JSON document we could not read is how a profile gets destroyed.
"""
import hashlib
import json

import pytest

from folego import paths
from folego.actions.tunings.engine import TuningEngine
from folego.actions.tunings.specs.startup_boost import STARTUP_BOOST
from folego.safely.audit import AuditLog
from folego.safely.backup import BackupStore


def minified(doc: dict) -> bytes:
    return json.dumps(doc, separators=(",", ":")).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def edge(fake_home):
    cfg = fake_home / ".config" / "microsoft-edge"
    cfg.mkdir(parents=True)
    return cfg


@pytest.fixture
def engine(fake_home):
    return TuningEngine(backup=BackupStore(paths.backup_dir()), audit=None)


def local_state(edge, doc):
    (edge / "Local State").write_bytes(minified(doc))
    return edge / "Local State"


# ------------------------------------------------------------------- detection

def test_a_present_key_is_read_at_its_exact_path(edge, engine):
    local_state(edge, {"startup_boost": {"enabled": True, "last_browser_open_time": "1"}})

    det = engine.detect(STARTUP_BOOST)

    assert det.exists and det.parses and det.present
    assert det.current is True
    assert det.change_needed is True


def test_a_key_already_at_its_desired_value_needs_no_change(edge, engine):
    local_state(edge, {"startup_boost": {"enabled": False}})

    det = engine.detect(STARTUP_BOOST)

    assert det.present and det.current is False
    assert det.change_needed is False


def test_an_absent_key_is_the_browsers_own_default_not_an_off_value(edge, engine):
    """Measured on the host: Local State holds startup_boost.last_browser_open_time
    and no enabled key at all, while the browser runs the boost because the user
    is signed in."""
    local_state(edge, {"startup_boost": {"last_browser_open_time": "13436417322947411"}})

    det = engine.detect(STARTUP_BOOST)

    assert det.exists and det.parses
    assert det.present is False and det.current is None
    assert det.change_needed is True


def test_a_missing_file_is_reported_not_assumed_empty(edge, engine):
    det = engine.detect(STARTUP_BOOST)

    assert det.exists is False
    assert det.change_needed is False
    assert "não existe" in det.error


def test_a_file_that_does_not_parse_is_refused_with_the_reader_error(edge, engine):
    (edge / "Local State").write_bytes(b'{"startup_boost":{"enabled":tru,')

    det = engine.detect(STARTUP_BOOST)

    assert det.exists and det.parses is False
    assert det.change_needed is False
    assert det.error


# ------------------------------------------------------------------------ plan

def test_a_desired_state_has_no_plan_at_all(edge, engine):
    local_state(edge, {"startup_boost": {"enabled": False}})

    assert engine.plan(engine.detect(STARTUP_BOOST)) is None


def test_the_plan_is_blocked_when_the_file_is_missing(edge, engine):
    plan = engine.plan(engine.detect(STARTUP_BOOST))

    assert plan is not None and plan.blocked


def test_the_plan_predicts_the_exact_bytes_and_both_digests(edge, engine):
    path = local_state(edge, {"startup_boost": {"last_browser_open_time": "1"}, "c": 1})

    plan = engine.plan(engine.detect(STARTUP_BOOST))

    assert plan.blocked is None
    assert plan.target == path
    assert plan.before_sha == sha(path.read_bytes())
    assert plan.after_sha == sha(minified({"startup_boost": {"enabled": False, "last_browser_open_time": "1"}, "c": 1}))
    assert plan.tuning is STARTUP_BOOST


def test_the_plan_carries_the_why_the_user_reads_before_clicking(edge, engine):
    local_state(edge, {"startup_boost": {"enabled": True}})

    plan = engine.plan(engine.detect(STARTUP_BOOST))

    assert plan.label and plan.why
    assert "Edge" in plan.label


def test_a_plan_for_a_file_that_does_not_parse_is_blocked(edge, engine):
    (edge / "Local State").write_bytes(b"{oops")

    plan = engine.plan(engine.detect(STARTUP_BOOST))

    assert plan is not None and plan.blocked


# ----------------------------------------------------------------------- apply

OPEN_EDGE = "pid 4321 msedge --profile-directory=Default"


@pytest.fixture
def live(edge):
    """An engine with the real seams: audit trail, backup store, Edge probe."""
    from types import SimpleNamespace

    from folego.safely.atomicfile import write_atomic

    state = {"running": None, "write": write_atomic}
    engine = TuningEngine(backup=BackupStore(paths.backup_dir()), audit=AuditLog(),
                          edge_running=lambda: state["running"],
                          write_fn=lambda path, data: state["write"](path, data))
    return SimpleNamespace(engine=engine, edge=edge, state=state)


def a_planned_tuning(live):
    local_state(live.edge, {"startup_boost": {"enabled": True, "last_browser_open_time": "1"}})
    return live.engine.plan(live.engine.detect(STARTUP_BOOST))


def test_apply_writes_nothing_without_an_explicit_confirmation(live):
    plan = a_planned_tuning(live)
    before = plan.target.read_bytes()

    result = live.engine.apply(plan)

    assert result.ok is False and "confirma" in result.reason.lower()
    assert plan.target.read_bytes() == before


def test_apply_refuses_while_the_browser_is_open_and_says_why(live):
    plan = a_planned_tuning(live)
    before = plan.target.read_bytes()
    live.state["running"] = OPEN_EDGE

    result = live.engine.apply(plan, confirm=True)

    assert result.ok is False
    assert "4321" in result.reason and "feche" in result.reason.lower()
    assert plan.target.read_bytes() == before, "an open Edge would re-save over us"


def test_apply_refusal_lands_in_the_audit_trail(live):
    plan = a_planned_tuning(live)
    live.state["running"] = OPEN_EDGE

    live.engine.apply(plan, confirm=True)

    records = AuditLog().tail(5)
    assert records[-1]["kind"] == "tuning.apply"
    assert records[-1]["outcome"] == "refused"
    assert records[-1]["action_id"] == "tunings.edge.startup_boost"


def test_apply_backs_the_original_bytes_up_before_touching_anything(live):
    plan = a_planned_tuning(live)
    original = plan.target.read_bytes()

    result = live.engine.apply(plan, confirm=True)

    store = BackupStore(paths.backup_dir())
    entry = store.read_manifest(result.backup_id)["entries"][0]
    payload = store.path_of(result.backup_id) / entry["stored"]
    assert entry["sha_before"] == plan.before_sha
    assert payload.read_bytes() == original


def test_apply_writes_the_planned_value_and_keeps_the_neighbour(live):
    plan = a_planned_tuning(live)

    result = live.engine.apply(plan, confirm=True)

    assert result.ok and result.sha == plan.after_sha
    doc = json.loads(plan.target.read_bytes())
    assert doc["startup_boost"]["enabled"] is False
    assert doc["startup_boost"]["last_browser_open_time"] == "1"
    record = AuditLog().tail(1)[0]
    assert record["outcome"] == "applied"
    assert record["risk"] == "reversible"
    assert record["backup_id"] == result.backup_id


def test_apply_refuses_a_file_that_changed_after_the_plan(live):
    plan = a_planned_tuning(live)
    live.edge.joinpath("Local State").write_bytes(
        minified({"startup_boost": {"enabled": True, "last_browser_open_time": "9"}}))

    result = live.engine.apply(plan, confirm=True)

    assert result.ok is False and "mudou" in result.reason
    assert json.loads(plan.target.read_bytes())["startup_boost"]["last_browser_open_time"] == "9"


def test_a_write_that_lands_wrong_is_reverted_from_the_backup(live):
    plan = a_planned_tuning(live)
    original = plan.target.read_bytes()
    live.state["write"] = write_half

    result = live.engine.apply(plan, confirm=True)

    assert result.ok is False and "verificação" in result.reason
    assert plan.target.read_bytes() == original, "a wrong write must not survive"
    assert AuditLog().tail(1)[0]["outcome"] == "verify_failed_reverted"


def write_half(path, data):
    from folego.safely.atomicfile import WriteResult, write_atomic
    result = write_atomic(path, data[: len(data) // 2])
    return WriteResult(sha256=result.sha256, size=result.size)


# ---------------------------------------------------------------------- revert

def test_revert_restores_the_original_bytes_byte_for_byte(live):
    plan = a_planned_tuning(live)
    applied = live.engine.apply(plan, confirm=True)

    back = live.engine.revert(STARTUP_BOOST)

    assert back.ok and back.sha == plan.before_sha
    assert plan.target.read_bytes() == minified(
        {"startup_boost": {"enabled": True, "last_browser_open_time": "1"}})
    assert applied.backup_id == back.backup_id


def test_revert_warns_before_discarding_a_change_we_did_not_make(live):
    plan = a_planned_tuning(live)
    live.engine.apply(plan, confirm=True)
    live.edge.joinpath("Local State").write_bytes(
        minified({"startup_boost": {"enabled": False, "user_added": "coisa do usuário"}}))

    back = live.engine.revert(STARTUP_BOOST)

    assert back.ok is False and "mudou" in back.reason
    assert "user_added" in plan.target.read_bytes().decode()


def test_revert_with_no_backup_says_so(live):
    local_state(live.edge, {"startup_boost": {"enabled": False}})

    back = live.engine.revert(STARTUP_BOOST)

    assert back.ok is False and "backup" in back.reason


# ----------------------------------------------------------------- persistence

def test_verify_confirms_the_tuned_file_still_holds(live):
    plan = a_planned_tuning(live)
    live.engine.apply(plan, confirm=True)

    check = live.engine.verify(plan)

    assert check.ok is True and "persiste" in check.message


def test_verify_flags_the_file_the_browser_rewrote_on_exit(live):
    plan = a_planned_tuning(live)
    live.engine.apply(plan, confirm=True)
    live.edge.joinpath("Local State").write_bytes(minified(
        {"startup_boost": {"enabled": True, "last_browser_open_time": "1"}}))

    check = live.engine.verify(plan)

    assert check.ok is False
    assert "sobrescrito" in check.message and "reaplicar" in check.message


# ----------------------------------------------------------------------- guard

def test_a_symlinked_local_state_is_refused_before_it_is_written(live, tmp_path):
    """Real hosts are full of symlinked browser dirs; following one would write
    outside the audited root."""
    elsewhere = tmp_path / "outro"
    elsewhere.write_bytes(minified({"startup_boost": {"enabled": True}}))
    link = live.edge / "Local State"
    link.unlink(missing_ok=True)
    link.symlink_to(elsewhere)

    plan = live.engine.plan(live.engine.detect(STARTUP_BOOST))

    assert plan.blocked and "symlink" in plan.blocked
    assert elsewhere.read_bytes() == minified({"startup_boost": {"enabled": True}})
