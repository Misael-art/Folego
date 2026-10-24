"""Fresh process protection at effect time, including managed ancestors.

Display caches never serve as the final authorization decision.
"""
from pathlib import Path

from .. import paths
from . import procfs
from .sessions import SessionRegistry, read_boot_id
from .exclusions import ExclusionList


class ProcessProtection:
    def __init__(self, *, sessions=None, exclusions=None, proc_root=None):
        self.proc_root = Path(proc_root or paths.proc_root())
        self.sessions = sessions or SessionRegistry(proc_root=self.proc_root)
        self.exclusions = exclusions or ExclusionList()

    def __call__(self, proc):
        try:
            sessions = self.sessions.snapshot(refresh=False)
            exclusions = self.exclusions.list()
            boot = read_boot_id(self.proc_root)
            if sessions and not boot:
                return "boot desconhecido; proteção de sessões não comprovada"
            by_key = {(s.pid, s.starttime): s for s in sessions
                      if not s.ended and s.boot_id == boot}
            current = proc
            seen = set()
            for _ in range(64):
                if current.pid in seen:
                    return "ancestralidade cíclica/desconhecida; preservar"
                seen.add(current.pid)
                session = by_key.get((current.pid, current.starttime))
                if session is not None and session.keep_active:
                    return f"sessão {session.session_id} marcada como manter ativo (inclui descendentes)"
                for item in exclusions:
                    if ExclusionList._match(item, current,
                            session.project if session else "", session.session_id if session else ""):
                        return f"exclusão {item.kind}:{item.value} (alvo/ancestral protegido)"
                if current.ppid <= 1:
                    return None
                parent = procfs.read_proc(self.proc_root, current.ppid)
                if parent is None:
                    return "ancestral ausente/ilegível; pertencimento não comprovado"
                if parent.starttime > current.starttime:
                    return "ancestral reutilizado; pertencimento não comprovado"
                current = parent
            return "limite de ancestralidade atingido; preservar"
        except Exception as exc:
            return f"proteção atual ilegível: {type(exc).__name__}: {exc}"
