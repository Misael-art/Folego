"""Registro append-only do que saiu da RAM e ficou na SSD, com teto de retenção.

Cada linha é uma transição (``partial`` → ``released`` → ``restored``/``dropped``/
``expired``); o estado vigente de um item é o da sua última linha. O orçamento é do
que ainda *ocupa* a SSD: ``partial`` conta, porque o clone existe. "RAM liberada" é o
outro lado da moeda: saiu da RAM e não voltou -- ``restored`` fica de fora, ``partial``
também, porque a liberação ainda não terminou.
"""
import json
import os
import time
from dataclasses import dataclass, field, fields
from pathlib import Path

from ... import paths

RETENTION_DAYS = 14.0
MAX_RETAINED_BYTES = 3 * 1024 ** 3

STATE_PARTIAL = "partial"
STATE_RELEASED = "released"
STATE_RESTORED = "restored"
STATE_DROPPED = "dropped"
STATE_EXPIRED = "expired"
# ainda ocupando a SSD
ACTIVE_STATES = (STATE_PARTIAL, STATE_RELEASED)

FIELDS = ("ts", "entry_id", "src", "volume", "stored", "bytes", "sha256", "age_days",
          "matched_pattern", "holder_pids", "state", "action_id", "audit_event_id")


@dataclass(frozen=True)
class LedgerRecord:
    ts: str
    entry_id: str
    src: str
    volume: str
    stored: str
    bytes: int
    sha256: str
    age_days: float
    matched_pattern: str | None
    holder_pids: tuple[int, ...]
    state: str
    action_id: str
    audit_event_id: str

    def to_dict(self) -> dict:
        # fields(self) e não zip(FIELDS, ...): se a ordem divergir do dataclass, o
        # zip truncaria em silêncio e o T10 regravaria linhas com campos trocados
        row = {f.name: getattr(self, f.name) for f in fields(self)}
        row["holder_pids"] = list(row["holder_pids"])
        return row


@dataclass(frozen=True)
class BudgetView:
    retained_bytes: int
    retained_count: int
    oldest_days: float
    slack_bytes: int
    freed_bytes: int
    by_volume: dict[str, int] = field(default_factory=dict)


def _days_since(ts: str, now: float) -> float:
    try:
        then = time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    except (ValueError, OverflowError):
        return 0.0
    return max(0.0, (now - then) / 86_400.0)


class Ledger:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else paths.tmp_ledger_path()

    # ------------------------------------------------------------------ escrita

    def append(self, **record) -> LedgerRecord:
        missing = [k for k in ("entry_id", "state", "action_id") if not record.get(k)]
        if missing:
            raise ValueError(f"ledger record requires {', '.join(missing)}")
        now = time.time()
        row = {
            "ts": record.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            **{k: record[k] for k in FIELDS if k != "ts" and k in record},
        }
        line = json.dumps(row, ensure_ascii=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        return self._hydrate(row)

    # ------------------------------------------------------------------- leitura

    def rows(self) -> list:
        if not self.path.exists():
            return []
        out = []
        for raw in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("entry_id"):
                out.append(row)
        return out

    def records(self) -> dict:
        """Estado vigente: a última linha de cada entry_id."""
        current = {}
        for row in self.rows():
            record = self._hydrate(row)
            current[record.entry_id] = record
        return current

    def retained(self) -> tuple:
        return tuple(r for r in self.records().values() if r.state in ACTIVE_STATES)

    def retained_bytes(self) -> int:
        return sum(r.bytes for r in self.retained())

    def retained_count(self) -> int:
        return len(self.retained())

    def oldest(self):
        return min(self.retained(), key=lambda r: r.ts, default=None)

    def find(self, handle: str):
        records = self.records()
        if handle in records:
            return records[handle]
        return next((r for r in records.values() if r.src == handle), None)

    def over_budget(self, *, days: float = RETENTION_DAYS,
                    max_bytes: int = MAX_RETAINED_BYTES, now: float | None = None):
        now = time.time() if now is None else now
        held = sorted(self.retained(), key=lambda r: (r.ts, r.entry_id))
        due = [r for r in held if _days_since(r.ts, now) > days]
        # "até caber" = conjunto mínimo: para de expulsar no segundo em que o resto
        # cabe. O termo devida à idade abate o excesso antes de expulsar qualquer
        # item saudável -- sem ele "b" pagaria por "a", que já está saindo.
        overflow = sum(r.bytes for r in held) - max_bytes - sum(r.bytes for r in due)
        for record in held:
            if overflow <= 0:
                break
            if record in due:
                continue
            due.append(record)
            overflow -= record.bytes
        return tuple(due)

    def budget_view(self, *, now: float | None = None) -> BudgetView:
        now = time.time() if now is None else now
        held = self.retained()
        by_volume: dict[str, int] = {}
        for record in held:
            by_volume[record.volume] = by_volume.get(record.volume, 0) + record.bytes
        oldest = self.oldest()
        return BudgetView(
            retained_bytes=sum(r.bytes for r in held),
            retained_count=len(held),
            oldest_days=_days_since(oldest.ts, now) if oldest else 0.0,
            slack_bytes=max(0, MAX_RETAINED_BYTES - sum(r.bytes for r in held)),
            freed_bytes=sum(r.bytes for r in self.records().values()
                            if r.state in (STATE_RELEASED, STATE_DROPPED, STATE_EXPIRED)),
            by_volume=by_volume,
        )

    @staticmethod
    def _hydrate(row: dict) -> LedgerRecord:
        known = {f.name for f in fields(LedgerRecord)}
        payload = {k: v for k, v in row.items() if k in known}
        payload.setdefault("holder_pids", ())
        payload["holder_pids"] = tuple(payload.get("holder_pids") or ())
        try:
            return LedgerRecord(**payload)
        except TypeError:  # linha de uma versão futura do registro: ignorada, não fatal
            return LedgerRecord(ts="", entry_id=row.get("entry_id", ""), src="",
                                volume="", stored="", bytes=int(row.get("bytes", 0)),
                                sha256="", age_days=0.0, matched_pattern=None,
                                holder_pids=(), state=row.get("state", STATE_PARTIAL),
                                action_id="", audit_event_id="")
