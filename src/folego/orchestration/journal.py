"""Diário de intenção do motor comum (F2): a intenção entra antes do efeito.

Append-only, uma linha JSON por registro, fsync a cada linha. A ordem é o
contrato: ``intent`` é gravado *antes* de o executor tocar no mundo; ``result``
depois. Uma operação repetida é respondida pelo registro, não reexecutada
(``state_of``), e uma intenção sem resultado (crash no meio) não é reaplicada às
cegas. Linha final truncada é a cauda de uma escrita interrompida: fica como
problema do diário, e o coordenador recusa mutar enquanto houver problema —
falhar fechado é melhor que aplicar em cima de estado desconhecido.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from .models import (SCHEMA, ActionPlan, ActionResult, OperationState,
                     OperationStatus, ValidationError)


class CorruptJournal(Exception):
    """O diário tem linha ilegível ou fora de sequência: mutações recusam."""


@dataclass(frozen=True)
class JournalRecord:
    seq: int
    ts: float
    operation_id: str
    kind: str            # "intent" | "result"
    plan: ActionPlan | None = None
    result: ActionResult | None = None


class Journal:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else paths.operations_journal_path()

    # ------------------------------------------------------------------ escrita

    def append_intent(self, plan: ActionPlan) -> JournalRecord:
        return self._append(kind="intent", operation_id=plan.operation_id,
                            payload={"plan": plan.to_dict()})

    def append_result(self, result: ActionResult) -> JournalRecord:
        return self._append(kind="result", operation_id=result.operation_id,
                            payload={"result": result.to_dict()})

    def _append(self, *, kind: str, operation_id: str, payload: dict) -> JournalRecord:
        records, problems = self.load()
        if problems:
            raise CorruptJournal("; ".join(problems))
        seq = (records[-1].seq if records else 0) + 1
        row = {"schema": SCHEMA, "seq": seq, "ts": time.time(),
               "operation_id": operation_id, "kind": kind, **payload}
        line = json.dumps(row, ensure_ascii=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            pending = memoryview(line.encode("utf-8"))
            while pending:
                written = os.write(fd, pending)
                if written <= 0:
                    raise OSError("escrita do diário não avançou")
                pending = pending[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        record, problem = self._decode(row)
        if problem is not None:  # não deve acontecer: acabamos de montar a linha
            raise CorruptJournal(problem)
        return record

    # ------------------------------------------------------------------ leitura

    def load(self) -> tuple[list[JournalRecord], list[str]]:
        if not self.path.exists():
            return [], []
        text = self.path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        records: list[JournalRecord] = []
        problems: list[str] = []
        expected = 1
        for number, raw in enumerate(lines, start=1):
            if not raw.strip():
                problems.append(f"linha {number}: vazia")
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                problems.append(f"linha {number}: JSON ilegível (escrita interrompida?)")
                continue
            record, problem = self._decode(row)
            if problem is not None:
                problems.append(f"linha {number}: {problem}")
                continue
            if record.seq != expected:
                problems.append(f"linha {number}: sequência {record.seq} "
                                f"onde se esperava {expected}")
                continue
            expected += 1
            records.append(record)
        return records, problems

    def records(self, operation_id: str | None = None) -> list[JournalRecord]:
        records, _ = self.load()
        if operation_id is None:
            return records
        return [r for r in records if r.operation_id == operation_id]

    def state_of(self, operation_id: str, *, allow_problems: bool = False) -> OperationState | None:
        records, problems = self.load()
        if problems and not allow_problems:
            raise CorruptJournal("; ".join(problems))
        mine = [r for r in records if r.operation_id == operation_id]
        if not mine:
            return None
        intent = next((r for r in mine if r.kind == "intent"), None)
        result = next((r for r in reversed(mine) if r.kind == "result"), None)
        if (intent is not None and result is not None and
                (result.result.action != intent.plan.action or
                 result.result.target_key != intent.plan.target.key)):
            raise CorruptJournal("resultado não corresponde à ação/alvo da intenção")
        if result is not None:
            return OperationState(operation_id, OperationStatus.COMPLETED,
                                  intent.plan if intent else None, result.result,
                                  intent.seq if intent else None, result.seq)
        if intent is not None:
            return OperationState(operation_id, OperationStatus.INTENDED,
                                  intent.plan, None, intent.seq, None)
        # só há resultado, sem intenção: registro de uma versão futura/entremezclada
        return OperationState(operation_id, OperationStatus.COMPLETED,
                              None, result.result if result else None, None,
                              result.seq if result else None)

    @staticmethod
    def _decode(row: object) -> tuple[JournalRecord | None, str | None]:
        if not isinstance(row, dict):
            return None, "registro não é objeto"
        if row.get("schema") != SCHEMA:
            return None, f"schema {row.get('schema')!r} não suportado"
        kind = row.get("kind")
        if kind not in ("intent", "result"):
            return None, f"kind desconhecido: {kind!r}"
        try:
            seq = int(row["seq"])
            ts = float(row["ts"])
        except (KeyError, TypeError, ValueError):
            return None, "seq/ts ausentes ou inválidos"
        operation_id = row.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            return None, "operation_id ausente"
        plan = result = None
        try:
            if kind == "intent":
                plan = ActionPlan.from_dict(row.get("plan") or {})
            else:
                result = ActionResult.from_dict(row.get("result") or {})
        except ValidationError as exc:
            return None, str(exc)
        if (plan is not None and plan.operation_id != operation_id or
                result is not None and result.operation_id != operation_id):
            return None, "operation_id do payload difere do registro"
        return JournalRecord(seq, ts, operation_id, kind, plan, result), None
