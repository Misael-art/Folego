"""Regra de destino (R12) com tabelas de monte de fixture — sem tocar no host."""
from folego.safely.mounts import covering_mount, destination_verdict, mount_of

MOUNTS = (
    ("/", "ext4"),
    ("/home", "ext4"),
    ("/tmp", "tmpfs"),
    ("/run/user/1000", "tmpfs"),
    ("/mnt/sdcard", "vfat"),
)


def test_the_deepest_covering_mount_wins():
    assert covering_mount("/tmp/qoder-cli-1000", MOUNTS) == ("/tmp", "tmpfs")
    assert covering_mount("/home/u/.local/share", MOUNTS) == ("/home", "ext4")
    assert covering_mount("/etc", MOUNTS) == ("/", "ext4")


def test_nothing_known_about_the_path_is_refused():
    """Sem a tabela, 'não é tmpfs' seria fé: a abrangência tem de ser dita."""
    verdict = destination_verdict("/home/u/.local/share/folego", mounts=())
    assert verdict.ok is False
    assert "conhecido" in verdict.reason


def test_a_ram_backed_destination_is_refused_and_named():
    verdict = destination_verdict("/tmp/folego-quarantine", mounts=MOUNTS)
    assert verdict.ok is False
    assert verdict.mount == "/tmp" and verdict.fs_type == "tmpfs"
    assert "RAM" in verdict.reason


def test_a_persistent_destination_is_accepted():
    verdict = destination_verdict("/home/u/.local/share/folego/tmp-quarantine",
                                  mounts=MOUNTS)
    assert verdict.ok is True
    assert verdict.mount == "/home" and verdict.fs_type == "ext4"
    assert "destino em" in verdict.reason


def test_the_same_mount_as_the_source_is_refused():
    verdict = destination_verdict("/home/u/.local/share/folego/quarantine",
                                  source_mount="/home", mounts=MOUNTS)
    assert verdict.ok is False
    assert verdict.same_mount_as_source is True
    assert "mesmo monte" in verdict.reason


def test_mount_of_reports_none_only_when_the_table_does_not_cover():
    """Com `/` na tabela tudo é coberto; sem tabela, nada é."""
    assert mount_of("/srv/coisa", MOUNTS) == "/"
    assert mount_of("/home/u/x", MOUNTS) == "/home"
    assert mount_of("/home/u/x", ()) is None
