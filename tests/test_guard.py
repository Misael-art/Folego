from types import SimpleNamespace

from folego.safely import guard

MOUNT_BLACKLIST = ["/mnt/sdcard/file", "/run/media/misael/card/x", "/etc/passwd"]


class FakeStat:
    def __init__(self, uid):
        self._uid = uid

    def __call__(self, path):
        return SimpleNamespace(st_uid=self._uid)


def test_accepts_regular_owned_file_under_allowed_root(tmp_path):
    edge = tmp_path / "edge-profile"
    edge.mkdir()
    target = edge / "Local State"
    target.write_bytes(b"{}")
    v = guard.validate_target(target, [edge])
    assert v.ok, v.reason


def test_accepts_missing_file_whose_parent_is_under_allowed_root(tmp_path):
    edge = tmp_path / "edge-profile"
    (edge / "Default").mkdir(parents=True)
    v = guard.validate_target(edge / "Default" / "inexistent.json", [edge])
    assert v.ok, v.reason


def test_rejects_path_outside_every_allowed_root(tmp_path):
    outside = tmp_path / "outra-coisa"
    outside.mkdir()
    target = outside / "x"
    target.write_bytes(b"")
    v = guard.validate_target(target, [tmp_path / "edge-profile"])
    assert not v.ok and "allowed" in v.reason.lower()


def test_blacklist_beats_allowlist_for_device_and_system_prefixes():
    for s in MOUNT_BLACKLIST:
        v = guard.validate_target(s, [__import__("pathlib").Path(s).parent])
        assert not v.ok, f"{s} must be refused even if its dir is allowed"
        assert v.reason != ""


def test_rejects_any_symlink_mutation_target(tmp_path):
    edge = tmp_path / "edge-profile"
    edge.mkdir()
    sneaky = tmp_path / "escape"
    sneaky.write_bytes(b"secret")
    link = edge / "Local State"
    link.symlink_to(sneaky)
    v = guard.validate_target(link, [edge])
    assert not v.ok and "symlink" in v.reason.lower()


def test_rejects_file_owned_by_other_uid(tmp_path):
    edge = tmp_path / "edge-profile"
    edge.mkdir()
    target = edge / "prefs"
    target.write_bytes(b"")
    v = guard.validate_target(target, [edge], stat_fn=FakeStat(uid=0))
    assert not v.ok and "owner" in v.reason.lower()


def test_rejects_missing_file_with_nonexistent_parent(tmp_path):
    edge = tmp_path / "edge-profile"
    v = guard.validate_target(edge / "nope" / "x.json", [edge])
    assert not v.ok and "parent" in v.reason.lower()
