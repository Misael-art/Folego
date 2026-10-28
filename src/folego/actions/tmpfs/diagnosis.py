"""Por que um tmpfs encheu: os maiores itens, quem os segura e qual o caminho oficial.

Somente leitura. Não sinaliza nem remove nada; transforma o "protegido" do plano em
um diagnóstico acionável. Um processo cujo pai é o `systemd --user` (ou o init) foi
adotado: quem o iniciou já saiu. Isso é um indício para revisão humana, nunca uma
autorização para sinal — a decisão continua com o dono da sessão.

As dicas de dono são conhecidas e versionadas aqui: cada uma diz qual ferramenta
criou o diretório e qual comando dela encerra a sessão preservando os dados.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# (padrão do caminho do item, ferramenta dona, comando oficial de encerramento)
OWNER_HINTS = (
    (re.compile(r"/forge-sessions(/|$)"), "SGDKForge session_coordinator",
     "cd ~/Projects/SGDKForge && python3 tools/sgdk_wrapper/session_coordinator.py list; "
     "depois: session_coordinator.py stop <sessão> (sem --force: SIGTERM, copia audio.raw para out/sessions)"),
)


@dataclass(frozen=True)
class Holder:
    pid: int
    name: str
    cmdline: str
    ppid: int
    parent: str
    adopted: bool
    tree_root: str = ""

    def to_dict(self) -> dict:
        return {"pid": self.pid, "name": self.name, "cmdline": self.cmdline,
                "ppid": self.ppid, "parent": self.parent, "adopted": self.adopted,
                "tree_root": self.tree_root}


@dataclass(frozen=True)
class Consumer:
    path: str
    bytes: int
    reason: str
    holders: tuple = ()
    owner: str = ""
    official_action: str = ""
    largest_files: tuple = field(default=())

    def to_dict(self) -> dict:
        return {"path": self.path, "bytes": self.bytes, "reason": self.reason,
                "holders": [h.to_dict() for h in self.holders], "owner": self.owner,
                "official_action": self.official_action,
                "largest_files": [list(item) for item in self.largest_files]}


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


USER_MANAGER = ("/usr/lib/systemd/systemd --user", "/lib/systemd/systemd --user")


def _ppid(pid: int, proc_root: str) -> int | None:
    stat = _read(Path(proc_root) / str(pid) / "stat")
    # comm pode ter espaços e parênteses: o ppid é o 2º campo depois do último ")"
    return int(stat.rsplit(")", 1)[1].split()[1]) if stat else None


def _cmd(pid: int, proc_root: str) -> str:
    return _read(Path(proc_root) / str(pid) / "cmdline").replace("\0", " ").strip()


def describe_process(pid: int, *, proc_root: str = "/proc") -> Holder | None:
    ppid = _ppid(pid, proc_root)
    if ppid is None:
        return None
    name = _read(Path(proc_root) / str(pid) / "comm").strip()
    parent_cmd = _cmd(ppid, proc_root)
    # Sobe até o filho direto do init/gerenciador do usuário: essa é a raiz da árvore.
    # Se a raiz foi adotada (pai = gerenciador), quem iniciou a árvore já saiu.
    root, adopted, hops = pid, False, 0
    while hops < 64:
        up = _ppid(root, proc_root)
        if up is None or up <= 1:
            adopted = up == 1
            break
        if _cmd(up, proc_root).startswith(USER_MANAGER):
            adopted = True
            break
        root, hops = up, hops + 1
    return Holder(pid, name, _cmd(pid, proc_root)[:240], ppid, parent_cmd[:120], adopted,
                  _cmd(root, proc_root)[:160] if root != pid else "")


def largest_files(path: str, *, limit: int = 3, max_entries: int = 20000) -> tuple:
    """Os maiores arquivos regulares sob `path`, sem seguir links e com teto de varredura."""
    found, seen = [], 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in files:
            seen += 1
            if seen > max_entries:
                break
            full = os.path.join(root, name)
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if os.path.isfile(full) and not os.path.islink(full):
                found.append((full, st.st_size))
        if seen > max_entries:
            break
    return tuple(sorted(found, key=lambda item: item[1], reverse=True)[:limit])


def diagnose(entries, *, top: int = 5, proc_root: str = "/proc", walk=largest_files) -> tuple:
    """Os `top` maiores itens já inventariados, com holders descritos e dica de dono."""
    consumers = []
    for entry in sorted(entries, key=lambda item: item.bytes, reverse=True)[:top]:
        if not entry.bytes:
            continue
        holders = tuple(h for h in (describe_process(pid, proc_root=proc_root)
                                    for pid in entry.holder_pids) if h)
        owner = action = ""
        for pattern, tool, command in OWNER_HINTS:
            if pattern.search(entry.path):
                owner, action = tool, command
                break
        consumers.append(Consumer(entry.path, entry.bytes, entry.reason, holders, owner, action,
                                  walk(entry.path) if entry.kind == "dir" else ((entry.path, entry.bytes),)))
    return tuple(consumers)
