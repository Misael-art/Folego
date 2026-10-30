"""Índice de fd por caminho, dentro dos volumes que observamos.

Não segue nada, não abre nada: só readlink de /proc/<pid>/fd/*. Um alvo fora dos
prefixos não nos diz respeito, e um fd de outro usuário que não conseguimos ler é
pulado — a varredura tem de terminar mesmo quando metade da sessão é opaca.

Sem /proc legível o índice chega com proc_count == 0, que quer dizer "não sabemos":
refs vazio nesse caso não prova nada, e quem vai mutar trata o índice como não provado.
Desde R02 esse "não sabemos" é nomeado: `state` vale `complete` (varremos tudo o que
existia), `partial` (algum /proc/<pid>/fd não pôde ser lido) ou `unavailable` (nem a
lista de pids pôde ser lida). `errors` carrega o porquê.
"""
import errno
import os
import time
from dataclasses import dataclass
from pathlib import Path

from ... import paths
from ...core.tmpfs import WATCHED


@dataclass(frozen=True)
class HolderIndex:
    refs: dict
    proc_count: int
    fd_count: int
    state: str = "complete"
    errors: tuple = ()

    def pids_holding(self, path: str) -> frozenset:
        prefix = str(path).rstrip(os.sep) or os.sep
        found: set[int] = set()
        for target, pids in self.refs.items():
            if target == prefix or target.startswith(prefix + os.sep):
                found.update(pids)
        return frozenset(found)


def _pid_dirs(root: Path, scandir_fn) -> tuple[list, tuple]:
    try:
        with scandir_fn(root) as it:
            return sorted(int(e.name) for e in it if e.name.isdigit()), ()
    except OSError as err:
        return [], (f"{root}: {err.strerror or err}",)


def holder_index(*, proc_root: str | None = None, prefixes=WATCHED, pids=None,
                 scandir_fn=os.scandir, readlink_fn=os.readlink,
                 include_process_refs=False, deadline_s=None, max_fds=None) -> HolderIndex:
    root = Path(proc_root or paths.proc_root())
    errors: list = []
    unavailable = False
    if pids is not None:
        seen = sorted(int(p) for p in pids)
    else:
        seen, list_errors = _pid_dirs(root, scandir_fn)
        if list_errors:
            unavailable = True
            errors.extend(list_errors)
    refs: dict[str, set[int]] = {}
    fd_count = 0
    deadline = time.monotonic() + deadline_s if deadline_s is not None else None
    def remember(target, pid):
        target = target.removesuffix(" (deleted)")
        for prefix in prefixes:
            base = prefix.rstrip(os.sep) or os.sep
            if target == base or target.startswith(base + os.sep):
                refs.setdefault(target, set()).add(pid)
                break

    for pid in seen:
        if deadline is not None and time.monotonic() >= deadline:
            errors.append("prazo de inventário de referências excedido")
            break
        if include_process_refs:
            try:
                remember(readlink_fn(root / str(pid) / "cwd"), pid)
                with (root / str(pid) / "maps").open() as stream:
                    mapping = stream.read(1024**2 + 1) if deadline is not None else stream.read()
                if deadline is not None and len(mapping) > 1024**2:
                    raise OSError("mapas excedem orçamento")
                for line in mapping.splitlines():
                    fields = line.split(maxsplit=5)
                    if len(fields) == 6 and fields[5].startswith("/"):
                        remember(fields[5], pid)
            except OSError as err:
                # A disappearing PID is benign only once its directory is gone.
                if (root / str(pid)).exists():
                    errors.append(f"{root}/{pid}/cwd,maps: {err}")
        fd_dir = root / str(pid) / "fd"
        try:
            with scandir_fn(fd_dir) as it:
                names = []
                for entry in it:
                    if ((max_fds is not None and fd_count + len(names) >= max_fds)
                            or (deadline is not None and time.monotonic() >= deadline)):
                        errors.append("inventário de descritores excede orçamento")
                        break
                    names.append(entry.name)
        except OSError as err:
            # ENOENT = o processo sumiu entre a lista e a leitura: não havia fd
            # aberto para provar. Qualquer outra falha deixa o índice parcial.
            if err.errno != errno.ENOENT:
                errors.append(f"{fd_dir}: {err.strerror or err}")
            continue
        for name in names:
            if deadline is not None and time.monotonic() >= deadline:
                errors.append("prazo de descritores excedido")
                break
            try:
                target = readlink_fn(os.path.join(str(fd_dir), name))
            except OSError as err:
                if err.errno != errno.ENOENT:
                    errors.append(f"{fd_dir}/{name}: {err}")
                continue
            fd_count += 1
            remember(target, pid)
    state = "unavailable" if unavailable else ("partial" if errors else "complete")
    return HolderIndex({k: tuple(sorted(v)) for k, v in sorted(refs.items())},
                       len(seen), fd_count, state, tuple(errors))
