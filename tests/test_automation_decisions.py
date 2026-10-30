"""F6 simulation records: 'executaria' is durable, execution is not."""
import json
import stat

from folego import cli
from folego.core.snapshot import OK, MemInfo, Snapshot, SourceQuality
from folego.orchestration.automation import (AGUARDAR, Candidate, evaluate)
from folego.orchestration.decisions import DecisionLog
from folego.orchestration.models import ActionPlan, Grant, ResourceIdentity

NOW = 10_000.0
MONO = 500.0


def plan(**over):
    base = {"action": "tmpfs.release",
            "target": ResourceIdentity.path("/tmp/folego-agente-1000", dev=8, ino=42),
            "params": {"bytes": 4096}, "created_at": NOW - 10,
            "expires_at": NOW + 60}
    base.update(over)
    return ActionPlan(**base)


def grant(**over):
    base = {"grant_id": "g-1", "action": "tmpfs.release",
            "resources": (plan().target,), "limits": {"bytes": 4096}, "issued_at": NOW - 100,
            "expires_at": NOW + 3600}
    base.update(over)
    return Grant(**base)


def snapshot():
    return Snapshot(ts=NOW, mem=MemInfo(1000, 500), swap_used_kb=0,
                    swap_total_kb=0, pressure_memory=None, pressure_io=None,
                    pressure_cpu=None, load=None, apps=(), self_rss_kb=1,
                    mono=MONO,
                    sources=(SourceQuality("meminfo", OK, "", MONO),))


def candidate(**over):
    base = dict(plan=plan(), owner_verified=True, sustained_samples=5,
                observed_for_s=600, boot_id="boot-a", last_boot_id="boot-a")
    base.update(over)
    return Candidate(**base)


def simulated():
    return evaluate(snapshot(), candidate(), mode="assistido",
                    preset="foco", grant=grant(), now=NOW, now_mono=MONO)


def test_a_simulated_decision_is_persisted_without_execution(tmp_path):
    log = DecisionLog(tmp_path / "decisions.jsonl", clock=lambda: NOW)
    decision = simulated()
    assert decision.simulated

    record = log.record(decision, mode="assistido", preset="foco", now=NOW)

    assert record["would_execute"] is True
    assert record["executed"] is False
    assert record["actor"] == "automation-simulacao"
    assert record["mode"] == "assistido" and record["preset"] == "foco"
    assert record["action"] == "tmpfs.release"
    assert record["target"]["key"] == "/tmp/folego-agente-1000"
    assert record["plan_digest"] == decision.plan.digest
    assert stat.S_IMODE(log.path.stat().st_mode) == 0o600
    assert log.recent(5) == [record]


def test_a_waiting_decision_is_not_written_as_would_execute(tmp_path):
    log = DecisionLog(tmp_path / "decisions.jsonl")
    decision = evaluate(snapshot(), candidate(sustained_samples=0),
                        mode="assistido", preset="foco", grant=grant(),
                        now=NOW, now_mono=MONO)
    assert decision.kind == AGUARDAR

    assert log.record(decision, mode="assistido", preset="foco") is None
    assert not log.path.exists()


def test_review_reads_only_the_requested_tail(tmp_path):
    log = DecisionLog(tmp_path / "decisions.jsonl", clock=lambda: NOW)
    decision = simulated()
    for i in range(8):
        log.record(decision, mode="assistido", preset="foco", actor=f"a{i}")

    rows = log.recent(3)
    assert [row["actor"] for row in rows] == ["a5", "a6", "a7"]


def test_the_decision_log_compacts_without_losing_records(tmp_path):
    log = DecisionLog(tmp_path / "decisions.jsonl", clock=lambda: NOW,
                      max_bytes=100)
    decision = simulated()
    for i in range(3):
        log.record(decision, mode="assistido", preset="foco", actor=f"a{i}")

    status = log.status()
    assert status["archive_count"] >= 1
    assert len(log.recent(10)) == 3
    assert len(log._archives()) == status["archive_count"]


def run(capsys, argv):
    code = cli.main(argv)
    captured = capsys.readouterr()
    payload = json.loads(captured.out) if captured.out.strip() else None
    return code, payload, captured


def test_cli_decisions_is_empty_and_read_only(fake_home, capsys):
    code, payload, _ = run(capsys, ["automation", "decisions", "--json"])
    assert code == cli.EXIT_OK
    assert payload["count"] == 0 and payload["decisions"] == []
    assert not (fake_home / ".local" / "state" / "folego").exists()


def test_cli_decisions_does_not_depend_on_a_valid_mode_record(fake_home, capsys):
    state = fake_home / ".local" / "state" / "folego"
    state.mkdir(parents=True)
    (state / "automation.json").write_text("lixo{")
    DecisionLog().record(simulated(), mode="assistido", preset="foco")

    code, payload, _ = run(capsys, ["automation", "decisions", "--json"])

    assert code == cli.EXIT_OK and payload["count"] == 1
    assert payload["decisions"][0]["executed"] is False
    assert "executaria" not in payload["decisions"][0], (
        "o JSON usa would_execute; o texto humano é que diz 'executaria'")
