"""M2 specs: the two Edge tunings whose keys were measured, not assumed.

Each spec names a file, a key path and a value. Everything below is checked
against the real machine: the key names come from ``strings`` over the installed
binary, and the splice is rehearsed on a copy of the real Local State so a
surprise in that 36 kB document surfaces in a test rather than in the profile.
"""
import difflib
import json
from pathlib import Path

import pytest

from deck_wellness import paths
from deck_wellness.actions.tunings.engine import TuningEngine
from deck_wellness.actions.tunings.registry import TUNINGS, tuning_by_id
from deck_wellness.actions.tunings.specs.background_mode import BACKGROUND_MODE
from deck_wellness.actions.tunings.specs.startup_boost import STARTUP_BOOST
from deck_wellness.safely.jsonedit import set_value

REAL_LOCAL_STATE = Path.home() / ".config" / "microsoft-edge" / "Local State"


def minified(doc: dict) -> bytes:
    return json.dumps(doc, separators=(",", ":")).encode()


@pytest.fixture
def edge(fake_home):
    cfg = fake_home / ".config" / "microsoft-edge"
    (cfg / "Default").mkdir(parents=True)
    return cfg


@pytest.fixture
def engine(edge):
    return TuningEngine(edge_running=lambda: None)


# ------------------------------------------------------------------- registry

def test_the_registry_lists_the_tunings_the_host_probe_confirmed():
    assert [t.id for t in TUNINGS] == ["edge.background_mode", "edge.startup_boost"]
    assert tuning_by_id("edge.startup_boost") is STARTUP_BOOST


def test_every_registered_tuning_names_its_why_in_portuguese():
    """The user reads these lines before clicking; an empty why is an unexplained
    mutation."""
    for tuning in TUNINGS:
        assert tuning.label and tuning.why
        assert tuning.why[-1] not in " "


# ------------------------------------------------------------- the two targets

def test_startup_boost_lives_in_local_state_and_background_mode_in_the_profile():
    assert STARTUP_BOOST.key_path == ("startup_boost", "enabled")
    assert BACKGROUND_MODE.key_path == ("background_mode", "enabled")
    assert STARTUP_BOOST.target() == paths.edge_local_state()
    assert BACKGROUND_MODE.target() == paths.edge_profile_preferences("Default")
    assert BACKGROUND_MODE.target() != STARTUP_BOOST.target()


def test_a_missing_profile_file_is_detected_as_absent_never_created(edge, engine):
    det = engine.detect(BACKGROUND_MODE)

    assert det.exists is False and det.change_needed is False
    assert "não existe" in det.error


def test_an_absent_background_key_is_planned_into_the_existing_profile_file(edge, engine):
    (edge / "Default" / "Preferences").write_bytes(
        minified({"session": {"restore_on_startup": 5}, "a": 1}))

    det = engine.detect(BACKGROUND_MODE)
    plan = engine.plan(det)

    assert det.present is False and det.change_needed
    doc = json.loads(minified({"background_mode": {"enabled": False},
                               "session": {"restore_on_startup": 5}, "a": 1}))
    assert plan.after_sha
    assert json.loads(set_value((edge / "Default" / "Preferences").read_bytes(),
                                BACKGROUND_MODE.key_path, False)) == doc
    assert b'"session":{"restore_on_startup":5}' in set_value(
        (edge / "Default" / "Preferences").read_bytes(), BACKGROUND_MODE.key_path, False)


def test_both_tunings_refuse_to_write_while_the_browser_is_open(edge, engine):
    (edge / "Local State").write_bytes(minified({"startup_boost": {"enabled": True}}))
    (edge / "Default" / "Preferences").write_bytes(minified({"session": {}}))
    open_edge = TuningEngine(edge_running=lambda: "pid 4321 · msedge · /opt/microsoft/msedge/msedge")

    for tuning in TUNINGS:
        plan = open_edge.plan(open_edge.detect(tuning))
        result = open_edge.apply(plan, confirm=True)
        assert result.ok is False and "Edge está aberto" in result.reason


def test_neither_tuning_would_write_a_file_outside_the_edge_directory(fake_home, tmp_path):
    from dataclasses import replace

    outside = tmp_path / "Preferences"
    outside.write_bytes(minified({"background_mode": {"enabled": True}}))
    stranger = replace(BACKGROUND_MODE, target=lambda: outside)
    engine = TuningEngine(edge_running=lambda: None,
                          config_root=fake_home / ".config" / "microsoft-edge")

    plan = engine.plan(engine.detect(stranger))

    assert plan.blocked and "outside every allowed root" in plan.blocked
    assert outside.read_bytes() == minified({"background_mode": {"enabled": True}})


# ------------------------------------------------- rehearsed on the real document

@pytest.mark.skipif(not REAL_LOCAL_STATE.is_file(), reason="Edge não está instalado")
def test_the_real_local_state_is_edited_inside_one_object_only():
    """One contiguous diff, inside startup_boost, everything else untouched — the
    claim the whole splicer exists to keep."""
    data = REAL_LOCAL_STATE.read_bytes()

    out = set_value(data, STARTUP_BOOST.key_path, False)

    diffs = [op for op in difflib.SequenceMatcher(None, data, out).get_opcodes()
             if op[0] != "equal"]
    assert len(diffs) == 1, f"mais de uma região mudou: {diffs}"
    kind, i1, i2, j1, j2 = diffs[0]
    assert kind in ("insert", "replace")
    assert i1 > data.index(b'"startup_boost":{'), "a edição escapou do objeto"
    assert json.loads(out)["startup_boost"]["enabled"] is False


@pytest.mark.skipif(not REAL_LOCAL_STATE.is_file(), reason="Edge não está instalado")
def test_the_real_document_keeps_every_other_section_byte_identical():
    data = REAL_LOCAL_STATE.read_bytes()
    doc = json.loads(data)

    out = set_value(data, STARTUP_BOOST.key_path, False)
    edited = json.loads(out)

    assert {k: v for k, v in edited.items() if k != "startup_boost"} == \
           {k: v for k, v in doc.items() if k != "startup_boost"}
    assert out.endswith(b"}")
    boost = doc.get("startup_boost", {})
    if "enabled" in boost:
        expected_growth = 5 - len(json.dumps(boost["enabled"], separators=(",", ":")))
    else:
        expected_growth = len(b'"enabled":false,')
    assert len(out) - len(data) == expected_growth
