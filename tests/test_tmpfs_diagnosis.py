from types import SimpleNamespace

from folego.actions.tmpfs import diagnosis


def fake_proc(tmp_path, procs):
    """procs: {pid: (comm, ppid, cmdline)} written as a minimal /proc."""
    for pid, (comm, ppid, cmdline) in procs.items():
        base = tmp_path / str(pid)
        base.mkdir()
        (base / "stat").write_text(f"{pid} ({comm}) S {ppid} 0 0\n")
        (base / "comm").write_text(comm + "\n")
        (base / "cmdline").write_text("\0".join(cmdline.split()) + "\0")
    return str(tmp_path)


def item(path, size, pids=(), kind="file", reason="refused: aberto"):
    return SimpleNamespace(path=path, bytes=size, holder_pids=pids, kind=kind, reason=reason)


def test_an_emulator_under_an_adopted_sandbox_is_reported_as_an_orphaned_tree(tmp_path):
    proc = fake_proc(tmp_path, {
        1531: ("systemd", 1, "/usr/lib/systemd/systemd --user"),
        1915380: ("bwrap", 1531, "bwrap --args 68 -- sh"),
        1915395: ("bwrap", 1915380, "bwrap --args 68 -- sh"),
        1915399: ("blastem.bin", 1915395, "/app/bin/blastem.bin -r U sess.bin"),
    })
    holder = diagnosis.describe_process(1915399, proc_root=proc)
    assert holder.adopted
    assert holder.tree_root.startswith("bwrap")
    assert holder.parent.startswith("bwrap")


def test_a_process_under_a_live_terminal_is_not_orphaned(tmp_path):
    proc = fake_proc(tmp_path, {
        1531: ("systemd", 1, "/usr/lib/systemd/systemd --user"),
        800: ("konsole", 1531, "/usr/bin/konsole"),
        900: ("bash", 800, "/bin/bash"),
    })
    # konsole itself is a direct child of the user manager: that is how desktop apps live;
    # what matters is the chain, which is reported, never turned into a signal.
    holder = diagnosis.describe_process(900, proc_root=proc)
    assert holder.tree_root == "/usr/bin/konsole"


def test_diagnose_orders_by_size_names_the_owner_and_skips_empty_entries(tmp_path):
    proc = fake_proc(tmp_path, {1531: ("systemd", 1, "/usr/lib/systemd/systemd --user"),
                                42: ("blastem.bin", 1531, "blastem")})
    entries = [item("/run/user/1000/blesh", 1000),
               item("/run/user/1000/forge-sessions", 1_500_000_000, (42,), kind="dir"),
               item("/run/user/1000/bus", 0)]
    walked = []
    found = diagnosis.diagnose(entries, proc_root=proc,
                               walk=lambda path: walked.append(path) or (("big", 10),))
    assert [c.path for c in found] == ["/run/user/1000/forge-sessions", "/run/user/1000/blesh"]
    forge = found[0]
    assert forge.owner == "SGDKForge session_coordinator"
    assert "session_coordinator.py stop" in forge.official_action
    assert forge.holders[0].pid == 42 and forge.holders[0].adopted
    assert walked == ["/run/user/1000/forge-sessions"]
    assert found[1].largest_files == (("/run/user/1000/blesh", 1000),)


def test_a_vanished_holder_is_dropped_not_invented(tmp_path):
    found = diagnosis.diagnose([item("/tmp/x", 10, (99999,))], proc_root=str(tmp_path))
    assert found[0].holders == ()


def test_largest_files_does_not_follow_links(tmp_path):
    (tmp_path / "a").write_bytes(b"x" * 10)
    (tmp_path / "b").write_bytes(b"x" * 30)
    outside = tmp_path.parent / "outside-target"
    outside.write_bytes(b"x" * 100)
    (tmp_path / "link").symlink_to(outside)
    result = diagnosis.largest_files(str(tmp_path))
    assert [size for _, size in result] == [30, 10]
    outside.unlink()
