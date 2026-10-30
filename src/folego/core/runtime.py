"""Read-only discovery of the current user's private session runtime."""
import os
import stat
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeLocation:
    path: str
    valid: bool
    reason: str = ""


def discover_runtime(*, env=None, uid=None, stat_fn=os.lstat) -> RuntimeLocation:
    env = os.environ if env is None else env
    uid = os.getuid() if uid is None else uid
    path = env.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    if not Path(path).is_absolute() or ".." in Path(path).parts:
        return RuntimeLocation(path, False, "runtime precisa ser absoluto e canônico")
    try:
        # Reject symbolic ancestors as well as a symbolic runtime itself.
        for ancestor in reversed((Path(path), *Path(path).parents)):
            info = stat_fn(ancestor)
            if not stat.S_ISDIR(info.st_mode):
                return RuntimeLocation(path, False, "runtime/ancestral não é diretório real")
        info = stat_fn(path)
        if info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700:
            return RuntimeLocation(path, False, "runtime sem propriedade/permissões privadas do UID")
    except OSError as exc:
        return RuntimeLocation(path, False, f"runtime não verificado: {exc}")
    return RuntimeLocation(path, True)
