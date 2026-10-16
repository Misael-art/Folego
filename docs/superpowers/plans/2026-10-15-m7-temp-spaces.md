# M7 — Espaços temporários (tmpfs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** monitorar `/tmp`, `/run/user/1000` e `/dev/shm`, liberar RAM de forma reversível para a SSD e registrar/gestionar o que ficou retido, sem jamais tocar em montagem, socket de sessão ou scratch de agente vivo.

**Architecture:** leitura barata em `core/tmpfs.py` (capacidade via `/proc/mounts` + `statvfs`) alimenta o `Snapshot` e o sinal da barra de título; a decisão vive em `actions/tmpfs/` (holders por `/proc/*/fd`, inventário, política de duplo filtro, plano refusal-first, liberação copy→verify→unlink com ledger e orçamento de retenção); GUI e CLI só formatam e disparam filhos matáveis.

**Tech Stack:** Python 3.14 (`requires-python = ">=3.14"`), PySide6 (venv com `--system-site-packages`), pytest (hypothesis já está no extras de dev e é usado em `tests/test_backup.py`, mas **nenhum** teste deste plano o usa — as entradas são enumeradas à mão porque o que importa aqui é o motivo exato de cada recusa), stdlib apenas (`os`, `shutil`, `stat`, `fnmatch`, `hashlib`, `json`, `dataclasses`).

**Spec:** `docs/superpowers/specs/2026-10-15-temp-spaces-monitor-design.md` — este plano argumenta a partir dela; os dois documentos viajam juntos.

## Global Constraints

- **Nenhuma mutação sem `--confirmar`**; as destrutivas pedem também `--irreversivel`. Reusar os códigos de saída de `cli.py:23-25`: `EXIT_OK=0`, `EXIT_REFUSED=1`, `EXIT_NEEDS_CONFIRM=2`.
- **Sem psutil e sem dependência nova**: `pyproject.toml` mantém `dependencies = []`.
- **Camadas** (`tests/test_layers.py`): `core/`, `safely/`, `actions/`, `process/`, `store/`, `paths.py`, `cli.py` não importam PySide6; nada em `ui/` contém `open("/proc`, `procfs.`, `sysfs.` ou `/mnt/`; importar `deck_wellness.cli` não pode carregar Qt.
- **Direção de dependência**: `actions/` consome `core/`; `core/` nunca importa `actions/`. Por isso a leitura de capacidade está em `core/tmpfs.py` (o collector precisa dela).
- **Copy pt-BR** em toda string vista pelo usuário, decimal com vírgula (`planner.fmt_bytes` devolve `1,5 GB`; `title_signal.fmt1` idem).
- **Recusa vai para stderr**; stdout com `--json` continua sendo **uma** linha parseável (o `TuneJobs._payload` lê a última linha de stdout, `ui/tune_jobs.py:154`).
- **Seam de `/proc`**: todo leitor recebe `proc_root` com default `paths.proc_root()`; usar as fixtures `fake_proc` e `fake_home` (`tests/conftest.py:34-54`).
- **Contrato do filho**: `python -m deck_wellness …`, nunca `-m deck_wellness.cli`; `TuneJobs._environment()` pinna `PYTHONPATH` para `…/src`.
- **Proibido nos testes**: escrever em `/tmp`, `/run/user/1000` ou `/dev/shm` reais; tocar `~/.config/microsoft-edge` (o tripwire de sessão já existe em `conftest.py:25`); nada sob `/mnt` (EIO conhecida do cartão).
- **O collector não estatiza device mount**: `statvfs` de tmpfs é syscall local; nenhum `stat`/`open` em `/mnt*` ou `/run/media*` (regra dura do docstring de `core/collector.py:1-6`).
- **Git**: sem remote configurado — `git commit` local, **nunca** `git push`.
- **TDD**: cada teste é escrito e **visto falhar** antes da implementação. Nenhum código de produção sem teste vermelho antes.
- **Rodar testes** sempre com `.venv/bin/python -m pytest` (o `addopts="-q"` do pyproject vale; passar `-v` quando o passo pedir).

**Evidência de host que o plano assume** (medida nesta sessão, 2026-10-15): `/tmp` 7,24 GiB com 1,79 usado (24,7 %) e 149 filhos no nível-1 no começo da sessão de design — 317 no fim, porque a própria sessão escreve scratch ali; `/run/user/1000` 1,45 GiB (`size=1517624k,mode=700`), 34 filhos; `/dev/shm` 7,24 GiB, 0,12 usado, 0 filhos; `/run/user/1000/doc` é montagem `fuse.portal` com `dr-x------` e mtime epoch; varredura completa de `/proc/*/fd` custa 0,079 s (492 procs, 9.862 fds).

Nenhum desses números é premissa de teste: as asserções da suíte usam volumes e
itens injetados, e o Task 14 re-mede todos eles no host e reconcilia contra `df`,
`/proc/self/mountinfo` e `sha256sum`. Uma contagem que mudou entre as duas medições
não é uma falha — é o motivo de o script imprimir a sua em vez de citar esta.

## File Structure

| arquivo | papel | ação |
|---|---|---|
| `src/deck_wellness/core/tmpfs.py` | leitura de capacidade da watch-list | criar |
| `src/deck_wellness/actions/tmpfs/__init__.py` | pacote | criar |
| `src/deck_wellness/actions/tmpfs/holders.py` | índice de fd por caminho | criar |
| `src/deck_wellness/actions/tmpfs/inventory.py` | classificação de nível-1 e de um item | criar |
| `src/deck_wellness/actions/tmpfs/policy.py` | duplo filtro + recusas R1–R8 | criar |
| `src/deck_wellness/actions/tmpfs/plan.py` | plano refusal-first + digest | criar |
| `src/deck_wellness/actions/tmpfs/trend.py` | ETA até lotar | criar |
| `src/deck_wellness/actions/tmpfs/ledger.py` | registro + orçamento de retenção | criar |
| `src/deck_wellness/actions/tmpfs/release.py` | release / restore / expire | criar |
| `src/deck_wellness/paths.py:34-39` | `tmp_quarantine_dir()`, `tmp_ledger_path()` | modificar |
| `src/deck_wellness/core/snapshot.py:62-74` | campo `tmpfs` no `Snapshot` | modificar |
| `src/deck_wellness/core/collector.py:24-61` | coletar volumes no snapshot | modificar |
| `src/deck_wellness/ui/title_signal.py:15-59` | 🟡/🔴 por ocupação de tmpfs | modificar |
| `src/deck_wellness/cli.py:14-21,38-105,228-235,459-486` | família `tmpfs` | modificar |
| `src/deck_wellness/ui/tmpfs_tab.py` | aba "temporários" | criar |
| `src/deck_wellness/ui/main_window.py:11-25,43-58,129-140` | quinta aba + shutdown do filho | modificar |
| `src/deck_wellness/ui/tune_jobs.py:21` | `MUTATING` passa a incluir os atos do tmpfs | modificar |
| `tools/verify_tmpfs.py` | evidência no host | criar |

Testes novos: `tests/test_core_tmpfs.py`, `test_tmpfs_holders.py`, `test_tmpfs_inventory.py`, `test_tmpfs_policy.py`, `test_tmpfs_plan.py`, `test_tmpfs_trend.py`, `test_tmpfs_ledger.py`, `test_tmpfs_release.py`, `test_cli_tmpfs.py`, `test_ui_tmpfs_tab.py`, `test_tools_verify_tmpfs.py`. Estendem-se `test_paths.py`, `test_collector.py`, `test_title_signal.py`, `test_ui_tray.py`, `test_ui_main_window_tabs.py`, `test_ui_tune_jobs.py`, `test_layers.py`.

**Lotes verticais** (um commit por tarefa, nada é empurrado): leitura (1–2) → decisão (3–6) → sinal (7) → gestão (8) → mutação (9–10) → CLI (11–12) → GUI (13) → evidência no host (14).

---

### Task 1: Capacidade dos volumes em watch-list

**Files:**
- Create: `src/deck_wellness/core/tmpfs.py`
- Create: `src/deck_wellness/actions/tmpfs/__init__.py`
- Test: `tests/test_core_tmpfs.py`

**Interfaces:**
- Consumes: `deck_wellness.paths.proc_root()`
- Produces: `WATCHED: tuple[str, ...] = ("/tmp", "/run/user/1000", "/dev/shm")`;
  `TmpfsVolume(path: str, fs_type: str, total_bytes: int, used_bytes: int, avail_bytes: int)` com
  propriedade `used_frac -> float` e `to_dict() -> dict` (chave `used_pct` já arredondada);
  `read_mounts(proc_root: str | None = None) -> tuple[tuple[str, str], ...]`;
  `watched_volumes(*, proc_root: str | None = None, statvfs_fn=os.statvfs, watched=WATCHED) -> tuple[TmpfsVolume, ...]`

- [ ] **Step 1: Escrever o teste que falha**

```python
"""Watch-list tmpfs: os três volumes que viram ENOSPC na RAM deste Deck.

O host monta tmpfs em muito mais lugares do que os que importam (/run,
/run/credentials/*, …), então isto é lista nominal, não "todo tmpfs".
"""
from collections import namedtuple

import pytest

from deck_wellness.core import tmpfs

GIB = 1024 ** 3
Statvfs = namedtuple("Statvfs", "f_frsize f_bsize f_blocks f_bfree f_bavail")

MOUNTS = """proc /proc proc rw,nosuid 0 0
tmpfs /tmp tmpfs rw,noatime,inode64 0 0
tmpfs /run/user/1000 tmpfs rw,nosuid,nodev,size=1517624k,mode=700 0 0
tmpfs /dev/shm tmpfs rw,nosuid,nodev,usrquota 0 0
tmpfs /run tmpfs rw,nosuid,nodev,size=761916k 0 0
tmpfs /run/credentials/systemd-networkd.service tmpfs ro,nosuid,nodev,noexec 0 0
/dev/nvme0n1p2 / ext4 rw,relatime 0 0
"""


def vfs(total_gib: float, used_gib: float) -> Statvfs:
    frsize = 4096
    blocks = int(total_gib * GIB) // frsize
    free = int((total_gib - used_gib) * GIB) // frsize
    return Statvfs(f_frsize=frsize, f_bsize=frsize, f_blocks=blocks,
                   f_bfree=free, f_bavail=free)


@pytest.fixture
def fake_mounts(fake_proc):
    (fake_proc / "mounts").write_text(MOUNTS)
    return fake_proc


def by_path(**stats):
    def statvfs_fn(path):
        return stats[str(path)]
    return statvfs_fn


def test_only_the_watch_list_tmpfs_are_reported(fake_mounts):
    got = tmpfs.watched_volumes(
        proc_root=str(fake_mounts),
        statvfs_fn=by_path(**{"/tmp": vfs(8, 2), "/run/user/1000": vfs(2, 0),
                              "/dev/shm": vfs(8, 1)}))
    assert [v.path for v in got] == ["/tmp", "/run/user/1000", "/dev/shm"]


def test_used_is_total_minus_free_and_avail_is_what_we_can_write(fake_mounts):
    got = tmpfs.watched_volumes(
        proc_root=str(fake_mounts),
        statvfs_fn=by_path(**{"/tmp": vfs(8, 2), "/run/user/1000": vfs(2, 0),
                              "/dev/shm": vfs(8, 1)}))
    assert (got[0].total_bytes, got[0].used_bytes, got[0].avail_bytes) == (
        8 * GIB, 2 * GIB, 6 * GIB)
    assert got[0].used_frac == pytest.approx(0.25)


def test_a_watched_path_that_is_not_tmpfs_is_not_measured(fake_proc):
    (fake_proc / "mounts").write_text("/dev/nvme0n1p2 /tmp ext4 rw 0 0\n")

    def never(path):
        raise AssertionError(f"statvfs chamado em {path}: o volume não é tmpfs")

    assert tmpfs.watched_volumes(proc_root=str(fake_proc), statvfs_fn=never) == ()


def test_a_volume_that_cannot_be_statvfs_is_dropped_not_invented(fake_mounts):
    def statvfs_fn(path):
        if str(path) == "/dev/shm":
            raise OSError("não montado")
        return vfs(8, 2)

    got = tmpfs.watched_volumes(proc_root=str(fake_mounts), statvfs_fn=statvfs_fn)
    assert [v.path for v in got] == ["/tmp", "/run/user/1000"]


def test_zero_sized_volume_does_not_divide_by_zero(fake_proc):
    (fake_proc / "mounts").write_text("tmpfs /tmp tmpfs rw 0 0\n")
    got = tmpfs.watched_volumes(proc_root=str(fake_proc), statvfs_fn=lambda p: vfs(0, 0))
    assert got[0].used_frac == 0.0


def test_to_dict_carries_the_rounded_used_pct(fake_mounts):
    """/tmp a 14,2857 % vira 14,3 %: é isto que a aba e o `--json` mostram."""
    got = tmpfs.watched_volumes(proc_root=str(fake_mounts),
                                statvfs_fn=by_path(**{"/tmp": vfs(7, 1),
                                                      "/run/user/1000": vfs(2, 1),
                                                      "/dev/shm": vfs(8, 0)}))
    assert got[0].to_dict()["used_pct"] == 14.3
    assert got[1].to_dict()["used_pct"] == 50.0


def test_missing_mounts_file_is_silence_not_an_exception(fake_proc):
    assert tmpfs.read_mounts(str(fake_proc)) == ()
    assert tmpfs.watched_volumes(proc_root=str(fake_proc),
                                 statvfs_fn=lambda p: vfs(8, 2)) == ()


def test_mount_points_unescape_the_kernel_octal_space(fake_proc):
    (fake_proc / "mounts").write_text("tmpfs /tmp/com\\040espaco tmpfs rw 0 0\n")
    assert ("/tmp/com espaco", "tmpfs") in tmpfs.read_mounts(str(fake_proc))


def test_the_document_portal_is_not_a_watched_volume(fake_proc):
    """/run/user/1000/doc é fuse.portal: fica de fora, e um statvfs nele nunca é chamado."""
    (fake_proc / "mounts").write_text("tmpfs /run/user/1000 tmpfs rw 0 0\n"
                                       "fuse.portal /run/user/1000/doc fuse.portal rw 0 0\n")

    def statvfs_fn(path):
        assert str(path) == "/run/user/1000"
        return vfs(2, 0)

    assert [v.path for v in tmpfs.watched_volumes(proc_root=str(fake_proc),
                                                  statvfs_fn=statvfs_fn)] == ["/run/user/1000"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_core_tmpfs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'deck_wellness.core.tmpfs'` (erro de collection nos 9 testes).

- [ ] **Step 3: Implementar o mínimo**

```python
"""Capacidade dos tmpfs que viram RAM: /tmp, /run/user/1000 e /dev/shm.

Ler isto não custa nada: /proc/mounts e um statvfs por volume, sem walk de árvore
e sem varrer fd — por isso cabe no poller de 2 s. É watch-list nominal: o host
monta tmpfs em /run, /run/credentials/* e outros lugares que nenhum agente
escreve. Nada aqui estatiza algo sob /mnt ou /run/media.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from .. import paths

WATCHED = ("/tmp", "/run/user/1000", "/dev/shm")
_ESCAPES = {"\\040": " ", "\\011": "\t", "\\012": "\n", "\\134": "\\"}


@dataclass(frozen=True)
class TmpfsVolume:
    path: str
    fs_type: str
    total_bytes: int
    used_bytes: int
    avail_bytes: int

    @property
    def used_frac(self) -> float:
        return self.used_bytes / self.total_bytes if self.total_bytes else 0.0

    def to_dict(self) -> dict:
        return {"path": self.path, "fs_type": self.fs_type,
                "total_bytes": self.total_bytes, "used_bytes": self.used_bytes,
                "avail_bytes": self.avail_bytes,
                "used_pct": round(self.used_frac * 100, 1)}


def _unescape(field: str) -> str:
    for needle, char in _ESCAPES.items():
        field = field.replace(needle, char)
    return field


def read_mounts(proc_root: str | None = None) -> tuple:
    """(mount_point, fs_type) por linha; () se o /proc não responder."""
    try:
        raw = (Path(proc_root or paths.proc_root()) / "mounts").read_text()
    except OSError:
        return ()
    out = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            out.append((_unescape(parts[1]), parts[2]))
    return tuple(out)


def watched_volumes(*, proc_root: str | None = None, statvfs_fn=os.statvfs,
                    watched=WATCHED) -> tuple:
    result = []
    for mount, fs_type in read_mounts(proc_root):
        if fs_type != "tmpfs" or mount not in watched:
            continue
        try:
            vfs = statvfs_fn(mount)
        except OSError:
            continue
        frsize = vfs.f_frsize or vfs.f_bsize
        total = vfs.f_blocks * frsize
        used = (vfs.f_blocks - vfs.f_bfree) * frsize
        result.append(TmpfsVolume(mount, fs_type, total, used, vfs.f_bavail * frsize))
    return tuple(result)
```

E `src/deck_wellness/actions/tmpfs/__init__.py`:

```python
"""M7: gestão dos tmpfs onde o trabalho de agente mora."""
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_core_tmpfs.py -v` → PASS (9).
Run: `.venv/bin/python -m pytest -q` → suite inteira verde (372 + 9 = 381).

- [ ] **Step 5: Commit**

```bash
git add src/deck_wellness/core/tmpfs.py src/deck_wellness/actions/tmpfs/__init__.py tests/test_core_tmpfs.py
git commit -m "M7 T1: capacidade dos tmpfs em watch-list — /tmp, /run/user/1000 e /dev/shm"
```

---

### Task 2: Quem está com o arquivo aberto

**Files:**
- Create: `src/deck_wellness/actions/tmpfs/holders.py`
- Test: `tests/test_tmpfs_holders.py`

**Interfaces:**
- Consumes: `core.tmpfs.WATCHED`, `paths.proc_root()`
- Produces: `HolderIndex(refs: dict[str, tuple[int, ...]], proc_count: int, fd_count: int)` com
  `pids_holding(path: str) -> frozenset[int]`;
  `holder_index(*, proc_root=None, prefixes=WATCHED, pids=None, scandir_fn=os.scandir, readlink_fn=os.readlink) -> HolderIndex`

- [ ] **Step 1: Escrever o teste que falha**

```python
"""Uma passada em /proc/<pid>/fd: barato o bastante para perguntar antes de cada liberação.

Medido neste Deck: 492 processos, 9.862 fd, 192 refs sob /tmp ∪ /run/user/1000 em
0,079 s. É a diferença entre liberar scratch de agente morto e cortar um vivo.
"""
import os

from deck_wellness.actions.tmpfs import holders


def make_proc(root, pid: int, links: dict):
    fd = root / str(pid) / "fd"
    fd.mkdir(parents=True)
    for name, target in links.items():
        os.symlink(target, fd / name)


def test_only_targets_under_the_prefixes_are_recorded(fake_proc):
    make_proc(fake_proc, 400, {"3": "/tmp/agente/sessao", "4": "/home/u/nota.md",
                               "5": "/run/user/1000/bus", "6": "socket:[917]"})
    idx = holders.holder_index(proc_root=str(fake_proc))
    assert idx.refs == {"/run/user/1000/bus": (400,), "/tmp/agente/sessao": (400,)}
    assert (idx.proc_count, idx.fd_count) == (1, 4)


def test_pids_holding_covers_a_directory_and_what_is_inside_it(fake_proc):
    make_proc(fake_proc, 700, {"0": "/tmp/qoder-cli-1000/abc/sessao-1/x"})
    idx = holders.holder_index(proc_root=str(fake_proc))
    assert idx.pids_holding("/tmp/qoder-cli-1000/abc") == frozenset({700})
    assert idx.pids_holding("/tmp/qoder-cli-1000/abc/sessao-1") == frozenset({700})
    assert idx.pids_holding("/tmp/qoder-cli-1000/outra") == frozenset()


def test_several_pids_on_the_same_file_are_all_named(fake_proc):
    make_proc(fake_proc, 11, {"0": "/tmp/node-compile-cache/a"})
    make_proc(fake_proc, 12, {"1": "/tmp/node-compile-cache/a"})
    idx = holders.holder_index(proc_root=str(fake_proc))
    assert idx.refs["/tmp/node-compile-cache/a"] == (11, 12)
    assert idx.pids_holding("/tmp/node-compile-cache") == frozenset({11, 12})


def test_a_process_we_cannot_read_is_skipped_without_raising(fake_proc):
    make_proc(fake_proc, 800, {"0": "/tmp/x"})
    real = os.scandir

    def deny(path):
        if str(path).endswith("/800/fd"):
            raise PermissionError(13, "denied")
        return real(path)

    idx = holders.holder_index(proc_root=str(fake_proc), scandir_fn=deny)
    assert idx.refs == {}
    assert idx.proc_count == 1        # o processo foi visto, o diretório fd não
    assert idx.fd_count == 0


def test_one_unreadable_fd_does_not_void_the_scan(fake_proc):
    make_proc(fake_proc, 900, {"0": "/tmp/legivel"})
    os.symlink("/tmp/sumiu", fake_proc / "900" / "fd" / "1")
    real = os.readlink

    def readlink(path):
        if str(path).endswith("/1"):
            raise OSError(2, "enoent")
        return real(path)

    idx = holders.holder_index(proc_root=str(fake_proc), readlink_fn=readlink)
    assert idx.refs == {"/tmp/legivel": (900,)}
    assert idx.fd_count == 1


def test_prefixes_are_configurable(fake_proc):
    make_proc(fake_proc, 5, {"0": "/var/tmp/algo"})
    idx = holders.holder_index(proc_root=str(fake_proc), prefixes=("/var/tmp",))
    assert idx.refs == {"/var/tmp/algo": (5,)}


def test_the_explicit_pid_list_decides_what_is_looked_at(fake_proc):
    make_proc(fake_proc, 21, {"0": "/tmp/um"})
    make_proc(fake_proc, 22, {"0": "/tmp/dois"})
    idx = holders.holder_index(proc_root=str(fake_proc), pids=[22])
    assert idx.refs == {"/tmp/dois": (22,)}
    assert idx.proc_count == 1
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_holders.py -v`
Expected: FAIL — `ModuleNotFoundError: ... 'deck_wellness.actions.tmpfs.holders'`.

- [ ] **Step 3: Implementar o mínimo**

```python
"""Índice de fd por caminho, dentro dos volumes que observamos.

Não segue nada, não abre nada: só readlink de /proc/<pid>/fd/*. Um alvo fora dos
prefixos não nos diz respeito, e um fd de outro usuário que não conseguimos ler é
pulado — a varredura tem de terminar mesmo quando metade da sessão é opaca.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from ... import paths
from ...core.tmpfs import WATCHED


@dataclass(frozen=True)
class HolderIndex:
    refs: dict
    proc_count: int
    fd_count: int

    def pids_holding(self, path: str) -> frozenset:
        prefix = str(path).rstrip(os.sep) or os.sep
        found: set[int] = set()
        for target, pids in self.refs.items():
            if target == prefix or target.startswith(prefix + os.sep):
                found.update(pids)
        return frozenset(found)


def _pid_dirs(root: Path, scandir_fn) -> list:
    try:
        with scandir_fn(root) as it:
            return sorted(int(e.name) for e in it if e.name.isdigit())
    except OSError:
        return []


def holder_index(*, proc_root: str | None = None, prefixes=WATCHED, pids=None,
                 scandir_fn=os.scandir, readlink_fn=os.readlink) -> HolderIndex:
    root = Path(proc_root or paths.proc_root())
    seen = (sorted(int(p) for p in pids) if pids is not None
            else _pid_dirs(root, scandir_fn))
    refs: dict[str, set[int]] = {}
    fd_count = 0
    for pid in seen:
        fd_dir = root / str(pid) / "fd"
        try:
            with scandir_fn(fd_dir) as it:
                names = sorted(e.name for e in it)
        except OSError:
            continue
        for name in names:
            try:
                target = readlink_fn(os.path.join(str(fd_dir), name))
            except OSError:
                continue
            fd_count += 1
            for prefix in prefixes:
                base = prefix.rstrip(os.sep) or os.sep
                if target == base or target.startswith(base + os.sep):
                    refs.setdefault(target, set()).add(pid)
                    break
    return HolderIndex({k: tuple(sorted(v)) for k, v in sorted(refs.items())},
                       len(seen), fd_count)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_holders.py -v` → PASS (7).
Run: `.venv/bin/python -m pytest -q` → verde.

- [ ] **Step 5: Commit**

```bash
git add src/deck_wellness/actions/tmpfs/holders.py tests/test_tmpfs_holders.py
git commit -m "M7 T2: índice de /proc/*/fd — provar que nada está aberto antes de liberar"
```

---

### Task 3: Inventário de um volume e de um item

**Files:**
- Create: `src/deck_wellness/actions/tmpfs/inventory.py`
- Test: `tests/test_tmpfs_inventory.py`

**Interfaces:**
- Consumes: `core.tmpfs.read_mounts`, `actions.disk.measure.measure_tree`, `holders.HolderIndex`/`holder_index`
- Produces: `TmpfsEntry(path, name, volume, kind, uid, bytes, files, age_days, is_mount_point, under_mount, holder_pids, truncated, errors)` (tudo com default a partir de `kind`),
  `kind_of(mode: int) -> str`,
  `entry_at(path, mounts, holders, *, volume, now=None, deadline_s=10.0, lstat_fn=os.lstat, measure_fn=measure_tree) -> TmpfsEntry`,
  `inventory(volume, mounts, holders, *, now=None, deadline_s=10.0, **kw) -> tuple[TmpfsEntry, ...]`,
  `scan_volume(volume, *, proc_root=None, now=None, deadline_s=10.0) -> tuple[mounts, holders, entries]`

- [ ] **Step 1: Escrever o teste que falha**

