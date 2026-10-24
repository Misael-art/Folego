"""Automation policy (F6): manual by default, simulation before execution.

This module decides *whether a candidate action would be allowed*, not how to
perform it. It never calls an executor, never touches the system and never widens
a grant. Modes, presets and grants are three independent inputs:

* mode says whether automation may run at all (manual/assisted/automatic);
* preset says how patient it must be (sustainability, warm-up, rate, breaker);
* grant says what it may touch, for how long and with which parameter ceilings.

Changing a preset cannot add an action or loosen a grant. A stale, missing or
unknown observation suspends the decision; a reboot/resume needs fresh proof; an
exhausted quota or an unproven owner refuses. The first (and currently only)
automation scope is ``tmpfs.release`` on a managed volume; discovered processes,
orphans and virtual disks stay manual by construction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..core.snapshot import Snapshot

MANUAL = "manual"
ASSISTED = "assistido"
AUTOMATIC = "automatico"
MODES = (MANUAL, ASSISTED, AUTOMATIC)

#: A primeira automação é deliberadamente estreita. Qualquer outra ação exige
#: revisão explícita e não entra por preset.
FIRST_AUTOMATION_ACTIONS = ("tmpfs.release",)

DESLIGADO = "desligado"
RECUSAR = "recusar"
SUSPENDER = "suspender"
AGUARDAR = "aguardar"
SIMULAR = "simular"
EXECUTAR = "executar"


@dataclass(frozen=True)
class Preset:
    name: str
    sustain_samples: int
    warmup_s: float
    min_interval_s: float
    max_per_hour: int
    max_failures: int = 2

    def __post_init__(self):
        if self.sustain_samples < 1:
            raise ValueError("preset: sustain_samples precisa ser >= 1")
        if self.warmup_s < 0 or self.min_interval_s < 0:
            raise ValueError("preset: tempos não podem ser negativos")
        if self.max_per_hour < 1 or self.max_failures < 1:
            raise ValueError("preset: limites precisam ser >= 1")


PRESETS: Mapping[str, Preset] = {
    "conservador": Preset("conservador", sustain_samples=5, warmup_s=300,
                          min_interval_s=300, max_per_hour=2, max_failures=1),
    "equilibrado": Preset("equilibrado", sustain_samples=3, warmup_s=120,
                          min_interval_s=120, max_per_hour=4, max_failures=2),
    "foco": Preset("foco", sustain_samples=2, warmup_s=60,
                   min_interval_s=60, max_per_hour=6, max_failures=2),
    "manutencao": Preset("manutencao", sustain_samples=6, warmup_s=600,
                         min_interval_s=600, max_per_hour=1, max_failures=1),
    "personalizado": Preset("personalizado", sustain_samples=3, warmup_s=120,
                            min_interval_s=120, max_per_hour=4, max_failures=2),
}


@dataclass(frozen=True)
class Candidate:
    """The observed opportunity plus the evidence the policy is allowed to use."""

    plan: object
    required_sources: tuple[str, ...] = ("meminfo",)
    protected: bool = False
    unknown: bool = False
    owner_verified: bool = False
    over_budget: bool = False
    budget_reason: str = ""
    sustained_samples: int = 0
    observed_for_s: float = 0.0
    runs_last_hour: int = 0
    consecutive_failures: int = 0
    last_run_at: float | None = None
    boot_id: str = ""
    last_boot_id: str = ""
    needs_revalidation: bool = False


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str
    plan: object | None = None
    preset: str = ""

    @property
    def will_execute(self) -> bool:
        return self.kind == EXECUTAR

    @property
    def simulated(self) -> bool:
        return self.kind == SIMULAR


def evaluate(snapshot: Snapshot, candidate: Candidate, *, mode: str,
             preset: str | Preset = "equilibrado", grant=None,
             now: float, max_age_s: float = 15.0,
             now_mono: float | None = None) -> Decision:
    """Return a decision without performing anything.

    ``now`` is wall-clock time for grants/plans; freshness uses the snapshot's
    monotonic clock. Passing the clocks explicitly keeps tests deterministic.
    """
    preset_obj = PRESETS.get(preset) if isinstance(preset, str) else preset
    if preset_obj is None:
        return Decision(RECUSAR, f"preset desconhecido: {preset!r}",
                        candidate.plan, str(preset))
    if mode not in MODES:
        return Decision(RECUSAR, f"modo desconhecido: {mode!r}",
                        candidate.plan, preset_obj.name)
    if mode == MANUAL:
        return Decision(DESLIGADO, "modo manual: nenhuma automação",
                        candidate.plan, preset_obj.name)

    plan = candidate.plan
    if getattr(plan, "action", "") not in FIRST_AUTOMATION_ACTIONS:
        return Decision(RECUSAR,
                        f"ação {getattr(plan, 'action', plan)!r} fora do escopo "
                        "automático inicial (somente tmpfs.release)",
                        plan, preset_obj.name)
    if candidate.protected:
        return Decision(RECUSAR, "recurso protegido por projeto/exclusão",
                        plan, preset_obj.name)
    if candidate.unknown:
        return Decision(RECUSAR,
                        "recurso desconhecido ou parcial: preservado, nunca "
                        "tratado como livre", plan, preset_obj.name)
    if grant is None:
        return Decision(RECUSAR, "sem grant: automação desligada",
                        plan, preset_obj.name)
    if not grant.active(now):
        return Decision(RECUSAR, "grant revogado, futuro ou expirado",
                        plan, preset_obj.name)
    covered, why = grant.covers(plan)
    if not covered:
        return Decision(RECUSAR, f"grant não cobre o plano: {why}",
                        plan, preset_obj.name)
    if getattr(plan, "expires_at", None) is not None and plan.expired(now):
        return Decision(RECUSAR, "plano expirado; nada será reexecutado",
                        plan, preset_obj.name)

    blockers = snapshot.action_blockers(
        required=candidate.required_sources, max_age_s=max_age_s,
        now_mono=now_mono)
    if blockers:
        return Decision(SUSPENDER,
                        "telemetria ausente, parcial ou antiga: " + "; ".join(blockers),
                        plan, preset_obj.name)
    if candidate.needs_revalidation:
        return Decision(SUSPENDER,
                        "retomada/reboot exige revalidar propriedade e plano",
                        plan, preset_obj.name)
    if candidate.last_boot_id and candidate.boot_id != candidate.last_boot_id:
        return Decision(SUSPENDER,
                        "boot diferente desde a última decisão: revalidar",
                        plan, preset_obj.name)
    if not candidate.owner_verified:
        return Decision(RECUSAR,
                        "propriedade do recurso não comprovada; permanece manual",
                        plan, preset_obj.name)
    if candidate.over_budget:
        reason = candidate.budget_reason or "orçamento de retenção esgotado"
        return Decision(RECUSAR, reason, plan, preset_obj.name)
    if candidate.consecutive_failures >= preset_obj.max_failures:
        return Decision(SUSPENDER,
                        "disjuntor aberto após falhas seguidas; nenhuma escalada",
                        plan, preset_obj.name)
    if candidate.sustained_samples < preset_obj.sustain_samples:
        return Decision(
            AGUARDAR,
            f"gatilho sustentado por {candidate.sustained_samples}/"
            f"{preset_obj.sustain_samples} amostras", plan, preset_obj.name)
    if candidate.observed_for_s < preset_obj.warmup_s:
        return Decision(
            AGUARDAR,
            f"aquecimento {candidate.observed_for_s:.0f}s/"
            f"{preset_obj.warmup_s:.0f}s", plan, preset_obj.name)
    if candidate.last_run_at is not None:
        elapsed = now - candidate.last_run_at
        if elapsed < preset_obj.min_interval_s:
            return Decision(
                AGUARDAR,
                f"intervalo mínimo: {elapsed:.0f}s/{preset_obj.min_interval_s:.0f}s",
                plan, preset_obj.name)
    if candidate.runs_last_hour >= preset_obj.max_per_hour:
        return Decision(AGUARDAR,
                        f"limite por hora atingido: {candidate.runs_last_hour}/"
                        f"{preset_obj.max_per_hour}", plan, preset_obj.name)

    if mode == ASSISTED:
        return Decision(SIMULAR,
                        "modo assistido: registraria a decisão sem executar",
                        plan, preset_obj.name)
    return Decision(EXECUTAR,
                    "modo automático: grant, evidência e limites conferem",
                    plan, preset_obj.name)
