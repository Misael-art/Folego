"""F3.5: user exclusions by identity, including the stronger keep-alive flag."""
import json

import pytest

from folego.core.exclusions import ExclusionError, ExclusionList
from fixtures_proc import proc_info


def test_absent_file_means_no_exclusions_and_creates_nothing(tmp_path):
    ledger = ExclusionList(tmp_path / "exclusions.json")
    assert ledger.list() == ()
    assert ledger.reason(proc_info(500, comm="anything")) is None
    assert not ledger.path.exists()
    assert not ledger._lock_path.exists(), "reading must not create a state sidecar"


def test_app_and_keep_active_are_persisted(tmp_path):
    path = tmp_path / "exclusions.json"
    ledger = ExclusionList(path)
    item = ledger.add("app", "my-build", keep_active=True)

    reason = ledger.reason(proc_info(500, comm="my-build"))
    assert reason == "exclusão app:my-build (manter ativo)"

    reloaded = ExclusionList(path)
    assert reloaded.list() == (item,)
    assert json.loads(path.read_text())["version"] == 1


def test_app_matches_the_executable_basename_not_only_comm(tmp_path):
    ledger = ExclusionList(tmp_path / "exclusions.json")
    ledger.add("app", "ninja")
    proc = proc_info(500, comm="build", cmdline=["/usr/bin/ninja", "-j4"])

    assert "ninja" in (ledger.reason(proc) or "")


def test_project_requires_the_session_project(tmp_path):
    ledger = ExclusionList(tmp_path / "exclusions.json")
    ledger.add("project", "Folego")
    proc = proc_info(500, comm="worker")

    assert ledger.reason(proc) is None
    assert ledger.reason(proc, project="folego") == "exclusão project:Folego"


def test_cmdline_path_and_session_kinds(tmp_path):
    proc = proc_info(500, comm="worker",
                     cmdline=["/usr/bin/worker", "--dangerous",
                              "/home/u/project/file"])
    cases = (("cmdline", "--dangerous", ""),
             ("path", "/home/u/project", ""),
             ("session", "abc", "abc"))
    for kind, value, session_id in cases:
        ledger = ExclusionList(tmp_path / f"{kind}.json")
        ledger.add(kind, value)
        reason = ledger.reason(proc, session_id=session_id)
        assert kind in (reason or ""), (kind, reason)


def test_remove_is_by_id_and_idempotent(tmp_path):
    ledger = ExclusionList(tmp_path / "exclusions.json")
    item = ledger.add("app", "x")

    assert ledger.remove(item.exclusion_id) is True
    assert ledger.remove(item.exclusion_id) is False
    assert ledger.list() == ()


def test_a_corrupt_file_fails_closed(tmp_path):
    path = tmp_path / "exclusions.json"
    path.write_text("{not json")
    ledger = ExclusionList(path)

    with pytest.raises(ExclusionError):
        ledger.list()
    assert "ilegíveis" in (ledger.reason(proc_info(500, comm="x")) or "")


def test_unknown_kind_is_refused(tmp_path):
    ledger = ExclusionList(tmp_path / "exclusions.json")
    with pytest.raises(ExclusionError):
        ledger.add("pid", "500")
