import pytest

from folego.actions.disk.review import identity, plan_quarantine
from folego.actions.disk.quarantine import Quarantine


def test_review_detects_deep_content_change(tmp_path):
    target = tmp_path / "cache"
    (target / "nested").mkdir(parents=True)
    payload = target / "nested/data"
    payload.write_bytes(b"old")
    reviewed = identity(target)
    payload.write_bytes(b"new work")
    assert identity(target) != reviewed
    assert payload.read_bytes() == b"new work"


@pytest.mark.parametrize("name", [".git", "credentials"])
def test_protected_tree_is_not_offered_as_an_action(tmp_path, name):
    target = tmp_path / "cache"
    target.mkdir()
    (target / name).write_bytes(b"protected")
    book = Quarantine(root=tmp_path / "retained", allowed_roots=[tmp_path])
    with pytest.raises(PermissionError, match="protegido"):
        plan_quarantine(target, book)
    assert (target / name).read_bytes() == b"protected"
    assert not book.root.exists()


def test_incomplete_or_symbolic_review_never_produces_a_plan(tmp_path):
    target = tmp_path / "cache"
    target.mkdir()
    (target / "data").write_bytes(b"keep")
    with pytest.raises(PermissionError, match="orçamento"):
        identity(target, max_entries=1)
    (target / "link").symlink_to(target / "data")
    with pytest.raises(PermissionError, match="simbólico"):
        identity(target)
    assert (target / "data").read_bytes() == b"keep"


def test_mount_identity_change_invalidates_evidence_without_host_mounts(tmp_path, monkeypatch):
    from pathlib import Path
    target = tmp_path / "cache"
    target.mkdir()
    initial = identity(target)
    original = Path.read_text
    def mount_changed(self, *args, **kwargs):
        text = original(self, *args, **kwargs)
        if str(self) == "/proc/self/mountinfo":
            text = "\n".join("999" + line for line in text.splitlines())
        return text
    monkeypatch.setattr(Path, "read_text", mount_changed)
    assert identity(target) != initial
    assert target.exists()
