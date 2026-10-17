"""Plano de liberação: seco, com digest e com as recusas dentro dele.

O digest existe para a mesma coisa que o digest do plano de tunings: poder dizer
"este é o plano que eu vi" depois de formatar, ordenar ou cortar.
"""
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .policy import classify


def item_id_for(path: str) -> str:
    return hashlib.sha256(str(path).encode()).hexdigest()[:12]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class PlanItem:
    item_id: str
    path: str
    name: str
    volume: str
    kind: str
    uid: int
    bytes: int
    files: int
    age_days: float
    holder_pids: tuple
    ok: bool
    reason: str
    matched: str | None
    truncated: bool
    errors: tuple

    def to_dict(self) -> dict:
        d = asdict(self)
        d["age_days"] = round(self.age_days, 2)
        d["holder_pids"] = list(self.holder_pids)
        d["errors"] = list(self.errors)
        return d


@dataclass(frozen=True)
class TmpfsPlan:
    generated_at: str
    volumes: tuple
    policy: object
    reclaimable: tuple
    protected: tuple
    total_bytes: int
    scanned_entries: int
    scanned_bytes: int
    digest: str
    errors: tuple

    def to_dict(self) -> dict:
        return {"generated_at": self.generated_at,
                "volumes": [v.to_dict() for v in self.volumes],
                "policy": self.policy.to_dict(),
                "reclaimable": [i.to_dict() for i in self.reclaimable],
                "protected": [i.to_dict() for i in self.protected],
                "total_bytes": self.total_bytes,
                "scanned_entries": self.scanned_entries,
                "scanned_bytes": self.scanned_bytes,
                "digest": self.digest,
                "errors": list(self.errors)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    def find(self, handle: str):
        for item in (*self.reclaimable, *self.protected):
            if item.item_id == handle or item.path == handle:
                return item
        return None


def build_plan(volumes, entries, policy, *, now=None) -> TmpfsPlan:
    now = time.time() if now is None else now
    eligible, refused, errors = [], [], []
    for entry in entries:
        verdict = classify(entry, policy)
        item = PlanItem(item_id=item_id_for(entry.path), path=entry.path,
                        name=entry.name, volume=entry.volume, kind=entry.kind,
                        uid=entry.uid, bytes=entry.bytes, files=entry.files,
                        age_days=entry.age_days, holder_pids=entry.holder_pids,
                        ok=verdict.ok, reason=verdict.reason, matched=verdict.matched,
                        truncated=entry.truncated, errors=entry.errors)
        errors.extend(entry.errors)
        (eligible if verdict.ok else refused).append(item)

    eligible.sort(key=lambda i: (-i.bytes, i.path))
    refused.sort(key=lambda i: i.path)
    digest = hashlib.sha256("\n".join(
        f"{i.item_id}\t{i.bytes}\t{i.age_days:.3f}\t{i.ok}\t{i.reason}"
        for i in (*eligible, *refused)).encode()).hexdigest()

    return TmpfsPlan(generated_at=_iso(now), volumes=tuple(volumes), policy=policy,
                     reclaimable=tuple(eligible), protected=tuple(refused),
                     total_bytes=sum(i.bytes for i in eligible),
                     scanned_entries=len(entries),
                     scanned_bytes=sum(i.bytes for i in entries),
                     digest=digest, errors=tuple(errors))