```python
"""Classificar sem adivinhar: tipo, dono, idade, monte, holder — por item.

A idade sai do arquivo mais novo *dentro* da árvore, não do mtime do diretório:
uma pasta de sessão pode ter mtime antigo e escrita de agora, e idade antiga
errada aqui é exatamente o acidente que estamos evitando.
"""
import os
import socket

import pytest

from deck_wellness.actions.tmpfs import holders, inventory
from deck_wellness.core.tmpfs import TmpfsVolume

NOW = 1_700_000_000.0
EMPTY = holders.HolderIndex({}, 0, 0)


def volume_dir(tmp_path):
    root = tmp_path / "tmp"
    root.mkdir()
    return root


def child(root, name, *, age_d=10.0, is_dir=False, content="x"):
    path = root / name
    if is_dir:
        (path / "inner").mkdir(parents=True)
        target = path / "inner"
    else:
        path.write_text(content)
        target = path
    stamp = NOW - age_d * 86_400
    os.utime(target, (stamp, stamp))
    return path


def test_age_uses_the_newest_file_inside_the_tree(tmp_path):
    root = volume_dir(tmp_path)
    session = child(root, "sessao", age_d=40.0, is_dir=True)
    fresh = session / "saida.log"
    fresh.write_text("agora")
    os.utime(fresh, (NOW - 60, NOW - 60))
    # escrever move o mtime do diretório para o relógio real de verdade; a cena do
    # docstring é mtime do diretório velho com escrita nova dentro — refaz o velho.
    # (sem isto, measure_tree devolve o mtime do diretório como mais novo e a idade
    # do pai sai 0.0: o teste não poderia passar, e a mutação não teria o que matar)
    os.utime(session, (NOW - 40 * 86_400, NOW - 40 * 86_400))

    entry = inventory.entry_at(str(fresh), (), EMPTY, volume=str(root), now=NOW)
    assert entry.age_days == pytest.approx(60 / 86_400, abs=1e-6)
    parent = inventory.entry_at(str(session), (), EMPTY, volume=str(root), now=NOW)
    assert parent.age_days == pytest.approx(60 / 86_400, abs=1e-6)


def test_kind_uid_and_size(tmp_path):
    root = volume_dir(tmp_path)
    child(root, "arquivo", content="12345")
    child(root, "dir-velho", is_dir=True)
    sock = socket.socket(socket.AF_UNIX)
    sock.bind(str(root / "sock"))
    os.mkfifo(root / "fifo")

    by_name = {e.name: e for e in inventory.inventory(str(root), (), EMPTY, now=NOW)}
    assert by_name["dir-velho"].kind == "dir"
    assert by_name["arquivo"].kind == "file" and by_name["arquivo"].bytes == 5
    assert by_name["sock"].kind == "socket"
    assert by_name["fifo"].kind == "fifo"
    for entry in by_name.values():
        assert entry.uid == os.getuid() and entry.volume == str(root)
    sock.close()
    os.unlink(str(root / "sock"))


def test_a_mount_point_is_flagged_and_never_measured(tmp_path):
    root = volume_dir(tmp_path)
    doc = child(root, "doc", is_dir=True)

    def spy(tree_root, **kw):
        raise AssertionError("measure_tree não pode entrar num ponto de montagem")

    entry = inventory.entry_at(str(doc), ((str(doc), "fuse.portal"),), EMPTY,
                                volume=str(root), now=NOW, measure_fn=spy)
    assert entry.is_mount_point is True
    assert entry.bytes == 0 and entry.files == 0


def test_a_directory_that_contains_a_mount_is_flagged(tmp_path):
    root = volume_dir(tmp_path)
    run = child(root, "run", is_dir=True)
    nested = run / "user" / "1000" / "doc"
    nested.mkdir(parents=True)

    def medido_ou_explodindo(p, **kw):
        raise AssertionError(f"medida dentro de um monte: {p}")

    entry = inventory.entry_at(str(run), ((str(nested), "fuse.portal"),), EMPTY,
                               volume=str(root), now=NOW,
                               measure_fn=medido_ou_explodindo)
    assert entry.is_mount_point is False and entry.under_mount is True


def test_holder_pids_come_from_the_index(tmp_path):
    root = volume_dir(tmp_path)
    session = child(root, "qoder-cli-1000", is_dir=True)
    idx = holders.HolderIndex({str(session / "inner"): (999,)}, 1, 1)
    entry = inventory.entry_at(str(session), (), idx, volume=str(root), now=NOW)
    assert entry.holder_pids == (999,)


def test_inventory_lists_only_the_top_level_children(tmp_path):
    root = volume_dir(tmp_path)
    outer = child(root, "outer", is_dir=True)
    (outer / "inner" / "deep").mkdir(parents=True)
    assert [e.name for e in inventory.inventory(str(root), (), EMPTY, now=NOW)] == ["outer"]


def test_an_unreadable_volume_reads_as_empty_not_as_clean(tmp_path):
    """`inventory` não tem canal de erro: volume ilegível devolve () mesmo.

    Pinar isto é o que obriga T11/T13 a dizer "pode estar vazio por permissão" em
    vez de apresentar um volume EACCES como limpo.
    """
    root = volume_dir(tmp_path)
    fechado = child(root, "fechado", is_dir=True)
    (fechado / "dentro").write_text("x")
    fechado.chmod(0o000)
    try:
        assert inventory.inventory(str(fechado), (), EMPTY, now=NOW) == ()
    finally:
        fechado.chmod(0o755)


def test_symlinks_are_reported_as_symlinks(tmp_path):
    root = volume_dir(tmp_path)
    victim = child(root, "precioso")
    os.symlink(str(victim), root / "link-velho")
    by_name = {e.name: e for e in inventory.inventory(str(root), (), EMPTY, now=NOW)}
    assert by_name["link-velho"].kind == "symlink"
    assert by_name["precioso"].kind == "file"


def test_a_child_that_vanished_is_not_invented_by_the_walk(tmp_path):
    """O walk só enxerga o que existe; o `lstat_fn` injetado vale para `entry_at`."""
    root = volume_dir(tmp_path)
    child(root, "presente")
    real = os.lstat

    def lstat(path):
        if str(path).endswith("morto"):
            raise OSError(2, "no such file")
        return real(path)

    entries = inventory.inventory(str(root), (), EMPTY, now=NOW, lstat_fn=lstat)
    assert [e for e in entries if e.name == "morto"] == []
    assert [e.name for e in entries] == ["presente"]


def test_entry_at_records_a_vanished_item_instead_of_raising(tmp_path):
    root = volume_dir(tmp_path)

    def lstat(path):
        raise OSError(2, "no such file")

    entry = inventory.entry_at(str(root / "morto"), (), EMPTY, volume=str(root),
                               now=NOW, lstat_fn=lstat)
    assert entry.kind == "missing"
    assert "no such file" in entry.errors[0]


def test_truncated_measurement_is_carried_out(tmp_path):
    root = volume_dir(tmp_path)
    big = child(root, "grande", is_dir=True)

    def truncated(tree_root, **kw):
        return type("S", (), {"bytes": 1, "files": 1, "newest_ns": 0,
                              "errors": ("lento",), "truncated": True})()

    entry = inventory.entry_at(str(big), (), EMPTY, volume=str(root), now=NOW,
                               measure_fn=truncated)
    assert entry.truncated is True and entry.errors == ("lento",)


def test_scan_volume_brings_mounts_holders_and_entries_together(fake_proc, tmp_path):
    from deck_wellness.core.tmpfs import TmpfsVolume as V

    (fake_proc / "mounts").write_text(f"tmpfs {tmp_path}/tmp tmpfs rw 0 0\n")
    root = volume_dir(tmp_path)
    child(root, "tmpdeadbeef", is_dir=True)
    mounts, idx, entries = inventory.scan_volume(V(str(root), "tmpfs", 100, 1, 99),
                                                 proc_root=str(fake_proc))
    assert [m[0] for m in mounts] == [str(root)]
    assert [e.name for e in entries] == ["tmpdeadbeef"]
    assert idx.proc_count >= 0
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_inventory.py -v`
Expected: FAIL — módulo `inventory` inexistente.

- [ ] **Step 3: Implementar o mínimo**

```python
"""Um olhar por cima do volume: o que é cada filho de nível-1.

Nada aqui decide — isto só chega honesto: tipo real (lstat; symlink é symlink),
dono, tamanho medido sem cruzar dispositivo, idade pelo arquivo mais novo da
árvore, monte lido do /proc/mounts (nunca por stat, que atravessaria um FUSE), e
os pids que têm algo aberto aqui.
"""
import os
import stat as statmod
import time
from dataclasses import dataclass
from pathlib import Path

from ...core.tmpfs import read_mounts
from ..disk.measure import measure_tree
from .holders import HolderIndex, holder_index

DAY_S = 86_400
KINDS = ((statmod.S_ISDIR, "dir"), (statmod.S_ISREG, "file"),
         (statmod.S_ISLNK, "symlink"), (statmod.S_ISSOCK, "socket"),
         (statmod.S_ISFIFO, "fifo"))


@dataclass(frozen=True)
class TmpfsEntry:
    path: str
    name: str
    volume: str
    kind: str = "other"
    uid: int = -1
    bytes: int = 0
    files: int = 0
    age_days: float = 0.0
    is_mount_point: bool = False
    under_mount: bool = False
    holder_pids: tuple = ()
    truncated: bool = False
    errors: tuple = ()


def kind_of(mode: int) -> str:
    for test, name in KINDS:
        if test(mode):
            return name
    return "other"


def _mount_state(path_str: str, mounts) -> tuple:
    points = {m for m, _ in mounts}
    return (path_str in points,
            any(m != path_str and m.startswith(path_str + os.sep) for m in points))


def entry_at(path, mounts, holders, *, volume: str, now=None, deadline_s: float = 10.0,
             lstat_fn=os.lstat, measure_fn=measure_tree) -> TmpfsEntry:
    now = time.time() if now is None else now
    p = Path(path)
    path_str = str(p)
    try:
        st = lstat_fn(path_str)
    except OSError as err:
        return TmpfsEntry(path_str, p.name, volume, "missing", -1, 0, 0, 0.0, False,
                          False, (), False, (f"{path_str}: {err.strerror or err}",))

    kind = kind_of(st.st_mode)
    is_point, under = _mount_state(path_str, mounts)
    size, files, newest_ns = 0, 0, st.st_mtime_ns
    truncated, errors = False, ()

    if kind == "dir" and not is_point and not under:
        stat = measure_fn(p, deadline_s=deadline_s)
        size, files = stat.bytes, stat.files
        newest_ns = stat.newest_ns or st.st_mtime_ns
        truncated, errors = stat.truncated, tuple(stat.errors)
    elif kind == "file":
        size, files = st.st_size, 1

    return TmpfsEntry(path_str, p.name, volume, kind, st.st_uid, size, files,
                      max(0.0, (now - newest_ns / 10**9) / DAY_S), is_point, under,
                      tuple(sorted(holders.pids_holding(path_str))), truncated, errors)


def inventory(volume, mounts, holders, *, now=None, deadline_s: float = 10.0,
              **kw) -> tuple:
    root = getattr(volume, "path", str(volume))
    try:
        names = sorted(os.listdir(root))
    except OSError:
        # Volume ilegível ou sumido devolve () — igual a volume vazio. A direção é
        # fail-closed (sem item, nada é liberado), mas NÃO é prova de limpeza: quem
        # apresenta (T11 `status`/`plan`, T13 aba) tem de dizer que leu o volume por
        # `read_mounts`/`statvfs` e que a lista de itens pode estar vazia por permissão.
        return ()
    return tuple(entry_at(os.path.join(root, name), mounts, holders, volume=str(root),
                          now=now, deadline_s=deadline_s, **kw) for name in names)


def scan_volume(volume, *, proc_root=None, now=None,
                deadline_s: float = 10.0) -> tuple:
    """Montes + holders + inventário de um volume: o tripé que CLI e liberação usam."""
    path = getattr(volume, "path", str(volume))
    mounts = read_mounts(proc_root)
    holders = holder_index(proc_root=proc_root, prefixes=(path,))
    return (mounts, holders,
            inventory(volume, mounts, holders, now=now, deadline_s=deadline_s))
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_inventory.py -v` → PASS (12).
Run: `.venv/bin/python -m pytest -q` → verde.

**Coerção de mutação:** usar `st_mtime_ns` do diretório em vez de `newest_ns` da
árvore, chamar `measure_tree` num item que é ponto de montagem, ou engolir o `OSError`
do `lstat` sem registrar em `errors` — cada um desses mata ao menos um teste desta
tarefa. Guarde a saída de `-v` no corpo do commit; a spec (§10) pede a evidência, não
a afirmação.

- [ ] **Step 5: Commit**

```bash
git add src/deck_wellness/actions/tmpfs/inventory.py tests/test_tmpfs_inventory.py
git commit -m "$(cat <<'MSG'
M7 T3: inventário de tmpfs — tipo, dono, idade real, monte e holder por item

<corpo: RED, GREEN com total da suíte, e a saída -v das três coerções de mutação,
uma por vez, com a linha revertida conferida byte a byte>
MSG
)"
```

---

### Task 4: A política de recusa (duplo filtro)

**Files:**
- Create: `src/deck_wellness/actions/tmpfs/policy.py`
- Test: `tests/test_tmpfs_policy.py`

**Interfaces:**
- Consumes: `TmpfsEntry` (T3), `core.tmpfs.WATCHED`
- Produces: `DEFAULT_ALLOW_PATTERNS`, `MIN_AGE_DAYS = 3.0`, `MAX_ITEM_BYTES = 2 * 1024**3`,
  `Policy(allow_patterns=..., min_age_days=..., max_item_bytes=..., volumes=...)` com `to_dict()`,
  `Eligibility(ok: bool, reason: str, matched: str | None = None)`,
  `matches(path: str, patterns) -> str | None`,
  `classify(entry, policy) -> Eligibility`

A ordem das regras é a da tabela §5 da spec, com uma regra extra entre R4 e R5: item
com `truncated` ou `errors` do walk nunca é elegível (uma leitura pela metade não prova
tamanho nem idade). O texto da razão segue o formato `refused: …` em todas elas — na R7
a spec escreve `protegido: mais novo que {floor} dias` na tabela, e a implementação
devolve `refused: {idade} d, mais novo que o piso de {piso} d`; o que a tabela exige é o
motivo nomeado por item, não a literalidade, e o Task 11 busca a palavra "piso".

`kind == "missing"` (filho que sumiu entre o `listdir` e o `lstat`, `inventory.py:62`) não
ganha ramo próprio: cai na R2 e a razão nomeia o tipo — `refused: missing não é arquivo nem
árvore regular`. Um ramo dedicado a ele violaria a R2 da tabela e quebraria o próprio teste
que enumera os tipos (`kind in verdict.reason` para `missing`).

A R7 escreve os dois números com vírgula (`refused: 0,5 d, mais novo que o piso de 3 d`), como
o resto do projeto (`actions/disk/planner.py:244`, `ui/title_signal.py:59`): essa string é a
copy que o usuário lê no `plan`/`status` do Task 11, e ninguém formata por ela depois — o
apresentador não reconta um número que já veio embutido no motivo.

- [ ] **Step 1: Escrever o teste que falha**

```python
"""Recusar é o default; liberar precisa de dois filtros e de um motivo nomeado.

Filtro 1 — o item é algo que entendemos (regular, nosso, não-monte, sem holder,
lido por inteiro). Filtro 2 — o nome casa num padrão de sujeira de agente que
reconhecemos. A primeira regra que pega é a razão devolvida, na ordem do §5 da
spec.
"""
import os

from deck_wellness.actions.tmpfs import policy
from deck_wellness.actions.tmpfs.inventory import TmpfsEntry

GIB = 1024 ** 3


def entry(**kw):
    base = dict(path="/tmp/qoder-cli-1000", name="qoder-cli-1000", volume="/tmp",
                kind="dir", uid=os.getuid(), bytes=1024, files=3, age_days=10.0,
                is_mount_point=False, under_mount=False, holder_pids=(),
                truncated=False, errors=())
    base.update(kw)
    return TmpfsEntry(**base)


def test_a_plain_agent_scratch_directory_is_eligible():
    verdict = policy.classify(entry(), policy.Policy())
    assert verdict.ok is True
    assert verdict.matched == "/tmp/qoder-cli-1000"
    assert "casado com" in verdict.reason


def test_a_session_nested_inside_a_container_is_not_an_inventoried_item():
    """O padrão casa com o que o inventory mede; o caminho fundo não é unidade de plano."""
    verdict = policy.classify(entry(path="/tmp/qoder-cli-1000/abc/sessao",
                                    name="sessao"), policy.Policy())
    assert verdict.ok is False and "allow-list" in verdict.reason


def test_a_mount_point_is_refused_before_anything_else():
    verdict = policy.classify(entry(is_mount_point=True, age_days=0.0), policy.Policy())
    assert verdict.ok is False and verdict.reason.startswith("refused: ponto de montagem")


def test_a_directory_containing_a_mount_is_refused():
    assert policy.classify(entry(under_mount=True), policy.Policy()).ok is False


def test_sockets_fifos_symlinks_and_missing_are_refused_by_kind():
    for kind in ("socket", "fifo", "symlink", "other", "missing"):
        verdict = policy.classify(entry(kind=kind), policy.Policy())
        assert verdict.ok is False, kind
        assert kind in verdict.reason


def test_someone_elses_junk_is_refused():
    verdict = policy.classify(entry(uid=os.getuid() + 1), policy.Policy())
    assert verdict.ok is False and "uid" in verdict.reason


def test_a_live_holder_is_refused_and_named():
    verdict = policy.classify(entry(holder_pids=(4242, 4243)), policy.Policy())
    assert verdict.ok is False
    assert "4242" in verdict.reason and "4243" in verdict.reason


def test_a_truncated_walk_is_not_evidence_enough_to_delete():
    verdict = policy.classify(entry(truncated=True), policy.Policy())
    assert verdict.ok is False and "incompleta (truncada)" in verdict.reason


def test_a_walk_that_failed_to_read_a_child_is_not_evidence_enough_to_delete():
    """Sem `errors` na regra, um walk que não leu um filho libera o irmão legível
    contando com um `bytes` e um `age_days` que sabem por baixo."""
    verdict = policy.classify(entry(errors=("/tmp/x: Permissão negada",)),
                              policy.Policy())
    assert verdict.ok is False and "incompleta" in verdict.reason


def test_a_huge_item_is_refused_by_the_per_item_ceiling():
    verdict = policy.classify(entry(bytes=3 * GIB), policy.Policy())
    assert verdict.ok is False and "limite por item" in verdict.reason


def test_a_volume_outside_the_watch_list_is_refused():
    verdict = policy.classify(entry(volume="/run", path="/run/algo"), policy.Policy())
    assert verdict.ok is False and "watch-list" in verdict.reason


def test_younger_than_the_floor_is_protected():
    verdict = policy.classify(entry(age_days=0.5), policy.Policy())
    assert verdict.ok is False and "piso" in verdict.reason
    assert "0,5 d" in verdict.reason and ".5" not in verdict.reason


def test_the_x11_socket_directory_is_never_eligible_with_the_default_list():
    verdict = policy.classify(entry(path="/tmp/.X11-unix", name=".X11-unix"),
                              policy.Policy())
    assert verdict.ok is False and "allow-list" in verdict.reason


def test_nothing_in_run_user_is_eligible_without_an_explicit_pattern():
    """Em /run/user/1000 mora a sessão: só com padrão explícito algo ali sai elegível."""
    session = entry(volume="/run/user/1000", path="/run/user/1000/gnupg", name="gnupg")
    assert policy.classify(session, policy.Policy()).ok is False
    with_pattern = policy.Policy(allow_patterns=("/run/user/1000/gnupg",))
    assert policy.classify(session, with_pattern).ok is True


def test_holder_refusal_outranks_a_matching_pattern():
    verdict = policy.classify(entry(holder_pids=(7,), age_days=0.1), policy.Policy())
    assert "processo" in verdict.reason


def test_matches_reports_the_first_pattern_that_hits():
    assert policy.matches("/tmp/pytest-of-misael/pytest-3",
                          policy.DEFAULT_ALLOW_PATTERNS) == "/tmp/pytest-of-*"
    assert policy.matches("/tmp/de-outro-lugar", policy.DEFAULT_ALLOW_PATTERNS) is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_policy.py -v`
Expected: FAIL — módulo `policy` inexistente.

- [ ] **Step 3: Implementar o mínimo**

