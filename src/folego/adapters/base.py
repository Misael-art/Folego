"""Common, read-only inventory contract for F7 adapters.

Every adapter returns availability, evidence, items and explicit protections in
the same shape. Inventory never mutates: the later action layer will have to add
plan/result separately, and absence of a tool is an unavailable adapter, never an
exception that takes the whole app down.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class InventoryItem:
    item_id: str
    label: str
    kind: str
    bytes_observed: int | None = None
    protected: bool = False
    reason: str = ""
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"item_id": self.item_id, "label": self.label, "kind": self.kind,
                "bytes_observed": self.bytes_observed,
                "protected": self.protected, "reason": self.reason,
                "detail": dict(self.detail)}


@dataclass(frozen=True)
class AdapterResult:
    name: str
    available: bool
    items: tuple[InventoryItem, ...] = ()
    evidence: tuple[str, ...] = ()
    reason: str = ""
    error: str = ""
    plan: tuple = ()
    result: None = None

    @property
    def protected(self) -> tuple[InventoryItem, ...]:
        return tuple(item for item in self.items if item.protected)

    def to_dict(self) -> dict:
        return {"name": self.name, "available": self.available,
                "items": [item.to_dict() for item in self.items],
                "evidence": list(self.evidence), "reason": self.reason,
                "error": self.error, "plan": list(self.plan), "result": self.result}


class Adapter:
    name = "adapter"

    def inventory(self) -> AdapterResult:  # pragma: no cover - interface
        raise NotImplementedError


def unavailable(name: str, reason: str) -> AdapterResult:
    return AdapterResult(name=name, available=False, reason=reason)
