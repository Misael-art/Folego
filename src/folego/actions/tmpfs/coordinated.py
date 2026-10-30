"""Ponte F2: os atos de tmpfs rodam sob o coordenador único.

O domínio (`release_item`, `restore_item`, `expire_over_budget`,
`recover_staging`) não conhece o motor comum: esta ponte é o único lugar que
liga os atos de tmpfs ao coordenador e traduz o resultado do domínio para o
``ActionResult`` estruturado (o esqueleto ``perform``/``Coordinated`` é
compartilhado em ``orchestration``). Sem confirmação nada entra no diário:
recusa de flag e dry-run continuam respondendo direto pelo domínio, que é quem
tem as mensagens. Devolve as duas faces (``Coordinated``) porque a CLI imprime
o texto do domínio e o diário guarda o veredito.
"""
from __future__ import annotations

from ...orchestration import (ActionResult, Coordinator, Coordinated, Outcome,
                              ResourceIdentity, perform)
from . import release as _release
from .release import ExpireResult, RecoverResult, ReleaseResult, RestoreResult

# ------------------------------------------------------------------ vereditos


def _verdict_release(result: ReleaseResult, target_key: str) -> ActionResult:
    if result.ok:
        outcome = Outcome.OK
    elif result.stored:
        # Clone retido e origem intacta: o ato fez parte do caminho (o ledger já
        # o registrou como `partial`), e chamar isso de recusa seria mentir sobre
        # o byte que saiu para a SSD.
        outcome = Outcome.PARTIAL
    else:
        outcome = Outcome.REFUSED
    return ActionResult(action=_release.KIND, outcome=outcome, target_key=target_key,
                        reason=result.reason,
                        effects={"entry_id": result.entry_id, "bytes": result.bytes,
                                 "stored": result.stored, "sha256": result.sha256,
                                 "freed_bytes": result.freed_bytes,
                                 "allocated_bytes": result.allocated_bytes,
                                 "ram_observed_bytes": result.ram_observed_bytes})


def _verdict_restore(result: RestoreResult, target_key: str) -> ActionResult:
    return ActionResult(action=_release.RESTORE_KIND,
                        outcome=Outcome.OK if result.ok else Outcome.REFUSED,
                        target_key=target_key, reason=result.reason,
                        effects={"entry_id": result.entry_id, "bytes": result.bytes,
                                 "restored_to": result.restored_to})


def _verdict_expire(result: ExpireResult, target_key: str) -> ActionResult:
    if not result.ok:
        outcome = Outcome.REFUSED
    elif result.errors:
        # O ato rodou e relatou suspeita (payload sumido, guard recusando): isso é
        # parcial nomeado, nunca um `sucesso` limpo por cima de erro relatado. O
        # que cada vítima sofreu está em `errors`/`effects`, não no vocabulário.
        outcome = Outcome.PARTIAL
    else:
        outcome = Outcome.OK
    return ActionResult(action=_release.EXPIRE_KIND, outcome=outcome,
                        target_key=target_key, reason=result.reason,
                        effects={"victims": list(result.victims),
                                 "freed_bytes": result.freed_bytes},
                        errors=tuple(result.errors))


def _verdict_recover(result: RecoverResult, target_key: str) -> ActionResult:
    if not result.ok and not result.errors:
        # recusa do ledger (nada rodou): chamar isso de sucesso ou de parcial
        # mentiria sobre o ato — desfecho encontrado pela entrega 7, que expôs a
        # recusa journalada como `sucesso` no recover confirmado
        outcome = Outcome.REFUSED
    elif result.errors or result.kept or not result.ok:
        # Falha relatada ou clone mantido para decisão manual: o ato pode ter
        # descartado parte, mas o assunto não fechou — parcial nomeado, nunca
        # sucesso limpo por cima do que ficou pendente.
        outcome = Outcome.PARTIAL
    else:
        outcome = Outcome.OK
    return ActionResult(action=_release.RECOVER_KIND, outcome=outcome,
                        target_key=target_key, reason=result.reason,
                        effects={"dropped": list(result.dropped),
                                 "kept": list(result.kept),
                                 "notes": list(result.notes)},
                        errors=tuple(result.errors))


# ---------------------------------------------------------------------- verbos


def release(*, coordinator: Coordinator, confirm: bool, plan, item, ledger,
            dest_root, audit, allowed_roots, now=None) -> Coordinated:
    def act():
        return _release.release_item(plan, item, ledger=ledger, dest_root=dest_root,
                                     audit=audit, confirm=confirm,
                                     allowed_roots=allowed_roots, now=now)

    if not confirm:
        return Coordinated(act(), None)
    return perform(
        coordinator=coordinator, action=_release.KIND,
        target=ResourceIdentity("path", item.path, {"volume": item.volume}),
        params={"bytes": item.bytes, "volume": item.volume},
        act=act, verdict=_verdict_release)


def restore(*, coordinator: Coordinator, confirm: bool, target, ledger, audit,
            allowed_roots, now=None) -> Coordinated:
    def act():
        return _release.restore_item(target, ledger=ledger, audit=audit,
                                     confirm=confirm, allowed_roots=allowed_roots,
                                     now=now)

    if not confirm:
        return Coordinated(act(), None)
    return perform(
        coordinator=coordinator, action=_release.RESTORE_KIND,
        target=ResourceIdentity.entry(str(target)), params={},
        act=act, verdict=_verdict_restore)


def expire(*, coordinator: Coordinator, confirm: bool, irreversible: bool,
           ledger, audit, days, max_bytes, allowed_roots, now=None) -> Coordinated:
    def act():
        return _release.expire_over_budget(
            ledger=ledger, audit=audit, days=days, max_bytes=max_bytes,
            confirm=confirm, irreversible=irreversible, now=now,
            allowed_roots=allowed_roots)

    if not (confirm and irreversible):
        # dry-run e recusa de flag não mutam: quem responde é o domínio, e o
        # diário não ganha operação de um ato que não aconteceria de todo.
        return Coordinated(act(), None)
    return perform(
        coordinator=coordinator, action=_release.EXPIRE_KIND,
        target=ResourceIdentity("group", "tmpfs.excedente"),
        params={"days": days, "max_bytes": max_bytes},
        act=act, verdict=_verdict_expire)


def recover(*, coordinator: Coordinator, confirm: bool, ledger, audit,
            allowed_roots) -> Coordinated:
    def act():
        return _release.recover_staging(ledger=ledger, audit=audit, confirm=confirm,
                                        allowed_roots=allowed_roots)

    if not confirm:
        # o dry-run do recover é o inventário do que seria descartado: não muta,
        # não entra no diário, e quem responde é o domínio.
        return Coordinated(act(), None)
    return perform(
        coordinator=coordinator, action=_release.RECOVER_KIND,
        target=ResourceIdentity("group", "tmpfs.staging"), params={},
        act=act, verdict=_verdict_recover)
