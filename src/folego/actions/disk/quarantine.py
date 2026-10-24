"""Disk hygiene M5 — reversible reclamation.

Deleting user data is never the first step. `move_in` renames a tree into the
app's quarantine directory on the *same* filesystem (atomic, zero-copy, fully
revertible); `purge` is a separate, explicit decision. The manifest is written
before the rename so an interrupted move can be repaired by `reconcile`.

O manifesto é versionado (envelope ``schema`` + ``entries``), escrito de forma
atômica com a geração anterior em ``manifest.json.bak``, e um manifesto
ilegível/inconsistente **bloqueia toda mutação** — nunca vira lista vazia. Listas
cruas do formato antigo continuam sendo lidas e são migradas na primeira escrita.
"""
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ... import paths
from ...safely import guard, persist
from ...safely.audit import AuditLog
from .measure import measure_tree

SCHEMA = 1

STATE_PLANNED = "planned"
STATE_STORED = "stored"
STATE_RESTORED = "restored"
STATE_PURGED = "purged"
STATE_DROPPED = "dropped"
STATES = (STATE_PLANNED, STATE_STORED, STATE_RESTORED, STATE_PURGED, STATE_DROPPED)

FIELDS = ("entry_id", "original", "stored", "bytes", "state", "moved_at", "action_id")


@dataclass(frozen=True)
class QuarantineEntry:
    entry_id: str
    original: str
    stored: str
    bytes: int
    state: str
    moved_at: str
    action_id: str

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id, "original": self.original, "stored": self.stored,
            "bytes": self.bytes, "state": self.state, "moved_at": self.moved_at,
            "action_id": self.action_id,
        }


@dataclass(frozen=True)
class ActionResult:
    entry_id: str
    ok: bool
    reason: str


@dataclass(frozen=True)
class ReconcileReport:
    """O que o `reconcile` decidiu, por transição, sem esconder o que ficou.

    ``repaired``: o rename tinha concluído (origem sumiu, payload existe) → a
    linha fecha como ``stored``. ``dropped``: o rename nunca aconteceu (origem
    intacta, sem payload) → a linha fecha como ``dropped``, nenhum dado tocado.
    ``manual``: ambíguo (ambos ou nenhum existem) → decisão humana, nada escrito.
    ``problems``: manifesto ilegível/inconsistente → nada foi escrito.
    """

    repaired: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
    manual: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()

    @property
    def mutated(self) -> bool:
        return bool(self.repaired or self.dropped)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _under(path_str: str, root: str) -> bool:
    return path_str == root or path_str.startswith(root + os.sep)


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:60] or "unnamed"


def _inconsistente(problems) -> str:
    return ("refused: manifesto da quarentena inconsistente; nada foi alterado: "
            + "; ".join(problems))


