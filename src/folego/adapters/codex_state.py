"""Detect and roll back an interrupted SQLite transaction in the Codex home.

After an unclean shutdown, a rollback-mode database (for example
``.codex-global-state.sqlite``) can keep a *hot journal*. SQLite must write to
undo it, so every read-only connection fails with ``attempt to write a readonly
database`` and Codex Desktop stops during bootstrap. The repair SQLite expects
is to open the database once with write access: it rolls the journal back itself.

This module never deletes or edits a journal by hand. It only proves the state,
copies the pair to a verified, persistent recovery folder and lets SQLite roll
it back. WAL databases, other folders and files held by any process are left as
they are.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
from urllib.parse import quote

from .. import paths
from ..core.tmpfs import read_mounts_checked
from ..safely.atomicfile import fsync_dir, write_atomic
from ..safely.mounts import destination_verdict

MAGIC = bytes.fromhex('d9d505f920a163d7')
MAX_DATABASE = 64 * 1024**2
MAX_JOURNAL = 64 * 1024**2
MAX_ENTRIES = 512
MAX_FDS = 200_000
MARGIN = 10 * 1024**3
SUFFIXES = ('.sqlite', '.db')


class StateError(RuntimeError):
    """The state could not be proven; the files are preserved."""


def codex_home(env=None) -> Path:
    env = os.environ if env is None else env
    value = env.get('CODEX_HOME')
    return Path(value) if value else Path(env.get('HOME') or Path.home()) / '.codex'


def recovery_root() -> Path:
    return paths.data_dir() / 'recovery' / 'codex-sqlite'


def _owned_regular(path: Path, limit: int) -> os.stat_result:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise StateError(f'{path.name}: não é arquivo regular do usuário; preservado')
    if info.st_nlink != 1 or info.st_size > limit:
        raise StateError(f'{path.name}: links ou tamanho fora do orçamento; preservado')
    return info


def _identity(info: os.stat_result) -> dict:
    return dict(dev=info.st_dev, ino=info.st_ino, size=info.st_size, mtime_ns=info.st_mtime_ns)


def _sha256(path: Path, expected: os.stat_result) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if _identity(os.fstat(stream.fileno())) != _identity(expected):
            raise StateError(f'{path.name}: mudou durante a leitura; preservado')
        digest = hashlib.sha256()
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _hot_header(path: Path) -> bool:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        return stream.read(len(MAGIC)) == MAGIC


def _directories(home: Path):
    for directory in (home, home / 'sqlite'):
        try:
            info = directory.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise StateError(f'{directory}: diretório sem propriedade comprovada')
        yield directory


def find_hot_journals(home: Path | None = None) -> list[dict]:
    """Cheap scan: names and headers only. Nothing is opened as a database."""
    home = codex_home() if home is None else Path(home)
    found = []
    for directory in _directories(home):
        with os.scandir(directory) as entries:
            names = [e.name for _, e in zip(range(MAX_ENTRIES + 1), entries)]
        if len(names) > MAX_ENTRIES:
            raise StateError(f'{directory}: inventário acima do orçamento')
        for name in sorted(names):
            if not name.endswith('-journal') or not name.removesuffix('-journal').endswith(SUFFIXES):
                continue
            journal = directory / name
            database = directory / name.removesuffix('-journal')
            try:
                jinfo = _owned_regular(journal, MAX_JOURNAL)
                if jinfo.st_size < 28 or not _hot_header(journal):
                    continue
                dinfo = _owned_regular(database, MAX_DATABASE)
            except FileNotFoundError:
                continue
            if dinfo.st_size == 0:
                continue
            if any((directory / (database.name + s)).exists() for s in ('-wal', '-shm')):
                raise StateError(f'{database.name}: journal e WAL ao mesmo tempo; revisão manual')
            found.append(dict(database=str(database), journal=str(journal),
                              database_stat=_identity(dinfo), journal_stat=_identity(jinfo)))
    return found


def _locked(targets, root: Path) -> bool:
    """Any POSIX/OFD lock on a target inode, from the world-readable lock table."""
    inodes = set()
    for target in targets:
        info = os.stat(target)
        inodes.add((os.major(info.st_dev), os.minor(info.st_dev), info.st_ino))
    try:
        table = (root / 'locks').read_text()
    except OSError as exc:
        raise StateError('tabela de locks do kernel indisponível; preservado') from exc
    for line in table.splitlines():
        for field in line.split():
            parts = field.split(':')
            if len(parts) == 3:
                try:
                    if (int(parts[0], 16), int(parts[1], 16), int(parts[2])) in inodes:
                        return True
                except ValueError:
                    continue
    return False


def openers(targets, *, proc_root: str | None = None) -> list[int]:
    """PIDs of this user's processes holding any target.

    Some processes of the same user hide their descriptors (non-dumpable, such
    as the systemd user manager). For them, any kernel lock on a target counts
    as use; SQLite also checks its own locks before a rollback.
    """
    root = Path(proc_root or paths.proc_root())
    wanted = {str(Path(t)) for t in targets}
    held, hidden, budget = [], [], MAX_FDS
    for entry in os.scandir(root):
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            if entry.stat(follow_symlinks=False).st_uid != os.getuid():
                continue
            fds = os.listdir(Path(entry.path) / 'fd')
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            hidden.append(int(entry.name))
            continue
        budget -= len(fds)
        if budget < 0:
            raise StateError('inventário de descritores acima do orçamento')
        for fd in fds:
            try:
                if os.readlink(Path(entry.path) / 'fd' / fd) in wanted:
                    held.append(int(entry.name))
                    break
            except (FileNotFoundError, ProcessLookupError):
                continue
            except PermissionError:
                hidden.append(int(entry.name))
                break
    if hidden and not held and _locked(targets, root):
        raise StateError(f'Lock ativo no banco e processos {hidden[:8]} não inspecionáveis; reparo adiado')
    return held


def revalidate(target: dict) -> None:
    """At the act: same files, still hot, nobody holding them."""
    database, journal = Path(target['database']), Path(target['journal'])
    if _identity(_owned_regular(database, MAX_DATABASE)) != target['database_stat']:
        raise StateError('Banco mudou desde a detecção; reparo bloqueado')
    if _identity(_owned_regular(journal, MAX_JOURNAL)) != target['journal_stat'] or not _hot_header(journal):
        raise StateError('Journal mudou desde a detecção; reparo bloqueado')
    holders = openers((database, journal))
    if holders:
        raise StateError(f'Banco em uso pelos processos {holders}; reparo adiado')


def preserve(target: dict, operation_id: str) -> dict:
    """Verified copy of the pair before any effect. Returns the manifest."""
    database, journal = Path(target['database']), Path(target['journal'])
    root = recovery_root()
    mounts, problem = read_mounts_checked()
    if problem:
        raise StateError(f'montes não confirmados: {problem}')
    probe = root
    while not probe.exists():
        probe = probe.parent
    verdict = destination_verdict(probe.resolve(), mounts=mounts)
    if not verdict.ok:
        raise StateError(verdict.reason)
    need = target['database_stat']['size'] + target['journal_stat']['size']
    fs = os.statvfs(probe)
    if fs.f_bavail * fs.f_frsize < need + MARGIN:
        raise StateError('Espaço insuficiente para a cópia de recuperação com a margem de 10 GiB')
    folder = root / operation_id
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    files = {}
    for source, key in ((database, 'database_stat'), (journal, 'journal_stat')):
        info = _owned_regular(source, MAX_DATABASE)
        if _identity(info) != target[key]:
            raise StateError(f'{source.name}: mudou antes da cópia; reparo bloqueado')
        expected = _sha256(source, info)
        copy = folder / source.name
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            write_atomic(copy, stream.read(), mode=0o600)
        if _sha256(copy, copy.lstat()) != expected:
            raise StateError(f'{source.name}: cópia de recuperação divergente; reparo bloqueado')
        files[source.name] = dict(source=str(source), sha256=expected, size=info.st_size)
    manifest = dict(schema=1, operation_id=operation_id, reason='hot journal SQLite após desligamento não limpo',
                    files=files, restore='Com o Codex fechado, copie os dois arquivos de volta para a origem.')
    write_atomic(folder / 'manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2).encode(), mode=0o600)
    fsync_dir(folder)
    return dict(folder=str(folder), files=files)


def _uri(path: Path, mode: str) -> str:
    return f'file:{quote(str(path))}?mode={mode}'


def rollback(target: dict) -> dict:
    """Let SQLite roll the hot journal back, then prove a read-only open works."""
    database, journal = Path(target['database']), Path(target['journal'])
    try:
        db = sqlite3.connect(_uri(database, 'rw'), uri=True, timeout=1, isolation_level=None)
        try:
            version = db.execute('pragma user_version').fetchone()[0]
            check = db.execute('pragma quick_check').fetchone()[0]
        finally:
            db.close()
    except sqlite3.Error as exc:
        raise StateError(f'SQLite recusou a reversão: {exc}') from exc
    if check != 'ok':
        raise StateError(f'quick_check após a reversão: {check}')
    if journal.exists() and _hot_header(journal):
        raise StateError('Journal continua pendente após a abertura com escrita')
    try:
        db = sqlite3.connect(_uri(database, 'ro'), uri=True, timeout=1)
        try:
            readonly = db.execute('pragma user_version').fetchone()[0]
        finally:
            db.close()
    except sqlite3.Error as exc:
        raise StateError(f'Abertura somente leitura ainda falha: {exc}') from exc
    if readonly != version:
        raise StateError('Versão lida em modo somente leitura divergente')
    return dict(user_version=version, quick_check=check)
