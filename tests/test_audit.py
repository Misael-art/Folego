import json
import stat

import pytest

from folego.safely import audit


def test_append_creates_jsonl_with_0600_and_uuid(fake_home):
    fake_home  # noqa: fixture installs env; paths resolve under tmp HOME
    log = audit.AuditLog()
    log.append(kind="apply", action_id="edge_startup_boost", outcome="ok",
               targets=["/x/Local State"], risk="low", backup_id="a/1-2")
    p = log.path
    assert p.exists()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    rec = json.loads(p.read_text().strip())
    assert rec["kind"] == "apply" and rec["action_id"] == "edge_startup_boost"
    assert len(rec["event_id"]) >= 8 and rec["ts"].endswith("Z")


def test_append_requires_kind_action_and_outcome(fake_home):
    log = audit.AuditLog()
    with pytest.raises(ValueError):
        log.append(kind="apply")


def test_tail_returns_last_records_in_order(fake_home):
    log = audit.AuditLog()
    for i in range(5):
        log.append(kind="kill", action_id=f"a{i}", outcome="ok")
    records = log.tail(2)
    assert [r["action_id"] for r in records] == ["a3", "a4"]


def test_corrupt_line_does_not_break_tail(fake_home):
    log = audit.AuditLog()
    log.append(kind="revert", action_id="bom", outcome="ok")
    with open(log.path, "a") as f:
        f.write("{truncado\n")
    records = log.tail(10)
    assert [r["action_id"] for r in records] == ["bom"]
