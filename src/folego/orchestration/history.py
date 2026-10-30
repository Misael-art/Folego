"""Bounded read-only journal overview; never used to authorize an operation.

A changed file is revalidated from the beginning, in bounded steps. An unchanged
file only costs stat/open/close. No journal contents or descriptor accumulate
between steps: only a line buffer, sequence counter and latest record survive.
The coordinator continues using the authoritative journal, not this view.
"""
import json
import os
import stat
import time
from datetime import datetime

from .journal import Journal

READ_BUDGET = 256 * 1024
LINE_LIMIT = 64 * 1024
STEP_SECONDS = .010


def format_history(records, problems):
    if problems:
        return (f"histórico com {len(problems)} problema(s): {problems[0]} — "
                "mutações devem ser recusadas até o reparo")
    if not records:
        return "nenhuma operação registrada (diário ainda não existe)"
    last = records[-1]
    try:
        stamp = datetime.fromtimestamp(last.ts).astimezone().strftime("%d/%m %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        stamp = "data inválida"
    if last.kind == "result" and last.result is not None:
        result = last.result
        detail = f"{stamp} · {result.action} · {result.outcome}"
        return detail + (f" — {result.reason}" if result.reason else "")
    if last.plan is not None:
        return (f"{stamp} · {last.plan.action} · intenção sem resultado "
                "registrado — consulte o efeito antes de repetir")
    return f"{stamp} · registro {last.kind} sem conteúdo interpretável"


class HistoryReader:
    def __init__(self, journal, *, clock=time.monotonic):
        self.journal = journal
        self.clock = clock
        self._signature = None
        self._complete = False
        self.verified = False
        self._text = "aguardando leitura do histórico"
        self._reset()
        self.bytes_read = 0  # measurable cumulative payload I/O, not OS cache size

    def _reset(self):
        self.offset = 0
        self.buffer = b""
        self.skipping = False
        self.expected = 1
        self.line = 0
        self.last = None
        self.problem_count = 0
        self.first_problem = ""

    @staticmethod
    def _stamp(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def _problem(self, reason):
        self.problem_count += 1
        if not self.first_problem:
            self.first_problem = f"linha {self.line}: {reason}"

    def _line(self, raw):
        self.line += 1
        if self.skipping or len(raw) > LINE_LIMIT:
            self._problem("registro excede o limite de leitura de 64 KiB; revisão necessária")
            self.skipping = False
            return
        try:
            row = json.loads(raw)
        except (ValueError, UnicodeError):
            self._problem("JSON ilegível (escrita interrompida?)")
            return
        record, problem = Journal._decode(row)
        if problem:
            self._problem(problem)
        elif record.seq != self.expected:
            self._problem(f"sequência {record.seq} onde se esperava {self.expected}")
        else:
            self._accept(record)
            self.expected += 1

    def _accept(self, record):
        self.last = record

    def refresh(self):
        self.verified = False
        # Legacy injected readers are test seams; even their load runs in the
        # overview worker. Production always uses the bounded path below.
        if not isinstance(self.journal, Journal):
            try:
                return format_history(*self.journal.load())
            except OSError as exc:
                return f"histórico ilegível ({exc}) — mutações não comprovadas"
        try:
            fd = os.open(self.journal.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            self._signature = None
            self._reset()
            self._text = format_history([], [])
            self._complete = True
            self.verified = True
            return self._text
        except OSError as exc:
            return f"histórico ilegível ({exc}) — mutações não comprovadas"
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise OSError("diário não é arquivo regular")
            signature = self._stamp(info)
            if signature != self._signature:
                self._reset()
                self._signature = signature
                self._complete = False
            if self._complete:
                self.verified = True
                return self._text
            remaining = READ_BUDGET
            deadline = self.clock() + STEP_SECONDS
            while remaining > 0 and self.clock() < deadline:
                chunk = os.pread(fd, min(16 * 1024, remaining), self.offset)
                self.bytes_read += len(chunk)
                self.offset += len(chunk)
                remaining -= len(chunk)
                if not chunk:
                    if self.buffer or self.skipping:
                        self._line(self.buffer)
                        self._problem("linha final sem terminador; escrita incompleta")
                    # Never label a moving snapshot as fully validated.
                    if self._stamp(os.fstat(fd)) != signature:
                        self._signature = None
                        return "histórico mudou durante a leitura; aguardando revalidação"
                    self._complete = True
                    self.verified = True
                    if self.problem_count:
                        self._text = (f"histórico com {self.problem_count} problema(s): {self.first_problem} — "
                                      "mutações devem ser recusadas até o reparo")
                    else:
                        self._text = format_history([self.last] if self.last else [], [])
                    return self._text
                pieces = chunk.split(b"\n")
                for piece in pieces[:-1]:
                    self._line(self.buffer + piece)
                    self.buffer = b""
                self.buffer += pieces[-1]
                if len(self.buffer) > LINE_LIMIT:
                    self.skipping = True
                    self.buffer = b""
            return "leitura do histórico em andamento; resultado ainda não comprovado"
        except OSError as exc:
            self._signature = None
            return f"histórico ilegível ({exc}) — mutações não comprovadas"
        finally:
            os.close(fd)


class PendingReader(HistoryReader):
    """Bounded pending-operation view, rebuilt after *any* signature change.

    Completed history is never retained. Partial/changed/corrupt views cannot
    authorize actions; the coordinator still revalidates the authoritative log.
    """
    def __init__(self, journal, *, action=None, clock=time.monotonic):
        self.action = action
        super().__init__(journal, clock=clock)

    def _reset(self):
        super()._reset()
        self.pending = {}

    def _accept(self, record):
        super()._accept(record)
        obj = record.plan if record.kind == "intent" else record.result
        target = (obj.action, obj.target.key if record.kind == "intent" else obj.target_key)
        previous = self.pending.get(record.operation_id)
        if previous is not None and previous != target:
            self._problem("resultado não corresponde à ação/alvo da intenção pendente")
            return
        if self.action is not None and obj.action != self.action:
            return
        if record.kind == "intent" or str(record.result.outcome) == "desconhecido":
            if record.operation_id not in self.pending and len(self.pending) >= 4096:
                self._problem("operações pendentes excedem orçamento; revisão necessária")
            else:
                self.pending[record.operation_id] = target
        else:
            self.pending.pop(record.operation_id, None)

    def ids(self):
        text = self.refresh()
        if not self.verified or self.problem_count:
            raise ValueError(text)
        return list(self.pending)
