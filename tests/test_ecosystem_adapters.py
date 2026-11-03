"""F7 adapters: absence is honest, protected items stay protected, no actions."""
import json
import subprocess
from types import SimpleNamespace

from folego.adapters.caches import CacheAdapter, CacheSpec
from folego.adapters.containers import ContainerAdapter
from folego.adapters.inventory import EcosystemInventory
from folego.adapters.libvirt import LibvirtAdapter
from folego.adapters.mounts import MountAdapter
from folego.adapters.projects import ProjectAdapter, ProjectSpec


def completed(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


# ------------------------------------------------------------------- projects

def test_a_dirty_worktree_is_protected_and_a_missing_project_is_unknown(tmp_path):
    clean = tmp_path / "clean"
    dirty = tmp_path / "dirty"
    clean.mkdir()
    dirty.mkdir()
    calls = []

    def runner(argv):
        calls.append(argv)
        if "status" in argv:
            if str(dirty) in argv:
                return completed("## main\n M arquivo.py\n")
            return completed("## main\n")
        return completed("worktree /x\n")

    adapter = ProjectAdapter(
        [ProjectSpec("clean", clean), ProjectSpec("dirty", dirty),
         ProjectSpec("missing", tmp_path / "missing")], runner=runner)
    result = adapter.inventory()

    by_id = {item.item_id: item for item in result.items}
    assert by_id["clean"].protected is False
    assert by_id["dirty"].protected is True
    assert "não salvo" in by_id["dirty"].reason
    assert by_id["missing"].protected is True
    assert by_id["missing"].bytes_observed is None
    assert len(calls) == 4  # two worktrees, status + worktree-list each


def test_a_git_lock_protects_without_running_git(tmp_path):
    project = tmp_path / "p"
    (project / ".git").mkdir(parents=True)
    (project / ".git" / "index.lock").write_text("")
    calls = []
    adapter = ProjectAdapter([ProjectSpec("p", project)],
                             runner=lambda argv: calls.append(argv) or
                             completed("## main\n"))
    result = adapter.inventory()
    assert result.items[0].protected is True
    assert "travado" in result.items[0].reason
    assert calls == [], "lock é evidência suficiente; não precisa ler o índice"


def test_unreadable_project_config_is_not_an_empty_success(tmp_path):
    config = tmp_path / "projects.json"
    config.write_text("lixo{")
    result = ProjectAdapter(config_path=config).inventory()
    assert result.available is True
    assert result.items == () and "ilegível" in result.error


# --------------------------------------------------------------------- caches

def test_cache_size_is_observed_without_following_symlinks(tmp_path):
    root = tmp_path / "cache"
    (root / "nested").mkdir(parents=True)
    (root / "a").write_bytes(b"1234")
    (root / "nested" / "b").write_bytes(b"56")
    (root / "link").symlink_to(root / "a")
    adapter = CacheAdapter([CacheSpec("c", root)], clock=lambda: 1_700_000_000.0)
    result = adapter.inventory()

    item = result.items[0]
    assert item.bytes_observed == 6
    assert item.detail["files"] == 2
    assert item.detail["regenerable"] is True
    assert item.protected is False


def test_a_missing_cache_is_unknown_and_protected(tmp_path):
    item = CacheAdapter([CacheSpec("missing", tmp_path / "no")]).inventory().items[0]
    assert item.bytes_observed is None and item.protected is True
    assert "ausente" in item.reason


# ------------------------------------------------------------------ containers

def container_runner(context="ctx-a"):
    def runner(argv):
        if "context" in argv:
            return completed(context + "\n")
        if "ps" in argv:
            return completed(json.dumps({
                "ID": "abc", "Names": "build", "State": "exited",
                "Image": "img:1", "Mounts": "vol1:/data"}) + "\n")
        if "volume" in argv:
            return completed(json.dumps({"Name": "vol1", "Driver": "local"}) + "\n")
        if "images" in argv:
            return completed(json.dumps({"ID": "sha256:dead", "Repository": "img",
                                         "Tag": "1"}) + "\n")
        return completed("")
    return runner


def test_a_volume_used_by_a_stopped_container_is_preserved():
    adapter = ContainerAdapter("docker", runner=container_runner("ctx-a"),
                               which=lambda name: "/usr/bin/" + name)
    result = adapter.inventory()

    volume = next(item for item in result.items if item.kind == "volume")
    assert volume.protected is True
    assert volume.detail["referenced"] is True
    assert "parado" in volume.reason
    assert result.items[0].detail["context"] == "ctx-a"
    assert result.items[0].detail["stopped"] is True


def test_two_engines_keep_their_contexts_separate():
    docker = ContainerAdapter("docker", runner=container_runner("dctx"),
                               which=lambda name: "/bin/" + name)
    podman = ContainerAdapter("podman", runner=container_runner("pctx"),
                              which=lambda name: "/bin/" + name)
    docker_result = docker.inventory()
    podman_result = podman.inventory()

    assert docker_result.name == "docker" and podman_result.name == "podman"
    assert docker_result.items[0].detail["context"] == "dctx"
    assert podman_result.items[0].detail["context"] == "pctx"
    assert docker_result.items[0].item_id != podman_result.items[0].item_id


def test_a_missing_container_engine_is_unavailable_not_an_exception():
    result = ContainerAdapter("docker", which=lambda name: None).inventory()
    assert result.available is False
    assert "não instalado" in result.reason


def test_a_broken_engine_output_is_not_treated_as_an_empty_host():
    def runner(argv):
        if "context" in argv:
            return completed("ctx")
        return completed("", returncode=1, stderr="daemon offline")
    result = ContainerAdapter("docker", runner=runner,
                              which=lambda name: "/bin/docker").inventory()
    assert result.available is False
    assert "daemon offline" in result.error
    assert result.items == ()


# -------------------------------------------------------------------- libvirt

def test_a_paused_vm_is_not_reported_as_free_ram_and_its_disk_is_protected():
    def runner(argv):
        if "list" in argv:
            return completed("vm1\n")
        if "domstate" in argv:
            return completed("paused\n")
        if "domblklist" in argv:
            return completed(" Target   Source\n vda      /var/lib/libvirt/images/base.qcow2\n")
        return completed("")
    result = LibvirtAdapter(uri="qemu:///system", runner=runner,
                            which=lambda name: "/usr/bin/virsh").inventory()

    domain = next(item for item in result.items if item.kind == "domain")
    disk = next(item for item in result.items if item.kind == "disk")
    assert domain.detail["state"] == "paused"
    assert domain.detail["ram_reclaimed"] is False
    assert disk.protected is True
    assert "referenciado" in disk.reason


def test_a_missing_virsh_is_unavailable():
    result = LibvirtAdapter(which=lambda name: None).inventory()
    assert result.available is False and "virsh" in result.reason


# --------------------------------------------------------------------- mounts

def test_only_external_mounts_are_inventoried_and_none_are_actionable(tmp_path):
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 8:1 / / rw - ext4 /dev/sda1 rw\n"
        "2 0 8:2 / /media/u/My\\040Disk rw - exfat /dev/sdb1 rw\n"
        "3 0 8:3 / /mnt/cache rw - btrfs /dev/sdc1 rw\n")
    result = MountAdapter(mountinfo).inventory()

    labels = {item.label for item in result.items}
    assert labels == {"/media/u/My Disk", "/mnt/cache"}
    assert all(item.protected for item in result.items)
    assert all("unmount" in item.reason for item in result.items)


