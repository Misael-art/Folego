"""Persistência durável de JSON/JSONL compartilhada (F2, entrega 5).

Desconhecido/ilegível nunca vira vazio: toda leitura devolve os problemas
encontrados (linha e motivo) junto do que pôde ser lido, e quem muta trata
problema como porta fechada. Escrita de arquivo inteiro é atômica (tmp + fsync +
rename + fsync do diretório em ``atomicfile.write_atomic``) e, quando pedida,
guarda a geração anterior como ``<nome>.bak`` antes de substituir — a migração de
formato nunca perde o original. Anexos JSONL são duráveis por linha (``O_APPEND``
+ fsync) e privados (0600).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .atomicfile import write_atomic

PRIVATE_MODE = 0o600


def append_jsonl(path: Path, row: dict) -> None:
    """Acrescenta uma linha JSON durável e privada (0600), criando o pai."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, PRIVATE_MODE)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def read_jsonl(path: Path) -> tuple[list[tuple[int, dict]], list[str]]:
    """Lê linhas JSON relatando cada problema com o número da linha.

    Devolve ``([(linha, registro), ...], problemas)``. Linha ilegível **não** é
    pulada em silêncio: entra no relatório; linhas que não são objeto também são
    problema. O número acompanha o registro para que quem valida campos nomeie o
    defeito sem reabrir o arquivo.
    """
    if not path.exists():
        return [], []
    text = path.read_text(encoding="utf-8", errors="replace")
    rows: list[tuple[int, dict]] = []
    problems: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            problems.append(f"linha {number}: vazia")
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            problems.append(f"linha {number}: JSON ilegível (escrita interrompida?)")
            continue
        if not isinstance(value, dict):
            problems.append(f"linha {number}: registro não é objeto")
            continue
        rows.append((number, value))
    return rows, problems


def read_json(path: Path) -> tuple[object | None, list[str]]:
    """Lê um arquivo JSON inteiro; ausente é ``(None, [])``; ilegível é problema."""
    if not path.exists():
        return None, []
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, [f"JSON ilegível: {exc}"]
    except OSError as exc:
        return None, [f"não foi possível ler: {exc}"]


def write_json_atomic(path: Path, payload: object, *, keep_backup: bool = True) -> None:
    """Substitui o arquivo em um passo atômico, com a geração anterior em ``.bak``.

    O backup é a garantia da migração: um manifesto legado nunca é sobrescrito
    sem que a versão anterior esteja durável e íntegra ao lado. Se o atual não
    puder ser lido para o backup, nada é escrito (falhar fechado, não perder).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if keep_backup and path.exists():
        previous = path.read_bytes()
        backup = path.with_name(path.name + ".bak")
        write_atomic(backup, previous)
        os.chmod(backup, PRIVATE_MODE)
    write_atomic(path, json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8"))
    os.chmod(path, PRIVATE_MODE)
