"""Uma passada em /proc/<pid>/fd: barato o bastante para perguntar antes de cada liberação.

Medido neste Deck: 492 processos, 9.862 fd, 192 refs sob /tmp ∪ /run/user/1000 em
0,079 s. É a diferença entre liberar scratch de agente morto e cortar um vivo.
"""
import os

from folego.actions.tmpfs import holders


def make_proc(root, pid: int, links: dict):
    fd = root / str(pid) / "fd"
    fd.mkdir(parents=True)
    for name, target in links.items():
        os.symlink(target, fd / name)


def test_only_targets_under_the_prefixes_are_recorded(fake_proc):
    make_proc(fake_proc, 400, {"3": "/tmp/agente/sessao", "4": "/home/u/nota.md",
                               "5": "/run/user/1000/bus", "6": "socket:[917]",
                               "7": "/tmpx/algo"})
    idx = holders.holder_index(proc_root=str(fake_proc))
    assert idx.refs == {"/run/user/1000/bus": (400,), "/tmp/agente/sessao": (400,)}
    assert (idx.proc_count, idx.fd_count) == (1, 5)
    assert "/tmpx/algo" not in idx.refs   # compartilha as letras, não o separador
    assert idx.pids_holding("/tmp/algo") == frozenset()
    assert idx.pids_holding("/tmpx/algo") == frozenset()


def test_pids_holding_covers_a_directory_and_what_is_inside_it(fake_proc):
    make_proc(fake_proc, 700, {"0": "/tmp/qoder-cli-1000/abc/sessao-1/x"})
    idx = holders.holder_index(proc_root=str(fake_proc))
    assert idx.pids_holding("/tmp/qoder-cli-1000/abc") == frozenset({700})
    assert idx.pids_holding("/tmp/qoder-cli-1000/abc/sessao-1") == frozenset({700})
    assert idx.pids_holding("/tmp/qoder-cli-1000/outra") == frozenset()
    assert idx.pids_holding("/tmp/qoder-cli-1000/ab") == frozenset()  # prefixo de string não é ancestral


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


def test_the_default_root_is_the_proc_seam_of_paths(fake_proc):
    make_proc(fake_proc, 300, {"0": "/dev/shm/fila"})
    idx = holders.holder_index()          # sem proc_root: paths.proc_root() decide
    assert idx.refs == {"/dev/shm/fila": (300,)}
    assert (idx.proc_count, idx.fd_count) == (1, 1)


def test_an_absent_proc_root_is_not_proof_of_no_holders(tmp_path):
    idx = holders.holder_index(proc_root=str(tmp_path / "nao-existe"))
    assert idx.refs == {}
    assert idx.proc_count == 0            # quer dizer "não sabemos", não "nada aberto"
    assert idx.fd_count == 0
    assert idx.state == "unavailable"     # R02: o índice diz que não pôde ler
    assert idx.errors, "a abrangência perdida tem de estar nomeada"


def test_a_complete_scan_over_an_empty_proc_root_is_complete(fake_proc):
    """Ler /proc e não achar processo é diferente de não conseguir ler /proc."""
    idx = holders.holder_index(proc_root=str(fake_proc))
    assert idx.state == "complete"
    assert idx.errors == ()


def test_an_unreadable_fd_directory_makes_the_index_partial(fake_proc):
    """R02: sem ler todos os fd, 'nenhum holder' é ignorância, não prova."""
    make_proc(fake_proc, 800, {"0": "/tmp/x"})
    real = os.scandir

    def deny(path):
        if str(path).endswith("/800/fd"):
            raise PermissionError(13, "denied")
        return real(path)

    idx = holders.holder_index(proc_root=str(fake_proc), scandir_fn=deny)
    assert idx.state == "partial"
    assert idx.errors, "o fd ilegível tem de aparecer no estado"


def test_an_unreadable_pid_directory_makes_the_index_partial(fake_proc):
    real = os.scandir

    def deny_pid_dirs(path):
        if str(path) == str(fake_proc):
            raise PermissionError(13, "denied")
        return real(path)

    idx = holders.holder_index(proc_root=str(fake_proc), scandir_fn=deny_pid_dirs)
    assert idx.state == "unavailable"
