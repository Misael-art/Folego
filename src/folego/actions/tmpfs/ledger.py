"""Registro append-only do que saiu da RAM e ficou na SSD, com teto de retenção.

Cada linha é uma transição (``staging`` → ``partial`` → ``released`` →
``restored``/``dropped``/``expired``); o estado vigente de um item é o da sua última
linha. ``staging`` é a tentativa em andamento: a linha entra **antes** da cópia, para
que uma queda no meio do caminho seja recuperável em vez de deixar clone órfão. O
orçamento é do que ainda *ocupa* a SSD: ``partial`` conta, porque o clone certificado
existe; ``staging`` fica fora (bytes desconhecidos até a certificação, e o `expire`
jamais pode apagar um clone que talvez seja a única cópia). "RAM liberada" é o outro
lado da moeda: saiu da RAM e não voltou -- ``restored`` fica de fora, ``partial``
também, porque a liberação ainda não terminou.

Persistência (F2, entrega 5): cada linha nova carrega ``schema``; linha sem o campo é
formato legado aceito, e schema de versão mais nova é **problema**, não dado. Linha
ilegível/sem ``entry_id`` é relatada (``load``/``problems``) em vez de pulada em
silêncio — quem muta recusa enquanto houver problema. Campos de tipo errado em linha
legível não derrubam a leitura (``_hydrate`` zera/coage); a linha degradada vira
decisão manual nos atos, nunca autorização de mutação.
"""
import time
from dataclasses import dataclass, field, fields
from pathlib import Path

from ... import paths
from ...safely import persist

SCHEMA = 1
RETENTION_DAYS = 14.0
MAX_RETAINED_BYTES = 3 * 1024 ** 3

STATE_STAGING = "staging"
STATE_PARTIAL = "partial"
STATE_RELEASED = "released"
STATE_RESTORED = "restored"
STATE_DROPPED = "dropped"
STATE_EXPIRED = "expired"
# ainda ocupando a SSD (e por isso sujeito ao orçamento e ao expire)
ACTIVE_STATES = (STATE_PARTIAL, STATE_RELEASED)
# qualquer estado que precise ser resolvido antes de liberar o mesmo caminho de
# novo: staging pede `recover`; partial/released pedem restore (ou expire). O
# orçamento NÃO usa esta tupla: staging tem bytes desconhecidos e origem viva.
UNRESOLVED_STATES = (STATE_STAGING, *ACTIVE_STATES)

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
    # campo de auditoria é opcional no registro: o reparo documentado do ledger é
    # editar a linha com o app parado, e a ausência deste campo não pode invalidar
    # o resto do registro (achado da entrega 6a na cota conjunta do staging)
    audit_event_id: str = ""

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


def _as_int(value) -> int:
    """Campo numérico de linha editada à mão não derruba a leitura inteira."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _days_since(ts: str, now: float) -> float:
    if not isinstance(ts, str):
        return 0.0
    try:
        then = time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    except (ValueError, OverflowError, TypeError):
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
            "schema": SCHEMA,
            "ts": record.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            **{k: record[k] for k in FIELDS if k != "ts" and k in record},
        }
        persist.append_jsonl(self.path, row)
        return self._hydrate(row)

    # ------------------------------------------------------------------- leitura

    def load(self) -> tuple[list[dict], list[str]]:
        """Linhas válidas e problemas — linha ilegível não é pulada em silêncio.

        ``schema`` ausente é formato legado (aceito, migra na próxima escrita da
        própria linha); ``schema`` de versão mais nova é problema: uma linha que
        esta versão não sabe interpretar não vira dado nem autoriza mutação.
        """
        rows, problems = persist.read_jsonl(self.path)
        valid = []
        for number, row in rows:
            schema = row.get("schema", SCHEMA)
            if not isinstance(schema, int) or isinstance(schema, bool) or schema < 1:
                problems.append(f"linha {number}: schema inválido: {schema!r}")
                continue
            if schema > SCHEMA:
                problems.append(f"linha {number}: schema {schema} é de uma versão "
                                "mais nova; esta versão não sabe interpretá-la")
                continue
            if not isinstance(row.get("entry_id"), str) or not row.get("entry_id"):
                problems.append(f"linha {number}: registro sem entry_id")
                continue
            valid.append(row)
        return valid, problems

    def problems(self) -> list[str]:
        """Quem muta recusa enquanto houver qualquer problema de leitura."""
        return self.load()[1]

    def rows(self) -> list:
        return self.load()[0]

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
        """Por entry_id explícito ou pelo caminho de origem.

        R04: o mesmo caminho pode ter vários ciclos (liberado, restaurado, liberado
        de novo). Para um caminho, o vigente é o ciclo *não resolvido* mais recente
        (staging/partial/released); sem ciclo ativo, o mais recente de todos.
        Devolver o ciclo velho fazia `release_item` liberar uma segunda cópia
        enquanto o clone ativo seguia na SSD; e um `staging` recém-criado ficaria
        escondido atrás de um `released` antigo se a preferência fosse só ACTIVE.
        """
        records = self.records()
        if handle in records:
            return records[handle]
        matching = [r for r in records.values() if r.src == handle]
        if not matching:
            return None
        pool = [r for r in matching if r.state in UNRESOLVED_STATES] or matching
        return max(pool, key=lambda r: (r.ts, r.entry_id))

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
        """Hidrata campo a campo: campo ausente/ilegível não blanka os demais.

        O reparo documentado do ledger é editar a linha com o app parado — por
        isso um campo removido vira ausência *localizada*: o `stored` legível
        continua legível, e é ele que `release`/`restore`/`expire` revalidam antes
        de tocar em qualquer coisa. `load` já garante `entry_id` não vazio; estado
        ausente assume `partial` (ocupando SSD), o lado conservador do orçamento.
        O fallback antigo blankava o registro inteiro quando faltava um campo —
        um `audit_event_id` de edição manual descartava `stored`/`src` em silêncio
        (achado da entrega 6a na cota conjunta do staging).
        """
        known = {f.name for f in fields(LedgerRecord)}
        payload = {k: v for k, v in row.items() if k in known}
        payload.setdefault("entry_id", "")
        payload.setdefault("ts", "")
        payload.setdefault("src", "")
        payload.setdefault("volume", "")
        payload.setdefault("stored", "")
        payload.setdefault("sha256", "")
        payload.setdefault("matched_pattern", None)
        payload.setdefault("action_id", "")
        holders = payload.get("holder_pids")
        payload["holder_pids"] = tuple(holders) if isinstance(holders, (list, tuple)) else ()
        payload["bytes"] = _as_int(payload.get("bytes"))
        try:
            payload["age_days"] = float(payload.get("age_days") or 0.0)
        except (TypeError, ValueError):
            payload["age_days"] = 0.0
        state = payload.get("state", STATE_PARTIAL)
        payload["state"] = state
        return LedgerRecord(**payload)
