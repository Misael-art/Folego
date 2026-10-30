import json
import os

import pytest

from folego.orchestration.history import HistoryReader, LINE_LIMIT, READ_BUDGET
from folego.orchestration.journal import Journal
from folego.orchestration.models import ActionResult, Outcome


def record(seq, reason="fixture"):
    result = ActionResult("disk.quarantine", Outcome.OK, f"op-{seq}", reason, "fixture")
    return json.dumps({"schema": 1, "seq": seq, "ts": 1700000000,
                       "kind": "result", "operation_id": result.operation_id,
                       "result": result.to_dict()}).encode() + b"\n"


def finish(reader):
    for _ in range(200):
        before = reader.bytes_read
        text = reader.refresh()
        assert reader.bytes_read - before <= READ_BUDGET
        assert len(reader.buffer) <= LINE_LIMIT
        if "em andamento" not in text:
            return text
    pytest.fail("bounded history reader failed to complete")


def test_large_history_is_bounded_and_unchanged_history_is_not_reread(tmp_path):
    path = tmp_path / "journal"
    path.write_bytes(b"".join(record(seq, "x" * 1024) for seq in range(1, 3001)))
    reader = HistoryReader(Journal(path))
    first = reader.refresh()
    assert "em andamento" in first and reader.bytes_read <= READ_BUDGET
    assert "disk.quarantine · sucesso" in finish(reader)
    assert reader.last.seq == 3000
    before = reader.bytes_read
    for _ in range(20):
        assert "sucesso" in reader.refresh()
    assert reader.bytes_read == before == path.stat().st_size


@pytest.mark.parametrize("change", ["append", "same_size", "replace", "truncate"])
def test_changed_file_revalidates_interior_corruption(tmp_path, change):
    path = tmp_path / "journal"
    path.write_bytes(record(1) + record(2))
    reader = HistoryReader(Journal(path))
    assert "sucesso" in finish(reader)
    corrupt = path.read_bytes().replace(b'"schema": 1', b'"schema": 9', 1)
    if change == "append":
        path.write_bytes(corrupt + record(3))
    elif change == "same_size":
        path.write_bytes(corrupt)
    elif change == "replace":
        replacement = tmp_path / "replacement"
        replacement.write_bytes(corrupt)
        replacement.replace(path)
    else:
        path.write_bytes(corrupt[:8])
    text = finish(reader)
    assert "problema" in text and "mutações devem ser recusadas" in text


def test_torn_final_line_never_becomes_a_valid_result(tmp_path):
    path = tmp_path / "journal"
    path.write_bytes(record(1)[:-1])
    reader = HistoryReader(Journal(path))
    assert "escrita incompleta" in finish(reader)
    with path.open("ab") as out:
        out.write(b"\n")
    assert "sucesso" in finish(reader)


def test_long_record_is_skipped_with_bounded_memory_and_explicit_problem(tmp_path):
    path = tmp_path / "journal"
    path.write_bytes(record(1, "x" * (LINE_LIMIT * 5)) + record(2))
    reader = HistoryReader(Journal(path))
    assert "64 KiB" in finish(reader)
    assert reader.problem_count > 0


@pytest.mark.parametrize("kind", ["fifo", "symlink"])
def test_special_files_fail_closed_without_blocking(tmp_path, kind):
    path = tmp_path / "journal"
    if kind == "fifo":
        os.mkfifo(path)
    else:
        target = tmp_path / "target"
        target.write_bytes(record(1))
        path.symlink_to(target)
    assert "ilegível" in HistoryReader(Journal(path)).refresh()


def test_missing_history_and_later_creation_are_distinguished(tmp_path):
    path = tmp_path / "journal"
    reader = HistoryReader(Journal(path))
    assert "nenhuma operação" in reader.refresh()
    path.write_bytes(record(1))
    assert "sucesso" in finish(reader)


def test_file_changed_mid_read_is_not_certified(tmp_path, monkeypatch):
    path = tmp_path / "journal"
    path.write_bytes(record(1))
    # Exercise signature revalidation independently of scheduler latency. The
    # separate expired-step case below covers the real production time budget.
    reader = HistoryReader(Journal(path), clock=lambda: 0)
    original = os.pread
    changed = False
    def mutate(fd, length, offset):
        nonlocal changed
        chunk = original(fd, length, offset)
        if not changed:
            changed = True
            path.write_bytes(record(1, "different"))
        return chunk
    monkeypatch.setattr(os, "pread", mutate)
    assert "mudou durante a leitura" in reader.refresh()
    assert "sucesso" in finish(reader)


def test_changed_file_when_step_expires_is_not_certified_before_next_read(tmp_path, monkeypatch):
    path = tmp_path / "journal"
    path.write_bytes(record(1))
    now = [0.0]
    reader = HistoryReader(Journal(path), clock=lambda: now[0])
    original = os.pread
    changed = False
    def mutate(fd, length, offset):
        nonlocal changed
        chunk = original(fd, length, offset)
        if not changed:
            changed = True
            path.write_bytes(record(1, "different"))
            now[0] += .020  # The unchanged 10 ms production budget expires.
        return chunk
    monkeypatch.setattr(os, "pread", mutate)
    assert "em andamento" in reader.refresh()
    assert not reader._complete
    assert "sucesso" in finish(reader)
    assert reader.last.result.reason == "different"
