"""Contrato da persistência compartilhada (F2, entrega 5).

Toda leitura relata: linha ilegível vira problema nomeado (nunca sumiço
silencioso), arquivo inteiro ilegível vira problema (nunca vazio). Toda escrita
de arquivo inteiro é atômica e guarda a geração anterior em `.bak`; anexos JSONL
são duráveis e privados.
"""
import json
import os

from folego.safely import persist


def test_append_jsonl_creates_parents_and_private_mode(tmp_path):
    path = tmp_path / "state" / "linhas.jsonl"

    persist.append_jsonl(path, {"a": 1})
    persist.append_jsonl(path, {"b": "ção"})

    rows, problems = persist.read_jsonl(path)
    assert [(n, r) for n, r in rows] == [(1, {"a": 1}), (2, {"b": "ção"})]
    assert problems == []
    assert (path.stat().st_mode & 0o077) == 0


def test_read_jsonl_reports_each_problem_with_its_line(tmp_path):
    path = tmp_path / "linhas.jsonl"
    path.write_text('{"ok": 1}\n\nlixo{\n[1, 2]\n{"ok": 2}\n', encoding="utf-8")

    rows, problems = persist.read_jsonl(path)

    assert [(n, r) for n, r in rows] == [(1, {"ok": 1}), (5, {"ok": 2})]
    assert [p.split(":")[0] for p in problems] == ["linha 2", "linha 3", "linha 4"]
    assert "vazia" in problems[0] and "ilegível" in problems[1]
    assert "não é objeto" in problems[2]


def test_read_jsonl_missing_file_is_empty_not_a_problem(tmp_path):
    assert persist.read_jsonl(tmp_path / "nao-existe.jsonl") == ([], [])


def test_read_json_reports_corruption_and_binary(tmp_path):
    assert persist.read_json(tmp_path / "nao-existe.json") == (None, [])

    good = tmp_path / "bom.json"
    good.write_text('{"schema": 1}', encoding="utf-8")
    assert persist.read_json(good) == ({"schema": 1}, [])

    bad = tmp_path / "mau.json"
    bad.write_text("{quebrado", encoding="utf-8")
    value, problems = persist.read_json(bad)
    assert value is None and problems and "ilegível" in problems[0]

    binary = tmp_path / "binario.json"
    binary.write_bytes(b"\xff\xfe\x00\x01")
    value, problems = persist.read_json(binary)
    assert value is None and problems, "ilegível não vira None silencioso"


def test_write_json_atomic_keeps_the_previous_generation(tmp_path):
    path = tmp_path / "manifest.json"

    persist.write_json_atomic(path, {"v": 1})

    backup = path.with_name("manifest.json.bak")
    assert not backup.exists(), "primeira escrita não tem geração anterior"
    assert (path.stat().st_mode & 0o077) == 0

    persist.write_json_atomic(path, {"v": 2})

    assert json.loads(path.read_text()) == {"v": 2}
    assert json.loads(backup.read_text()) == {"v": 1}
    assert (backup.stat().st_mode & 0o077) == 0

    persist.write_json_atomic(path, {"v": 3})

    assert json.loads(path.read_text()) == {"v": 3}
    assert json.loads(backup.read_text()) == {"v": 2}, "só a geração imediata"


def test_write_json_atomic_without_backup_leaves_no_bak(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text('{"antigo": true}', encoding="utf-8")

    persist.write_json_atomic(path, {"novo": True}, keep_backup=False)

    assert json.loads(path.read_text()) == {"novo": True}
    assert not path.with_name("manifest.json.bak").exists()


def test_write_json_atomic_fails_closed_when_the_current_file_is_unreadable(tmp_path):
    """Sem conseguir ler o atual para o backup, nada é sobrescrito."""
    path = tmp_path / "manifest.json"
    path.write_text('{"antigo": true}', encoding="utf-8")
    os.chmod(path, 0)
    try:
        try:
            persist.write_json_atomic(path, {"novo": True})
            raise AssertionError("deveria falhar ao ler o atual para o backup")
        except PermissionError:
            pass
        os.chmod(path, 0o600)
        assert json.loads(path.read_text()) == {"antigo": True}
    finally:
        os.chmod(path, 0o600)
