"""M4 actions: terminate proven orphans or a whole browser group.

Every signal is preceded by a fresh /proc read. A snapshot is a statement about
the past; the pid in it may already be recycled, re-parented or renamed, and a
second SIGKILL to the wrong pid takes someone's unsaved work. So the live check
has to pass again at the moment of the click.
"""
import os
from dataclasses import dataclass
from pathlib import Path
from signal import SIGKILL, SIGTERM

from ... import paths
from ...core import procfs
from ...core.orphans import is_adopted, is_protected, is_tooling, under_automation_control
from ...core.snapshot import ProcInfo
from ...safely.audit import AuditLog

CONFIRM_REQUIRED = "recusado: encerramento forçado exige confirmação explícita"


@dataclass(frozen=True)
class TermResult:
    pid: int
    comm: str
    ok: bool
    signal: int
    reason: str | None = None


class Reaper:
    def __init__(self, *, proc_root=None, kill_fn=os.kill, audit: AuditLog | None = None):
        self.proc_root = Path(proc_root) if proc_root else Path(paths.proc_root())
        self.kill_fn = kill_fn
        self.audit = audit

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
        """Group mode: the family is the unit, so orphan rules do not re-apply."""
        return tuple(
            self._send(member, SIGTERM, kind="process.group-terminate",
                       action_id=f"groups.{group.group}", require_orphan=False)
            for member in group.members)

    # ----------------------------------------------------------------– internals

    def _parent(self, live: ProcInfo):
        """The live parent, when it exists: adoption is a relationship between two
        /proc entries, and the click must judge both as they are now."""
        return procfs.read_proc(self.proc_root, live.ppid) if live.ppid else None

    def _send(self, target, sig, *, kind: str, action_id: str,
              require_orphan: bool) -> TermResult:
        live = procfs.read_proc(self.proc_root, target.pid)
        if live is None:
            return self._refuse(target, sig, kind=kind, action_id=action_id,
                                reason=f"pid {target.pid} não existe mais")
        if live.starttime != target.starttime:
            return self._refuse(target, sig, kind=kind, action_id=action_id,
                                reason=f"pid {target.pid} foi reutilizado "
                                       f"(nascimento {live.starttime} ≠ {target.starttime})")
        if is_protected(live):
            return self._refuse(target, sig, kind=kind, action_id=action_id,
                                reason=f"{live.comm or 'pid ' + str(live.pid)} é alvo protegido")
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
            self.kill_fn(target.pid, sig)
        except PermissionError as err:
            return self._refuse(target, sig, kind=kind, action_id=action_id,
                                reason=f"sem permissão para sinalizar {comm}: {err}",
                                outcome="error")
        except ProcessLookupError:
            return self._record(target, sig, kind=kind, action_id=action_id,
                                outcome="gone",
                                reason="já saiu entre a checagem e o sinal", comm=comm)
        except OSError as err:
            return self._refuse(target, sig, kind=kind, action_id=action_id,
                                reason=str(err), outcome="error")
        return self._record(target, sig, kind=kind, action_id=action_id,
                            outcome="signaled" if sig == SIGTERM else "killed",
                            reason=None, comm=comm)

    def _refuse(self, target, sig, *, kind: str, action_id: str, reason: str,
                outcome: str = "refused") -> TermResult:
        result = TermResult(target.pid, getattr(target, "comm", ""), False, sig, reason)
        self._audit(kind=kind, action_id=action_id, outcome=outcome, result=result,
                    sig=sig)
        return result

    def _record(self, target, sig, *, kind: str, action_id: str, outcome: str,
               reason: str | None, comm: str) -> TermResult:
        result = TermResult(target.pid, comm, True, sig, reason)
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