def test_unreadable_mountinfo_is_unavailable(tmp_path):
    result = MountAdapter(tmp_path / "missing").inventory()
    assert result.available is False and "ilegível" in result.reason


# ------------------------------------------------------------------ aggregate

def test_cli_json_serializes_exactly_one_collected_snapshot(monkeypatch, capsys):
    import json
    from folego import cli
    from folego.adapters.base import AdapterResult

    class Counting:
        name = "projects"
        calls = 0

        def inventory(self):
            self.calls += 1
            return AdapterResult(self.name, True, evidence=(str(self.calls),))

    adapter = Counting()
    monkeypatch.setattr(cli, "default_adapters", lambda: (adapter,))
    assert cli.main(["ecosystem", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert adapter.calls == 1
    assert payload["adapters"][0]["evidence"] == ["1"]

class Boom:
    name = "boom"

    def inventory(self):
        raise RuntimeError("explodiu")


def test_one_adapter_crash_does_not_hide_the_others():
    class Fine:
        name = "fine"

        def inventory(self):
            from folego.adapters.base import AdapterResult
            return AdapterResult("fine", True, evidence=("ok",))

    payload = EcosystemInventory([Boom(), Fine()]).to_dict()
    assert payload["available"] == 1 and payload["unavailable"] == 1
    assert payload["errors"] == ["boom"]
    assert payload["adapters"][1]["available"] is True
