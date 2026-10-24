"""M4 actions: terminate proven orphans or a whole browser group.

Every signal is preceded by a fresh /proc read. A snapshot is a statement about
the past; the pid in it may already be recycled, re-parented or renamed, and a
second SIGKILL to the wrong pid takes someone's unsaved work. So the live check
has to pass again at the moment of the click. The pidfd is opened **before** the
re-read: even a recycle between the check and the signal cannot receive it.

SIGTERM is followed for a bounded window: `exited is True` means the process was
observed gone (or a zombie — it no longer runs), `False` means it survived and
is named as such. Survivors are never escalated automatically; SIGKILL only
happens when the caller asks for it explicitly and confirms.
"""
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from signal import SIGKILL, SIGTERM

from ... import paths
from ...core import procfs
from ...core.orphans import is_adopted, is_protected, is_tooling, under_automation_control
from ...core.snapshot import ProcInfo
from ...safely import procs
from ...safely.audit import AuditLog

CONFIRM_REQUIRED = "recusado: encerramento forçado exige confirmação explícita"


@dataclass(frozen=True)
class TermResult:
    pid: int
    comm: str
    ok: bool
    signal: int
    reason: str | None = None
    # None = não acompanhado (porta fechada/recusa, ou acompanhamento desligado)
    exited: bool | None = None
    identity: str = "starttime"  # como a identidade foi estabilizada no ato