```python
"""O duplo filtro: o que é, e qual nome reconhecemos.

A allow-list default só cobre /tmp. /run/user/1000 é monitorado e nunca liberado
por padrão — ali vivem o socket do Wayland, o D-Bus, o PipeWire e o portal de
documentos; esvaziar aquilo derruba a sessão gráfica, não o agente. /dev/shm é
medido e permanece imutável porque o guard blacklista o prefixo /dev.

Os padrões são escritos na granularidade que o `inventory` mede — o filho direto
do volume. `/tmp/qoder-cli-1000` é a unidade, não a sessão dentro dela: a
ferramenta recria o próprio diretório-raiz, e a idade da árvore inteira (arquivo
mais novo dentro) é que decide. Um padrão `/tmp/qoder-cli-1000/*` nunca casaria
com nada que inventariamos.
"""
import fnmatch
import os
from dataclasses import dataclass

from ...core.tmpfs import WATCHED

MIN_AGE_DAYS = 3.0
MAX_ITEM_BYTES = 2 * 1024 ** 3

DEFAULT_ALLOW_PATTERNS = (
    "/tmp/qoder-cli-1000",
    "/tmp/node-compile-cache",
    "/tmp/tsx-1000",
    "/tmp/pytest-of-*",
    "/tmp/playwright_*",
    "/tmp/tmp*",
)


@dataclass(frozen=True)
class Policy:
    allow_patterns: tuple = DEFAULT_ALLOW_PATTERNS
    min_age_days: float = MIN_AGE_DAYS
    max_item_bytes: int = MAX_ITEM_BYTES
    volumes: tuple = WATCHED

    def to_dict(self) -> dict:
        return {"allow_patterns": list(self.allow_patterns),
                "min_age_days": self.min_age_days,
                "max_item_bytes": self.max_item_bytes,
                "volumes": list(self.volumes)}


@dataclass(frozen=True)
class Eligibility:
    ok: bool
    reason: str
    matched: str | None = None


def matches(path: str, patterns) -> str | None:
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return pattern
    return None


def classify(entry, policy: Policy) -> Eligibility:
    if entry.is_mount_point or entry.under_mount:
        return Eligibility(False, "refused: ponto de montagem (ou contém uma)")
    if entry.kind not in ("dir", "file"):
        return Eligibility(False,
                           f"refused: {entry.kind} não é arquivo nem árvore regular")
    if entry.uid != os.getuid():
        return Eligibility(False, f"refused: dono uid {entry.uid}, não deste usuário")
    if entry.holder_pids:
        pids = ", ".join(str(p) for p in entry.holder_pids)
        return Eligibility(False, f"refused: {len(entry.holder_pids)} processo(s) "
                                  f"com fd aberto: {pids}")
    if entry.truncated or entry.errors:
        por = ("truncada" if entry.truncated
               else f"{len(entry.errors)} erro(s) de walk")
        return Eligibility(False, f"refused: leitura incompleta ({por}) — "
                                  f"tamanho e idade não provam")
    if entry.bytes > policy.max_item_bytes:
        return Eligibility(False,
                           f"refused: {entry.bytes} bytes acima do limite por item")
    if entry.volume not in policy.volumes:
        return Eligibility(False, f"refused: volume {entry.volume} fora da watch-list")
    if entry.age_days < policy.min_age_days:
        idade = f"{entry.age_days:.1f}".replace(".", ",")
        piso = f"{policy.min_age_days:g}".replace(".", ",")
        return Eligibility(False, f"refused: {idade} d, mais novo que o piso "
                                  f"de {piso} d")
    matched = matches(entry.path, policy.allow_patterns)
    if matched is None:
        return Eligibility(False, "refused: fora da allow-list de sujeira de agente")
    return Eligibility(True, f"liberável: casado com {matched}", matched)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_policy.py -v` → PASS (16).
Run: `.venv/bin/python -m pytest -v 2>&1 | tail -2` → `418 passed` (402 + 16). O `-q` extra
empilhado com `addopts = "-q"` leva a verbosidade a −2 e suprime a linha de resumo: para
conferir o total use `-v … | tail -2`.

- [ ] **Step 5: Commit**

```bash
git add src/deck_wellness/actions/tmpfs/policy.py tests/test_tmpfs_policy.py
git commit -m "M7 T4: política de recusa-primeiro — tipo + allow-list, com motivo por item"
```

---

### Task 5: O plano refusal-first

**Files:**
- Create: `src/deck_wellness/actions/tmpfs/plan.py`
- Test: `tests/test_tmpfs_plan.py`

**Interfaces:**
- Consumes: `TmpfsVolume` (T1), `TmpfsEntry` (T3), `Policy`/`classify` (T4)
- Produces: `item_id_for(path) -> str`,
  `PlanItem(item_id, path, name, volume, kind, uid, bytes, files, age_days, holder_pids, ok, reason, matched, truncated, errors)` com `to_dict()`,
  `TmpfsPlan(generated_at, volumes, policy, reclaimable, protected, total_bytes, scanned_entries, scanned_bytes, digest, errors)` com `to_dict()`, `to_json()`, `find(handle)`,
  `build_plan(volumes, entries, policy, *, now=None) -> TmpfsPlan`

- [ ] **Step 1: Escrever o teste que falha**

```python
"""O plano é a autoridade: cada item entra com veredito e a contagem tem de fechar.

reclaimable + protected == scanned_entries é a mesma reconciliação que o M5 provou
(141 = 34+85+22+0). Sem ela, "protegi tudo" pode significar "perdi itens".
"""
import json
import os

from deck_wellness.actions.tmpfs import plan
from deck_wellness.actions.tmpfs.inventory import TmpfsEntry
from deck_wellness.actions.tmpfs.policy import Policy
from deck_wellness.core.tmpfs import TmpfsVolume

NOW = 1_700_000_000.0
GIB = 1024 ** 3


def vol(path="/tmp", used=2 * GIB):
    return TmpfsVolume(path, "tmpfs", 8 * GIB, used, 8 * GIB - used)


def entry(name, *, path=None, kind="dir", age_days=10.0, bytes=100, uid=os.getuid(),
          holder_pids=(), truncated=False):
    return TmpfsEntry(path or f"/tmp/{name}", name, "/tmp", kind, uid, bytes, 1,
                      age_days, False, False, holder_pids, truncated, ())


def test_every_entry_lands_on_exactly_one_side():
    entries = [entry("qoder-cli-1000"), entry("novo", age_days=0.2),
               entry("desconhecido")]
    p = plan.build_plan((vol(),), entries, Policy(), now=NOW)
    assert p.scanned_entries == 3
    assert len(p.reclaimable) + len(p.protected) == p.scanned_entries
    assert [i.path for i in p.reclaimable] == ["/tmp/qoder-cli-1000"]
    assert all(i.reason.startswith("refused:") for i in p.protected)


def test_total_bytes_counts_only_the_reclaimable_side():
    entries = [entry("qoder-cli-1000", bytes=700), entry("desconhecido", bytes=5000)]
    p = plan.build_plan((vol(),), entries, Policy(), now=NOW)
    assert (p.total_bytes, p.scanned_bytes) == (700, 5700)


def test_digest_is_stable_for_the_same_plan_and_moves_with_age():
    entries = [entry("qoder-cli-1000")]
    assert (plan.build_plan((vol(),), entries, Policy(), now=NOW).digest ==
            plan.build_plan((vol(),), entries, Policy(), now=NOW).digest)
    older = plan.build_plan((vol(),), [entry("qoder-cli-1000", age_days=11.0)],
                            Policy(), now=NOW)
    assert older.digest != plan.build_plan((vol(),), entries, Policy(), now=NOW).digest


def test_the_digest_pins_the_item_rows_and_not_the_capacity_echo():
    """A fronteira, pinada: mudar a capacidade do volume NÃO muda o digest.

    O digest é sha256 do conteúdo canônico das LINHAS DO PLANO (item, bytes, idade,
    veredito, motivo), que é exatamente o conjunto "o que seria apagado" — o mesmo
    escopo do digest do plano de disco do M5 (`actions/disk/planner.py:185`, que hashia
    só `[[path, bytes], …]`; o daqui é mais rico). Echo de capacidade e de política entra
    no JSON para o usuário ler, mas não no digest: uma política que não vira veredito
    nenhum deixa as linhas idênticas, e o que protege de verdade é a releitura —
    `release_item` (T9) re-classifica e re-digere a árvore do item antes de unlinkar, e
    recusa quando o `tree_digest` difere. Se um dia o digest passar a cobrir capacidade e
    política, este teste quebra de propósito e a troca é decisão, não acidente.
    """
    entries = [entry("qoder-cli-1000")]
    same_rows = plan.build_plan((vol(used=7 * GIB),), entries, Policy(), now=NOW)
    assert same_rows.digest == plan.build_plan((vol(),), entries, Policy(), now=NOW).digest


def test_the_biggest_reclaimable_item_is_offered_first():
    entries = [entry("qoder-cli-1000", bytes=700), entry("node-compile-cache", bytes=900)]
    p = plan.build_plan((vol(),), entries, Policy(), now=NOW)
    assert [i.path for i in p.reclaimable] == ["/tmp/node-compile-cache",
                                               "/tmp/qoder-cli-1000"]


def test_equal_sized_reclaimable_items_are_ordered_by_path():
    entries = [entry("qoder-cli-1000"), entry("node-compile-cache")]
    p = plan.build_plan((vol(),), entries, Policy(), now=NOW)
    assert [i.path for i in p.reclaimable] == ["/tmp/node-compile-cache",
                                               "/tmp/qoder-cli-1000"]


def test_item_ids_distinguish_paths_and_are_stable():
    """Um `item_id_for` que devolvesse constante passaria em todos os testes acima:
    `find(item.item_id)` acha o primeiro item dos dois lados, e nenhum digest é fixado
    por valor. Dois caminhos, dois ids — é o que o `--item` do CLI vai receber."""
    assert plan.item_id_for("/tmp/a") != plan.item_id_for("/tmp/b")
    assert plan.item_id_for("/tmp/a") == plan.item_id_for("/tmp/a")
    assert len(plan.item_id_for("/tmp/a")) == 12
    p = plan.build_plan((vol(),), [entry("qoder-cli-1000"), entry("node-compile-cache")],
                        Policy(), now=NOW)
    assert len({i.item_id for i in p.reclaimable}) == 2


def test_json_round_trips_as_one_line_with_the_volume_attached():
    p = plan.build_plan((vol(),), [entry("qoder-cli-1000")], Policy(), now=NOW)
    text = p.to_json()
    assert "\n" not in text.strip()
    payload = json.loads(text)
    assert payload["scanned_entries"] == 1
    assert payload["volumes"][0]["path"] == "/tmp"
    assert payload["reclaimable"][0]["matched"] == "/tmp/qoder-cli-1000"
    assert payload["policy"]["min_age_days"] == 3.0


def test_find_accepts_the_short_id_and_the_exact_path():
    p = plan.build_plan((vol(),), [entry("qoder-cli-1000"), entry("desconhecido")],
                        Policy(), now=NOW)
    item = p.reclaimable[0]
    assert p.find(item.item_id).path == "/tmp/qoder-cli-1000"
    assert p.find("/tmp/desconhecido").ok is False
    assert p.find("nao-existe") is None


def test_holder_pids_and_truncation_reach_the_payload():
    p = plan.build_plan((vol(),), [entry("a", holder_pids=(9,), truncated=True)],
                        Policy(), now=NOW)
    assert p.protected[0].holder_pids == (9,)
    assert p.protected[0].to_dict()["truncated"] is True


def test_walk_errors_are_carried_into_the_plan():
    broken = TmpfsEntry("/tmp/morto", "morto", "/tmp", "missing", -1, 0, 0, 0.0,
                        False, False, (), False, ("/tmp/morto: no such file",))
    p = plan.build_plan((vol(),), [broken], Policy(), now=NOW)
    assert p.errors == ("/tmp/morto: no such file",)
    assert p.scanned_entries == 1 and p.reclaimable == ()


def test_an_empty_volume_yields_an_empty_but_honest_plan():
    p = plan.build_plan((vol(),), (), Policy(), now=NOW)
    assert (p.scanned_entries, p.total_bytes, p.reclaimable, p.protected) == (
        0, 0, (), ())
    assert p.digest and p.generated_at.startswith("2023-11-14")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_plan.py -v`
Expected: FAIL — módulo `plan` inexistente.

- [ ] **Step 3: Implementar o mínimo**

```python
"""Plano de liberação: seco, com digest e com as recusas dentro dele.

O digest existe para a mesma coisa que o digest do plano de tunings: poder dizer
"este é o plano que eu vi" depois de formatar, ordenar ou cortar.
"""
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .policy import classify


def item_id_for(path: str) -> str:
    return hashlib.sha256(str(path).encode()).hexdigest()[:12]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class PlanItem:
    item_id: str
    path: str
    name: str
    volume: str
    kind: str
    uid: int
    bytes: int
    files: int
    age_days: float
    holder_pids: tuple
    ok: bool
    reason: str
    matched: str | None
    truncated: bool
    errors: tuple

    def to_dict(self) -> dict:
        d = asdict(self)
        d["age_days"] = round(self.age_days, 2)
        d["holder_pids"] = list(self.holder_pids)
        d["errors"] = list(self.errors)
        return d


@dataclass(frozen=True)
class TmpfsPlan:
    generated_at: str
    volumes: tuple
    policy: object
    reclaimable: tuple
    protected: tuple
    total_bytes: int
    scanned_entries: int
    scanned_bytes: int
    digest: str
    errors: tuple

    def to_dict(self) -> dict:
        return {"generated_at": self.generated_at,
                "volumes": [v.to_dict() for v in self.volumes],
                "policy": self.policy.to_dict(),
                "reclaimable": [i.to_dict() for i in self.reclaimable],
                "protected": [i.to_dict() for i in self.protected],
                "total_bytes": self.total_bytes,
                "scanned_entries": self.scanned_entries,
                "scanned_bytes": self.scanned_bytes,
                "digest": self.digest,
                "errors": list(self.errors)}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    def find(self, handle: str):
        for item in (*self.reclaimable, *self.protected):
            if item.item_id == handle or item.path == handle:
                return item
        return None


def build_plan(volumes, entries, policy, *, now=None) -> TmpfsPlan:
    now = time.time() if now is None else now
    eligible, refused, errors = [], [], []
    for entry in entries:
        verdict = classify(entry, policy)
        item = PlanItem(item_id=item_id_for(entry.path), path=entry.path,
                        name=entry.name, volume=entry.volume, kind=entry.kind,
                        uid=entry.uid, bytes=entry.bytes, files=entry.files,
                        age_days=entry.age_days, holder_pids=entry.holder_pids,
                        ok=verdict.ok, reason=verdict.reason, matched=verdict.matched,
                        truncated=entry.truncated, errors=entry.errors)
        errors.extend(entry.errors)
        (eligible if verdict.ok else refused).append(item)

    eligible.sort(key=lambda i: (-i.bytes, i.path))
    refused.sort(key=lambda i: i.path)
    digest = hashlib.sha256("\n".join(
        f"{i.item_id}\t{i.bytes}\t{i.age_days:.3f}\t{i.ok}\t{i.reason}"
        for i in (*eligible, *refused)).encode()).hexdigest()

    return TmpfsPlan(generated_at=_iso(now), volumes=tuple(volumes), policy=policy,
                     reclaimable=tuple(eligible), protected=tuple(refused),
                     total_bytes=sum(i.bytes for i in eligible),
                     scanned_entries=len(entries),
                     scanned_bytes=sum(i.bytes for i in entries),
                     digest=digest, errors=tuple(errors))
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_plan.py -v` → PASS (12).
Run: `.venv/bin/python -m pytest -v 2>&1 | tail -2` → `430 passed` (418 + 12). O `-q` extra
empilhado com `addopts = "-q"` leva a verbosidade a −2 e suprime a linha de resumo.

- [ ] **Step 5: Commit**

```bash
git add src/deck_wellness/actions/tmpfs/plan.py tests/test_tmpfs_plan.py
git commit -m "M7 T5: plano refusal-first com digest e contagens reconciliáveis"
```

---

### Task 6: Tendência e ETA até lotar

**Files:**
- Create: `src/deck_wellness/actions/tmpfs/trend.py`
- Test: `tests/test_tmpfs_trend.py`

**Interfaces:**
- Consumes: nada (matemática pura)
- Produces: `eta_hours(samples: tuple[tuple[float, int], ...], capacity_bytes: int, *, now=None, min_samples: int = 3, horizon_s: float = 900.0) -> float | None`

- [ ] **Step 1: Escrever o teste que falha**

```python
"""ETA é extrapolação, não promessa: devolve None quando não sabe.

Amostra insuficiente, tendência de queda ou volume já cheio devolvem None — nunca
0, porque 0 seria lido como "vai lotar agora", o oposto de "não tenho evidência
de crescimento".
"""
import pytest

from deck_wellness.actions.tmpfs import trend

GIB = 1024 ** 3


def test_growing_usage_extrapolates_to_the_cap():
    samples = ((0.0, 1 * GIB), (60.0, 2 * GIB), (120.0, 3 * GIB))
    got = trend.eta_hours(samples, 8 * GIB, now=120.0)
    assert got == pytest.approx(300 / 3600, abs=1e-3)      # 1 GiB/min, faltam 5 GiB


def test_declining_usage_has_no_eta():
    assert trend.eta_hours(((0.0, 5 * GIB), (60.0, 3 * GIB), (120.0, 1 * GIB)),
                           8 * GIB, now=120.0) is None


def test_flat_usage_has_no_eta():
    assert trend.eta_hours(((0.0, 2 * GIB), (60.0, 2 * GIB), (120.0, 2 * GIB)),
                           8 * GIB, now=120.0) is None


def test_two_samples_are_not_a_trend():
    assert trend.eta_hours(((0.0, 1 * GIB), (60.0, 2 * GIB)), 8 * GIB, now=60.0) is None


def test_a_full_volume_is_not_future_news():
    assert trend.eta_hours(((0.0, 7 * GIB), (60.0, 8 * GIB), (120.0, 8 * GIB)),
                           8 * GIB, now=120.0) is None


def test_samples_outside_the_window_are_ignored():
    samples = ((0.0, 0), (3000.0, 1 * GIB), (3060.0, 2 * GIB), (3120.0, 3 * GIB))
    assert trend.eta_hours(samples, 8 * GIB, now=3120.0) == pytest.approx(
        300 / 3600, abs=1e-3)


def test_no_capacity_no_answer():
    assert trend.eta_hours(((0.0, 1), (60.0, 2), (120.0, 3)), 0, now=120.0) is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_trend.py -v`
Expected: FAIL — módulo `trend` inexistente.

- [ ] **Step 3: Implementar o mínimo**

```python
"""Regressão linear sobre a janela curta de amostras de ocupação."""
import time


def eta_hours(samples, capacity_bytes: int, *, now=None, min_samples: int = 3,
              horizon_s: float = 900.0):
    now = time.time() if now is None else now
    window = sorted(((ts, used) for ts, used in samples if now - ts <= horizon_s),
                    key=lambda s: s[0])
    if len(window) < min_samples or capacity_bytes <= 0:
        return None

    n = len(window)
    mean_x = sum(ts for ts, _ in window) / n
    mean_y = sum(used for _, used in window) / n
    denom = sum((ts - mean_x) ** 2 for ts, _ in window)
    if denom <= 0:
        return None
    slope = sum((ts - mean_x) * (used - mean_y) for ts, used in window) / denom
    if slope <= 0:
        return None

    remaining = capacity_bytes - window[-1][1]
    if remaining <= 0:
        return None
    return round(remaining / slope / 3600.0, 3)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_trend.py -v` → PASS (7).
Run: `.venv/bin/python -m pytest -v 2>&1 | tail -2` → `437 passed` (430 + 7).

- [ ] **Step 5: Commit**

```bash
git add src/deck_wellness/actions/tmpfs/trend.py tests/test_tmpfs_trend.py
git commit -m "M7 T6: ETA até lotar — extrapolação que devolve None sem evidência"
```

---

### Task 7: A pressão do tmpfs chega ao título da janela

**Files:**
- Modify: `src/deck_wellness/core/snapshot.py:61-74` (campo `tmpfs`)
- Modify: `src/deck_wellness/core/collector.py:1-61` (ler volumes no `collect()`)
- Modify: `src/deck_wellness/ui/title_signal.py:15-55`
- Test: `tests/test_title_signal.py`, `tests/test_collector.py`, `tests/test_ui_tray.py` (estender)

**Interfaces:**
- Consumes: `core.tmpfs.watched_volumes(proc_root=…)`, `TmpfsVolume.used_frac` (T1)
- Produces: `Snapshot.tmpfs: tuple[TmpfsVolume, ...] = ()`;
  `MetricsCollector.tmpfs_fn: Callable[[str], tuple] | None = None`;
  `Thresholds.tmpfs_yellow_frac: float = 0.75`, `Thresholds.tmpfs_red_frac: float = 0.90`;
  `worst_tmpfs(snapshot, thresholds) -> TmpfsVolume | None`; sufixo no título
  `· {path} {pct}%` (inteiro, sem vírgula — é porcentagem, não grandeza)

- [ ] **Step 1: Escrever os testes que falham**

Em `tests/test_title_signal.py`, estender o helper existente (linha 6) para aceitar
volumes e acrescentar os testes abaixo. O helper passa a ser:

```python
def snap(available_kb, total_kb=14_374_304, psi10=0.0, self_rss_kb=96_000, tmpfs=()):
    return Snapshot(
        ts=0.0,
        mem=MemInfo(total_kb, available_kb),
        swap_used_kb=0, swap_total_kb=7_208_724,
        pressure_memory=Pressure(psi10, psi10, psi10, 0) if psi10 is not None else None,
        pressure_io=None, pressure_cpu=None,
        load=LoadAvg(1, 1, 1, 1, 1),
        apps=(AppRSS("edge", 1_400_000, 21),),
        self_rss_kb=self_rss_kb,
        tmpfs=tmpfs,
    )
```

E no fim do arquivo:

```python
from deck_wellness.core.tmpfs import TmpfsVolume

GIB = 1024 ** 3


def vol(path="/tmp", total=7.24, used=0.0):
    used_bytes = int(used * GIB)
    total_bytes = int(total * GIB)
    return TmpfsVolume(path, "tmpfs", total_bytes, used_bytes, total_bytes - used_bytes)


def test_tmpfs_at_95_percent_is_red_even_with_plenty_of_ram():
    # RAM folgada (5 GB de 14 GB disponíveis): só o tmpfs pode explicar o 🔴
    s = title_signal.compute(snap(5_000_000, tmpfs=(vol(used=6.88, total=7.24),)))
    assert s.level == "red" and s.emoji == "🔴"


def test_tmpfs_at_80_percent_is_yellow():
    s = title_signal.compute(snap(5_000_000, tmpfs=(vol(used=5.8, total=7.24),)))
    assert s.level == "yellow"


def test_tmpfs_below_the_floor_does_not_touch_the_signal():
    before = title_signal.compute(snap(5_000_000))
    after = title_signal.compute(snap(5_000_000, tmpfs=(vol(used=5.0, total=7.24),)))
    assert after.level == before.level == "green"
    assert after.text == before.text


def test_the_floor_itself_is_included():
    # 6 GiB de 8 = 0,75 exato (e 0,75 é representável em binário, então este teste
    # é fronteira de verdade, não sorteio de ponto flutuante). Trocar `>=` por `>`
    # faria um volume exatamente no piso sumir do título.
    volume = TmpfsVolume("/dev/shm", "tmpfs", 8 * GIB, 6 * GIB, 2 * GIB)
    s = title_signal.compute(snap(5_000_000, tmpfs=(volume,)))
    assert s.level == "yellow" and s.text.endswith("· /dev/shm 75%")


def test_the_title_names_the_worst_watched_volume():
    # os dois passam do piso de 75%: com um só flagged, min e max dariam o mesmo
    # volume e o seletor do pior ficaria sem teste
    s = title_signal.compute(snap(5_000_000, tmpfs=(
        vol("/tmp", used=6.0, total=7.24), vol("/run/user/1000", total=1.45, used=1.40))))
    assert s.text.endswith("· /run/user/1000 97%")


def test_the_tmpfs_rule_only_escalates_never_relaxes():
    # RAM crítica continua vermelha com tmpfs tranquilo
    s = title_signal.compute(snap(1_000_000, tmpfs=(vol(used=0.5),)))
    assert s.level == "red"


def test_a_yellow_tmpfs_does_not_downgrade_a_red_machine():
    # 80% de tmpfs sozinho é amarelo; com RAM crítica o título segue vermelho,
    # só que agora dizendo as duas coisas. Afrouxar `elif level == "green"` para
    # `else` é a inversão que este teste existe para pegar.
    s = title_signal.compute(snap(1_000_000, tmpfs=(vol(used=5.8, total=7.24),)))
    assert s.level == "red" and s.emoji == "🔴"
    assert "/tmp 80%" in s.text
```

Em `tests/test_collector.py` (o fixture `env` já existe):

```python
def test_the_collector_carries_watched_volumes_into_the_snapshot(env):
    from deck_wellness.core.tmpfs import TmpfsVolume
    proc_root, sys_root = env
    volumes = (TmpfsVolume("/tmp", "tmpfs", 8 * 1024**3, 7 * 1024**3, 1024**3),)
    snap = collector.MetricsCollector(
        proc_root=proc_root, sys_root=sys_root, tmpfs_fn=lambda root: volumes).collect()
    assert snap.tmpfs == volumes


def test_a_fake_proc_root_with_no_mounts_carries_no_tmpfs(env):
    """O collector não inventa ocupação: sem /proc/mounts não há volume medido."""
    proc_root, sys_root = env
    snap = collector.MetricsCollector(proc_root=proc_root, sys_root=sys_root).collect()
    assert snap.tmpfs == ()
```

Em `tests/test_ui_tray.py`, estender o `snap()` local (linha 23) com `tmpfs=()` e
`tmpfs=tmpfs` no `Snapshot(...)`, e somar. O arquivo ainda não importa
`TmpfsVolume` — a linha 10 hoje é
`from deck_wellness.core.snapshot import MemInfo, Pressure, Snapshot` e precisa
ganhar um `from deck_wellness.core.tmpfs import TmpfsVolume` junto: sem isso o
vermelho do Step 2 seria `NameError`, que é defeito do teste e não evidência da
funcionalidade ausente.

```python
def test_the_tooltip_shows_the_worst_watched_volume(qapp):
    """A bandeja não tem regra própria: ela herda o texto do título."""
    tray, _ = build()
    tray.install()
    tray.show_snapshot(snap(tmpfs=(TmpfsVolume(
        "/tmp", "tmpfs", 8 * 1024**3, 7_639_801_600, 419_430_400),)))
    assert "/tmp 93%" in tray.tray.tooltips[-1]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_title_signal.py tests/test_collector.py tests/test_ui_tray.py -v`
Expected: FAIL — `Snapshot.__init__() got an unexpected keyword argument 'tmpfs'` e,
para os testes de título, `TypeError: __init__() got an unexpected keyword argument 'tmpfs_fn'`.

- [ ] **Step 3: Escrever a implementação mínima**

`core/snapshot.py` — import e campo (depois de `procs`, antes de `errors`; campos com
default vêm depois dos obrigatórios):

```python
from .tmpfs import TmpfsVolume
```

```python
    procs: tuple[ProcInfo, ...] = ()
    tmpfs: tuple[TmpfsVolume, ...] = ()
    errors: tuple[str, ...] = field(default_factory=tuple)
```

`core/collector.py` — o `statvfs` de tmpfs é syscall local, e `read_mounts` some o
volume que não é mais montado; nada aqui faz walk de árvore nem varre fd:

```python
from typing import Callable

from . import procfs, sysfs, tmpfs as tmpfs_read

def _read_tmpfs(proc_root: str) -> tuple:
    return tmpfs_read.watched_volumes(proc_root=proc_root)
```

No dataclass `MetricsCollector`, acrescentar o campo (após `max_groups`):

```python
    tmpfs_fn: Callable[[str], tuple] | None = None
```

Em `collect()`, antes do `return Snapshot(...)`:

```python
        # None, não a função, como default: função como default de campo de
        # dataclass vira método ligado e receberia `self` como primeiro argumento
        volumes = (self.tmpfs_fn or _read_tmpfs)(str(root))
```

e no construtor do `Snapshot` a linha `tmpfs=volumes,`.

`ui/title_signal.py` — as regras de RAM/PSI/RSS não mudam; o tmpfs só escala:

```python
    self_rss_yellow_kb: int = 300_000
    tmpfs_yellow_frac: float = 0.75
    tmpfs_red_frac: float = 0.90
```

```python
def worst_tmpfs(snapshot: Snapshot, thresholds: Thresholds) -> TmpfsVolume | None:
    """O volume em watch que merece aparecer no título, ou None enquanto todos folgam."""
    flagged = [v for v in snapshot.tmpfs if v.used_frac >= thresholds.tmpfs_yellow_frac]
    return max(flagged, key=lambda v: v.used_frac) if flagged else None
```

Dentro de `compute`, depois de decidir `level` pelas regras atuais e antes do `emoji`:

```python
    worst = worst_tmpfs(snapshot, thresholds)
    if worst is not None:
        if worst.used_frac >= thresholds.tmpfs_red_frac:
            level = "red"
        elif level == "green":
            level = "yellow"
```

e no fim, depois de montar `text`:

```python
    if worst is not None:
        text += f" · {worst.path} {round(worst.used_frac * 100)}%"
```

Import necessário no topo: `from ..core.tmpfs import TmpfsVolume`.

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_title_signal.py tests/test_collector.py tests/test_ui_tray.py -v` → PASS.
Run: `.venv/bin/python -m pytest -v 2>&1 | tail -2` → `447 passed` (437 + 10). O
`Snapshot` com campo novo não quebra `test_workers.py`/`test_ui_dashboard.py`, que só
passam os campos antigos.

**Coerção de mutação:** inverter `elif level == "green"` para `else`, trocar
`>= thresholds.tmpfs_yellow_frac` por `>`, ou remover o sufixo do título matam ao
menos um teste desta tarefa; `min` em vez de `max` por `used_frac` mata
`test_the_title_names_the_worst_watched_volume`. Guarde a saída de `-v` e o resultado
de cada mutação no corpo do commit — a spec (§10) pede a evidência, não a afirmação.

- [ ] **Step 5: Commit**

```bash
git add src/deck_wellness/core/snapshot.py src/deck_wellness/core/collector.py \
        src/deck_wellness/ui/title_signal.py tests/test_title_signal.py \
        tests/test_collector.py tests/test_ui_tray.py
git commit -m "M7 T7: pressão de tmpfs no título — escala o sinal, nunca relaxa"
```

---

### Task 8: Ledger append-only e orçamento de retenção

**Files:**
- Modify: `src/deck_wellness/paths.py:38-39` (antes de `audit_log_path`)
- Create: `src/deck_wellness/actions/tmpfs/ledger.py`
- Test: `tests/test_tmpfs_ledger.py`, `tests/test_paths.py` (estender)

**Interfaces:**
- Consumes: `paths.tmp_ledger_path()`, `paths.tmp_quarantine_dir()`, o mesmo mecanismo de
  append+`fsync` de `safely/audit.py:48-53`
- Produces: `RETENTION_DAYS = 14.0`, `MAX_RETAINED_BYTES = 3 * 1024**3`,
  `STATE_PARTIAL/RELEASED/RESTORED/DROPPED/EXPIRED`, `ACTIVE_STATES`,
  `LedgerRecord(ts, entry_id, src, volume, stored, bytes, sha256, age_days,
  matched_pattern, holder_pids, state, action_id, audit_event_id)` com `to_dict()`;
  `BudgetView(retained_bytes, retained_count, oldest_days, slack_bytes, freed_bytes, by_volume)`;
  `Ledger(path=None)`, `rows() -> list[dict]`, `append(**fields) -> LedgerRecord`,
  `records() -> dict[str, LedgerRecord]`, `retained() -> tuple[LedgerRecord, ...]`,
  `retained_bytes() -> int`, `retained_count() -> int`, `oldest() -> LedgerRecord | None`,
  `find(handle: str) -> LedgerRecord | None`,
  `over_budget(*, days=RETENTION_DAYS, max_bytes=MAX_RETAINED_BYTES, now=None) -> tuple[LedgerRecord, ...]`,
  `budget_view(*, now=None) -> BudgetView`

- [ ] **Step 1: Escrever os testes que falham**

```python
"""O que ficou na SSD é registro, não esquecimento: append-only e com teto.

Sem orçamento, "liberar RAM" só empurra o lixo para outro disco. Cada linha é uma
transição; o estado vigente é o da última linha de cada entry_id — igual ao audit,
só que aqui o tamanho do que está retido decide se a próxima liberação acontece.
"""
import json
import time

import pytest

from deck_wellness.actions.tmpfs import ledger as L
from deck_wellness.paths import tmp_ledger_path

DAY = 86_400
NOW = 1_700_000_000.0
GIB = 1024 ** 3


@pytest.fixture
def book(tmp_path):
    return L.Ledger(tmp_path / "tmp-ledger.jsonl")


def rec(**over):
    base = dict(entry_id="1700-a", src="/tmp/velho", volume="/tmp",
                stored="/home/u/.local/share/deck-wellness/tmp-quarantine/x",
                bytes=1024, sha256="ab" * 32, age_days=4.0,
                matched_pattern="/tmp/tmp*", holder_pids=(), state=L.STATE_RELEASED,
                action_id="tmpfs.release", audit_event_id="e1")
    base.update(over)
    return base


def stamp(days_ago: float, *, ledger) -> str:
    """Escreve uma linha com ts falsa para trás: o ledger usa o relógio injetável."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ",
                         time.gmtime(NOW - days_ago * DAY))


def test_paths_land_on_the_ssd_not_in_ram(fake_home):
    from deck_wellness import paths
    assert paths.tmp_ledger_path() == (
        fake_home / ".local" / "state" / "deck-wellness" / "tmp-ledger.jsonl")
    assert paths.tmp_quarantine_dir() == (
        fake_home / ".local" / "share" / "deck-wellness" / "tmp-quarantine")


def test_append_writes_one_fsynced_line_per_transition(book):
    first = book.append(**rec())
    second = book.append(**rec(state=L.STATE_RESTORED, entry_id="1700-a"))
    lines = (book.path.read_text(encoding="utf-8")).splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["state"] == "released"
    assert first.entry_id == second.entry_id


def test_the_current_state_is_the_last_line_for_an_entry(book):
    book.append(**rec(entry_id="1700-a"))
    book.append(**rec(entry_id="1700-a", state=L.STATE_RESTORED))
    book.append(**rec(entry_id="1700-b"))
    current = book.records()
    assert current["1700-a"].state == L.STATE_RESTORED
    assert current["1700-b"].state == L.STATE_RELEASED
    assert book.retained_count() == 1


def test_restored_and_dropped_stop_counting_against_the_budget(book):
    book.append(**rec(entry_id="1700-a", bytes=4096))
    book.append(**rec(entry_id="1700-b", bytes=8192))
    assert book.retained_bytes() == 12_288
    book.append(**rec(entry_id="1700-a", state=L.STATE_RESTORED))
    book.append(**rec(entry_id="1700-b", state=L.STATE_DROPPED))
    assert book.retained_bytes() == 0 and book.retained_count() == 0


def test_partial_counts_as_retained_because_it_occupies_the_ssd(book):
    book.append(**rec(state=L.STATE_PARTIAL, bytes=5_000_000))
    assert book.retained_bytes() == 5_000_000
    assert book.records()["1700-a"].state == L.STATE_PARTIAL


def test_over_budget_returns_victims_oldest_first(book):
    """A mais velha sai primeiro: é a única ordem que o usuário pode auditar."""
    book.append(**rec(entry_id="a", bytes=2 * GIB, state=L.STATE_RELEASED))
    book.append(**rec(entry_id="b", bytes=2 * GIB, state=L.STATE_RELEASED))
    # envelhece "a" reescrevendo a linha
    rows = [json.loads(line) for line in book.path.read_text().splitlines()]
    rows[0]["ts"] = stamp(days_ago=30, ledger=book)
    book.path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    due = book.over_budget(now=NOW)
    assert [r.entry_id for r in due] == ["a"]
    assert book.oldest().entry_id == "a"


def test_over_budget_is_empty_inside_both_limits(book):
    book.append(**rec(entry_id="a", bytes=1024))
    assert book.over_budget(now=NOW) == ()


def test_bytes_over_the_ceiling_evict_oldest_until_it_fits(book):
    for i, size in enumerate((2 * GIB, 2 * GIB, 2 * GIB)):
        book.append(**rec(entry_id=f"e{i}", bytes=size, ts=""))
    due = book.over_budget(max_bytes=5 * GIB, now=NOW)
    assert [r.entry_id for r in due] == ["e0", "e1"]  # sobra e2 = 2 GiB ≤ 5 GiB


def test_budget_view_reports_ram_freed_against_ssd_retained(book):
    book.append(**rec(entry_id="a", bytes=3 * GIB, volume="/tmp"))
    book.append(**rec(entry_id="b", bytes=1 * GIB, volume="/run/user/1000"))
    book.append(**rec(entry_id="a", state=L.STATE_RESTORED, bytes=3 * GIB))
    view = book.budget_view(now=NOW)
    assert view.retained_bytes == 1 * GIB
    assert view.freed_bytes == 1 * GIB            # o que a RAM ainda não viu de volta
    assert view.slack_bytes == L.MAX_RETAINED_BYTES - 1 * GIB
    assert view.by_volume == {"/run/user/1000": 1 * GIB}


def test_a_corrupt_line_is_skipped_not_fatal(book):
    book.append(**rec(entry_id="a"))
    with open(book.path, "a", encoding="utf-8") as f:
        f.write("{isto não é json}\n")
    assert book.retained_count() == 1


def test_find_accepts_entry_id_or_the_tail_of_a_path(book):
    book.append(**rec(entry_id="1700-deadbeef", src="/tmp/qoder-cli-1000/x"))
    assert book.find("1700-deadbeef").entry_id == "1700-deadbeef"
    assert book.find("/tmp/qoder-cli-1000/x").entry_id == "1700-deadbeef"
    assert book.find("inexistente") is None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'deck_wellness.actions.tmpfs.ledger'`
e `AttributeError: module 'deck_wellness.paths' has no attribute 'tmp_quarantine_dir'`.

- [ ] **Step 3: Escrever a implementação mínima**

`paths.py` — antes de `audit_log_path()`:

```python
def tmp_quarantine_dir() -> Path:
    """Retenção de tmpfs: o destino é a SSD, nunca um tmpfs (RAM)."""
    return data_dir() / "tmp-quarantine"


def tmp_ledger_path() -> Path:
    return state_dir() / "tmp-ledger.jsonl"
```

`actions/tmpfs/ledger.py`:

```python
"""Registro append-only do que saiu da RAM e ficou na SSD, com teto de retenção.

Cada linha é uma transição (``partial`` → ``released`` → ``restored``/``dropped``/
``expired``); o estado vigente de um item é o da sua última linha. O orçamento é do
que ainda *ocupa* a SSD: ``partial`` conta, porque o clone existe.
"""
import json
import os
import time
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from ... import paths

RETENTION_DAYS = 14.0
MAX_RETAINED_BYTES = 3 * 1024 ** 3

STATE_PARTIAL = "partial"
STATE_RELEASED = "released"
STATE_RESTORED = "restored"
STATE_DROPPED = "dropped"
STATE_EXPIRED = "expired"
# ainda ocupando a SSD
ACTIVE_STATES = (STATE_PARTIAL, STATE_RELEASED)

FIELDS = ("ts", "entry_id", "src", "volume", "stored", "bytes", "sha256", "age_days",
          "matched_pattern", "holder_pids", "state", "action_id", "audit_event_id")


@dataclass(frozen=True)
class LedgerRecord:
    ts: str
    entry_id: str
    src: str
    volume: str
    stored: str
    bytes: int
    sha256: str
    age_days: float
    matched_pattern: str | None
    holder_pids: tuple[int, ...]
    state: str
    action_id: str
    audit_event_id: str

    def to_dict(self) -> dict:
        return {k: (list(v) if k == "holder_pids" else v)
                for k, v in zip(FIELDS, (getattr(self, f.name) for f in fields(self)))}


@dataclass(frozen=True)
class BudgetView:
    retained_bytes: int
    retained_count: int
    oldest_days: float
    slack_bytes: int
    freed_bytes: int
    by_volume: dict[str, int] = field(default_factory=dict)


def _days_since(ts: str, now: float) -> float:
    try:
        then = time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    except (ValueError, OverflowError):
        return 0.0
    return max(0.0, (now - then) / 86_400.0)


class Ledger:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else paths.tmp_ledger_path()

    # ------------------------------------------------------------------ escrita

    def append(self, **record) -> LedgerRecord:
        missing = [k for k in ("entry_id", "state", "action_id") if not record.get(k)]
        if missing:
            raise ValueError(f"ledger record requires {', '.join(missing)}")
        now = time.time()
        row = {
            "ts": record.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            **{k: record[k] for k in FIELDS if k != "ts" and k in record},
        }
        line = json.dumps(row, ensure_ascii=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode())
            os.fsync(fd)
        finally:
            os.close(fd)
        return self._hydrate(row)

    # ------------------------------------------------------------------- leitura

    def rows(self) -> list:
        if not self.path.exists():
            return []
        out = []
        for raw in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("entry_id"):
                out.append(row)
        return out

    def records(self) -> dict:
        """Estado vigente: a última linha de cada entry_id."""
        current = {}
        for row in self.rows():
            record = self._hydrate(row)
            current[record.entry_id] = record
        return current

    def retained(self) -> tuple:
        return tuple(r for r in self.records().values() if r.state in ACTIVE_STATES)

    def retained_bytes(self) -> int:
        return sum(r.bytes for r in self.retained())

    def retained_count(self) -> int:
        return len(self.retained())

    def oldest(self):
        return min(self.retained(), key=lambda r: r.ts, default=None)

    def find(self, handle: str):
        records = self.records()
        if handle in records:
            return records[handle]
        return next((r for r in records.values() if r.src == handle), None)

    def over_budget(self, *, days: float = RETENTION_DAYS,
                    max_bytes: int = MAX_RETAINED_BYTES, now: float | None = None):
        now = time.time() if now is None else now
        held = sorted(self.retained(), key=lambda r: (r.ts, r.entry_id))
        due = [r for r in held if _days_since(r.ts, now) > days]
        if sum(r.bytes for r in held) > max_bytes:
            remaining = max_bytes - sum(r.bytes for r in due)
            for record in held:
                if record in due or remaining < 0:
                    continue
                due.append(record)
                remaining -= record.bytes
        return tuple(due)

    def budget_view(self, *, now: float | None = None) -> BudgetView:
        now = time.time() if now is None else now
        held = self.retained()
        by_volume: dict[str, int] = {}
        for record in held:
            by_volume[record.volume] = by_volume.get(record.volume, 0) + record.bytes
        oldest = self.oldest()
        return BudgetView(
            retained_bytes=sum(r.bytes for r in held),
            retained_count=len(held),
            oldest_days=_days_since(oldest.ts, now) if oldest else 0.0,
            slack_bytes=max(0, MAX_RETAINED_BYTES - sum(r.bytes for r in held)),
            freed_bytes=sum(r.bytes for r in self.records().values()
                            if r.state in (STATE_RESTORED, STATE_DROPPED, STATE_EXPIRED)),
            by_volume=by_volume,
        )

    @staticmethod
    def _hydrate(row: dict) -> LedgerRecord:
        known = {f.name for f in fields(LedgerRecord)}
        payload = {k: v for k, v in row.items() if k in known}
        payload.setdefault("holder_pids", ())
        payload["holder_pids"] = tuple(payload.get("holder_pids") or ())
        try:
            return LedgerRecord(**payload)
        except TypeError:  # linha de uma versão futura do registro: ignorada, não fatal
            return LedgerRecord(ts="", entry_id=row.get("entry_id", ""), src="",
                                volume="", stored="", bytes=int(row.get("bytes", 0)),
                                sha256="", age_days=0.0, matched_pattern=None,
                                holder_pids=(), state=row.get("state", STATE_PARTIAL),
                                action_id="", audit_event_id="")
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_ledger.py tests/test_paths.py -v` → PASS (12 + as existentes).
Run: `.venv/bin/python -m pytest -q` → verde.

**Coerção de mutação:** tirar `STATE_PARTIAL` de `ACTIVE_STATES`, contar `restored`
como retido, ou ordenar `over_budget` do mais novo para o mais velho — cada um desses
mata ao menos um teste desta tarefa. Guarde a saída de `-v` no corpo do commit; a
spec (§10) pede a evidência, não a afirmação.

- [ ] **Step 5: Commit**

```bash
git add src/deck_wellness/paths.py src/deck_wellness/actions/tmpfs/ledger.py \
        tests/test_tmpfs_ledger.py tests/test_paths.py
git commit -m "M7 T8: ledger de retenção com orçamento — a SSD não vira o lixo novo"
```

---

### Task 9: Liberar RAM — copiar, verificar, então apagar

**Files:**
- Create: `src/deck_wellness/actions/tmpfs/release.py`
- Test: `tests/test_tmpfs_release.py`

**Interfaces:**
- Consumes: `TmpfsPlan`/`PlanItem` (T5), `Policy`/`classify` (T4), `entry_at`/`scan_volume`
  (T3), `read_mounts` (T1), `holder_index` (T2), `Ledger` (T8), `safely.guard.validate_target`,
  `safely.hashing.sha256_file`, `safely.audit.AuditLog`, `actions.disk.planner.default_allowed_roots`
- Produces: `MUTABLE_VOLUMES = ("/tmp", "/run/user/1000")`, `KIND = "tmpfs.release"`,
  `ReleaseResult(ok, entry_id, reason, bytes, stored, sha256, freed_bytes)` com `to_dict()`,
  `tree_digest(path) -> tuple[str, int]`, `default_allowed_roots(home=None) -> list`,
  `release_item(plan, item, *, ledger, dest_root=None, audit=None, confirm=False,
  entry_fn=_fresh_entry, statvfs_fn=os.statvfs, now=None, allowed_roots=None,
  remove_fn=None, proc_root=None) -> ReleaseResult`

- [ ] **Step 1: Escrever o teste que falha**

```python
"""A promessa deste arquivo é tirar bytes da RAM sem perder nenhum.

Cross-device é o ponto, não um bug: o `Quarantine.move_in` do M5 recusa rename
entre dispositivos porque lá a promessa é zero-copy; aqui a promessa é liberar
memória, então o movimento é explicitamente copy → verify → unlink, e o ledger
registra o meio do caminho.
"""
import json
import os
import shutil
import time
from pathlib import Path

import pytest

from deck_wellness.actions.tmpfs import release
from deck_wellness.actions.tmpfs.inventory import TmpfsEntry
from deck_wellness.actions.tmpfs.ledger import (MAX_RETAINED_BYTES, RETENTION_DAYS,
                                                 STATE_PARTIAL, STATE_RELEASED, Ledger)
from deck_wellness.actions.tmpfs.plan import PlanItem, build_plan
from deck_wellness.actions.tmpfs.policy import Policy
from deck_wellness.core.tmpfs import TmpfsVolume
from deck_wellness.safely.audit import AuditLog

DAY = 86_400
NOW = 1_700_000_000.0
GIB = 1024 ** 3
VOL = TmpfsVolume("/tmp", "tmpfs", 8 * GIB, 2 * GIB, 6 * GIB)


def sandbox_policy(tmp_path):
    """A allow-list do chão falso: o que está sob `tmp_path` é reconhecido.

    Sem isto, a elegibilidade destes testes dependeria do nome que o pytest dá ao
    `tmp_path` dele (ele costuma cair sob `/tmp/pytest-of-*`, que casa com um
    padrão default por acaso) — e `--basetemp` trocaria o resultado.
    """
    return Policy(allow_patterns=(str(tmp_path / "qoder-cli-1000"),
                                  str(tmp_path / "qoder-cli-1000" / "*")))


def item(tmp_path, name="qoder-cli-1000", size=4096, *, holder=(),
         mode=0o040755):
    """Um diretório real na SSD-emulada do tmp_path, velho e sem dono aberto."""
    src = tmp_path / name
    src.mkdir(parents=True, exist_ok=True)
    (src / "blob.bin").write_bytes(b"a" * size)
    old = NOW - 10 * DAY
    os.utime(src / "blob.bin", (old, old))
    os.utime(src, (old, old))
    entry = TmpfsEntry(path=str(src), name=src.name, volume="/tmp", kind="dir",
                       uid=os.getuid(), bytes=size, files=1, age_days=10.0,
                       is_mount_point=False, under_mount=False,
                       holder_pids=tuple(holder))
    plan = build_plan((VOL,), (entry,), sandbox_policy(tmp_path), now=NOW)
    return plan, plan.find(str(src)), src


def free(tmp_path, path, **entry_kw):
    """entry_fn padrão: re-derivado limpo, sem holder, sem monte."""
    return lambda p, **kw: TmpfsEntry(path=p, name=Path(p).name, volume="/tmp",
                                      kind="dir", uid=os.getuid(), bytes=4096,
                                      files=1, age_days=10.0, is_mount_point=False,
                                      under_mount=False, holder_pids=(), **entry_kw)


def roots(tmp_path):
    return [tmp_path, Path.home() / ".local"]


@pytest.fixture
def book(tmp_path):
    return Ledger(tmp_path / "ledger.jsonl")


@pytest.fixture
def audit(tmp_path):
    return AuditLog(tmp_path / "audit.jsonl")


def test_release_without_confirmation_writes_nothing(tmp_path, book, audit):
    plan, it, src = item(tmp_path)
    res = release.release_item(plan, it, ledger=book, audit=audit,
                               dest_root=tmp_path / "retida",
                               allowed_roots=roots(tmp_path))
    assert res.ok is False and "--confirmar" in res.reason
    assert (src / "blob.bin").exists()
    assert not (tmp_path / "retida").exists()
    assert book.retained_count() == 0


def test_release_copies_verifies_and_frees_the_bytes(tmp_path, book, audit):
    plan, it, src = item(tmp_path, size=8192)
    res = release.release_item(plan, it, ledger=book, audit=audit, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(tmp_path),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is True and res.freed_bytes == 8192
    assert not src.exists(), "a origem tem de sumir — é RAM liberada"
    stored = Path(res.stored)
    assert (stored / "blob.bin").read_bytes() == b"a" * 8192
    assert book.records()[res.entry_id].state == STATE_RELEASED
    assert book.retained_bytes() == 8192
    kinds = [r["kind"] for r in audit.tail(8)]
    assert "tmpfs.release" in kinds


def test_a_holder_that_appeared_after_the_plan_refuses_the_release(tmp_path, book):
    plan, it, src = item(tmp_path)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida",
                               entry_fn=free(tmp_path, holder_pids=(4242,)),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "fd aberto" in res.reason
    assert (src / "blob.bin").exists()


def test_a_mount_point_that_appeared_after_the_plan_refuses(tmp_path, book):
    plan, it, src = item(tmp_path)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida",
                               entry_fn=free(tmp_path, is_mount_point=True),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "montagem" in res.reason
    assert (src / "blob.bin").exists()


def test_release_refuses_when_the_destination_has_no_room(tmp_path, book):
    plan, it, src = item(tmp_path, size=6 * GIB)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(tmp_path),
                               statvfs_fn=lambda p: _vfs(1 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "destino" in res.reason
    assert (src / "blob.bin").exists()


def test_release_refuses_when_retention_would_exceed_the_budget(tmp_path, book):
    plan, it, src = item(tmp_path, size=1024)
    book.append(entry_id="velha", src="/tmp/velha", volume="/tmp",
                stored=str(tmp_path / "velha"), bytes=MAX_RETAINED_BYTES,
                sha256="x", age_days=1.0, matched_pattern="/tmp/tmp*",
                holder_pids=(), state=STATE_RELEASED, action_id="tmpfs.release",
                audit_event_id="e")
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(tmp_path),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "orçamento" in res.reason
    assert "velha" in res.reason, "a recusa tem de apontar a candidata a expire"


def test_dev_shm_is_measured_never_mutated(tmp_path, book):
    """R9: o guard já blacklista /dev; este teste prova que não afrouxamos nada.

    A allow-list é alargada de propósito aqui: sem um padrão casando, a recusa viria
    do filtro de padrão e o teste não diria nada sobre o guard.
    """
    assert "/dev/shm" not in release.MUTABLE_VOLUMES
    src = tmp_path / "shm" / "bloco"
    src.mkdir(parents=True)
    (src / "d.txt").write_text("x")
    entry = TmpfsEntry(path="/dev/shm/bloco", name="bloco", volume="/dev/shm",
                       kind="dir", uid=os.getuid(), bytes=1, files=1, age_days=9.0,
                       is_mount_point=False, under_mount=False, holder_pids=())
    plan = build_plan((TmpfsVolume("/dev/shm", "tmpfs", 8 * GIB, 0, 8 * GIB),),
                      (entry,), Policy(allow_patterns=("/dev/shm/*",)), now=NOW)
    res = release.release_item(plan, plan.find("/dev/shm/bloco"), ledger=book,
                               confirm=True, dest_root=tmp_path / "retida",
                               entry_fn=free(tmp_path),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "blacklisted prefix" in res.reason


def test_a_failed_removal_leaves_the_clone_recorded_as_partial(tmp_path, book, audit):
    plan, it, src = item(tmp_path)

    def boom(path):
        raise OSError(30, "Read-only file system")

    res = release.release_item(plan, it, ledger=book, audit=audit, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(tmp_path),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW, remove_fn=boom)
    assert res.ok is False
    assert (src / "blob.bin").exists(), "nada se perde: o original continua lá"
    assert Path(res.stored).exists(), "o clone existe e está registrado"
    record = book.records()[res.entry_id]
    assert record.state == STATE_PARTIAL
    assert book.retained_bytes() == record.bytes


def test_a_digest_mismatch_refuses_and_keeps_the_original(tmp_path, book, monkeypatch):
    plan, it, src = item(tmp_path)

    def diverged(path):
        # o clone (sob "retida") aparenta outro conteúdo que não a origem
        return ("b" * 64, 4096) if "retida" in str(path) else ("a" * 64, 4096)

    monkeypatch.setattr(release, "tree_digest", diverged)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(tmp_path),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok is False and "digest" in res.reason
    assert (src / "blob.bin").exists()
    assert not any((tmp_path / "retida").rglob("blob.bin")), "o clone divergente é desfeito"


def test_releasing_a_path_already_in_the_ledger_is_refused(tmp_path, book):
    plan, it, src = item(tmp_path)
    res = release.release_item(plan, it, ledger=book, confirm=True,
                               dest_root=tmp_path / "retida", entry_fn=free(tmp_path),
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               allowed_roots=roots(tmp_path), now=NOW)
    assert res.ok
    again = release.release_item(plan, it, ledger=book, confirm=True,
                                 dest_root=tmp_path / "retida", entry_fn=free(tmp_path),
                                 statvfs_fn=lambda p: _vfs(20 * GIB),
                                 allowed_roots=roots(tmp_path), now=NOW)
    assert again.ok is False and "ledger" in again.reason


def test_tree_digest_is_stable_and_order_independent(tmp_path):
    a = tmp_path / "a"
    (a / "sub").mkdir(parents=True)
    (a / "sub" / "b.txt").write_text("conteúdo")
    (a / "a.txt").write_text("abc")
    first, size = release.tree_digest(a)
    os.utime(a / "a.txt", (NOW, NOW))  # mtime não entra no digest
    second, _ = release.tree_digest(a)
    assert first == second and len(first) == 64
    assert size == len("abc") + len("conteúdo")


class _vfs:
    def __init__(self, avail):
        self.f_frsize = 4096
        self.f_bavail = avail // 4096
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_release.py -v`
Expected: FAIL — `ImportError: cannot import name 'release' from 'deck_wellness.actions.tmpfs'`.
Os testes de cima dependem de `PlanItem.matched` vir preenchido pelo `build_plan` (T5)
e de `plan.find(caminho)` aceitar o caminho absoluto como alça.

- [ ] **Step 3: Escrever a implementação mínima**

`actions/tmpfs/release.py` — parte 1 (resultados, ids, digest):

```python
"""Liberar RAM de um tmpfs: copiar para a SSD, verificar, só então apagar.

A ordem é a segurança: toda recusa acontece antes de qualquer escrita, o clone é
conferido contra a origem, e o ledger registra o estado intermediário (``partial``)
em vez de deixá-lo ser inferido. Se a remoção falhar, nada foi perdido.
"""
import hashlib
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ... import paths
from ...safely import guard
from ...safely.hashing import sha256_file
from ..disk import planner
from .inventory import TmpfsEntry, entry_at
from .holders import holder_index
from .ledger import (Ledger, LedgerRecord, MAX_RETAINED_BYTES, RETENTION_DAYS,
                     STATE_PARTIAL, STATE_RELEASED)
from .policy import classify
from ...core.tmpfs import WATCHED, read_mounts

KIND = "tmpfs.release"
# /dev/shm é medido e exibido, nunca mutável: o guard blacklista o prefixo /dev
MUTABLE_VOLUMES = ("/tmp", "/run/user/1000")


@dataclass(frozen=True)
class ReleaseResult:
    ok: bool
    entry_id: str
    reason: str
    bytes: int = 0
    stored: str = ""
    sha256: str = ""
    freed_bytes: int = 0

    def to_dict(self) -> dict:
        return {"ok": self.ok, "entry_id": self.entry_id, "reason": self.reason,
                "bytes": self.bytes, "stored": self.stored, "sha256": self.sha256,
                "freed_bytes": self.freed_bytes}


def _stamp(now: float) -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))


def _entry_id(now: float) -> str:
    return f"{int(now)}-{uuid.uuid4().hex[:8]}"


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:60] or "unnamed"


def default_allowed_roots(home=None) -> list:
    home = Path(home) if home else Path.home()
    return planner.default_allowed_roots(home) + [Path(p) for p in MUTABLE_VOLUMES]


def tree_digest(path: Path) -> tuple[str, int]:
    """Conteúdo e tamanho, em ordem estável: mtime e donos não mudam o digest."""
    root = Path(path)
    h = hashlib.sha256()
    total = 0
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            h.update(f"L:{rel}:{os.readlink(p)}\n".encode())
        elif p.is_file():
            total += p.stat().st_size
            h.update(f"F:{rel}:{sha256_file(p)}\n".encode())
    return h.hexdigest(), total


def _fresh_entry(path: str, *, volume: str = "", proc_root: str | None = None,
                 now: float | None = None) -> TmpfsEntry:
    """Re-derivado no momento da mutação: o plano pode estar superado."""
    mounts = read_mounts(proc_root)
    holders = holder_index(prefixes=(volume or path,), proc_root=proc_root)
    return entry_at(path, mounts, holders, volume=volume, now=now)
```

Parte 2 (o ato):

```python
def _refuse(entry_id: str, reason: str) -> ReleaseResult:
    return ReleaseResult(False, entry_id, reason)


def release_item(plan, item, *, ledger, dest_root=None, audit=None, confirm=False,
                 entry_fn=_fresh_entry, statvfs_fn=os.statvfs, now: float | None = None,
                 allowed_roots=None, remove_fn=None, proc_root=None) -> ReleaseResult:
    now = time.time() if now is None else now
    entry_id = _entry_id(now)
    src = Path(item.path)
    if not confirm:
        return _refuse(entry_id, "refused: liberar RAM exige --confirmar; "
                                 "nada foi alterado")

    held = ledger.find(item.path)
    if held is not None:
        return _refuse(entry_id, f"refused: {item.path} já está no ledger como "
                                 f"{held.state} ({held.entry_id}); a correção é "
                                 "manual (restore ou purge por id)")

    fresh = entry_fn(str(src), volume=item.volume, proc_root=proc_root, now=now)
    verdict = classify(fresh, plan.policy, now=now)
    if not verdict.ok:
        return _refuse(entry_id, f"refused: {verdict.reason}")

    roots = list(allowed_roots) if allowed_roots else default_allowed_roots()
    for check in (src,):
        guard_verdict = guard.validate_target(check, roots)
        if not guard_verdict.ok:
            return _refuse(entry_id, guard_verdict.reason)

    dest_root = Path(dest_root) if dest_root else paths.tmp_quarantine_dir()
    dest = dest_root / _stamp(now) / _sanitize(src.name)
    if not guard.validate_target(dest_root.parent, roots).ok:
        return _refuse(entry_id, "refused: o destino de retenção não é gravável "
                                 "por este usuário")

    if statvfs_fn(str(dest_root if dest_root.exists() else dest_root.parent)).f_bavail \
            * statvfs_fn(str(dest_root if dest_root.exists() else dest_root.parent)).f_frsize \
            < 2 * item.bytes:
        return _refuse(entry_id, f"refused: o destino não tem folga para copiar "
                                 f"{item.bytes} bytes antes de apagar a origem")

    if ledger.retained_bytes() + item.bytes > MAX_RETAINED_BYTES:
        oldest = ledger.oldest()
        return _refuse(entry_id, f"refused: reter mais {item.bytes} bytes estouraria "
                                 f"o orçamento de {MAX_RETAINED_BYTES}; a candidata "
                                 f"a expirar é {oldest.entry_id} ({oldest.src})")

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest, symlinks=True)
        else:
            shutil.copy2(src, dest)
    except OSError as err:
        _quiet_remove(dest)
        return _refuse(entry_id, f"refused: a cópia falhou ({err.strerror or err}); "
                                 "a origem está intacta")

    source_digest, _ = tree_digest(src)
    clone_digest, clone_bytes = tree_digest(dest)
    if source_digest != clone_digest:
        _quiet_remove(dest)
        return _refuse(entry_id, "refused: o digest do clone difere da origem; "
                                 "nada foi apagado")

    # o clone existe e o original ainda está lá: esse estado é registrado, não inferido
    ledger.append(**_fields(entry_id, item, fresh, dest, clone_digest, clone_bytes,
                            STATE_PARTIAL, audit))
    _sync_dir(dest.parent)

    remove = remove_fn or _remove
    try:
        remove(src)
    except OSError as err:
        _audit(audit, entry_id, STATE_PARTIAL, [str(src), str(dest)],
               plan_digest=plan.digest,
               error=f"a origem não pôde ser removida: {err.strerror or err}")
        return ReleaseResult(False, entry_id,
                             f"refused: o clone está em {dest} e registrado como "
                             f"partial; a origem não foi removida "
                             f"({err.strerror or err}); nada foi perdido",
                             bytes=item.bytes, stored=str(dest), sha256=clone_digest,
                             freed_bytes=0)

    ledger.append(**_fields(entry_id, item, fresh, dest, clone_digest, clone_bytes,
                            STATE_RELEASED, audit))
    _audit(audit, entry_id, STATE_RELEASED, [str(src), str(dest)],
           plan_digest=plan.digest)
    return ReleaseResult(True, entry_id, "ok", bytes=item.bytes, stored=str(dest),
                         sha256=clone_digest, freed_bytes=item.bytes)


def _sync_dir(path: Path) -> None:
    """fsync do diretório: é o que torna a linha `partial` verdadeira depois de um tombo."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
```

e os helpers de remoção/registro:

```python
def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _quiet_remove(path: Path) -> None:
    try:
        _remove(path)
    except OSError:
        pass  # o clone falho não apaga nada de valor; a recusa já foi reportada


def _fields(entry_id, item, fresh, dest, digest, size, state, audit) -> dict:
    event = ""
    if audit is not None:
        last = audit.tail(1)
        event = last[-1]["event_id"] if last else ""
    return {
        "entry_id": entry_id, "src": item.path, "volume": item.volume,
        "stored": str(dest), "bytes": size, "sha256": digest,
        "age_days": fresh.age_days, "matched_pattern": item.matched,
        "holder_pids": tuple(fresh.holder_pids), "state": state,
        "action_id": KIND, "audit_event_id": event,
    }


def _audit(audit, entry_id, outcome, targets, *, plan_digest=None, error=None) -> None:
    if audit is None:
        return
    audit.append(kind=KIND, action_id=entry_id, outcome=outcome, targets=targets,
                 risk="reversible", plan_digest=plan_digest, error=error)
```

A ordem das chamadas é o contrato: `_fields(..., STATE_PARTIAL)` e o `fsync` do
diretório vêm **antes** de `remove(src)`; a linha `released` vem **depois**. O
`audit_event_id` do ledger aponta para o evento de auditoria já escrito, por isso
`_fields` lê `audit.tail(1)` — se o auditor for `None`, o campo fica vazio em vez de
mentir.

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_release.py -v` → PASS (12).
Run: `.venv/bin/python -m pytest -q` → verde.

**Evidência de não-vacuidade:** `test_release_copies_verifies_and_frees_the_bytes`
falha se o `unlink` da origem for removido, e `test_a_failed_removal_leaves_the_clone_recorded_as_partial`
falha se a linha `partial` for escrita depois do `rmtree`. Trocar `f_bavail` por
`f_bfree` no checador de folga mata `test_release_refuses_when_the_destination_has_no_room`.

- [ ] **Step 5: Commit**

```bash
git add src/deck_wellness/actions/tmpfs/release.py tests/test_tmpfs_release.py
git commit -m "M7 T9: liberação reversível — copy, verify, ledger partial, unlink"
```

---

### Task 10: Devolver e expirar o que está retido

**Files:**
- Modify: `src/deck_wellness/actions/tmpfs/release.py` (acrescentar restore/expire)
- Test: `tests/test_tmpfs_release.py` (estender)

**Interfaces:**
- Consumes: `Ledger` (T8), `guard.validate_target`, `tree_digest`, `read_mounts`,
  `AuditLog`, `STATE_*` de `ledger.py`
- Produces: `RestoreResult(ok, entry_id, reason, bytes, restored_to)`,
  `ExpireResult(ok, reason, victims: tuple[str, ...], freed_bytes, errors: tuple[str, ...])`,
  `restore_item(record_or_id, *, ledger, audit=None, confirm=False,
  statvfs_fn=os.statvfs, allowed_roots=None, now=None, mounts_fn=read_mounts) -> RestoreResult`,
  `expire_over_budget(*, ledger, audit=None, days=RETENTION_DAYS,
  max_bytes=MAX_RETAINED_BYTES, confirm=False, irreversible=False, now=None,
  allowed_roots=None, remove_fn=_remove) -> ExpireResult`

- [ ] **Step 1: Escrever o teste que falha**

Acrescentar a `tests/test_tmpfs_release.py`:

```python
"""Devolver e expirar: os dois lados do ledger, com a mesma recusa primeiro.

Restaurar volta a copiar (SSD → tmpfs é outro cross-device) e só apaga o clone
depois do digest bater. Expirar é o único ato irreversível daqui, e por isso pede
duas flags.
"""


def stored(tmp_path, book, *, name="sessao-velha", size=4096, days=1.0, entry_id=None):
    """Coloca um item no ledger do jeito que release_item o deixaria."""
    payload = tmp_path / "retida" / "20261015T000000Z" / name
    payload.mkdir(parents=True)
    (payload / "blob.bin").write_bytes(b"a" * size)
    digest, total = release.tree_digest(payload)
    entry_id = entry_id or f"1700-{name}"
    # ts explícito: sem ele o "hoje" do relógio real deixaria a idade injetada sem efeito
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - days * DAY))
    book.append(ts=ts, entry_id=entry_id, src=str(tmp_path / name), volume="/tmp",
                stored=str(payload), bytes=total, sha256=digest, age_days=days,
                matched_pattern="/tmp/tmp*", holder_pids=(), state=STATE_RELEASED,
                action_id="tmpfs.release", audit_event_id="e")
    return entry_id, payload


def test_restore_without_confirmation_moves_nothing(tmp_path, book):
    entry_id, payload = stored(tmp_path, book)
    res = release.restore_item(entry_id, ledger=book, allowed_roots=[tmp_path])
    assert res.ok is False and "--confirmar" in res.reason
    assert payload.exists()


def test_restore_copies_back_and_frees_the_budget(tmp_path, book, audit):
    entry_id, payload = stored(tmp_path, book, size=8192)
    original = Path(book.records()[entry_id].src)
    res = release.restore_item(entry_id, ledger=book, audit=audit, confirm=True,
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               mounts_fn=lambda: (),
                               allowed_roots=[tmp_path], now=NOW)
    assert res.ok is True
    assert (original / "blob.bin").read_bytes() == b"a" * 8192
    assert not payload.exists(), "devolvido: o clone não pode ficar dos dois lados"
    assert book.records()[entry_id].state == "restored"
    assert book.retained_bytes() == 0


def test_restore_refuses_when_the_original_path_already_exists(tmp_path, book):
    entry_id, payload = stored(tmp_path, book)
    Path(book.records()[entry_id].src).mkdir(parents=True)
    res = release.restore_item(entry_id, ledger=book, confirm=True,
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               mounts_fn=lambda: (),
                               allowed_roots=[tmp_path], now=NOW)
    assert res.ok is False and "já existe" in res.reason
    assert payload.exists(), "nada é sobrescrito"


def test_restore_refuses_when_a_mount_appeared_in_the_way(tmp_path, book):
    """R1 vale nas duas direções: devolver para dentro de um monte é recusado."""
    entry_id, payload = stored(tmp_path, book)
    mounted = f"{tmp_path}/sessao-velha/novo-monte"
    res = release.restore_item(entry_id, ledger=book, confirm=True,
                               statvfs_fn=lambda p: _vfs(20 * GIB),
                               mounts_fn=lambda: ((mounted, "fuse.portal"),),
                               allowed_roots=[tmp_path], now=NOW)
    assert res.ok is False and "monte" in res.reason
    assert payload.exists(), "o retido continua na SSD"


def test_restore_refuses_when_the_volume_has_no_room(tmp_path, book):
    entry_id, payload = stored(tmp_path, book, size=6 * GIB)
    res = release.restore_item(entry_id, ledger=book, confirm=True,
                               statvfs_fn=lambda p: _vfs(1 * GIB),
                               mounts_fn=lambda: (),
                               allowed_roots=[tmp_path], now=NOW)
    assert res.ok is False and "espaço" in res.reason


def test_expire_dry_run_lists_exactly_what_it_would_delete(tmp_path, book):
    old, old_payload = stored(tmp_path, book, name="antiga", days=40)
    fresh, fresh_payload = stored(tmp_path, book, name="nova", days=1)
    res = release.expire_over_budget(ledger=book, now=NOW)
    assert res.ok is True
    assert res.victims == (old,)
    assert "antiga" in res.reason and "nova" not in res.reason
    assert old_payload.exists(), "dry-run não apaga nada"


def test_expire_needs_two_flags(tmp_path, book):
    stored(tmp_path, book, name="antiga", days=40)
    half = release.expire_over_budget(ledger=book, confirm=True, now=NOW)
    assert half.ok is False and "--irreversivel" in half.reason
    other = release.expire_over_budget(ledger=book, irreversible=True, now=NOW)
    assert other.ok is False and "--confirmar" in other.reason


def test_expire_removes_oldest_first_and_audits_each(tmp_path, book, audit):
    old, old_payload = stored(tmp_path, book, name="antiga", days=40, size=2048)
    fresh, fresh_payload = stored(tmp_path, book, name="nova", days=1, size=1024)
    res = release.expire_over_budget(ledger=book, audit=audit, confirm=True,
                                     irreversible=True, now=NOW,
                                     allowed_roots=[tmp_path])
    assert res.ok is True and res.victims == (old,)
    assert not old_payload.exists() and fresh_payload.exists()
    assert book.records()[old].state == "expired"
    assert book.retained_bytes() == 1024
    assert [r["kind"] for r in audit.tail(4)][-1] == "tmpfs.expire"


def test_expire_reports_the_bytes_it_frees_even_when_a_path_is_already_gone(tmp_path, book):
    gone, payload = stored(tmp_path, book, name="sumida", days=40, size=4096)
    shutil.rmtree(payload)
    res = release.expire_over_budget(ledger=book, confirm=True, irreversible=True,
                                     now=NOW, allowed_roots=[tmp_path])
    assert res.ok is True and res.victims == (gone,)
    assert res.errors, "o ledger sabia de um payload que não existe mais"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_release.py -v -k "restore or expire"`
Expected: FAIL — `AttributeError: module 'deck_wellness.actions.tmpfs.release' has no
attribute 'restore_item'`.

**Evidência de não-vacuidade neste passo:** `test_restore_refuses_when_a_mount_appeared_in_the_way`
é o que impede `_foreign_mount` de virar um `return None` confortável; se alguém
afrouxar o guard para `/tmp` sem mexer aqui, `test_dev_shm_is_measured_never_mutated`
ainda falha. As chamadas de sucesso injetam `mounts_fn=lambda: ()` de propósito: sem
isso a prova dependeria de o `tmp_path` do pytest cair sob o `/tmp` montado desta
máquina, e um `--basetemp` em outra partição inverteria o veredito sem bug nenhum.

- [ ] **Step 3: Escrever a implementação mínima**

Acrescentar a `release.py` (e somar `STATE_RESTORED`, `STATE_EXPIRED`, `STATE_DROPPED`
ao import de `.ledger` que já existe no topo do arquivo):

```python
RESTORE_KIND = "tmpfs.restore"
EXPIRE_KIND = "tmpfs.expire"


@dataclass(frozen=True)
class RestoreResult:
    ok: bool
    entry_id: str
    reason: str
    bytes: int = 0
    restored_to: str = ""


@dataclass(frozen=True)
class ExpireResult:
    ok: bool
    reason: str
    victims: tuple[str, ...] = ()
    freed_bytes: int = 0
    errors: tuple[str, ...] = ()


def _foreign_mount(path: str, mounts, volume: str) -> str | None:
    """O monte que *contém* o destino tem de ser o próprio volume, e nada pode
    estar montado *dentro* dele.

    É a R1 lida ao contrário: `/run` e `/run/user/1000` são ambos tmpfs montados, e
    um destino dentro do volume é legítimo; o que não é legítimo é o caminho cair
    sob um monte que não é o volume medido (um `private/tmp` de systemd, um portal
    novo) ou escrever por cima de um monte que apareceu dentro dele.
    """
    points = [m for m, _ in mounts]
    covering = [m for m in points if path == m or path.startswith(m + os.sep)]
    deepest = max(covering, key=len, default=None)
    if deepest is not None and deepest != volume:
        return deepest
    return next((m for m in points if m.startswith(path + os.sep)), None)


def restore_item(record_or_id, *, ledger, audit=None, confirm=False,
                 statvfs_fn=os.statvfs, allowed_roots=None,
                 now: float | None = None, mounts_fn=read_mounts) -> RestoreResult:
    now = time.time() if now is None else now
    record = record_or_id if isinstance(record_or_id, LedgerRecord) \
        else ledger.find(str(record_or_id))
    if record is None:
        return RestoreResult(False, str(record_or_id), "refused: entrada desconhecida "
                                                       "no ledger")
    if record.state not in (STATE_RELEASED, STATE_PARTIAL):
        return RestoreResult(False, record.entry_id,
                             f"refused: a entrada está {record.state}")
    entry_id = record.entry_id
    if not confirm:
        return RestoreResult(False, entry_id, "refused: restaurar exige --confirmar; "
                                              "nada foi alterado")

    original = Path(record.src)
    stored_path = Path(record.stored)
    if original.exists():
        return RestoreResult(False, entry_id,
                             f"refused: {original} já existe, nada é sobrescrito")
    if not stored_path.exists():
        return RestoreResult(False, entry_id, "refused: o payload retido sumiu da SSD")

    roots = list(allowed_roots) if allowed_roots else default_allowed_roots()
    verdict = guard.validate_target(original, roots)
    if not verdict.ok:
        return RestoreResult(False, entry_id, verdict.reason)
    mount = _foreign_mount(str(original.resolve()), mounts_fn(), record.volume)
    if mount is not None:
        return RestoreResult(False, entry_id,
                             f"refused: {original} cruza o monte {mount}, que não é "
                             f"o volume {record.volume}")

    volume = Path(record.volume)
    stat = statvfs_fn(str(volume))
    if stat.f_bavail * stat.f_frsize < record.bytes:
        return RestoreResult(False, entry_id,
                             f"refused: {volume} não tem espaço para devolver "
                             f"{record.bytes} bytes")

    try:
        original.parent.mkdir(parents=True, exist_ok=True)
        if stored_path.is_dir():
            shutil.copytree(stored_path, original, symlinks=True)
        else:
            shutil.copy2(stored_path, original)
    except OSError as err:
        _quiet_remove(original)
        return RestoreResult(False, entry_id, f"refused: a cópia de volta falhou "
                                              f"({err.strerror or err}); a SSD mantém o item")

    clone_digest, _ = tree_digest(stored_path)
    back_digest, size = tree_digest(original)
    if clone_digest != back_digest:
        _quiet_remove(original)
        return RestoreResult(False, entry_id,
                             "refused: o digest da volta difere do retido; o clone "
                             "da SSD foi mantido")

    _quiet_remove(stored_path)
    _transition(ledger, record, STATE_RESTORED, RESTORE_KIND, bytes=size)
    if audit is not None:
        audit.append(kind=RESTORE_KIND, action_id=entry_id, outcome="restored",
                     targets=[record.stored, str(original)], risk="reversible")
    return RestoreResult(True, entry_id, "ok", bytes=size, restored_to=str(original))


def _transition(ledger, record: LedgerRecord, state: str, action_id: str, **changes):
    """Uma linha nova, com o relógio de agora: o `ts` do registro é a origem, não a transição."""
    ledger.append(**{**record.to_dict(), **changes, "ts": "", "state": state,
                     "action_id": action_id, "audit_event_id": ""})


def expire_over_budget(*, ledger, audit=None, days: float = RETENTION_DAYS,
                       max_bytes: int = MAX_RETAINED_BYTES, confirm=False,
                       irreversible=False, now: float | None = None,
                       allowed_roots=None, remove_fn=_remove) -> ExpireResult:
    now = time.time() if now is None else now
    victims = ledger.over_budget(days=days, max_bytes=max_bytes, now=now)
    listed = ", ".join(f"{r.entry_id} ({r.bytes} bytes, {r.src})" for r in victims)

    if not victims:
        return ExpireResult(True, "nada vencido: a retenção cabe no orçamento "
                                  f"({days:g} d / {max_bytes} bytes)")
    if confirm != irreversible:
        missing = "--irreversivel" if confirm else "--confirmar"
        return ExpireResult(False, f"refused: expirar é irreversível e exige "
                                   f"--confirmar e --irreversivel (faltou {missing}); "
                                   f"nada foi alterado")
    if not confirm:
        # o dry-run devolve a lista que um --confirmar --irreversivel apagaria, no
        # mesmo formato: é assim que o usuário audita antes de confiar no ato
        return ExpireResult(True, f"dry-run: expiraria {len(victims)} entrada(s): "
                                  f"{listed}; nada foi alterado",
                                  tuple(r.entry_id for r in victims))

    roots = list(allowed_roots) if allowed_roots else default_allowed_roots()
    freed, errors, done = 0, [], []
    for record in victims:
        payload = Path(record.stored)
        verdict = guard.validate_target(payload, roots)
        if not verdict.ok:
            errors.append(f"{record.entry_id}: {verdict.reason}")
            continue
        try:
            if payload.exists():
                remove_fn(payload)
            else:
                errors.append(f"{record.entry_id}: o payload {payload} já não existia")
        except OSError as err:
            errors.append(f"{record.entry_id}: {err.strerror or err}")
            continue
        freed += record.bytes
        done.append(record.entry_id)
        _transition(ledger, record, STATE_EXPIRED, EXPIRE_KIND)
        if audit is not None:
            audit.append(kind=EXPIRE_KIND, action_id=record.entry_id,
                         outcome="expired", targets=[record.stored],
                         risk="irreversible")
    return ExpireResult(True, f"expiradas {len(done)} entrada(s), {freed} bytes "
                              f"liberados da SSD", tuple(done), freed, tuple(errors))
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_tmpfs_release.py -v` → PASS (todos).
Run: `.venv/bin/python -m pytest -q` → verde.

- [ ] **Step 5: Commit**

```bash
git add src/deck_wellness/actions/tmpfs/release.py tests/test_tmpfs_release.py
git commit -m "M7 T10: restore e expire — devolver com digest, expirar com duas flags"
```

---

### Task 11: CLI de leitura — `tmpfs status` e `tmpfs plan`

**Files:**
- Modify: `src/deck_wellness/cli.py:14-30` (imports + seams), `:38-105` (parser),
  antes de `_TUNE_HANDLERS` (handlers) e em `main()` (`ns.command == "tune"` é o vizinho)
- Test: `tests/test_cli_tmpfs.py`

**Interfaces:**
- Consumes: `core.tmpfs.watched_volumes`/`WATCHED`, `inventory.scan_volume`,
  `policy.Policy`/`DEFAULT_ALLOW_PATTERNS`, `plan.build_plan`, `planner.fmt_bytes`
- Produces: aliases monkeypatcháveis `_tmpfs_volumes = watched_volumes` e
  `_tmpfs_now = time.time`; `_tmpfs_roots(raiz=None) -> list[str]`;
  `tmpfs_policy(permitir=(), dias=None, volumes=None) -> Policy`;
  `_scan_tmpfs(raiz=None, prazo=10.0) -> (volumes, entries)`;
  `_build_tmpfs_plan(raiz=None, permitir=(), dias=None, prazo=10.0) -> TmpfsPlan`;
  `_TMPFS_HANDLERS` com `status`/`plan`

- [ ] **Step 1: Escrever o teste que falha**

```python
"""A face headless do M7: o que quebra quando o desktop é o problema tem de funcionar no TTY.

Os testes trocam o volume real pelo de `tmp_path`: o CLI varre, planeja e formata de
verdade, só o chão é falso. `fake_proc` garante montes vazios e nenhum holder.
"""
import json
import os
import time

import pytest

from deck_wellness import cli
from deck_wellness.cli import main
from deck_wellness.core.tmpfs import TmpfsVolume

DAY = 86_400
GIB = 1024 ** 3


@pytest.fixture
def fake_tmp(tmp_path, fake_proc, monkeypatch):
    """Um tmpfs de mentira montado em `tmp_path/tmp`, com as três sortes de item.

    As unidades são os **filhos diretos** do volume — é o que `inventory` mede, e é
    o que uma ferramenta recria sozinha (`/tmp/qoder-cli-1000`, não a sessão dentro
    dela). Duas trocas fazem o chão falso virar um host: `WATCHED` passa a ser a
    raiz de `tmp_path`, e os padrões default passam a ser os caminhos reais dela —
    sem isso nada num chão temporário casaria com a allow-list do `/tmp` verdadeiro.
    """
    root = tmp_path / "tmp"
    eligible = root / "qoder-cli-1000"
    stranger = root / "de-outro-lugar"
    young = root / "pytest-of-misael"
    for item in (eligible, stranger, young):
        item.mkdir(parents=True)
    (eligible / "blob.bin").write_bytes(b"a" * 4096)
    (stranger / "velho.bin").write_bytes(b"c" * 1024)
    (young / "vivo.bin").write_bytes(b"b" * 2048)
    old = time.time() - 10 * DAY
    for item, name in ((eligible, "blob.bin"), (stranger, "velho.bin")):
        os.utime(item / name, (old, old))
        os.utime(item, (old, old))
    volume = TmpfsVolume(str(root), "tmpfs", 8 * GIB, 1 * GIB, 7 * GIB)
    monkeypatch.setattr(cli, "_tmpfs_volumes", lambda **kw: (volume,))
    monkeypatch.setattr(cli, "WATCHED", (str(root),))
    monkeypatch.setattr(cli.tmpfs_policy_mod, "DEFAULT_ALLOW_PATTERNS",
                        (str(eligible), str(young)))
    return root, volume


def test_tmpfs_status_prints_each_watched_volume(fake_tmp, capsys):
    root, volume = fake_tmp
    code = main(["tmpfs", "status"])
    out = capsys.readouterr().out
    assert code == 0
    assert str(root) in out
    assert "8,0 GB" in out and "1,0 GB" in out


def test_tmpfs_status_json_is_one_parseable_line(fake_tmp, capsys):
    main(["tmpfs", "status", "--json"])
    raw = capsys.readouterr().out
    assert len(raw.strip().splitlines()) == 1
    payload = json.loads(raw)
    assert payload["volumes"][0]["used_pct"] == 12.5
    assert payload["worst"]["path"] == str(fake_tmp[0])


def test_tmpfs_plan_is_a_dry_run_that_names_both_sides(fake_tmp, capsys):
    root, _ = fake_tmp
    code = main(["tmpfs", "plan"])
    captured = capsys.readouterr()
    assert code == 0
    assert "recuperáveis 4,0 KB em 1 item(ns); protegidos 2" in captured.out
    assert "piso" in captured.out                 # pytest-of-misael: novo demais
    assert "fora da allow-list" in captured.out   # de-outro-lugar: sem padrão
    assert "impressão" in captured.out
    assert (root / "pytest-of-misael" / "vivo.bin").exists()


def test_tmpfs_plan_json_reconciles_and_carries_a_digest(fake_tmp, capsys):
    main(["tmpfs", "plan", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["reclaimable"]) + len(payload["protected"]) == \
        payload["scanned_entries"] == 3
    assert len(payload["digest"]) == 64
    assert len(payload["reclaimable"]) == 1 and len(payload["protected"]) == 2, \
        "o plano tem de listar os dois lados"


def test_tmpfs_plan_only_takes_roots_from_the_watch_list(capsys):
    code = main(["tmpfs", "plan", "--raiz", "/home/misael"])
    assert code == cli.EXIT_REFUSED
    assert "watch-list" in capsys.readouterr().err


def test_tmpfs_plan_permitira_adds_a_pattern_and_flips_the_item(fake_tmp, capsys):
    root, _ = fake_tmp
    stranger = str(root / "de-outro-lugar")
    main(["tmpfs", "plan"])
    assert "fora da allow-list" in capsys.readouterr().out
    main(["tmpfs", "plan", "--permitir", stranger])
    out = capsys.readouterr().out
    assert "fora da allow-list" not in out
    assert f"· {stranger} ·" in out, "o item entrou na lista de liberáveis"


def test_unknown_tmpfs_subcommand_is_refused(capsys):
    code = main(["tmpfs", "limpar-tudo"])
    assert code == cli.EXIT_NEEDS_CONFIRM
    assert "desconhecido" in capsys.readouterr().err
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_cli_tmpfs.py -v`
Expected: FAIL — `refused: comando desconhecido: tmpfs` / `SystemExit: 2`, porque o
subcomando ainda não existe no parser.

- [ ] **Step 3: Escrever a implementação mínima**

Imports e seams no topo de `cli.py` (junto de `_sleep = time.sleep`, linha 30):

```python
from .actions.tmpfs import inventory, plan as tmpfs_plan, policy as tmpfs_policy_mod
from .core.tmpfs import WATCHED, watched_volumes

_tmpfs_volumes = watched_volumes
_tmpfs_now = time.time
```

No `build_parser()`, depois do bloco `tune`:

```python
    tmpfs = commands.add_parser(
        "tmpfs", help="espaços em RAM (/tmp, /run/user, /dev/shm): ver e liberar com confirmação")
    tmpfs_sub = tmpfs.add_subparsers(dest="sub", required=True)

    status = tmpfs_sub.add_parser("status", help="capacidade e pressão dos volumes (não escreve)")
    status.add_argument("--json", action="store_true", help="saída para máquinas")
    status.add_argument("--raiz", action="append", default=None,
                        help="restringe a um volume da watch-list (repetível)")

    plan = tmpfs_sub.add_parser("plan", help="dry-run: elegíveis e protegidos (nada muda)")
    plan.add_argument("--json", action="store_true", help="saída para máquinas")
    plan.add_argument("--raiz", action="append", default=None,
                      help="restringe a um volume da watch-list (repetível)")
    plan.add_argument("--dias", type=float, default=None,
                      help=f"idade mínima em dias (padrão {tmpfs_policy_mod.MIN_AGE_DAYS:g})")
    plan.add_argument("--permitir", action="append", default=[], dest="permitir",
                      help="padrão extra de allow-list, item por item")
    plan.add_argument("--prazo", type=float, default=10.0,
                      help="segundos máximos de varredura por volume")
```

Os handlers:

```python
def _tmpfs_roots(raiz=None) -> list:
    """`--raiz` só aceita o que a watch-list conhece: /run e /run/credentials não."""
    wanted = list(raiz or WATCHED)
    outside = [w for w in wanted if w not in WATCHED]
    if outside:
        sys.stderr.write("refused: fora da watch-list: " + ", ".join(outside) +
                         " (o que não medimos não mutamos)\n")
    return [w for w in wanted if w in WATCHED]


def tmpfs_policy(permitir=(), dias=None, volumes=None) -> tmpfs_policy_mod.Policy:
    """O escopo de volume segue o que foi medido: em produção `_tmpfs_roots` já
    garantiu que é watch-list, e num teste o chão falso é o próprio volume."""
    allow = tuple(tmpfs_policy_mod.DEFAULT_ALLOW_PATTERNS) + tuple(permitir or ())
    return tmpfs_policy_mod.Policy(
        allow_patterns=allow,
        min_age_days=tmpfs_policy_mod.MIN_AGE_DAYS if dias is None else dias,
        volumes=tuple(volumes) if volumes else tmpfs_policy_mod.WATCHED)


def _scan_tmpfs(raiz=None, prazo: float = 10.0):
    volumes = [v for v in _tmpfs_volumes() if v.path in _tmpfs_roots(raiz)]
    entries = []
    for volume in volumes:
        _, _, found = inventory.scan_volume(volume, now=_tmpfs_now(),
                                            deadline_s=prazo)
        entries.extend(found)
    return volumes, entries


def _build_tmpfs_plan(raiz=None, permitir=(), dias=None, prazo: float = 10.0):
    """A única porta para um plano: leitura + política, sem mutação nenhuma."""
    volumes, entries = _scan_tmpfs(raiz, prazo)
    plan = tmpfs_plan.build_plan(volumes, entries,
                                 tmpfs_policy(permitir, dias, [v.path for v in volumes]),
                                 now=_tmpfs_now())
    return plan


def _cmd_tmpfs_status(args) -> int:
    volumes = [v for v in _tmpfs_volumes() if v.path in _tmpfs_roots(args.raiz)]
    if not volumes:
        sys.stderr.write("refused: nenhum volume da watch-list montado "
                         "(nem /tmp, nem /run/user/1000, nem /dev/shm)\n")
        return EXIT_REFUSED
    if args.json:
        print(json.dumps({"volumes": [v.to_dict() for v in volumes],
                          "worst": max(volumes, key=lambda v: v.used_frac).to_dict()},
                         ensure_ascii=False))
        return EXIT_OK
    print("Espaços temporários (são RAM; seco aqui = ENOSPC no agente):")
    for volume in sorted(volumes, key=lambda v: v.used_frac, reverse=True):
        print(f"{volume.path} · {volume.fs_type} · {planner.fmt_bytes(volume.total_bytes)} · "
              f"usado {planner.fmt_bytes(volume.used_bytes)} · "
              f"livre {planner.fmt_bytes(volume.avail_bytes)} · "
              f"{round(volume.used_frac * 100)}%")
    worst = max(volumes, key=lambda v: v.used_frac)
    print(f"\npior volume: {worst.path} a {round(worst.used_frac * 100)}%")
    print("Para ver o plano: deck-wellness tmpfs plan (dry-run, nada muda)")
    return EXIT_OK


def _cmd_tmpfs_plan(args) -> int:
    result = _build_tmpfs_plan(args.raiz, args.permitir, args.dias, args.prazo)
    if not result.volumes:
        sys.stderr.write("refused: nenhum volume da watch-list montado\n")
        return EXIT_REFUSED
    if args.json:
        print(result.to_json())
        return EXIT_OK
    print("Plano de liberação (dry-run: nada foi movido):")
    print(f"volumes: {', '.join(v.path for v in result.volumes)}")
    print(f"recuperáveis {planner.fmt_bytes(result.total_bytes)} em "
          f"{len(result.reclaimable)} item(ns); protegidos {len(result.protected)}")
    for item in result.reclaimable:
        print(f"  · {item.path} · {planner.fmt_bytes(item.bytes)} · "
              f"{item.age_days:.0f} d · padrão {item.matched}")
    for item in result.protected:
        print(f"  protegido: {item.path} · {item.reason}")
    print(f"\nscanned {result.scanned_entries} item(ns) · "
          f"{planner.fmt_bytes(result.scanned_bytes)} lidos · "
          f"impressão: {result.digest[:16]}")
    if result.scanned_entries != len(result.reclaimable) + len(result.protected):
        sys.stderr.write("aviso: a contagem não fechou — o plano é incompleto\n")
        return EXIT_REFUSED
    print("\nPara liberar um item: deck-wellness tmpfs release <caminho> --confirmar "
          "(vai para a SSD e volta com tmpfs restore)")
    return EXIT_OK


_TMPFS_HANDLERS = {
    "status": _cmd_tmpfs_status,
    "plan": _cmd_tmpfs_plan,
}
```

Em `main()`, ao lado do ramo do `tune`:

```python
    if ns.command == "tmpfs":
        handler = _TMPFS_HANDLERS.get(ns.sub)
        if handler is None:
            sys.stderr.write(f"refused: subcomando desconhecido: {ns.sub}\n")
            return EXIT_NEEDS_CONFIRM
        return handler(ns)
```

e a string de uso do `refused: comando desconhecido` passa a dizer
`[disk …] [orphans] [groups] [tune …] [tmpfs status|plan|release|restore|ledger|expire]`.

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_cli_tmpfs.py -v` → PASS (7).
Run: `.venv/bin/python -m pytest -q` → verde (o `test_layers` continua provando que
importar `deck_wellness.cli` não carrega Qt).

- [ ] **Step 5: Commit**

```bash
git add src/deck_wellness/cli.py tests/test_cli_tmpfs.py
git commit -m "M7 T11: tmpfs status/plan na CLI — plano refusal-first num TTY"
```

---

### Task 12: CLI de mutação — `release`, `restore`, `ledger`, `expire`

**Files:**
- Modify: `src/deck_wellness/cli.py` (parser + 4 handlers + `_TMPFS_HANDLERS`)
- Test: `tests/test_cli_tmpfs.py` (estender)

**Interfaces:**
- Consumes: `tmpfs_plan.build_plan`/`_scan_tmpfs` (T11), `release.release_item`,
  `release.restore_item`, `release.expire_over_budget`, `ledger.Ledger`,
  `paths.tmp_quarantine_dir()`/`tmp_ledger_path()`, `planner.default_allowed_roots`
- Produces: seams `_tmpfs_ledger()`, `_tmpfs_audit()`, `_tmpfs_dest()`,
  `_tmpfs_guard_roots()`, e entradas em `_TMPFS_HANDLERS`

- [ ] **Step 1: Escrever o teste que falha**

Somar ao topo de `tests/test_cli_tmpfs.py`:
`from deck_wellness.actions.tmpfs.ledger import MAX_RETAINED_BYTES, Ledger`.

```python
def tmpfs_env(tmp_path, fake_tmp, monkeypatch):
    """CLI e atos no mesmo chão falso: ledger, quarentena e raízes do guard."""
    root, volume = fake_tmp
    monkeypatch.setattr(cli, "_tmpfs_ledger",
                        lambda: Ledger(tmp_path / "state" / "tmp-ledger.jsonl"))
    monkeypatch.setattr(cli, "_tmpfs_dest", lambda: tmp_path / "retida")
    monkeypatch.setattr(cli, "_tmpfs_guard_roots", lambda: [tmp_path])
    monkeypatch.setattr(cli, "_tmpfs_now", lambda: time.time())
    return root, volume


def test_release_refuses_without_confirmation(tmp_path, fake_tmp, monkeypatch, capsys):
    tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    target = str(fake_tmp[0] / "qoder-cli-1000")
    code = main(["tmpfs", "release", target])
    assert code == cli.EXIT_NEEDS_CONFIRM
    assert "--confirmar" in capsys.readouterr().err


def test_release_moves_the_item_and_prints_the_entry_id(tmp_path, fake_tmp, monkeypatch,
                                                        capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    target = str(root / "qoder-cli-1000")
    code = main(["tmpfs", "release", target, "--confirmar"])
    out = capsys.readouterr().out
    assert code == 0
    assert "liberado" in out
    assert not (root / "qoder-cli-1000").exists()
    assert any((tmp_path / "retida").rglob("blob.bin"))
    assert "tmpfs restore" in out, "a saída tem de dizer como desfazer"


def test_release_of_a_protected_item_is_refused_with_its_reason(tmp_path, fake_tmp,
                                                                monkeypatch, capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    code = main(["tmpfs", "release", str(root / "pytest-of-misael"), "--confirmar"])
    assert code == cli.EXIT_REFUSED
    assert "refused" in capsys.readouterr().err


def test_restore_without_confirmation_moves_nothing(tmp_path, fake_tmp, monkeypatch,
                                                    capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    target = str(root / "qoder-cli-1000")
    main(["tmpfs", "release", target, "--confirmar"])
    entry_id = _ledger_records(tmp_path)[0]["entry_id"]
    code = main(["tmpfs", "restore", entry_id])
    assert code == cli.EXIT_NEEDS_CONFIRM
    assert "--confirmar" in capsys.readouterr().err


def test_restore_returns_the_item_to_its_original_path(tmp_path, fake_tmp, monkeypatch,
                                                       capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    target = str(root / "qoder-cli-1000")
    main(["tmpfs", "release", target, "--confirmar"])
    entry_id = _ledger_records(tmp_path)[0]["entry_id"]
    code = main(["tmpfs", "restore", entry_id, "--confirmar"])
    assert code == 0
    assert (target / "blob.bin").read_bytes() == b"a" * 4096
    assert not any((tmp_path / "retida").rglob("blob.bin"))


def test_ledger_prints_ram_freed_against_ssd_retained(tmp_path, fake_tmp, monkeypatch,
                                                       capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar"])
    capsys.readouterr()
    code = main(["tmpfs", "ledger"])
    out = capsys.readouterr().out
    assert code == 0
    assert "retido" in out and "qoder-cli-1000" in out
    assert "orçamento" in out


def test_ledger_json_is_one_line_with_the_budget(tmp_path, fake_tmp, monkeypatch, capsys):
    tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    main(["tmpfs", "ledger", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["records"] == []
    assert payload["budget"]["retained_bytes"] == 0
    assert payload["budget"]["slack_bytes"] == MAX_RETAINED_BYTES


def test_expire_requires_both_flags(tmp_path, fake_tmp, monkeypatch, capsys):
    tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    code = main(["tmpfs", "expire", "--confirmar"])
    assert code == cli.EXIT_NEEDS_CONFIRM
    assert "--irreversivel" in capsys.readouterr().err


def test_expire_dry_run_then_confirm(tmp_path, fake_tmp, monkeypatch, capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar"])
    capsys.readouterr()
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 40 * DAY))
    path = tmp_path / "state" / "tmp-ledger.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        row["ts"] = old
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    code = main(["tmpfs", "expire", "--dias", "14"])
    listed = capsys.readouterr().out
    assert code == 0 and "dry-run" in listed
    assert any((tmp_path / "retida").rglob("blob.bin")), "dry-run não apaga"

    code = main(["tmpfs", "expire", "--dias", "14", "--confirmar", "--irreversivel"])
    assert code == 0
    assert not any((tmp_path / "retida").rglob("blob.bin"))


def _ledger_records(tmp_path) -> list:
    """Lê o registro: a asserção cai sobre o arquivo, não sobre uma redação do teste."""
    path = tmp_path / "state" / "tmp-ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_cli_tmpfs.py -v -k "release or restore or ledger or expire"`
Expected: FAIL — `refused: subcomando desconhecido: release` (exit 2) em todos.

- [ ] **Step 3: Escrever a implementação mínima**

Seams ao lado dos da tarefa anterior:

```python
from . import paths
from .actions.tmpfs import release as tmpfs_release
from .actions.tmpfs.ledger import MAX_RETAINED_BYTES, RETENTION_DAYS, Ledger


def _tmpfs_ledger() -> Ledger:
    return Ledger()


def _tmpfs_audit() -> AuditLog:
    return AuditLog()


def _tmpfs_dest() -> Path:
    return paths.tmp_quarantine_dir()


def _tmpfs_guard_roots() -> list:
    return tmpfs_release.default_allowed_roots()
```

Funções, não `lambda`: o traceback de um filho que morreu no meio de uma liberação
precisa apontar para um nome com linha.

Parser (dentro do bloco `tmpfs`, depois de `plan`):

```python
    for name, help_text in (
        ("release", "liberar um item para a SSD: copy → verify → unlink, com ledger"),
        ("restore", "devolver um item do ledger ao lugar original"),
    ):
        sub = tmpfs_sub.add_parser(name, help=help_text)
        sub.add_argument("target", help="caminho (release) ou id do ledger (restore)")
        sub.add_argument("--confirmar", action="store_true", help="aceita esta mutação")
        sub.add_argument("--prazo", type=float, default=10.0,
                         help="segundos máximos de varredura por volume")

    ledger = tmpfs_sub.add_parser("ledger", help="o que está retido e o orçamento")
    ledger.add_argument("--json", action="store_true", help="saída para máquinas")

    expire = tmpfs_sub.add_parser("expire", help="seca a retenção que estourou o orçamento")
    expire.add_argument("--dias", type=float, default=RETENTION_DAYS,
                        help="idade acima da qual a retenção vence")
    expire.add_argument("--max-bytes", type=int, default=MAX_RETAINED_BYTES,
                        help="teto de bytes retidos na SSD")
    expire.add_argument("--confirmar", action="store_true", help="apaga em vez de listar")
    expire.add_argument("--irreversivel", action="store_true",
                        help="aceita que o conteúdo retido não voltará")
```

Handlers:

```python
def _cmd_tmpfs_release(args) -> int:
    # o plano é refeito no ato: só se libera o que a política classificou agora
    plan = _build_tmpfs_plan(prazo=args.prazo)
    item = plan.find(args.target)
    if item is None:
        sys.stderr.write(f"refused: {args.target} não está no plano — só se libera o "
                         "que o plano classificou (deck-wellness tmpfs plan)\n")
        return EXIT_REFUSED
    result = tmpfs_release.release_item(
        plan, item, ledger=_tmpfs_ledger(), audit=_tmpfs_audit(),
        confirm=args.confirmar, dest_root=_tmpfs_dest(),
        allowed_roots=_tmpfs_guard_roots(), now=_tmpfs_now())
    if not result.ok:
        sys.stderr.write(f"{result.reason}\n")
        return EXIT_NEEDS_CONFIRM if not args.confirmar else EXIT_REFUSED
    print(f"liberado: {planner.fmt_bytes(result.freed_bytes)} de RAM · "
          f"{item.path}")
    print(f"   retido em: {result.stored}")
    print(f"   sha256:    {result.sha256}")
    print(f"   id:        {result.entry_id}")
    print(f"   devolve:   deck-wellness tmpfs restore {result.entry_id} --confirmar")
    return EXIT_OK


def _cmd_tmpfs_restore(args) -> int:
    if not args.confirmar:
        sys.stderr.write("refused: restaurar regrava no tmpfs e exige --confirmar "
                         "(nada foi alterado)\n")
        return EXIT_NEEDS_CONFIRM
    result = tmpfs_release.restore_item(
        args.target, ledger=_tmpfs_ledger(), audit=_tmpfs_audit(), confirm=True,
        allowed_roots=_tmpfs_guard_roots(), now=_tmpfs_now())
    if not result.ok:
        sys.stderr.write(f"{result.reason}\n")
        return EXIT_REFUSED
    print(f"devolvido: {planner.fmt_bytes(result.bytes)} para {result.restored_to}")
    return EXIT_OK


def _cmd_tmpfs_ledger(args) -> int:
    book = _tmpfs_ledger()
    view = book.budget_view(now=_tmpfs_now())
    records = [r.to_dict() for r in book.records().values()]
    if args.json:
        print(json.dumps({"records": records, "budget": {
            "retained_bytes": view.retained_bytes, "retained_count": view.retained_count,
            "oldest_days": round(view.oldest_days, 1), "slack_bytes": view.slack_bytes,
            "freed_bytes": view.freed_bytes, "by_volume": view.by_volume,
            "max_bytes": MAX_RETAINED_BYTES, "days": RETENTION_DAYS}},
            ensure_ascii=False))
        return EXIT_OK
    if not records:
        print("ledger vazio: nada retido na SSD")
        return EXIT_OK
    for record in sorted(records, key=lambda r: r["ts"]):
        print(f"{record['entry_id']} · {record['state']} · "
              f"{planner.fmt_bytes(record['bytes'])} · {record['src']}")
    print(f"\nretido na SSD: {planner.fmt_bytes(view.retained_bytes)} em "
          f"{view.retained_count} item(ns) · mais velho {view.oldest_days:.1f} d")
    print(f"RAM liberada de fato: {planner.fmt_bytes(view.freed_bytes)} · "
          f"folga do orçamento: {planner.fmt_bytes(view.slack_bytes)} "
          f"de {planner.fmt_bytes(MAX_RETAINED_BYTES)}")
    if view.retained_bytes > MAX_RETAINED_BYTES:
        sys.stderr.write("aviso: a retenção estourou o orçamento — rode "
                         "deck-wellness tmpfs expire\n")
    return EXIT_OK


def _cmd_tmpfs_expire(args) -> int:
    result = tmpfs_release.expire_over_budget(
        ledger=_tmpfs_ledger(), audit=_tmpfs_audit(), days=args.dias,
        max_bytes=args.max_bytes, confirm=args.confirmar,
        irreversible=args.irreversivel, now=_tmpfs_now(),
        allowed_roots=_tmpfs_guard_roots())
    if not result.ok:
        sys.stderr.write(f"{result.reason}\n")
        return EXIT_NEEDS_CONFIRM
    print(result.reason)
    for line in result.errors:
        print(f"aviso: {line}")
    if result.freed_bytes:
        print(f"expirado: {planner.fmt_bytes(result.freed_bytes)} da SSD")
    return EXIT_OK


_TMPFS_HANDLERS.update({
    "release": _cmd_tmpfs_release,
    "restore": _cmd_tmpfs_restore,
    "ledger": _cmd_tmpfs_ledger,
    "expire": _cmd_tmpfs_expire,
})
```

**Evidência de não-vacuidade:** `test_release_moves_the_item_and_prints_the_entry_id`
falha se o handler chamar `release_item` com `confirm=args.confirmar` invertido, e
`test_expire_requires_both_flags` falha se `expire_over_budget` aceitar uma flag só.
Nenhum teste toca `/tmp`, `/run/user/1000` ou `/dev/shm` reais: `fake_tmp` troca o
volume por `tmp_path` e `tmpfs_env` troca ledger, destino e raízes do guard.

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_cli_tmpfs.py -v` → PASS (todos).
Run: `.venv/bin/python -m pytest -q` → verde.

- [ ] **Step 5: Commit**

```bash
git add src/deck_wellness/cli.py tests/test_cli_tmpfs.py
git commit -m "M7 T12: tmpfs release/restore/ledger/expire na CLI — mutação com duas flags"
```

---

### Task 13: Quinta aba "temporários" — a janela só fala com o filho em JSON

**Files:**
- Create: `src/deck_wellness/ui/tmpfs_tab.py`
- Modify: `src/deck_wellness/cli.py` (`--json` em release/restore/expire + um ramo de saída em cada handler)
- Modify: `src/deck_wellness/ui/tune_jobs.py:21` (`MUTATING`)
- Modify: `src/deck_wellness/ui/main_window.py` (docstring, imports, `TABS`, `TMPFS_TIMEOUT_MS`, `__init__`, `apply_snapshot`, `closeEvent`)
- Test: `tests/test_ui_tmpfs_tab.py` (novo), `tests/test_ui_main_window_tabs.py` (estender), `tests/test_ui_tune_jobs.py` (estender), `tests/test_cli_tmpfs.py` (estender), `tests/test_layers.py` (estender)

**Interfaces:**
- Consumes: `TmpfsVolume` (T1), `trend.eta_hours` (T6), `TmpfsPlan.to_dict()`/`PlanItem.to_dict()` (T5), `Ledger.budget_view` via o payload JSON do T12, `release_item.to_dict()` (T9), `planner.fmt_bytes`, `TuneJobs.run(acao, alvo, confirm=, done=)` e `argv_factory(acao, alvo, confirm)`
- Produces: `argv_for(acao, target="", confirm=False) -> list[str]`, `JSON_ACTIONS`, `VOLUME_COLUMNS`, `PLAN_COLUMNS`, `LEDGER_COLUMNS`, `TmpfsTab(jobs=…, confirm_fn=None, parent=None)` com `show_volumes(volumes, ts=None)`, `show_plan(payload)`, `show_ledger(payload)`, `refresh()`, `release_clicked(row)`, `restore_clicked(row)`, `expire_clicked()`, atributos `volume_rows/plan_rows/ledger_rows/budget/release_buttons/restore_buttons/pressure/summary/budget_label/status`; `MainWindow(..., tmpfs_jobs=None)` com atributo `.tmpfs`

- [ ] **Step 1: Escrever os testes que falham — a aba**

```python
"""M7 na janela: a aba mostra o que o filho respondeu e não move nada sozinha.

O contrato é o do `disk_tab`: entram tuplas planas vindas do poller, sai argv de
filho matável. Nada aqui abre /proc, varre árvore ou escreve byte — e o ETA é
extrapolação das amostras que a própria aba guardou, nunca uma promessa.
"""
import sys

import pytest

from deck_wellness.core.tmpfs import TmpfsVolume
from deck_wellness.ui.tmpfs_tab import (LEDGER_COLUMNS, PLAN_COLUMNS, VOLUME_COLUMNS,
                                        TmpfsTab, argv_for)

pytest.importorskip("PySide6")

GIB = 1024 ** 3


def col(columns, key):
    return [k for k, _ in columns].index(key)


class FakeJobs:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def run(self, acao, target, *, confirm=False, done):
        self.calls.append((acao, target, confirm))
        done(self.answers(acao, target))

    def shutdown(self):
        self.calls.append(("shutdown", "*", False))


def plan_item(**over):
    base = {"item_id": "a" * 16, "path": "/tmp/qoder-cli-1000", "name": "qoder-cli-1000",
            "volume": "/tmp", "kind": "dir", "uid": 1000, "bytes": 4096, "files": 1,
            "age_days": 10.0, "holder_pids": [1234], "ok": True,
            "reason": "liberável: casado com /tmp/qoder-cli-1000",
            "matched": "/tmp/qoder-cli-1000", "truncated": False, "errors": []}
    base.update(over)
    return base


def plan_payload(acao="plan", target=""):
    refused = plan_item(item_id="b" * 16, path="/tmp/.X11-unix", name=".X11-unix",
                        ok=False, reason="refused: fora da allow-list de sujeira "
                                         "de agente", matched=None, holder_pids=[],
                        bytes=2048, files=1, age_days=9.0)
    return {"acao": acao, "ok": True, "exit": 0, "generated_at": "2026-10-15T00:00:00Z",
            "volumes": [], "policy": {},
            "reclaimable": [plan_item()], "protected": [refused],
            "total_bytes": 4096, "scanned_entries": 2, "scanned_bytes": 6144,
            "digest": "d" * 64, "errors": []}


def ledger_payload(acao="ledger", target=""):
    return {"acao": acao, "ok": True, "exit": 0,
            "records": [{"ts": "2026-10-01T00:00:00Z", "entry_id": "1700-abc",
                         "src": "/tmp/qoder-cli-1000", "volume": "/tmp",
                         "stored": "/home/u/.local/share/deck-wellness/tmp-quarantine/x",
                         "bytes": 4096, "sha256": "a" * 64, "age_days": 30.0,
                         "matched_pattern": "/tmp/qoder-cli-1000", "holder_pids": [1234],
                         "state": "released", "action_id": "tmpfs.release",
                         "audit_event_id": "e" * 32}],
            "budget": {"retained_bytes": 4096, "retained_count": 1, "oldest_days": 30.0,
                       "slack_bytes": 5 * GIB, "freed_bytes": 4096,
                       "by_volume": {"/tmp": 4096}, "max_bytes": 3 * GIB, "days": 14.0}}


def mutation_payload(acao="release", target=""):
    return {"acao": acao, "ok": True, "exit": 0, "entry_id": "1700-abc", "reason": "ok",
            "bytes": 4096, "stored": "/ssd/1700-abc", "sha256": "a" * 64,
            "freed_bytes": 4096, "restored_to": "/tmp/qoder-cli-1000", "victims": [],
            "errors": []}


ANSWERS = {"plan": plan_payload, "ledger": ledger_payload, "release": mutation_payload,
           "restore": mutation_payload, "expire": mutation_payload}


def answers(acao, target):
    return ANSWERS[acao](acao, target)


@pytest.fixture
def jobs():
    return FakeJobs(answers)


@pytest.fixture
def tab(qapp, jobs):
    return TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)


def test_argv_is_the_same_headless_cli_a_tty_would_run():
    assert argv_for("plan") == [sys.executable, "-m", "deck_wellness", "tmpfs", "plan",
                                 "--json"]
    assert argv_for("ledger") == [sys.executable, "-m", "deck_wellness", "tmpfs",
                                  "ledger", "--json"]


def test_a_mutation_carries_the_target_and_the_right_flags():
    assert argv_for("release", "/tmp/qoder-cli-1000", True) == [
        sys.executable, "-m", "deck_wellness", "tmpfs", "release", "/tmp/qoder-cli-1000",
        "--json", "--confirmar"]
    assert argv_for("expire", "", True)[-2:] == ["--confirmar", "--irreversivel"]
    assert "--irreversivel" not in argv_for("expire", "", False)


def test_the_volumes_come_from_the_poller_and_nothing_is_scanned(qapp, jobs):
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)
    t.show_volumes((TmpfsVolume("/tmp", "tmpfs", 8 * GIB, 7 * GIB, GIB),), ts=0.0)
    assert t.volume_rows[0]["path"] == "/tmp"
    assert t.volume_table.item(0, col(VOLUME_COLUMNS, "total")).text() == "8,0 GB"
    assert t.volume_table.item(0, col(VOLUME_COLUMNS, "used")).text() == "7,0 GB"
    assert t.volume_table.cellWidget(0, col(VOLUME_COLUMNS, "bar")).value() == 88
    assert t.volume_rows[0]["eta"] == "—"          # uma amostra não é tendência
    assert jobs.calls == []


def test_the_eta_column_extrapolates_the_samples_this_tab_collected(qapp, jobs):
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)
    for ts, used in ((0.0, 1 * GIB), (60.0, 2 * GIB), (120.0, 3 * GIB)):
        t.show_volumes((TmpfsVolume("/tmp", "tmpfs", 8 * GIB, used, 8 * GIB - used),),
                       ts=ts)
    assert t.volume_rows[0]["eta"] == "5 min"
    assert t.volume_table.item(0, col(VOLUME_COLUMNS, "eta")).text() == "5 min"
    assert "5 min" in t.pressure.text()


def test_refresh_asks_the_child_for_plan_and_ledger_only(tab, jobs):
    tab.refresh()
    assert [c[0] for c in jobs.calls] == ["plan", "ledger"]
    assert all(c[2] is False for c in jobs.calls), "leitura nunca leva --confirmar"
    assert tab.plan_rows[0]["path"] == "/tmp/qoder-cli-1000"
    assert tab.ledger_rows[0]["entry_id"] == "1700-abc"
    assert "impressão" in tab.summary.text()


def test_the_plan_table_keeps_the_refused_side_with_its_reason(tab):
    tab.show_plan(plan_payload())
    states = [tab.plan_table.item(r, col(PLAN_COLUMNS, "state")).text()
              for r in range(tab.plan_table.rowCount())]
    assert states[0] == "candidato"
    assert "fora da allow-list" in states[1]


def test_an_unreconciled_count_is_announced_not_hidden(tab):
    payload = plan_payload()
    payload["scanned_entries"] = 9
    tab.show_plan(payload)
    assert "não fechou" in tab.status.text()


def test_releasing_asks_with_path_bytes_and_holder_pids(qapp, jobs):
    seen = []
    t = TmpfsTab(jobs=jobs,
                 confirm_fn=lambda title, text: seen.append((title, text)) or True)
    t.show_plan(plan_payload())
    t.release_buttons[0].click()
    title, text = seen[0]
    assert "/tmp/qoder-cli-1000" in text
    assert "4,0 KB" in text and "1234" in text
    assert jobs.calls[-1] == ("release", "/tmp/qoder-cli-1000", True)
    assert "1700-abc" in t.status.text()


def test_a_declined_dialog_moves_nothing(qapp, jobs):
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: False)
    t.show_plan(plan_payload())
    t.release_buttons[0].click()
    assert jobs.calls == []
    assert "cancelado" in t.status.text()


def test_a_refusal_from_the_child_is_printed_as_a_refusal(qapp):
    def refused(acao, target):
        return {"acao": acao, "ok": False, "exit": 1,
                "reason": "refused: 1 processo com fd aberto: 1234"}
    t = TmpfsTab(jobs=FakeJobs(refused), confirm_fn=lambda *a: True)
    t.show_plan(plan_payload())
    t.release_buttons[0].click()
    assert "recusado" in t.status.text() and "1234" in t.status.text()


def test_restoring_is_per_entry_and_needs_confirmation(qapp, jobs):
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)
    t.show_ledger(ledger_payload())
    t.restore_buttons[0].click()
    assert jobs.calls[-1] == ("restore", "1700-abc", True)
    assert "devolvido" in t.status.text()


def test_expiring_says_it_is_irreversible_before_running(qapp):
    seen = []
    jobs = FakeJobs(answers)
    t = TmpfsTab(jobs=jobs,
                 confirm_fn=lambda title, text: seen.append(text) or True)
    t.show_ledger(ledger_payload())
    t.expire_button.click()
    assert "irreversível" in seen[0] and "4,0 KB" in seen[0]
    assert jobs.calls[-1] == ("expire", "", True)


def test_the_budget_line_shows_ram_freed_against_ssd_retained(tab):
    tab.show_ledger(ledger_payload())
    assert "retido 4,0 KB" in tab.budget_label.text()
    assert "RAM liberada 4,0 KB" in tab.budget_label.text()
    assert "folga 5,0 GB" in tab.budget_label.text()


def test_a_child_that_answered_nothing_is_not_a_success(qapp):
    t = TmpfsTab(jobs=FakeJobs(lambda acao, target: None), confirm_fn=lambda *a: True)
    t.show_plan(None)
    t.show_ledger(None)
    assert t.plan_rows == [] and t.ledger_rows == []
    assert t.summary.text() == "sem plano"
    assert "sem leitura do ledger" in t.budget_label.text()
```

- [ ] **Step 2: Estender janela, camada de filhos, CLI e camadas**

Em `tests/test_ui_main_window_tabs.py`: atualize o docstring para cinco abas, acrescente o
fixture de resposta e os casos abaixo, e **substitua** `test_the_window_offers_the_four_
approved_tabs_in_order` e `test_closing_the_window_takes_both_child_layers_down`.

```python
def tmpfs_answer(acao, tuning_id):
    return {"acao": acao, "ok": True, "exit": 0, "generated_at": "x", "volumes": [],
            "policy": {}, "reclaimable": [], "protected": [], "total_bytes": 0,
            "scanned_entries": 0, "scanned_bytes": 0, "digest": "d" * 64, "errors": [],
            "records": [], "budget": {"retained_bytes": 0, "retained_count": 0,
                                      "oldest_days": 0.0, "slack_bytes": 0,
                                      "freed_bytes": 0, "by_volume": {},
                                      "max_bytes": 0, "days": 14.0}}


@pytest.fixture
def window(qapp):
    win = MainWindow(collector_factory=lambda: snap,
                     jobs=FakeJobs(detect_answer), disk_jobs=FakeJobs(plan_answer),
                     tmpfs_jobs=FakeJobs(tmpfs_answer))
    return win


def test_the_window_offers_the_five_approved_tabs_in_order(window):
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == \
        ["memória", "ajustes", "órfãos", "disco", "temporários"]
    assert window.tabs.widget(4) is window.tmpfs


def test_closing_the_window_takes_every_child_layer_down(window):
    """A child stuck in D-state must not outlive the window that spawned it."""
    window.close()
    assert window._jobs.calls == [("shutdown", "*", False)]
    assert window._disk_jobs.calls == [("shutdown", "*", False)]
    assert window._tmpfs_jobs.calls == [("shutdown", "*", False)]


def test_the_watched_volumes_land_on_the_tmpfs_tab(window):
    from deck_wellness.core.tmpfs import TmpfsVolume
    window.apply_snapshot(snap(tmpfs=(TmpfsVolume("/tmp", "tmpfs", 8 * GIB, 7 * GIB,
                                                  GIB),)))
    assert window.tmpfs.volume_rows[0]["path"] == "/tmp"


def test_the_window_never_scans_tmpfs_by_itself(window):
    """Abrir a janela não pode virar varredura: o plano é ato de quem está olhando."""
    window.apply_snapshot(snap())
    assert window._tmpfs_jobs.calls == []
    window.tmpfs.refresh()
    assert [c[0] for c in window._tmpfs_jobs.calls] == ["plan", "ledger"]
```

Somar a `tests/test_ui_tune_jobs.py` (usa `pump`, `sandbox` e `qapp` que já existem no arquivo):

```python
def test_a_tmpfs_release_blocks_the_next_mutation(qapp, sandbox):
    """Duas liberações simultâneas seriam duas cópias grandes ao mesmo tempo."""
    from deck_wellness.ui.tune_jobs import TuneJobs

    answers = []
    layer = TuneJobs(env=sandbox, timeout_ms=6000,
                     argv_factory=lambda acao, alvo, confirm:
                     [sys.executable, "-c", "import time; time.sleep(2)"])
    try:
        layer.run("release", "/tmp/qoder-cli-1000", confirm=True, done=answers.append)
        qapp.processEvents()
        assert layer.in_flight == 1
        layer.run("restore", "1700-abc", confirm=True, done=answers.append)
        assert answers[-1]["ok"] is False and "em voo" in answers[-1]["reason"]
        assert layer.in_flight == 1, "a recusa não abre um segundo filho"
    finally:
        layer.shutdown()
        pump(qapp, lambda: layer.in_flight == 0)
```

Somar a `tests/test_cli_tmpfs.py`:

```python
def test_release_json_is_one_line_and_restore_names_the_target(tmp_path, fake_tmp,
                                                               monkeypatch, capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    target = str(root / "qoder-cli-1000")
    code = main(["tmpfs", "release", target, "--confirmar", "--json"])
    raw = capsys.readouterr().out
    assert code == 0 and len(raw.strip().splitlines()) == 1
    payload = json.loads(raw)
    assert payload["ok"] is True and payload["freed_bytes"] == 4096
    assert payload["entry_id"]

    code = main(["tmpfs", "restore", payload["entry_id"], "--confirmar", "--json"])
    got = json.loads(capsys.readouterr().out)
    assert code == 0 and got["restored_to"] == target


def test_a_mutation_refusal_keeps_stdout_empty_and_stderr_explains(tmp_path, fake_tmp,
                                                                   monkeypatch, capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    code = main(["tmpfs", "release", str(root / "pytest-of-misael"), "--confirmar",
                 "--json"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_REFUSED
    assert captured.out == "", "recusa é stderr: a linha --json tem de ser parseável"
    assert "refused" in captured.err
```

Somar a `tests/test_layers.py` — a regra nova não copia o glob, ela prova que o glob
não é vazio:

```python
def test_the_tmpfs_layers_are_actually_scanned():
    """Se `actions/tmpfs` ou `ui/tmpfs_tab.py` ficassem de fora, `offenders == []`
    seria verdade sobre nada. Esta é a não-vacuidade das duas regras acima."""
    covered = {str(f.relative_to(SRC)) for f in py_files(NO_QT + ["ui"])}
    for name in ("actions/tmpfs/release.py", "actions/tmpfs/ledger.py",
                 "actions/tmpfs/policy.py", "ui/tmpfs_tab.py"):
        assert name in covered, f"a regra de camadas não enxerga {name}"
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_ui_tmpfs_tab.py tests/test_layers.py tests/test_cli_tmpfs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'deck_wellness.ui.tmpfs_tab'`, e
em `test_layers` o `FileNotFoundError`/`AssertionError` do arquivo que ainda não existe;
as duas novas da CLI falham com `unrecognized arguments: --json`.
Run: `.venv/bin/python -m pytest tests/test_ui_main_window_tabs.py -v`
Expected: FAIL — `MainWindow.__init__() got an unexpected keyword argument 'tmpfs_jobs'`.

- [ ] **Step 4: `--json` nas mutações da CLI**

No parser, dentro do `for name, help_text in (("release", …), ("restore", …))` e no
`expire`:

```python
        sub.add_argument("--json", action="store_true",
                        help="uma linha de saída para máquinas (a recusa segue no stderr)")
```

Nos handlers, o ramo de sucesso — o `--json` **só** imprime JSON; a recusa continua
saindo pelo stderr com o código, porque é assim que `TuneJobs._payload` transforma
"stdout vazio" em `ok: False` com o motivo do filho:

```python
    if not result.ok:
        sys.stderr.write(f"{result.reason}\n")
        return EXIT_NEEDS_CONFIRM if not args.confirmar else EXIT_REFUSED
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False))
        return EXIT_OK
```

e, em `_cmd_tmpfs_restore`:

```python
    if args.json:
        print(json.dumps({"acao": "restore", "ok": True, "entry_id": result.entry_id,
                          "bytes": result.bytes, "restored_to": result.restored_to,
                          "reason": "ok"}, ensure_ascii=False))
        return EXIT_OK
```

e, em `_cmd_tmpfs_expire`, depois do `if not result.ok:`:

```python
    if args.json:
        print(json.dumps({"acao": "expire", "ok": True, "reason": result.reason,
                          "victims": list(result.victims),
                          "freed_bytes": result.freed_bytes,
                          "errors": list(result.errors)}, ensure_ascii=False))
        return EXIT_OK
```

- [ ] **Step 5: A mutação passa a contar como mutação**

`src/deck_wellness/ui/tune_jobs.py:21`:

```python
MUTATING = ("apply", "revert", "release", "restore", "expire")
```

- [ ] **Step 6: Escrever `ui/tmpfs_tab.py`**

```python
"""M7 tab: read what the child answered, ask before any RAM is freed.

Nothing here walks a tree or opens /proc — the volumes arrive from the poller as
plain tuples and the plan/ledger come from a killable child running the same
headless CLI a TTY would use. The ETA is extrapolation over the samples this
widget collected; a refusal from the child is printed as a refusal, never as a
silent "nothing happened" that could be read as success.
"""
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QPushButton, QProgressBar, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..actions.disk.planner import fmt_bytes
from ..actions.tmpfs import trend

JSON_ACTIONS = ("plan", "ledger", "release", "restore", "expire")
SAMPLES_KEPT = 600  # 20 min de poller de 2 s; a janela do ETA é de 15 min
PENDING = "consultando o tmpfs (dry-run, nada é movido)…"
VOLUME_COLUMNS = (("path", "volume"), ("fs_type", "tipo"), ("total", "total"),
                  ("used", "usado"), ("avail", "livre"), ("bar", "ocupação"),
                  ("eta", "lotar em"))
PLAN_COLUMNS = (("path", "item"), ("size", "tamanho"), ("age", "idade"),
                ("holders", "donos"), ("state", "estado"), ("act", ""))
LEDGER_COLUMNS = (("entry_id", "id"), ("state", "estado"), ("size", "tamanho"),
                  ("src", "origem"), ("act", ""))


def argv_for(acao: str, target: str = "", confirm: bool = False) -> list:
    argv = [sys.executable, "-m", "deck_wellness", "tmpfs", acao]
    if target:
        argv.append(str(target))
    if acao in JSON_ACTIONS:
        argv.append("--json")
    if confirm:
        argv.append("--confirmar")
    if acao == "expire" and confirm:
        argv.append("--irreversivel")
    return argv


def _human_eta(hours: float) -> str:
    if hours >= 24:
        return f"{hours / 24:.0f} dias"
    if hours >= 1:
        return f"{hours:.1f} h".replace(".", ",")
    return f"{hours * 60:.0f} min"


def _table(columns):
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels([title for _, title in columns])
    table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return table


def _fill(table, columns, rows, *, action=None, label=""):
    """Preenche e devolve os botões da coluna de ato, na ordem das linhas."""
    table.setRowCount(len(rows))
    buttons = []
    for position, row in enumerate(rows):
        for column, (key, _) in enumerate(columns):
            if key == "bar":
                bar = QProgressBar(table)
                bar.setRange(0, 100)
                bar.setTextVisible(False)
                bar.setValue(row["pct"])
                table.setCellWidget(position, column, bar)
            elif key == "act":
                button = QPushButton(label, table)
                button.clicked.connect(
                    lambda _=False, r=row, a=action: a(r))
                buttons.append(button)
                table.setCellWidget(position, column, button)
            else:
                table.setItem(position, column, QTableWidgetItem(str(row.get(key, ""))))
    return buttons


class TmpfsTab(QWidget):
    def __init__(self, *, jobs, confirm_fn=None, parent=None):
        super().__init__(parent)
        self._jobs = jobs
        self._confirm = confirm_fn or self._ask_dialog
        self._samples: dict[str, list] = {}
        self.volume_rows: list[dict] = []
        self.plan_rows: list[dict] = []
        self.ledger_rows: list[dict] = []
        self.budget: dict = {}
        self.release_buttons: list[QPushButton] = []
        self.restore_buttons: list[QPushButton] = []

        self.pressure = QLabel("nenhum volume da watch-list montado")
        self.pressure.setWordWrap(True)
        self.volume_table = _table(VOLUME_COLUMNS)
        self.summary = QLabel(PENDING)
        self.summary.setWordWrap(True)
        self.plan_table = _table(PLAN_COLUMNS)
        self.budget_label = QLabel("sem leitura do ledger")
        self.budget_label.setWordWrap(True)
        self.ledger_table = _table(LEDGER_COLUMNS)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.refresh_button = QPushButton("Atualizar plano")
        self.refresh_button.clicked.connect(self.refresh)
        self.expire_button = QPushButton("Expirar o excedente do orçamento")
        self.expire_button.clicked.connect(self.expire_clicked)
        bar = QHBoxLayout()
        bar.addWidget(self.refresh_button)
        bar.addWidget(self.expire_button)
        bar.addStretch(1)

        layout = QVBoxLayout(self)
        for widget in (self.pressure, self.volume_table, self.summary, self.plan_table,
                       self.budget_label, self.ledger_table, self.status):
            layout.addWidget(widget)
        layout.addLayout(bar)

    # -------------------------------------------------------------------- leitura

    def show_volumes(self, volumes, ts=None):
        """O poller traz tuplas planas; a aba só formata e lembra das amostras."""
        ts = time.time() if ts is None else ts
        self.volume_rows = []
        for volume in sorted(volumes, key=lambda v: v.used_frac, reverse=True):
            series = self._samples.setdefault(volume.path, [])
            series.append((ts, volume.used_bytes))
            del series[:-SAMPLES_KEPT]
            hours = trend.eta_hours(tuple(series), volume.total_bytes, now=ts)
            self.volume_rows.append({
                "path": volume.path, "fs_type": volume.fs_type,
                "total": fmt_bytes(volume.total_bytes), "used": fmt_bytes(volume.used_bytes),
                "avail": fmt_bytes(volume.avail_bytes),
                "pct": round(volume.used_frac * 100),
                "eta": "—" if hours is None else _human_eta(hours)})
        _fill(self.volume_table, VOLUME_COLUMNS, self.volume_rows)
        if not self.volume_rows:
            self.pressure.setText("nenhum volume da watch-list montado")
            return
        worst = self.volume_rows[0]
        lotar = "" if worst["eta"] == "—" else f" · lota em {worst['eta']}"
        self.pressure.setText(f"pior volume: {worst['path']} a {worst['pct']}%{lotar}")

    def refresh(self):
        self.summary.setText(PENDING)
        self._jobs.run("plan", "", done=self.show_plan)
        self._jobs.run("ledger", "", done=self.show_ledger)

    def show_plan(self, payload):
        if not payload or "reclaimable" not in payload:
            reason = (payload or {}).get("reason") or "o filho não respondeu"
            self.plan_rows, self.release_buttons = [], []
            self.plan_table.setRowCount(0)
            self.summary.setText("sem plano")
            self.status.setText(f"não foi possível planejar: {reason}")
            return
        candidates, protected = payload["reclaimable"], payload["protected"]
        self.plan_rows = [self._plan_row(i) for i in candidates] + \
                         [self._plan_row(i) for i in protected]
        self.release_buttons = _fill(self.plan_table, PLAN_COLUMNS, self.plan_rows,
                                     action=self.release_clicked, label="Liberar")
        self.summary.setText(
            f"liberáveis {fmt_bytes(payload['total_bytes'])} em {len(candidates)} "
            f"item(ns) · protegidos {len(protected)} · lidos "
            f"{payload['scanned_entries']} · impressão {payload['digest'][:16]}")
        if payload["scanned_entries"] != len(candidates) + len(protected):
            self.status.setText("aviso: a contagem não fechou — o plano é incompleto "
                                "e nada aqui deve ser liberado")
        else:
            self.status.setText("isto é um plano: nada foi movido. Liberar pede "
                                "confirmação, e o item volta por esta aba.")

    def show_ledger(self, payload):
        if not payload or "records" not in payload:
            self.ledger_rows, self.restore_buttons = [], []
            self.ledger_table.setRowCount(0)
            self.budget_label.setText("sem leitura do ledger")
            self.status.setText(((payload or {}).get("reason")
                                 or "o filho não respondeu") + " (ledger)")
            return
        self.budget = payload.get("budget") or {}
        self.ledger_rows = [{"entry_id": r["entry_id"], "state": r["state"],
                             "size": fmt_bytes(r["bytes"]), "src": r["src"]}
                            for r in payload["records"]]
        # a linha `partial` mantém botão: quem recusa é o ato, com motivo — a aba
        # não inventa regra que o digest já aplica
        self.restore_buttons = _fill(self.ledger_table, LEDGER_COLUMNS,
                                     self.ledger_rows, action=self.restore_clicked,
                                     label="Restaurar")
        self.budget_label.setText(
            f"retido {fmt_bytes(self.budget['retained_bytes'])} na SSD em "
            f"{self.budget['retained_count']} item(ns) · o mais velho "
            f"{self.budget['oldest_days']:.1f} d · RAM liberada "
            f"{fmt_bytes(self.budget['freed_bytes'])} · folga "
            f"{fmt_bytes(self.budget['slack_bytes'])}")

    @staticmethod
    def _plan_row(item):
        return {"path": item["path"], "bytes": item["bytes"],
                "size": fmt_bytes(item["bytes"]),
                "age": f"{item['age_days']:.0f} d",
                "holders": ", ".join(str(p) for p in item["holder_pids"]) or "nenhum",
                "state": "candidato" if item["ok"] else item["reason"],
                "item_id": item["item_id"]}

    # ----------------------------------------------------------------------- atos

    def release_clicked(self, row):
        if not self._confirm(
                "Liberar espaço em RAM",
                f"Vou tirar {row['size']} de RAM movendo\n  {row['path']}\n"
                "para a quarentena na SSD, verificando hash por arquivo antes de "
                "apagar a origem.\n\n"
                f"Processos com arquivo aberto aqui: {row['holders']}.\n"
                "Volta por esta aba, com o id do registro — e enquanto estiver retido "
                "conta no orçamento de retenção."):
            self.status.setText(f"cancelado: nada foi liberado ({row['path']})")
            return
        self._jobs.run("release", row["path"], confirm=True, done=self.show_mutation)

    def restore_clicked(self, row):
        if not self._confirm(
                "Devolver ao espaço temporário",
                f"Vou copiar {row['size']} de volta para\n  {row['src']}\n"
                "e apagar o clone na SSD depois que o hash bater. Se o caminho de "
                "destino virou ponto de montagem, a recusa vem antes de qualquer "
                "escrita."):
            self.status.setText(f"cancelado: nada foi devolvido ({row['entry_id']})")
            return
        self._jobs.run("restore", row["entry_id"], confirm=True, done=self.show_mutation)

    def expire_clicked(self):
        if not self.budget:
            self.status.setText("sem leitura do ledger: nada a expirar")
            return
        retained = fmt_bytes(self.budget.get("retained_bytes", 0))
        if not self._confirm(
                "Expirar retenção (irreversível)",
                f"Vou apagar {retained} que estão retidos na SSD além do orçamento "
                f"({self.budget.get('days', 0):g} dias ou "
                f"{fmt_bytes(self.budget.get('max_bytes', 0))}).\n\n"
                "Isto é irreversível: o conteúdo não volta, e o histórico do ledger "
                "continua registrado."):
            self.status.setText("cancelado: nada foi expirado")
            return
        self._jobs.run("expire", "", confirm=True, done=self.show_mutation)

    def show_mutation(self, payload):
        if not payload:
            self.status.setText("o filho não respondeu; nada é considerado feito")
            return
        if not payload.get("ok"):
            self.status.setText("recusado: "
                                f"{payload.get('reason') or 'motivo não informado'}")
            return
        acao = payload.get("acao", "")
        if acao == "release":
            self.status.setText(f"liberado {fmt_bytes(payload['freed_bytes'])} de RAM · "
                                f"id {payload['entry_id']} · devolva por esta aba")
        elif acao == "restore":
            self.status.setText(f"devolvido {fmt_bytes(payload['bytes'])} para "
                                f"{payload['restored_to']}")
        else:
            lines = [f"expirado {fmt_bytes(payload['freed_bytes'])} da SSD · "
                     f"{len(payload.get('victims') or ())} item(ns)"]
            lines += [f"aviso: {line}" for line in payload.get("errors") or ()]
            self.status.setText("\n".join(lines))
        # re-leitura pelo loop de eventos: um veredito novo não pode nascer de dentro
        # do callback do filho anterior
        QTimer.singleShot(0, self.refresh)

    def _ask_dialog(self, title: str, text: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes |
                               QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes
```

- [ ] **Step 7: Ligar a quinta aba**

`ui/main_window.py`: a primeira linha do docstring passa a dizer `five tabs`; os imports
ganham `from .tmpfs_tab import TmpfsTab, argv_for`; as constantes:

```python
TABS = (("memória", "dashboard"), ("ajustes", "tunings"),
        ("órfãos", "orphans"), ("disco", "disk"), ("temporários", "tmpfs"))
DISK_TIMEOUT_MS = 120_000  # the real cache walk took 54,7 s on this Deck (M3 log)
TMPFS_TIMEOUT_MS = 45_000  # três volumes × o prazo de varredura de 10 s, com folga
```

No `__init__`, o parâmetro `tmpfs_jobs=None` depois de `disk_jobs=None`, a camada e a aba:

```python
        self._tmpfs_jobs = tmpfs_jobs if tmpfs_jobs is not None else TuneJobs(
            parent=self, argv_factory=argv_for, timeout_ms=TMPFS_TIMEOUT_MS)
...
        self.tmpfs = TmpfsTab(jobs=self._tmpfs_jobs, confirm_fn=confirm_fn)
```

Em `apply_snapshot`, depois do `dashboard.show_snapshot(...)` e antes da bandeja:

```python
        self.tmpfs.show_volumes(snapshot.tmpfs, ts=snapshot.ts)
```

E em `closeEvent`, a terceira demissão:

```python
            self._tmpfs_jobs.shutdown()
```

`JUMPS` **não** ganha entrada: nenhuma regra de sugestão aponta para esta aba ainda
(§"adiado" da spec), e `jump_to` de um destino desconhecido já é testado como no-op.
O tooltip da bandeja também não muda aqui — ele herda `title_signal.compute` do Task 7.

- [ ] **Step 8: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_ui_tmpfs_tab.py tests/test_ui_main_window_tabs.py tests/test_ui_tune_jobs.py tests/test_layers.py -v` → PASS.
Run: `.venv/bin/python -m pytest -q` → verde.

**Evidência de não-vacuidade:** `test_a_declined_dialog_moves_nothing` falha se
`release_clicked` dispensar o `confirm_fn`; `test_the_volumes_come_from_the_poller_and_-
nothing_is_scanned` falha se a aba chamar `refresh()` no `__init__` (ou se `show_volumes`
decidir varrer algo em vez de receber tuplas); `test_a_tmpfs_release_blocks_the_next_-
mutation` falha se `MUTATING` ficar em `("apply", "revert")`; `test_a_mutation_refusal_-
keeps_stdout_empty_and_stderr_explains` falha se o `--json` de um ato impresso a recusa no
stdout — seria lido como payload ok pelo `TuneJobs._payload`; e
`test_the_tmpfs_layers_are_actually_scanned` falha se qualquer um dos quatro arquivos
sair do conjunto que as regras de camada inspecionam.

- [ ] **Step 9: Commit**

```bash
git add src/deck_wellness/ui/tmpfs_tab.py src/deck_wellness/ui/main_window.py \
        src/deck_wellness/ui/tune_jobs.py src/deck_wellness/cli.py \
        tests/test_ui_tmpfs_tab.py tests/test_ui_main_window_tabs.py \
        tests/test_ui_tune_jobs.py tests/test_layers.py tests/test_cli_tmpfs.py
git commit -m "M7 T13: quinta aba temporários — a janela libera RAM pelo filho matável, com diálogo"
```

---

### Task 14: Evidência no host — `tools/verify_tmpfs.py`

**Files:**
- Create: `tools/verify_tmpfs.py`
- Test: `tests/test_tools_verify_tmpfs.py`

**Interfaces:**
- Consumes: `cli.main`, `cli._build_tmpfs_plan(raiz=None, permitir=(), dias=None, prazo=10.0)`,
  `core.tmpfs.watched_volumes`/`read_mounts`/`WATCHED`/`TmpfsVolume.used_frac`,
  `holders.holder_index` (com `proc_count`/`fd_count`/`refs`), `inventory.entry_at`,
  `policy.Policy`/`classify`, `ledger.Ledger`/`budget_view`, `release.release_item`/
  `restore_item`/`tree_digest`, `safely.audit.AuditLog`, `planner.fmt_bytes`,
  `paths.tmp_ledger_path`/`audit_log_path`/`state_dir`
- Produces: constantes `USED_TOLERANCE`, `TOTAL_TOLERANCE`, `COUNT_TOLERANCE`,
  `HOLDER_BUDGET_S`, `CYCLE_AGE_DAYS`, `PROTECTIONS`; helpers puros
  `parse_df(text) -> dict[str, tuple[int, int, int]]`,
  `parse_mountinfo(text) -> dict[str, str]`,
  `volume_mismatches(volumes, df_rows, *, used_tolerance=…, total_tolerance=…) -> list[str]`,
  `count_mismatches(reclaimable, protected, scanned, depth1_total, *, tolerance=…) -> list[str]`,
  `protection_mismatches(items, expected=PROTECTIONS) -> list[str]` (itens = triplos
  `(path, ok, reason)`), `tripwire_mismatches(before: dict, after: dict) -> list[str]`;
  e `main(argv=None) -> int`

**Por que existe um teste para um script de host:** as reconciliações abaixo do
`main()` são funções puras sobre números e texto. O host real só entra no `main()`.
Assim o comparador é provado fora do host — um plano que não fecha tem de ser
nomeado por um teste, senão o log do Deck é só uma descrição otimista. O *ciclo*
em si não é repetível headless (precisa de cross-device real, tmpfs e `/proc`);
ele é a junção do que as Tasks 9 e 10 já cobriram com bytes reais.

- [ ] **Step 1: Escrever o teste que falha**

Criar `tests/test_tools_verify_tmpfs.py`:

```python
"""O script de evidência só vale se os seus comparadores pegarem um desencontro.

Nada aqui toca o host: as funções puras recebem o texto capturado do `df` real e
números de mentira, e a pergunta testada é de não-vacuidade — um plano que não
fecha, um volume que diverge, uma proteção que virou elegível e um ledger que
mudou têm de ser nomeados.
"""
import importlib.util
from pathlib import Path

from deck_wellness.core.tmpfs import TmpfsVolume

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("verify_tmpfs", ROOT / "tools" / "verify_tmpfs.py")
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)

GIB = 1024 ** 3

# saída real de `df -B1 --output=target,fstype,size,used,avail` neste host (pt_BR)
DF_TEXT = """Montado em     Tipo  Blocos de 1B      Usado      Disp.
/dev                                                 devtmpfs   7706644480            0   7706644480
/                                                      btrfs 999888179200 836337844224 159013257216
/tmp                                                 tmpfs      7770247168   1128648704    6641598464
/run/user/1000                                       tmpfs      1554046976      8572928    1545474048
/dev/shm                                             tmpfs      7770247168    173494272    7596752896
"""

MOUNTINFO_TEXT = """34 28 0:42 / /dev/shm rw,nosuid,nodev shared:4 - tmpfs tmpfs rw,inode64,usrquota
48 32 0:52 / /tmp rw,noatime shared:88 - tmpfs tmpfs rw,inode64
918 29 0:74 / /run/user/1000 rw,nosuid,nodev,relatime shared:521 - tmpfs tmpfs rw,size=1517624k,mode=700
656 918 0:83 / /run/user/1000/doc rw,nosuid,nodev,relatime shared:1044 - fuse.portal portal rw,user_id=1000
"""


def volume(path="/tmp", total=7770247168, used=1128648704, avail=6641598464):
    return TmpfsVolume(path, "tmpfs", total, used, avail)


def test_parse_df_reads_only_tmpfs_rows_and_skips_the_localized_header():
    rows = verify.parse_df(DF_TEXT)
    assert rows["/tmp"] == (7770247168, 1128648704, 6641598464)
    assert "/run/user/1000" in rows and "/dev/shm" in rows
    assert "/" not in rows and "/dev" not in rows, "btrfs e devtmpfs não são a watch-list"


def test_parse_mountinfo_takes_the_mount_point_from_the_left_of_the_separator():
    kinds = verify.parse_mountinfo(MOUNTINFO_TEXT)
    assert kinds["/run/user/1000/doc"] == "fuse.portal"
    assert kinds["/tmp"] == "tmpfs"


def test_volume_mismatches_accepts_a_reconciled_read():
    assert verify.volume_mismatches([volume()], verify.parse_df(DF_TEXT)) == []


def test_volume_mismatches_names_a_wrong_total():
    broken = [volume(total=8 * GIB)]
    problems = verify.volume_mismatches(broken, verify.parse_df(DF_TEXT))
    assert len(problems) == 1 and "/tmp" in problems[0] and "total" in problems[0]


def test_volume_mismatches_tolerates_drift_a_live_tmpfs_actually_has():
    quiet = verify.volume_mismatches([volume(used=1128648704 + 3 * 1024 ** 2)],
                                     verify.parse_df(DF_TEXT))
    loud = verify.volume_mismatches([volume(used=1128648704 + 2 * GIB)],
                                    verify.parse_df(DF_TEXT))
    assert quiet == [], "um tmpfs vivo se move entre as duas leituras"
    assert len(loud) == 1 and "usado" in loud[0]


def test_count_mismatches_names_a_plan_that_does_not_close():
    assert verify.count_mismatches(4, 309, 313, 313) == []
    problems = verify.count_mismatches(4, 300, 313, 313)
    assert any("4+300" in p for p in problems)


def test_count_mismatches_tolerates_children_that_came_and_went():
    assert verify.count_mismatches(4, 309, 313, 317) == []
    problems = verify.count_mismatches(4, 309, 313, 400)
    assert any("87" in p for p in problems)
    assert verify.count_mismatches(4, 309, 320, 313), "o plano não pode inventar item"


def test_protection_mismatches_names_a_mount_that_came_out_eligible():
    items = [("/run/user/1000/doc", True, "liberável: casado com /tmp/tmp*")]
    problems = verify.protection_mismatches(items, (("/run/user/1000/doc", ("monte",)),))
    assert len(problems) == 1 and "ELEGÍVEL" in problems[0]


def test_protection_mismatches_accepts_the_real_refusal_reason():
    items = [("/run/user/1000/doc", False, "refused: ponto de montagem (ou contém uma)"),
             ("/run/user/1000/bus", False, "refused: socket não é arquivo nem árvore regular"),
             ("/tmp/qoder-cli-1000", False, "refused: 0,1 d, mais novo que o piso de 3 d")]
    assert verify.protection_mismatches(items) == []


def test_protection_mismatches_names_the_wrong_reason():
    items = [("/run/user/1000/doc", False, "refused: fora da allow-list de sujeira de agente")]
    problems = verify.protection_mismatches(items)
    assert any("motivo" in p for p in problems), "doc protegido pelo motivo errado é um bug"


def test_protection_mismatches_names_an_absent_protection():
    problems = verify.protection_mismatches([], (("/tmp/.X11-unix", ("uid",)),))
    assert len(problems) == 1 and "não apareceu" in problems[0]


def test_the_tripwire_names_a_record_that_changed():
    before = {"ledger": "aaaa", "audit": "bbbb"}
    assert verify.tripwire_mismatches(before, dict(before)) == []
    problems = verify.tripwire_mismatches(before, {"ledger": "cccc", "audit": "bbbb"})
    assert len(problems) == 1 and "ledger" in problems[0]
    assert len(verify.tripwire_mismatches(before, {"ledger": "aaaa"})) == 1, \
        "uma chave que sumiu do checklist é tão ruim quanto um hash que mudou"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_tools_verify_tmpfs.py -v`
Expected: FAIL — `FileNotFoundError`/`AttributeError` ao carregar `tools/verify_tmpfs.py`
inexistente. Se algum teste passar aqui, ele está testando dados de mentira contra
nada: reveja antes de continuar.

- [ ] **Step 3: Escrever o script**

Criar `tools/verify_tmpfs.py`:

```python
"""Prova re-executável do M7 neste host: os três volumes, o plano real e um ciclo.

    .venv/bin/python tools/verify_tmpfs.py | tee .scratch/m7-verify-tmpfs.log
    .venv/bin/python tools/verify_tmpfs.py --sem-ciclo   # leitura pura; nada é escrito

Nada aqui roda como root e nada aqui escreve no ledger real, no audit real ou em
`~/.config/microsoft-edge`. As grandezas do app são conferidas contra quem não passa
por este código: `df -B1` para as capacidades, `/proc/self/mountinfo` para os montes,
`sha256sum` para os bytes do ciclo e `os.listdir` para a contagem de nível-1. O número
que se reconcilia é a última linha de stdout de `tmpfs plan --json` — exatamente o
contrato que a aba consome, não uma chamada interna escolhida a dedo.

O único escrita em tmpfs real é um diretório com nonce no nome: criado, segurado por
um fd nosso, liberado (copy→verify→unlink para um scratch na SSD), devolvido e apagado
por esta própria execução (§11 e §13.3 da spec). O §13.2 pedia hash do conteúdo dos
três volumes antes/depois das leituras; num tmpfs vivo isso nunca fecha — outros
processos escrevem o tempo todo. O substituto honesto é um hash de árvore de um
diretório quieto (`/tmp/.X11-unix`) antes e depois de `status` e `plan`, mais o
tripwire por hash em `tmp-ledger.jsonl` e `audit.jsonl`: se a injeção de caminhos do
ciclo falhar, a execução falha em vez de sujar o registro do host.

O ciclo nunca chama `expire` — apagar retenção é irreversível e pede as duas flags de
um humano. As contagens de nível-1 impressas aqui substituem as da §"evidência" do
plano (149 no começo da sessão de design, 317 no fim): drift esperado, nada é assumido.
"""
import argparse
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from deck_wellness import cli, paths  # noqa: E402
from deck_wellness.actions.disk.planner import fmt_bytes  # noqa: E402
from deck_wellness.actions.tmpfs import holders, inventory, ledger as ledger_mod, policy, release  # noqa: E402
from deck_wellness.core import tmpfs as tmpfs_mod  # noqa: E402
from deck_wellness.safely.audit import AuditLog  # noqa: E402

USED_TOLERANCE = 64 * 1024 ** 2   # um tmpfs vivo se move entre as duas leituras
TOTAL_TOLERANCE = 1024            # o tamanho do volume não muda sem `mount -o remount`
COUNT_TOLERANCE = 8               # filhos de nível-1 nascem e morrem durante o walk
HOLDER_BUDGET_S = 2.0             # a promessa medida foi 0,079 s; o teto é folgado
CYCLE_AGE_DAYS = 5.0              # acima do piso de 3 d, para o item ser elegível
QUIET_TREE = Path("/tmp/.X11-unix")
PROTECTIONS = (
    ("/run/user/1000/doc", ("monte",)),          # o portal: o acidente canônico
    ("/run/user/1000/bus", ("não é arquivo",)),  # o socket do D-Bus da sessão
    ("/tmp/qoder-cli-1000", ()),                 # scratch vivo: qualquer recusa serve
)


def parse_df(text: str) -> dict:
    """target -> (total, usado, livre) em bytes, das linhas tmpfs.

    O cabeçalho vem traduzido (pt_BR) e é sempre a primeira linha, então ele é
    descartado por posição, não por conteúdo. Um target com espaço quebraria este
    parser — nenhum dos três volumes da watch-list tem.
    """
    rows = {}
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 5 and fields[1] == "tmpfs":
            rows[fields[0]] = (int(fields[2]), int(fields[3]), int(fields[4]))
    return rows


def parse_mountinfo(text: str) -> dict:
    """mount point -> fstype, do arquivo que o kernel escreveu.

    O ponto de montagem é o quinto campo antes do " - "; depois dele vêm fstype,
    fonte e opções. /proc/mounts não serve como testemunha: é o mesmo arquivo que
    `core.tmpfs.read_mounts` lê, e concordar consigo mesmo não é evidência.
    """
    kinds = {}
    for line in text.splitlines():
        head, sep, tail = line.partition(" - ")
        fields, rest = head.split(), tail.split()
        if sep and len(fields) >= 5 and len(rest) >= 2:
            kinds[fields[4]] = rest[0]
    return kinds


def volume_mismatches(volumes, df_rows, *, used_tolerance=USED_TOLERANCE,
                      total_tolerance=TOTAL_TOLERANCE) -> list:
    problems = []
    for v in volumes:
        direct = df_rows.get(v.path)
        if direct is None:
            problems.append(f"{v.path}: o df de fora não conhece este volume")
            continue
        total, used, avail = direct
        print(f"{v.path}: app {fmt_bytes(v.total_bytes)} total, {fmt_bytes(v.used_bytes)} "
              f"usado, {fmt_bytes(v.avail_bytes)} livre · {v.used_frac * 100:.1f}% | "
              f"df {fmt_bytes(used)} usado, {fmt_bytes(avail)} livre")
        if abs(total - v.total_bytes) > total_tolerance:
            problems.append(f"{v.path}: total diverge do df (app {v.total_bytes} vs {total})")
        if abs(used - v.used_bytes) > used_tolerance:
            problems.append(f"{v.path}: usado diverge do df em "
                            f"{fmt_bytes(abs(used - v.used_bytes))} (app {v.used_bytes} "
                            f"vs {used})")
        if abs(avail - v.avail_bytes) > used_tolerance:
            problems.append(f"{v.path}: livre diverge do df em "
                            f"{fmt_bytes(abs(avail - v.avail_bytes))} — é o número que "
                            f"decide ENOSPC de um agente")
    return problems


def count_mismatches(reclaimable: int, protected: int, scanned: int, depth1_total: int,
                     *, tolerance=COUNT_TOLERANCE) -> list:
    problems = []
    if reclaimable + protected != scanned:
        problems.append(f"a contagem interna não fechou: {reclaimable}+{protected} != "
                        f"{scanned} — 'protegi tudo' pode significar 'perdi itens'")
    if scanned > depth1_total:
        problems.append(f"o plano conta {scanned} itens e os volumes têm {depth1_total} "
                        "filhos de nível-1: algo entrou no plano sem ser filho direto")
    drift = depth1_total - scanned
    if drift > tolerance:
        problems.append(f"{drift} filho(s) de nível-1 não chegaram ao plano (tolerância "
                        f"{tolerance}): leitura truncada ou walk parado no prazo")
    return problems


def protection_mismatches(items, expected=PROTECTIONS) -> list:
    """Cada proteção esperada tem de estar recusada, e pelo motivo que a nomeia."""
    by_path = {path: (ok, reason) for path, ok, reason in items}
    problems = []
    for path, needles in expected:
        found = by_path.get(path)
        if found is None:
            problems.append(f"{path} não apareceu no inventário — nada prova que ele é "
                            "protegido")
            continue
        ok, reason = found
        print(f"protecao {path}: {'LIBERÁVEL' if ok else 'recusado'} · {reason}")
        if ok:
            problems.append(f"{path} saiu ELEGÍVEL: {reason}")
        elif needles and not any(needle in reason for needle in needles):
            problems.append(f"{path} foi recusado por um motivo que não o esperado "
                            f"{needles}: {reason}")
    return problems


def tripwire_mismatches(before: dict, after: dict) -> list:
    problems = []
    for label, digest in before.items():
        if label not in after:
            problems.append(f"{label} sumiu do checklist depois da execução")
        elif after[label] != digest:
            problems.append(f"{label} mudou durante esta verificação "
                            f"({digest[:12]} → {after[label][:12]})")
    return problems


def sha256_of(path: Path) -> str:
    """Hash de arquivo por programa de fora; um registro ausente é uma testemunha válida."""
    if not path.exists():
        return "ausente"
    out = subprocess.run(["sha256sum", str(path)], capture_output=True, text=True,
                         timeout=60)
    return out.stdout.split()[0] if out.returncode == 0 else f"erro: {out.stderr[:60]}"


def record_hashes() -> dict:
    return {"tmp-ledger.jsonl": sha256_of(paths.tmp_ledger_path()),
            "audit.jsonl": sha256_of(paths.audit_log_path())}


def run_cli(argv: list) -> tuple:
    """Chama o `main()` do app e devolve (código, stdout). stderr vai para o log."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


def payload_of(stdout: str) -> dict:
    """O mesmo contrato da aba: a última linha de stdout é o JSON."""
    return json.loads(stdout.strip().splitlines()[-1])


def depth1_total(volumes) -> int:
    total = 0
    for v in volumes:
        try:
            names = os.listdir(v.path)
        except OSError as err:
            print(f"filhos_1n {v.path}=ilegível ({err.strerror or err})")
            continue
        print(f"filhos_1n {v.path}={len(names)}")
        total += len(names)
    return total


def check_montes(problems: list) -> None:
    """Os montes que o app lêem são os que o kernel publica, e o portal está entre eles."""
    kinds = parse_mountinfo(Path("/proc/self/mountinfo").read_text())
    app_mounts = dict(tmpfs_mod.read_mounts())
    for path in tmpfs_mod.WATCHED:
        if kinds.get(path) != "tmpfs":
            problems.append(f"{path}: mountinfo diz {kinds.get(path)!r}, não tmpfs")
        if app_mounts.get(path) != "tmpfs":
            problems.append(f"{path}: read_mounts não o vê como tmpfs "
                            f"(viu {app_mounts.get(path)!r})")
    dentro = {m: fs for m, fs in app_mounts.items() if m.startswith("/run/user/1000/")}
    print(f"montes_dentro_da_sessao={dentro or 'nenhum'}")
    if "/run/user/1000/doc" not in app_mounts:
        problems.append("o portal de documentos não está nos montes que o app lê: R1 "
                        "não teria o que proteger")
    for mount, fs in dentro.items():
        if kinds.get(mount) != fs:
            problems.append(f"{mount}: app diz {fs}, mountinfo diz {kinds.get(mount)}")


def check_holders(problems: list) -> None:
    start = time.perf_counter()
    index = holders.holder_index()
    custo = time.perf_counter() - start
    print(f"holders=custo={custo:.3f}s proc={index.proc_count} fd={index.fd_count} "
          f"refs={len(index.refs)}")
    if custo > HOLDER_BUDGET_S:
        problems.append(f"a varredura de fds custou {custo:.3f}s, acima do orçamento de "
                        f"{HOLDER_BUDGET_S:g}s — o collector não pode pagar isso")


def check_readonly(volumes, problems) -> dict:
    """`status` e `plan` sem flag não alteram um byte (§13.2), com o plano da CLI reconciliado."""
    before_tree = release.tree_digest(QUIET_TREE) if QUIET_TREE.is_dir() else None
    code, _ = run_cli(["tmpfs", "status"])
    if code != 0:
        problems.append(f"`tmpfs status` voltou {code} sem nenhuma flag")
    code, stdout = run_cli(["tmpfs", "plan", "--json"])
    if code != 0:
        problems.append(f"`tmpfs plan --json` voltou {code}")
        return {}
    payload = payload_of(stdout)
    vistos = {v["path"]: v for v in payload["volumes"]}
    for v in volumes:
        direto = vistos.get(v.path)
        if direto is None:
            problems.append(f"{v.path}: o plano não traz este volume")
        elif abs(direto["used_bytes"] - v.used_bytes) > USED_TOLERANCE:
            problems.append(f"{v.path}: duas leituras do app, dois números — o plano viu "
                            f"{direto['used_bytes']} e o collector viu {v.used_bytes}")
    if before_tree is not None:
        after_tree = release.tree_digest(QUIET_TREE)
        print(f"arvore_quieta={QUIET_TREE} digest_antes={before_tree[0][:12]} "
              f"digest_depois={after_tree[0][:12]} bytes={before_tree[1]}")
        if before_tree != after_tree:
            problems.append(f"uma leitura sem flag alterou {QUIET_TREE}: "
                            "o plano não é dry-run")
    print(f"plano=gerado={payload['generated_at']} digest={payload['digest'][:12]} "
          f"varridos={payload['scanned_entries']} recuperaveis="
          f"{len(payload['reclaimable'])} protegidos={len(payload['protected'])} "
          f"recuperaveis_bytes={fmt_bytes(payload['total_bytes'])} "
          f"erros_de_leitura={len(payload['errors'])}")
    for err in payload["errors"][:5]:
        print(f"  erro: {err}")
    return payload


def print_candidatos(payload: list, limit: int = 8) -> None:
    order = sorted(payload, key=lambda d: -d["bytes"])
    for item in order[:limit]:
        print(f"  · {fmt_bytes(item['bytes']):>9} · {item['age_days']:>5} d · "
              f"{item['path']} · {item['reason']}")
    if len(order) > limit:
        print(f"  · … {len(order) - limit} item(ns) além dos {limit} maiores")


def check_allow_list_gate(root: Path, problems: list) -> None:
    """Sem o padrão explícito, o mesmo item tem de ser recusado pelo filtro 2.

    Usa o `classify` direto no item recém-lido: um scan inteiro de /tmp só para
    provar a allow-list seria lento demais para ser re-executado.
    """
    entry = inventory.entry_at(str(root), tmpfs_mod.read_mounts(),
                               holders.holder_index(prefixes=(str(root),)),
                               volume="/tmp")
    verdict = policy.classify(entry, policy.Policy())
    print(f"sem_permitir={'LIBERÁVEL' if verdict.ok else verdict.reason}")
    if verdict.ok:
        problems.append("o item sintético saiu elegível sem padrão de allow-list: o "
                        "filtro 2 não está segurando")
    elif "allow-list" not in verdict.reason:
        problems.append(f"recusado pelo motivo errado antes da allow-list: "
                        f"{verdict.reason}")


def make_item(nonce: str) -> Path:
    root = Path("/tmp") / f"deckwellness-verify-{nonce}"
    (root / "sub").mkdir(parents=True)
    (root / "a.bin").write_bytes(b"a" * 4096)
    (root / "sub" / "b.bin").write_bytes(b"b" * 8192)
    old = time.time() - CYCLE_AGE_DAYS * 86_400
    for p in (root / "sub" / "b.bin", root / "a.bin", root / "sub", root):
        os.utime(p, (old, old))   # o mtime do diretório por último: escrever neles o atualiza
    return root


def file_map(root: Path) -> dict:
    """Resumo por arquivo, medido por `sha256sum` — não pelo digest da aplicação."""
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): sha256_of(p)
            for p in sorted(root.rglob("*")) if p.is_file()}


def check_cycle(scratch: Path, problems: list, prazo: float) -> None:
    nonce = f"{os.getpid()}-{int(time.time())}"
    root = make_item(nonce)
    original = file_map(root)
    print(f"item_sintetico={root} arquivos={ {k: v[:8] for k, v in original.items()} }")
    try:
        plan = cli._build_tmpfs_plan(permitir=[str(root)], prazo=prazo)
        item = plan.find(str(root))
        if item is None:
            problems.append("o item sintético não está no inventário de /tmp")
            return
        if not item.ok:
            problems.append(f"o item sintético, elegível por construção, foi recusado: "
                            f"{item.reason}")
            return
        print(f"elegivel={item.reason} bytes={item.bytes} arquivos={item.files} "
              f"idade={item.age_days:.1f} d")
        check_allow_list_gate(root, problems)

        fd = os.open(root / "a.bin", os.O_RDONLY)
        try:
            held = cli._build_tmpfs_plan(permitir=[str(root)], prazo=prazo)
            got = held.find(str(root))
            if got is None or got.ok:
                problems.append("o item com um fd nosso aberto saiu elegível: R4 não pegou")
            else:
                print(f"com_fd_aberto={got.reason}")
        finally:
            os.close(fd)

        book = ledger_mod.Ledger(path=scratch / "tmp-ledger.jsonl")
        audit = AuditLog(path=scratch / "audit.jsonl")
        dest = scratch / "retida"
        livre_antes = os.statvfs("/tmp").f_bavail * os.statvfs("/tmp").f_frsize
        res = release.release_item(plan, item, ledger=book, dest_root=dest,
                                   audit=audit, confirm=True)
        if not res.ok:
            problems.append(f"a liberação real recusou: {res.reason}")
            return
        stored = Path(res.stored)
        clone = file_map(stored)
        livre_depois = os.statvfs("/tmp").f_bavail * os.statvfs("/tmp").f_frsize
        print(f"liberado=entry={res.entry_id} bytes={res.bytes} "
              f"liberados={res.freed_bytes} digest={res.sha256[:12]} "
              f"clone={stored} statvfs_livre_antes={fmt_bytes(livre_antes)} "
              f"depois={fmt_bytes(livre_depois)}")
        if clone != original:
            problems.append(f"o clone na SSD não bate com o original medido por "
                            f"sha256sum: {clone} != {original}")
        if root.exists():
            problems.append("o original continua na RAM depois de uma liberação ok")
        if book.retained_bytes() != res.bytes:
            problems.append(f"o ledger retém {book.retained_bytes()} e a liberação "
                            f"declarou {res.bytes}")
        if len(res.sha256) != 64:
            problems.append(f"o digest liberado não é um sha256: {res.sha256}")
        if abs(livre_depois - livre_antes) < res.bytes:
            print("obs: o ganho de 12 KiB some no ruído de um /tmp vivo — não é "
                  "assercão, é observação")

        rst = release.restore_item(res.entry_id, ledger=book, audit=audit, confirm=True)
        if not rst.ok:
            problems.append(f"a devolução real recusou: {rst.reason}")
            return
        voltou = file_map(Path(rst.restored_to))
        print(f"devolvido=para={rst.restored_to} bytes={rst.bytes} "
              f"clone_restou={stored.exists()} retido={book.retained_bytes()}")
        if voltou != original:
            problems.append(f"o que voltou não é o que foi embora: {voltou} != {original}")
        if stored.exists():
            problems.append("devolvido e o clone continua dos dois lados da SSD")
        if book.retained_bytes() != 0:
            problems.append(f"o orçamento não liberou: retido={book.retained_bytes()}")

        view = book.budget_view()
        print(f"orcamento_scratch=retido={fmt_bytes(view.retained_bytes)} "
              f"itens={view.retained_count} liberado={fmt_bytes(view.freed_bytes)} "
              f"folga={fmt_bytes(view.slack_bytes)} linhas={len(book.rows())}")
        print(f"linhas_do_ledger={[ (r['entry_id'], r['state']) for r in book.rows() ]}")
    finally:
        shutil.rmtree(root, ignore_errors=True)
        print(f"limpeza={root} existe_ainda={root.exists()}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sem-ciclo", action="store_true",
                        help="não escreve em /tmp: pula elegibilidade, fd aberto e o "
                             "ciclo release→restore")
    parser.add_argument("--prazo", type=float, default=10.0,
                        help="orçamento de walk por item, em segundos")
    args = parser.parse_args(argv)

    problems: list[str] = []
    volumes = tmpfs_mod.watched_volumes()
    df_rows = parse_df(subprocess.run(
        ["df", "-B1", "--output=target,fstype,size,used,avail"],
        capture_output=True, text=True, timeout=60).stdout)
    problems += volume_mismatches(volumes, df_rows)
    check_montes(problems)
    check_holders(problems)

    before = record_hashes()
    payload = check_readonly(volumes, problems)
    if payload:
        print(f"candidatos=[{ ', '.join(i['path'] for i in payload['reclaimable'][:6]) }]")
        print_candidatos(payload["reclaimable"])
        items = [(i["path"], i["ok"], i["reason"])
                 for i in (*payload["reclaimable"], *payload["protected"])]
        problems += count_mismatches(len(payload["reclaimable"]),
                                     len(payload["protected"]),
                                     payload["scanned_entries"], depth1_total(volumes))
        problems += protection_mismatches(items)
        motivos = Counter(i["reason"].partition(":")[2].split(";")[0].strip()[:32]
                          for i in payload["protected"])
        for motivo, qtd in motivos.most_common():
            print(f"recusa={motivo} itens={qtd}")

    if not args.sem_ciclo:
        # o scratch nasce sob XDG state: SSD, dentro das default_allowed_roots(), e
        # retenção em RAM seria a antítese do que esta execução está provando
        scratch = Path(tempfile.mkdtemp(prefix="deckwellness-verify-",
                                        dir=str(paths.state_dir())))
        try:
            check_cycle(scratch, problems, args.prazo)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
            print(f"scratch_removido={scratch} existe_ainda={scratch.exists()}")

    print(f"registros_do_host={before}")
    after = record_hashes()
    problems += tripwire_mismatches(before, after)

    for line in problems:
        print(f"FALHA: {line}")
    print(f"uid={os.getuid()} veredicto={'FALHOU' if problems else 'OK'} "
          f"problemas={len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
```

O scratch do ciclo nasce sob XDG state — SSD, dentro das `default_allowed_roots()`, e
nunca sob um tmpfs, porque reter em RAM seria a antítese do que a execução prova. O
`finally` remove o diretório inteiro, e a linha `scratch_removido=… existe_ainda=False`
é a testemunha de que a execução não deixou rastro.

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_tools_verify_tmpfs.py -v` → PASS (12).

- [ ] **Step 5: Rodar a suíte inteira**

Run: `.venv/bin/python -m pytest -q` → verde.

Este teste **não** toca o host: ele alimenta os comparadores com texto capturado e
números. O `main()` só roda quando um humano chama o script. Confirme que nada no
arquivo novo escreve fora de `tmp_path` — a suíte continua sem tocar `/tmp`,
`/run/user/1000`, `/dev/shm` nem o Edge real (o tripwire de sessão do `conftest.py:25`
ainda passa).

- [ ] **Step 6: Rodar a leitura pura no Deck**

```bash
mkdir -p .scratch
.venv/bin/python tools/verify_tmpfs.py --sem-ciclo | tee .scratch/m7-verify-tmpfs-leitura.log
```

Saída esperada (números do momento, não valores fixos): três linhas `…: app … | df …`,
`montes_dentro_da_sessao={'/run/user/1000/doc': 'fuse.portal', …}`, `holders=custo=…s
proc=… fd=… refs=…`, `plano=… recuperaveis=… protegidos=…`, `arvore_quieta=… digest`
igual nos dois lados, as três linhas `protecao …recusado`, o histograma `recusa=…` e
`veredicto=OK problemas=0`.

Se `--sem-ciclo` já falhar, o problema é de leitura e tem de ser resolvido antes de
qualquer escrita: nada do que segue é evidência enquanto um comparador estiver errado.

- [ ] **Step 7: Rodar o ciclo real no Deck**

```bash
.venv/bin/python tools/verify_tmpfs.py | tee .scratch/m7-verify-tmpfs.log
echo "ledger real ainda igual?"; sha256sum ~/.local/state/deck-wellness/tmp-ledger.jsonl
```

Saída esperada acrescenta:

```
item_sintetico=/tmp/deckwellness-verify-<pid>-<ts> arquivos={'a.bin': '…', 'sub/b.bin': '…'}
elegivel=liberável: casado com /tmp/deckwellness-verify-… bytes=12288 arquivos=2 idade=5,0 d
sem_permitir=refused: fora da allow-list de sujeira de agente
com_fd_aberto=refused: 1 processo(s) com fd aberto: <pid>
liberado=entry=… bytes=12288 liberados=12288 digest=… clone=…/retida/…
devolvido=para=/tmp/deckwellness-verify-… bytes=12288 clone_restou=False retido=0
orcamento_scratch=retido=0,0 B itens=0 liberado=12,0 KB folga=… linhas=3
limpeza=/tmp/deckwellness-verify-… existe_ainda=False
scratch_removido=… existe_ainda=False
veredicto=OK problemas=0
```

`linhas=3` é a reconciliação do ledger: `partial` → `released` → `restored`, uma por
transição, nenhuma delas no `tmp-ledger.jsonl` do host (o `sha256sum` acima tem de
bater com o `record_hashes` impresso no log).

- [ ] **Step 8: Coerção de mutação e honestidade do log**

Cada comparador do Step 3 tem de poder falhar, e o teste do Step 1 prova isso fora
do host: afrouxar `TOTAL_TOLERANCE`, trocar `>` por `>=` em `scanned > depth1_total`,
aceitar uma proteção `ok=True`, ou esquecer uma chave no `tripwire_mismatches` — cada
um mata ao menos um teste. No host, as três testemunhas externas são `df`,
`/proc/self/mountinfo` e `sha256sum`; nenhuma delas é código deste repositório.

Escreva no corpo do commit o resumo da execução real: `holders=custo=…s`, as contagens
de nível-1 dos três volumes, `recuperaveis/protegidos`, os motivos de proteção e o
`veredicto`. Guarde os dois logs em `.scratch/` (não são versionados) — a auditoria é
pelo caminho estável, não por esta afirmação.

- [ ] **Step 9: Commit**

```bash
git add tools/verify_tmpfs.py tests/test_tools_verify_tmpfs.py
git commit -m "M7 T14: evidência no host — df/mountinfo/sha256sum de fora, contagem reconciliada e um ciclo real com tripwire no ledger"
```
