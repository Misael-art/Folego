"""Contratos do motor comum (F2): independentes de Qt, serializáveis e validados.

Estes modelos são a linguagem compartilhada entre GUI, CLI e futuras automações:
um ``ActionPlan`` diz *o quê*, sobre qual identidade estável, com que parâmetros e
até quando vale; um ``Grant`` diz o que está autorizado e por quanto tempo; um
``ActionResult`` diz o que aconteceu, inclusive quando o resultado é parcial,
desconhecido ou uma recusa. Serialização versionada (``schema``) e validação na
entrada: um plano alterado no caminho não passa, porque o digest é recalculado.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping
from types import MappingProxyType

SCHEMA = 1


class ValidationError(ValueError):
    """Entrada recusada na fronteira: tipo, forma, versão ou digest divergente."""


class Outcome(StrEnum):
    OK = "sucesso"
    PARTIAL = "parcial"
    REFUSED = "recusa"
    FAILED = "falha"
    CANCELLED = "cancelamento"
    UNKNOWN = "desconhecido"


class OperationStatus(StrEnum):
    UNKNOWN = "desconhecido"
    INTENDED = "intencao"
    COMPLETED = "concluida"


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise ValidationError(message)


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(_plain(payload), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _plain(value):
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def _freeze(value):
    if isinstance(value, Mapping):
        _require(all(isinstance(k, str) for k in value), "snapshot: chaves precisam ser strings")
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(v) for v in value)
    _require(value is None or isinstance(value, (str, bool, int, float)),
             "snapshot: valor não é JSON")
    _require(not isinstance(value, float) or math.isfinite(value), "snapshot: número não finito")
    return value


def digest_of(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _now() -> float:
    return time.time()


def _schema_in(row: Mapping[str, Any], what: str) -> None:
    _require(isinstance(row, dict), f"{what}: esperava um objeto JSON")
    _require(row.get("schema") == SCHEMA,
             f"{what}: schema {row.get('schema')!r} não suportado (esperado {SCHEMA})")


# --------------------------------------------------------------------- identities

KINDS = ("path", "process", "entry", "volume", "tuning", "group")


@dataclass(frozen=True)
class ResourceIdentity:
    """Identidade estável de um alvo — nunca só um caminho ou um PID soltos.

    ``process`` exige ``pid`` + ``start_ticks`` (reuso de PID não confunde);
    ``path`` carrega ``dev``/``ino`` quando conhecidos; ``entry`` é o id do ledger.
    """

    kind: str
    key: str
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        _require(self.kind in KINDS, f"identidade: kind desconhecido: {self.kind!r}")
        _require(isinstance(self.key, str) and bool(self.key),
                 "identidade: key vazia")
        detail = dict(self.detail)
        _require(all(isinstance(k, str) for k in detail),
                 "identidade: detail só aceita chaves string")
        if self.kind == "process":
            pid, start = detail.get("pid"), detail.get("start_ticks")
            _require(isinstance(pid, int) and not isinstance(pid, bool) and pid > 0,
                     "identidade de processo: pid inteiro > 0 é obrigatório")
            _require(isinstance(start, int) and not isinstance(start, bool) and start >= 0,
                     "identidade de processo: start_ticks é obrigatório (reuso de PID)")
        object.__setattr__(self, "detail", _freeze(detail))

    # ------------------------------------------------------------- construtores
    @classmethod
    def path(cls, value: str | Path, *, dev: int | None = None,
             ino: int | None = None) -> "ResourceIdentity":
        detail = {k: v for k, v in (("dev", dev), ("ino", ino)) if v is not None}
        return cls("path", str(value), detail)

    @classmethod
    def process(cls, pid: int, start_ticks: int) -> "ResourceIdentity":
        return cls("process", f"{pid}:{start_ticks}",
                   {"pid": pid, "start_ticks": start_ticks})

    @classmethod
    def entry(cls, entry_id: str) -> "ResourceIdentity":
        return cls("entry", str(entry_id))

    @classmethod
    def tuning(cls, action_id: str) -> "ResourceIdentity":
        return cls("tuning", str(action_id))

    # ------------------------------------------------------------- serialização
    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "kind": self.kind, "key": self.key,
                "detail": _plain(self.detail)}

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "ResourceIdentity":
        _schema_in(row, "identidade")
        _require(isinstance(row.get("detail", {}), dict),
                 "identidade: detail precisa ser objeto")
        return cls(row.get("kind"), row.get("key"), row.get("detail") or {})


# ------------------------------------------------------------------------- plans


@dataclass(frozen=True)
class ActionPlan:
    """O que será feito, sobre o quê, com quais limites e até quando vale.

    ``digest`` cobre ação + alvo + parâmetros: um plano que chega alterado de
    outra camada não é executado. ``expires_at`` é o prazo do plano — plano
    expirado é recusado pelo coordenador, não revalidado no escuro.
    """

    action: str
    target: ResourceIdentity
    params: Mapping[str, Any] = field(default_factory=dict)
    operation_id: str = ""
    created_at: float = 0.0
    expires_at: float | None = None
    notes: tuple[str, ...] = ()
    plan_version: int = 2
    policy_version: int = 1

    def __post_init__(self):
        _require(isinstance(self.action, str) and "." in self.action,
                 f"plano: action inválida: {self.action!r}")
        _require(isinstance(self.target, ResourceIdentity),
                 "plano: target precisa ser ResourceIdentity")
        _require(isinstance(self.params, Mapping), "plano: params precisa ser objeto")
        if not self.operation_id:
            object.__setattr__(self, "operation_id", uuid.uuid4().hex)
        _require(isinstance(self.operation_id, str) and bool(self.operation_id),
                 "plano: operation_id inválido")
        if not self.created_at:
            object.__setattr__(self, "created_at", _now())
        if self.plan_version == 2 and self.expires_at is None:
            object.__setattr__(self, "expires_at", self.created_at + 300.0)
        _require(isinstance(self.created_at, (int, float)) and self.created_at > 0,
                 "plano: created_at inválido")
        if self.expires_at is not None:
            _require(isinstance(self.expires_at, (int, float)) and
                     self.expires_at > self.created_at,
                     "plano: expires_at precisa ser posterior a created_at")
        _require(self.plan_version in (1, 2), "plano: versão não suportada")
        _require(type(self.policy_version) is int and self.policy_version == 1,
                 "plano: política não suportada")
        _require(math.isfinite(self.created_at), "plano: created_at não finito")
        _require(self.expires_at is None or math.isfinite(self.expires_at),
                 "plano: expires_at não finito")
        object.__setattr__(self, "params", _freeze(self.params))
        object.__setattr__(self, "notes", tuple(self.notes))
        _require(all(isinstance(note, str) for note in self.notes), "plano: notes precisa conter texto")

    @property
    def digest(self) -> str:
        fields = {"schema": SCHEMA, "action": self.action,
                  "target": self.target.to_dict(), "params": self.params}
        if self.plan_version == 2:
            fields.update(plan_version=2, policy_version=self.policy_version,
                          operation_id=self.operation_id, created_at=self.created_at,
                          expires_at=self.expires_at, notes=self.notes)
        return digest_of(fields)

    def expired(self, now: float | None = None) -> bool:
        now = _now() if now is None else now
        return self.expires_at is not None and now >= self.expires_at

    def to_dict(self) -> dict:
        row = {"schema": SCHEMA, "operation_id": self.operation_id,
                "action": self.action, "target": self.target.to_dict(),
                "params": _plain(self.params), "created_at": self.created_at,
                "expires_at": self.expires_at, "notes": list(self.notes),
                "digest": self.digest}
        if self.plan_version == 2:
            row.update(plan_version=2, policy_version=self.policy_version)
        return row

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "ActionPlan":
        _schema_in(row, "plano")
        plan = cls(action=row.get("action"),
                   target=ResourceIdentity.from_dict(row.get("target") or {}),
                   params=row.get("params") or {}, operation_id=row.get("operation_id") or "",
                   created_at=row.get("created_at") or 0.0,
                   expires_at=row.get("expires_at"),
                   notes=tuple(row.get("notes") or ()),
                   plan_version=row.get("plan_version", 1),
                   policy_version=row.get("policy_version", 1))
        stored = row.get("digest")
        _require(stored == plan.digest,
                 "plano: digest não confere — o plano foi alterado no caminho")
        return plan


# ------------------------------------------------------------------------ grants


@dataclass(frozen=True)
class Grant:
    """Autorização persistida, limitada e revogável (nunca implícita).

    ``limits`` compara por chave de ``plan.params``: inteiro é teto (``<=``),
    string/valor é igualdade, lista é pertinência. Sem limite para a chave, o
    parâmetro não é coberto — o grant é fechado por construção.
    """

    grant_id: str
    action: str
    limits: Mapping[str, Any] = field(default_factory=dict)
    issued_at: float = 0.0
    expires_at: float | None = None
    revoked_at: float | None = None
    source: str = "usuario"
    resources: tuple[ResourceIdentity, ...] = ()

    def __post_init__(self):
        _require(bool(self.grant_id), "grant: grant_id vazio")
        _require(isinstance(self.action, str) and "." in self.action,
                 f"grant: action inválida: {self.action!r}")
        if not self.issued_at:
            object.__setattr__(self, "issued_at", _now())
        _require(isinstance(self.limits, Mapping), "grant: limits precisa ser objeto")
        for name, value in (("issued_at", self.issued_at), ("expires_at", self.expires_at),
                            ("revoked_at", self.revoked_at)):
            _require(value is None or (type(value) in (int, float) and math.isfinite(value)),
                     f"grant: {name} precisa ser finito")
        object.__setattr__(self, "limits", _freeze(self.limits))
        _require(all(isinstance(r, ResourceIdentity) for r in self.resources),
                 "grant: resources precisa conter identidades")
        object.__setattr__(self, "resources", tuple(self.resources))

    def active(self, now: float | None = None) -> bool:
        now = _now() if now is None else now
        if not self.resources or not self.limits:
            return False
        if (self.action != "tmpfs.release" or set(self.limits) - {"bytes", "volume"}
                or type(self.limits.get("bytes")) is not int or self.limits["bytes"] < 0
                or self.expires_at is None or not 0 < self.expires_at - self.issued_at <= 86400):
            return False
        if self.revoked_at is not None:
            return False
        if self.issued_at > now:
            return False
        return self.expires_at is None or now < self.expires_at

    def covers(self, plan: ActionPlan) -> tuple[bool, str]:
        if plan.action != self.action:
            return False, f"ação {plan.action} fora do grant {self.grant_id}"
        if self.action != "tmpfs.release" or set(self.limits) - {"bytes", "volume"}:
            return False, "ação/parâmetros fora do schema autorizado"
        if plan.target.kind == "path" and any(
                type(plan.target.detail.get(key)) is not int or plan.target.detail[key] <= 0
                for key in ("dev", "ino")):
            return False, "identidade de caminho incompleta; device/inode obrigatórios"
        if not self.limits:
            return False, "grant vazio não autoriza parâmetros ou alvos"
        for key, limit in self.limits.items():
            if key not in plan.params:
                return False, f"parâmetro obrigatório ausente no plano: {key}"
            value = plan.params[key]
            if isinstance(limit, (int, float)) and not isinstance(limit, bool):
                if limit < 0 or (isinstance(value, (int, float)) and value < 0):
                    return False, f"{key}: limite/valor negativo não autorizado"
            if isinstance(limit, bool) or limit is None:
                if value != limit:
                    return False, f"{key}={value!r} difere do grant ({limit!r})"
            elif isinstance(limit, int):
                if not isinstance(value, int) or isinstance(value, bool) or value > limit:
                    return False, f"{key}={value!r} excede o teto {limit}"
            elif isinstance(limit, (list, tuple)):
                if value not in limit:
                    return False, f"{key}={value!r} fora da lista do grant"
            elif value != limit:
                return False, f"{key}={value!r} difere do grant ({limit!r})"
        extra = set(plan.params) - set(self.limits)
        if extra:
            return False, "parâmetros não autorizados: " + ", ".join(sorted(extra))
        if plan.target not in self.resources:
            return False, "identidade do alvo fora do escopo autorizado"
        return True, "coberto"

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "grant_id": self.grant_id, "action": self.action,
                "limits": _plain(self.limits), "issued_at": self.issued_at,
                "expires_at": self.expires_at, "revoked_at": self.revoked_at,
                "source": self.source, "resources": [r.to_dict() for r in self.resources]}

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "Grant":
        _schema_in(row, "grant")
        _require(not (set(row) - {"schema", "grant_id", "action", "limits", "issued_at",
                                 "expires_at", "revoked_at", "source", "resources"}),
                 "grant: campos inesperados")
        _require(isinstance(row.get("resources", []), list), "grant: resources precisa ser lista")
        return cls(grant_id=row.get("grant_id") or "", action=row.get("action"),
                   limits=row.get("limits") or {}, issued_at=row.get("issued_at") or 0.0,
                   expires_at=row.get("expires_at"), revoked_at=row.get("revoked_at"),
                   source=row.get("source") or "usuario",
                   resources=tuple(ResourceIdentity.from_dict(r) for r in row.get("resources", [])))


# ----------------------------------------------------------------------- results


@dataclass(frozen=True)
class ActionResult:
    """O veredito estruturado de um ato — inclusive quando não houve ato."""

    action: str
    outcome: Outcome
    operation_id: str = ""
    reason: str | None = None
    target_key: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    effects: Mapping[str, Any] = field(default_factory=dict)
    errors: tuple[str, ...] = ()

    def __post_init__(self):
        _require(isinstance(self.action, str) and "." in self.action,
                 f"resultado: action inválida: {self.action!r}")
        try:
            outcome = Outcome(self.outcome)
        except ValueError:
            raise ValidationError(f"resultado: outcome desconhecido: {self.outcome!r}")
        object.__setattr__(self, "outcome", outcome)
        _require(isinstance(self.effects, Mapping), "resultado: effects precisa ser objeto")
        object.__setattr__(self, "effects", dict(self.effects))
        object.__setattr__(self, "errors", tuple(self.errors))

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.OK

    @property
    def partial(self) -> bool:
        return self.outcome is Outcome.PARTIAL

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "operation_id": self.operation_id,
                "action": self.action, "outcome": str(self.outcome),
                "reason": self.reason, "target_key": self.target_key,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "effects": dict(self.effects), "errors": list(self.errors)}

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "ActionResult":
        _schema_in(row, "resultado")
        return cls(action=row.get("action"), outcome=row.get("outcome"),
                   operation_id=row.get("operation_id") or "",
                   reason=row.get("reason"), target_key=row.get("target_key") or "",
                   started_at=row.get("started_at"), finished_at=row.get("finished_at"),
                   effects=row.get("effects") or {}, errors=tuple(row.get("errors") or ()))


@dataclass(frozen=True)
class OperationState:
    """O que o diário sabe de uma operação: nenhuma linha, intenção, ou resultado."""

    operation_id: str
    status: OperationStatus
    intent: ActionPlan | None = None
    result: ActionResult | None = None
    intent_seq: int | None = None
    result_seq: int | None = None

    def __post_init__(self):
        _require(bool(self.operation_id), "estado: operation_id vazio")
        try:
            status = OperationStatus(self.status)
        except ValueError:
            raise ValidationError(f"estado: status desconhecido: {self.status!r}")
        object.__setattr__(self, "status", status)

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "operation_id": self.operation_id,
                "status": str(self.status),
                "intent": self.intent.to_dict() if self.intent else None,
                "result": self.result.to_dict() if self.result else None,
                "intent_seq": self.intent_seq, "result_seq": self.result_seq}

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "OperationState":
        _schema_in(row, "estado")
        intent = row.get("intent")
        result = row.get("result")
        return cls(operation_id=row.get("operation_id") or "",
                   status=row.get("status"),
                   intent=ActionPlan.from_dict(intent) if intent else None,
                   result=ActionResult.from_dict(result) if result else None,
                   intent_seq=row.get("intent_seq"), result_seq=row.get("result_seq"))

    @classmethod
    def unknown(cls, operation_id: str) -> "OperationState":
        return cls(operation_id, OperationStatus.UNKNOWN)