class Quarantine:
    def __init__(self, root: Path | None = None, *, allowed_roots=None,
                 audit: AuditLog | None = None, stat_fn=os.stat):
        self.root = Path(root) if root else paths.data_dir() / "quarantine"
        self.allowed_roots = list(allowed_roots) if allowed_roots else [Path.home()]
        self.audit = audit
        self.stat_fn = stat_fn

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    # ------------------------------------------------------------------ leitura

    def _load(self) -> tuple[list[dict], list[str]]:
        """Linhas válidas do manifesto e problemas — ilegível nunca vira vazio."""
        payload, problems = persist.read_json(self.manifest_path)
        if problems:
            return [], problems
        if payload is None:
            return [], []
        if isinstance(payload, list):
            rows = payload  # formato legado (lista crua): aceito e migrado na escrita
        elif isinstance(payload, dict):
            if payload.get("schema") != SCHEMA:
                return [], [f"schema {payload.get('schema')!r} não suportado "
                            f"(esperado {SCHEMA})"]
            rows = payload.get("entries")
            if not isinstance(rows, list):
                return [], ["envelope sem lista 'entries'"]
        else:
            return [], ["manifesto não é lista nem objeto"]
        return self._validate(rows)

    def _validate(self, rows: list) -> tuple[list[dict], list[str]]:
        valid: list[dict] = []
        problems: list[str] = []
        seen: set[str] = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                problems.append(f"entrada {index}: não é objeto")
                continue
            missing = [k for k in FIELDS if k not in row]
            if missing:
                problems.append(f"entrada {index}: campos ausentes: {', '.join(missing)}")
                continue
            entry_id = row.get("entry_id")
            if not isinstance(entry_id, str) or not entry_id:
                problems.append(f"entrada {index}: entry_id vazio")
                continue
            if entry_id in seen:
                problems.append(f"entrada {index}: entry_id repetido: {entry_id}")
                continue
            seen.add(entry_id)
            if row.get("state") not in STATES:
                problems.append(f"entrada {index} ({entry_id}): estado desconhecido: "
                                f"{row.get('state')!r}")
                continue
            size = row.get("bytes")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                problems.append(f"entrada {index} ({entry_id}): bytes inválidos: {size!r}")
                continue
            bad_path = [k for k in ("original", "stored")
                        if not isinstance(row.get(k), str) or not row.get(k)
                        or not Path(row[k]).is_absolute()]
            if bad_path:
                # `Path("")` é `.`: caminho registrado tem de ser absoluto, senão
                # um purge poderia apontar para o diretório de trabalho
                problems.append(f"entrada {index} ({entry_id}): caminho não absoluto: "
                                + ", ".join(f"{k}={row.get(k)!r}" for k in bad_path))
                continue
            # o payload tem de estar confinado à raiz privada da quarentena: o
            # guard aceita qualquer caminho sob as raízes permitidas (home
            # inclusive), então um manifesto com `stored` solto apontaria o
            # `purge` para fora — a relação entrada → payload → raiz é validada
            if not _under(str(Path(row["stored"]).resolve()), str(self.root.resolve())):
                problems.append(f"entrada {index} ({entry_id}): payload fora da raiz "
                                f"privada da quarentena: {row['stored']!r}")
                continue
            valid.append(row)
        return valid, problems

    @staticmethod
    def _hydrate(row: dict) -> QuarantineEntry:
        return QuarantineEntry(**{k: row[k] for k in FIELDS})

    def inspect(self) -> tuple[dict, list[str]]:
        """Entradas válidas + problemas: mutação trata problema como porta fechada."""
        rows, problems = self._load()
        return {r["entry_id"]: self._hydrate(r) for r in rows}, problems

    def entries(self) -> dict:
        return self.inspect()[0]

    def _require_clean(self) -> list:
        rows, problems = self._load()
        if problems:
            raise PermissionError(_inconsistente(problems))
        return rows

    def reclaimable_bytes(self) -> int:
        return sum(e.bytes for e in self.entries().values() if e.state == STATE_STORED)

    # ------------------------------------------------------------------ escrita

    def _write(self, rows: list) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        persist.write_json_atomic(self.manifest_path,
                                  {"schema": SCHEMA, "entries": rows})

    def _update(self, entry_id: str, **changes) -> QuarantineEntry:
        rows, problems = self._load()
        if problems:
            raise RuntimeError("manifesto da quarentena mudou no meio do ato: "
                               + "; ".join(problems))
        found = None
        for row in rows:
            if row["entry_id"] == entry_id:
                row.update(changes)
                found = row
        if found is None:
            raise RuntimeError(f"entrada {entry_id} sumiu do manifesto no meio do ato")
        self._write(rows)
        return self._hydrate(found)

    def _audit(self, kind: str, entry_id: str, outcome: str, targets: list[str],
               error: str | None = None) -> None:
        if self.audit is None:
            return
        self.audit.append(kind=kind, action_id=entry_id, outcome=outcome,
                          targets=targets, risk="reversible" if outcome != "purged"
                          else "irreversible", error=error)

    def _check(self, p: Path) -> None:
        verdict = guard.validate_target(p, self.allowed_roots)
        if not verdict.ok:
            raise PermissionError(verdict.reason)

    # ---------------------------------------------------------------------- atos

    def move_in(self, path, *, action_id: str = "disk.quarantine", expected_identity=None) -> QuarantineEntry:
        rows = self._require_clean()
        p = Path(os.path.expanduser(str(path)))
        self._check(p)
        if not p.exists():
            raise PermissionError(f"refused: nothing to quarantine at {p}")
        root_resolved = str(self.root.resolve())
        if _under(str(p.resolve()), root_resolved) or str(p.resolve()) == root_resolved:
            raise PermissionError("refused: path is already inside the quarantine root")

        self.root.mkdir(parents=True, exist_ok=True)
        if self.stat_fn(p).st_dev != self.stat_fn(self.root).st_dev:
            raise PermissionError(
                f"refused: cross-device move for {p} would be a copy, not a rename")

        stat = measure_tree(p)
        if expected_identity is not None:
            from .review import identity
            if identity(p) != expected_identity:
                raise PermissionError("refused: evidência mudou durante a preparação da quarentena")
        entry_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        stored = self.root / f"{_sanitize(p.name)}-{entry_id}"
        entry = QuarantineEntry(entry_id, str(p), str(stored), stat.bytes,
                                STATE_PLANNED, "", action_id)
        rows.append(entry.to_dict())
        self._write(rows)

        if expected_identity is not None and identity(p) != expected_identity:
            raise PermissionError("refused: evidência mudou antes do rename; origem preservada")

        os.rename(p, stored)
        if expected_identity is not None:
            moved_info = os.stat(stored, follow_symlinks=False)
            if (moved_info.st_dev, moved_info.st_ino) != (
                    expected_identity.detail["dev"], expected_identity.detail["ino"]):
                raise RuntimeError("identidade inesperada após rename; conteúdo retido, recuperação pendente")
        moved = self._update(entry_id, state=STATE_STORED, moved_at=_now())
        self._audit("disk.quarantine", entry_id, STATE_STORED, [str(p), str(stored)])
        return moved

    def restore(self, entry_id: str) -> ActionResult:
        entries, problems = self.inspect()
        if problems:
            return ActionResult(entry_id, False, _inconsistente(problems))
        entry = entries.get(entry_id)
        if entry is None:
            return ActionResult(entry_id, False, "refused: unknown quarantine entry")
        if entry.state != STATE_STORED:
            return ActionResult(entry_id, False, f"refused: entry is {entry.state}")
        original = Path(entry.original)
        if original.exists():
            return ActionResult(entry_id, False,
                                "refused: original path already exists, nothing overwritten")
        verdict = guard.validate_target(original, self.allowed_roots)
        if not verdict.ok:
            return ActionResult(entry_id, False, verdict.reason)
        if not Path(entry.stored).exists():
            return ActionResult(entry_id, False, "refused: stored payload is missing")

        os.rename(entry.stored, original)
        self._update(entry_id, state=STATE_RESTORED, moved_at=_now())
        self._audit("disk.restore", entry_id, STATE_RESTORED,
                    [entry.stored, entry.original])
        return ActionResult(entry_id, True, "ok")

    def purge(self, entry_id: str) -> ActionResult:
        entries, problems = self.inspect()
        if problems:
            return ActionResult(entry_id, False, _inconsistente(problems))
        entry = entries.get(entry_id)
        if entry is None:
            return ActionResult(entry_id, False, "refused: unknown quarantine entry")
        if entry.state != STATE_STORED:
            return ActionResult(entry_id, False, f"refused: entry is already {entry.state}")
        self._check(Path(entry.stored))

        shutil.rmtree(entry.stored)
        self._update(entry_id, state=STATE_PURGED, moved_at=_now())
        self._audit("disk.purge", entry_id, STATE_PURGED, [entry.stored])
        return ActionResult(entry_id, True, "ok")

    # ------------------------------------------------------------------ reparo

    def reconcile(self, *, dry_run: bool = False) -> ReconcileReport:
        """Fecha as transições deixadas por uma queda, sem adivinhar.

        Roda sob o coordenador quando há mais de um processo: a classificação
        assume que nenhum `move_in` está no meio do rename. Origem sumida com o
        payload presente → ``stored`` (o rename concluiu). Origem intacta sem
        payload → ``dropped`` (o rename nunca aconteceu; nenhum dado é tocado).
        Ambos ou nenhum → decisão manual, nada é escrito. ``dry_run`` classifica
        sem escrever (é assim que a ponte decide se há reparo a registrar).
        """
        rows, problems = self._load()
        if problems:
            return ReconcileReport(problems=tuple(problems))
        repaired, dropped, manual = [], [], []
        for row in rows:
            if row["state"] != STATE_PLANNED:
                continue
            original, stored = Path(row["original"]), Path(row["stored"])
            if not original.exists() and stored.exists():
                repaired.append(row)
            elif original.exists() and not stored.exists():
                dropped.append(row)
            else:
                manual.append(row["entry_id"])
        report = ReconcileReport(
            repaired=tuple(r["entry_id"] for r in repaired),
            dropped=tuple(r["entry_id"] for r in dropped),
            manual=tuple(manual))
        if dry_run or not report.mutated:
            return report
        stamp = _now()
        for row in repaired:
            row["state"] = STATE_STORED
            row["moved_at"] = stamp
        for row in dropped:
            row["state"] = STATE_DROPPED
            row["moved_at"] = stamp
        self._write(rows)
        for row in repaired:
            self._audit("disk.reconcile", row["entry_id"], STATE_STORED, [row["stored"]])
        for row in dropped:
            self._audit("disk.reconcile", row["entry_id"], STATE_DROPPED, [row["original"]])
        return report
