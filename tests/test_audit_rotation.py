"""F8 audit rotation: bounded active file, compressed archive, no lost event."""
import gzip
import json
from concurrent.futures import ThreadPoolExecutor

from folego import cli
from folego.safely.audit import AuditLog


def add(log, n=1):
    for i in range(n):
        log.append(kind="test", action_id=f"a{i}", outcome="ok")


def test_rotation_compacts_the_active_file_and_preserves_every_record(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", max_bytes=10_000)
    add(log, 5)
    before = log.tail(10)
    assert len(before) == 5

    result = log.rotate(now=1_700_000_000)

    assert result["rotated"] is True
    assert result["active_bytes_after"] == 0
    archive = tmp_path / "audit-20231114T221320Z.jsonl.gz"
    assert archive.exists()
    with gzip.open(archive, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    assert [row["action_id"] for row in rows] == [f"a{i}" for i in range(5)]
    assert len(log.archived_records()) == 5
    assert log.tail(10) == [], "o ativo recomeçou vazio"


def test_append_after_rotation_starts_a_new_active_file(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", max_bytes=10_000)
    add(log, 1)
    log.rotate(now=1_700_000_000)
    add(log, 1)
    assert len(log.tail(10)) == 1
    assert len(log.archived_records()) == 2


def test_the_active_file_rotates_by_budget_before_append(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", max_bytes=80)
    add(log, 3)
    status = log.status()
    assert status["archive_count"] >= 2, "cada append acima do teto rotaciona o anterior"
    assert status["active_bytes"] > 0
    assert len(log.archived_records()) == 3


def test_rotation_is_idempotent_when_the_active_file_is_empty(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", max_bytes=10_000)
    assert log.rotate(now=1_700_000_000)["rotated"] is False
    assert log.status()["archive_count"] == 0


def test_rotation_keeps_old_archives_instead_of_deleting_evidence(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", max_bytes=10_000)
    add(log, 1)
    first = log.rotate(now=1_700_000_000)["archive"]
    add(log, 1)
    second = log.rotate(now=1_700_000_001)["archive"]

    assert first != second
    assert len(log.status()["archives"]) == 2
    assert len(log.archived_records()) == 2


def test_concurrent_appends_and_rotation_do_not_lose_records(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl", max_bytes=10_000)

    def writer(worker):
        for i in range(20):
            log.append(kind="test", action_id=f"{worker}-{i}", outcome="ok")

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(writer, worker) for worker in range(4)]
        for future in futures:
            future.result()
        log.rotate(now=1_700_000_000)

    records = log.archived_records()
    assert len(records) == 80
    assert len({row["action_id"] for row in records}) == 80


# ------------------------------------------------------------------------- CLI

def run(capsys, argv):
    code = cli.main(argv)
    captured = capsys.readouterr()
    payload = json.loads(captured.out) if captured.out.strip() else None
    return code, payload, captured


def test_cli_logs_status_and_dry_run_do_not_rotate(fake_home, capsys):
    log = AuditLog()
    add(log, 1)

    code, payload, _ = run(capsys, ["logs", "status", "--json"])
    assert code == cli.EXIT_OK and payload["active_bytes"] > 0
    assert payload["archive_count"] == 0

    code, payload, _ = run(capsys, ["logs", "rotate", "--json"])
    assert code == cli.EXIT_OK and payload["rotated"] is False
    assert log.status()["active_bytes"] > 0


def test_cli_logs_rotate_confirms_and_lists_the_archive(fake_home, capsys):
    add(AuditLog(), 2)

    code, payload, _ = run(capsys, ["logs", "rotate", "--confirmar", "--json"])
    assert code == cli.EXIT_OK and payload["rotated"] is True
    assert payload["active_bytes_after"] == 0

    code, payload, _ = run(capsys, ["logs", "archives", "--json"])
    assert code == cli.EXIT_OK and payload["archive_count"] == 1
    assert payload["archives"][0]["path"].endswith(".jsonl.gz")