class Reaper:
    def __init__(self, *, proc_root=None, kill_fn=os.kill, audit: AuditLog | None = None,
                 pin_fn=None, follow_up_s: float = 2.0, poll_s: float = 0.05,
                 clock=time.monotonic, sleep=time.sleep, protected_fn=None):
        self.proc_root = Path(proc_root) if proc_root else Path(paths.proc_root())
        self.kill_fn = kill_fn
        self.audit = audit
        self.pin_fn = pin_fn or procs.pin
        self.follow_up_s = max(0.0, float(follow_up_s))
        self.poll_s = max(0.001, float(poll_s))
        self._clock = clock
        self._sleep = sleep
        self.protected_fn = protected_fn

    def terminate(self, target, *, require_orphan: bool = True) -> TermResult:
        return self._send(target, SIGTERM, kind="process.terminate",
                          action_id="orphans.term", require_orphan=require_orphan)

    def force(self, target, *, confirm: bool = False,
              require_orphan: bool = True) -> TermResult:
        if not confirm:
            return self._refuse(target, SIGKILL, kind="process.kill",
                               action_id="orphans.kill", reason=CONFIRM_REQUIRED)
        return self._send(target, SIGKILL, kind="process.kill",
                          action_id="orphans.kill", require_orphan=require_orphan)

    def terminate_group(self, group) -> tuple[TermResult, ...]:
        """Group mode: the family is the unit, so orphan rules do not re-apply.

        Every member is checked and signalled first; the SIGTERM follow-up is
        collective, so a family of ten does not wait ten times the window.
        """
        pairs = [
            (self._send(member, SIGTERM, kind="process.group-terminate",
                        action_id=f"groups.{group.group}", require_orphan=False,
                        follow=False), member.starttime)
            for member in group.members]
        return self._follow_group(pairs)

    def terminate_many(self, targets):
        pairs = [(self._send(target, SIGTERM, kind="process.terminate",
                             action_id="orphans.term", require_orphan=True, follow=False),
                  target.starttime) for target in targets]
        return self._follow_group(pairs)

    def force_many(self, targets, *, confirm=False, require_orphan=True):
        if not confirm:
            return tuple(self.force(t, confirm=False, require_orphan=require_orphan) for t in targets)
        pairs = [(self._send(target, SIGKILL, kind="process.kill",
                             action_id="orphans.kill", require_orphan=require_orphan, follow=False),
                  target.starttime) for target in targets]
        return self._follow_group(pairs)

    # ----------------------------------------------------------------– internals

    def _parent(self, live: ProcInfo):
        """The live parent, when it exists: adoption is a relationship between two
        /proc entries, and the click must judge both as they are now."""
        return procfs.read_proc(self.proc_root, live.ppid) if live.ppid else None

    def _gone(self, pid: int, starttime: int) -> bool | None:
        """Saiu de verdade: ausente, zumbi (não roda mais) ou PID com outra vida."""
        live = procfs.read_proc(self.proc_root, pid)
        if live is not None:
            return live.starttime != starttime or live.state == "Z"
        try:
            (self.proc_root / str(pid)).stat()
        except FileNotFoundError:
            try:
                self.proc_root.stat()
            except OSError:
                return None
            return True
        except OSError:
            return None
        return None  # live PID directory, but its identity could not be read

    def _await_exit(self, pid: int, starttime: int, *,
                    deadline: float | None = None) -> bool | None:
        deadline = self._clock() + self.follow_up_s if deadline is None else deadline
        while True:
            gone = self._gone(pid, starttime)
            if gone is True:
                return True
            now = self._clock()
            if now >= deadline:
                return gone
            self._sleep(min(self.poll_s, deadline - now))

    def _follow_group(self, pairs) -> tuple[TermResult, ...]:
        """Acompanha todos os sinais confirmados da leva com um prazo só."""
        if self.follow_up_s <= 0:
            return tuple(result for result, _ in pairs)
        pending = {result.pid: starttime for result, starttime in pairs
                   if result.ok}
        remaining = dict(pending)
        deadline = self._clock() + self.follow_up_s
        while remaining:
            remaining = {pid: starttime for pid, starttime in remaining.items()
                         if not self._gone(pid, starttime)}
            if not remaining:
                break
            now = self._clock()
            if now >= deadline:
                break
            self._sleep(min(self.poll_s, deadline - now))
        exited = {pid: (self._gone(pid, pending[pid]) if pid in remaining else True)
                  for pid in pending}
        return tuple(replace(result, exited=exited[result.pid])
                     if result.pid in exited else result
                     for result, _ in pairs)

    def _send(self, target, sig, *, kind: str, action_id: str,
              require_orphan: bool, follow: bool = True) -> TermResult:
        # o fd (quando existe) é aberto ANTES da releitura: se o PID for
        # reciclado entre a checagem e o sinal, ele ainda aponta para o processo
        # verificado; e um pidfd de processo que sumiu levanta ESRCH, não erra o alvo
        try:
            pinned = self.pin_fn(target.pid)
        except ProcessLookupError:
            return self._refuse(target, sig, kind=kind, action_id=action_id,
                                reason=f"pid {target.pid} não existe mais")
        except OSError as err:
            return self._refuse(target, sig, kind=kind, action_id=action_id,
                                reason=f"não foi possível pinar pid {target.pid}: {err}",
                                outcome="error")
        try:
            live = procfs.read_proc(self.proc_root, target.pid)
            if live is None:
                return self._refuse(target, sig, kind=kind, action_id=action_id,
                                    reason=f"pid {target.pid} não existe mais")
            if live.starttime != target.starttime:
                return self._refuse(target, sig, kind=kind, action_id=action_id,
                                    reason=f"pid {target.pid} foi reutilizado "
                                           f"(nascimento {live.starttime} ≠ "
                                           f"{target.starttime})")
            if is_protected(live):
                return self._refuse(target, sig, kind=kind, action_id=action_id,
                                    reason=f"{live.comm or 'pid ' + str(live.pid)} é alvo protegido")
            if live.comm != target.comm:
                return self._refuse(target, sig, kind=kind, action_id=action_id,
                                    reason="identidade de aplicação mudou após a análise")
            if live.uid != os.getuid() or live.pid == os.getpid():
                return self._refuse(target, sig, kind=kind, action_id=action_id,
                                    reason="UID de outro usuário ou próprio executor: protegido")
            if require_orphan:
                ticks = getattr(target, "cpu_ticks", None)
                if ticks is not None and ticks != live.utime + live.stime:
                    return self._refuse(target, sig, kind=kind, action_id=action_id,
                                        reason="atividade de CPU mudou após a análise; preservar trabalho")
                children = procfs.scan_processes(self.proc_root, limit=8192)
                if children.error or children.unreadable or children.truncated:
                    return self._refuse(target, sig, kind=kind, action_id=action_id,
                                        reason="descendentes não comprovados; leitura de processos incompleta")
                if any(p.ppid == live.pid and p.state != "Z" for p in children.procs):
                    return self._refuse(target, sig, kind=kind, action_id=action_id,
                                        reason="processo passou a ter descendentes; propriedade/trabalho preservados")
            if self.protected_fn is not None:
                # A lista de sessões/exclusões pode mudar entre a montagem da
                # lista e o clique. Revalidar no ato é o que torna "manter ativo"
                # uma promessa, não um detalhe de interface.
                try:
                    extra = self.protected_fn(live)
                except Exception as exc:
                    return self._refuse(
                        target, sig, kind=kind, action_id=action_id,
                        reason=f"proteção ilegível: {type(exc).__name__}: {exc}",
                        outcome="error")
                if extra:
                    return self._refuse(target, sig, kind=kind, action_id=action_id,
                                        reason=f"proteção: {extra}")
            if not require_orphan and (is_tooling(live) or under_automation_control(live)):
                # group mode: a driver may have attached since the list was made, and a
                # family SIGTERM would cut off a session the user cannot see
                return self._refuse(target, sig, kind=kind, action_id=action_id,
                                    reason=f"pid {target.pid} é navegador sob controle de "
                                           f"automação (driver remoto ou shell de teste)")
            if require_orphan and not is_adopted(live, self._parent(live)):
                return self._refuse(target, sig, kind=kind, action_id=action_id,
                                    reason=f"pid {target.pid} já tem pai ({live.ppid}); "
                                           f"não é mais órfão")
            comm = live.comm or target.comm
            try:
                procs.send(pinned, sig, kill_fn=self.kill_fn)
            except PermissionError as err:
                return self._refuse(target, sig, kind=kind, action_id=action_id,
                                    reason=f"sem permissão para sinalizar {comm}: {err}",
                                    outcome="error")
            except ProcessLookupError:
                return replace(
                    self._record(target, sig, kind=kind, action_id=action_id,
                                 outcome="gone",
                                 reason="já saiu entre a checagem e o sinal",
                                 comm=comm, identity=pinned.method),
                    exited=True)
            except OSError as err:
                return self._refuse(target, sig, kind=kind, action_id=action_id,
                                    reason=str(err), outcome="error")
            result = self._record(
                target, sig, kind=kind, action_id=action_id,
                outcome="signaled" if sig == SIGTERM else "killed",
                reason=None, comm=comm, identity=pinned.method)
            if follow and self.follow_up_s > 0:
                result = replace(result, exited=self._await_exit(target.pid,
                                                                 live.starttime))
            return result
        finally:
            procs.close(pinned)

    def _refuse(self, target, sig, *, kind: str, action_id: str, reason: str,
                outcome: str = "refused") -> TermResult:
        result = TermResult(target.pid, getattr(target, "comm", ""), False, sig, reason)
        self._audit(kind=kind, action_id=action_id, outcome=outcome, result=result,
                    sig=sig)
        return result

    def _record(self, target, sig, *, kind: str, action_id: str, outcome: str,
               reason: str | None, comm: str,
               identity: str = "starttime") -> TermResult:
        result = TermResult(target.pid, comm, True, sig, reason, identity=identity)
        self._audit(kind=kind, action_id=action_id, outcome=outcome,
                    result=result, sig=sig)
        return result

    def _audit(self, *, kind: str, action_id: str, outcome: str, result: TermResult,
               sig: int) -> None:
        if self.audit is None:
            return
        self.audit.append(
            kind=kind, action_id=action_id, outcome=outcome,
            targets=[f"pid={result.pid}", result.comm or "unknown"],
            risk="disruptive" if sig == SIGTERM else "irreversible",
            error=result.reason)
