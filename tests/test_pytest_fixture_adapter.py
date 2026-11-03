import os
import pwd

from folego.actions.tmpfs.holders import HolderIndex
from folego.adapters.pytest_fixtures import PytestFixtureAdapter


def tree(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    root = runtime / "codex-desktop/tmp" / f"pytest-of-{pwd.getpwuid(os.getuid()).pw_name}"
    root.mkdir(parents=True, mode=0o700)
    for number in range(1, 5):
        (root / f"pytest-{number}").mkdir()
        (root / f"pytest-{number}/payload").write_bytes(b"preserve")
    return runtime, root


def test_current_locked_and_mapped_fixtures_stay_protected(tmp_path):
    runtime, root = tree(tmp_path)
    (root / "pytest-current").symlink_to("pytest-1")
    (root / "pytest-2/.lock").write_text("123")
    holders = HolderIndex({str(root / "pytest-3/payload"): (123,)}, 1, 0)
    seen = []
    def references(**kwargs):
        seen.append(kwargs)
        return holders
    result = PytestFixtureAdapter(runtime=runtime, holders_fn=references).inventory()
    assert result.available and not result.error
    states = [item.detail["state"] for item in result.items]
    assert states == ["current", "locked", "referenced", "legacy_review"]
    assert all(item.protected and not item.detail["automatic_eligible"] for item in result.items)
    assert seen[0]["include_process_refs"] is True
    assert all((root / f"pytest-{n}/payload").read_bytes() == b"preserve" for n in range(1, 5))


def test_changed_pytest_current_is_seen_on_next_review_without_removal(tmp_path):
    runtime, root = tree(tmp_path)
    current = root / "pytest-current"
    current.symlink_to("pytest-1")
    adapter = PytestFixtureAdapter(runtime=runtime, holders_fn=lambda **kw: HolderIndex({}, 1, 0))
    first = adapter.inventory()
    current.unlink()
    current.symlink_to("pytest-4")
    second = adapter.inventory()
    assert first.items[0].detail["state"] == "current"
    assert second.items[3].detail["state"] == "current"
    assert all(item.protected for item in second.items)
    assert (root / "pytest-1/payload").read_bytes() == b"preserve"


def test_opaque_proc_never_becomes_unused(tmp_path):
    runtime, root = tree(tmp_path)
    result = PytestFixtureAdapter(runtime=runtime, holders_fn=lambda **kw:
        HolderIndex({}, 1, 0, "partial", ("maps denied",))).inventory()
    assert all(item.detail["state"] == "unknown" for item in result.items)


def test_symbolic_fixture_root_is_not_followed(tmp_path):
    runtime, root = tree(tmp_path)
    original = root.with_name("preserved")
    root.rename(original)
    root.symlink_to(original, target_is_directory=True)
    result = PytestFixtureAdapter(runtime=runtime).inventory()
    assert not result.available
    assert (original / "pytest-1/payload").read_bytes() == b"preserve"


def test_fixture_inventory_is_reachable_from_cli_without_effects(tmp_path, monkeypatch, capsys):
    import json
    from folego import cli
    runtime, root = tree(tmp_path)
    adapter = PytestFixtureAdapter(runtime=runtime, holders_fn=lambda **kw: HolderIndex({}, 1, 0))
    monkeypatch.setattr(cli, "default_adapters", lambda: (adapter,))
    assert cli.main(["ecosystem", "--adapter", "pytest-fixtures", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["adapters"][0]["items"]) == 4
    assert all(item["protected"] for item in payload["adapters"][0]["items"])
    assert (root / "pytest-1/payload").read_bytes() == b"preserve"
