"""Tuning mutations share the disk/tmpfs coordinator and durable journal."""
from ...orchestration import ActionResult, Coordinator, Coordinated, Outcome, ResourceIdentity, perform
from .engine import ApplyResult, RevertResult


def _identity(tuning, target):
    detail = {"path": str(target)}
    try:
        info = target.lstat()
        detail.update(dev=info.st_dev, ino=info.st_ino, mode=info.st_mode)
    except FileNotFoundError:
        detail["absent"] = True
        info = target.parent.stat()
        detail.update(parent_dev=info.st_dev, parent_ino=info.st_ino)
    return ResourceIdentity("tuning", tuning.id, detail)


def _verdict(action, result, key):
    outcome = Outcome.OK if result.ok else Outcome.REFUSED
    # A backup or a verified rollback is observable state, even if application
    # did not finish as requested. Never label it as a no-effect refusal.
    if not result.ok and result.backup_id and action == "tuning.apply":
        outcome = Outcome.PARTIAL
    if not result.ok and getattr(result, "effect_started", False):
        outcome = Outcome.UNKNOWN
    return ActionResult(action, outcome, target_key=key, reason=result.reason,
                        effects={"backup_id": result.backup_id, "sha": result.sha,
                                 "file": str(result.target)})


def apply(engine, plan, *, confirm=False, coordinator=None):
    if not confirm:
        return Coordinated(engine.apply(plan, confirm=False), None)
    try:
        target = _identity(plan.tuning, plan.target)
    except OSError as exc:
        return Coordinated(ApplyResult(plan.tuning, plan.target, False,
                                       f"identidade não comprovada: {exc}"), None)

    def act():
        if _identity(plan.tuning, plan.target) != target:
            return ApplyResult(plan.tuning, plan.target, False,
                               "arquivo/identidade mudou após o plano; faça nova análise")
        return engine.apply(plan, confirm=True)

    return perform(coordinator=coordinator or Coordinator(), action="tuning.apply", target=target,
                   params={"before_sha": plan.before_sha, "after_sha": plan.after_sha},
                   act=act, verdict=lambda result, key: _verdict("tuning.apply", result, key))


def revert(engine, tuning, *, confirm=False, coordinator=None):
    if not confirm:
        return Coordinated(engine.revert(tuning, confirm=False), None)
    path = tuning.target()
    try:
        target = _identity(tuning, path)
    except OSError as exc:
        return Coordinated(RevertResult(tuning, path, False,
                                        f"identidade não comprovada: {exc}"), None)

    def act():
        if _identity(tuning, path) != target:
            return RevertResult(tuning, path, False,
                                "arquivo/identidade mudou antes de restaurar")
        return engine.revert(tuning, confirm=True)

    return perform(coordinator=coordinator or Coordinator(), action="tuning.revert", target=target,
                   params={}, act=act, verdict=lambda result, key: _verdict("tuning.revert", result, key))
