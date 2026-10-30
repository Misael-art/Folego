import os
from pathlib import Path

import pytest

from folego import shortcuts


def make_exe(tmp_path, name="run.sh"):
    exe = tmp_path / "app" / name
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return exe


def locations(tmp_path):
    menu, desk = tmp_path / "share/applications", tmp_path / "Área de trabalho"
    desk.mkdir()
    return (("menu", menu), ("desktop", desk))


def test_missing_shortcuts_are_created_executable_and_marked(tmp_path):
    exe = make_exe(tmp_path)
    states = shortcuts.ensure(executable=exe, locations=locations(tmp_path))
    assert [s.status for s in states] == ["created", "created"]
    for state in states:
        text = Path(state.path).read_text()
        assert f'Exec="{exe}"' in text and f"TryExec={exe}" in text and shortcuts.MARKER in text
        assert os.access(state.path, os.X_OK)


def test_second_run_is_a_no_op(tmp_path):
    exe = make_exe(tmp_path)
    where = locations(tmp_path)
    shortcuts.ensure(executable=exe, locations=where)
    before = {s.path: os.stat(s.path).st_mtime_ns for s in shortcuts.ensure(executable=exe, locations=where)}
    states = shortcuts.ensure(executable=exe, locations=where)
    assert [s.status for s in states] == ["present", "present"]
    assert {s.path: os.stat(s.path).st_mtime_ns for s in states} == before


def test_a_moved_installation_refreshes_only_our_own_shortcut(tmp_path):
    where = locations(tmp_path)
    shortcuts.ensure(executable=make_exe(tmp_path, "old.sh"), locations=where)
    user_file = where[1][1] / shortcuts.FILENAME
    user_file.write_text("[Desktop Entry]\nName=Meu Fôlego\nExec=custom\n")
    new = make_exe(tmp_path, "new.sh")
    states = {s.location: s for s in shortcuts.ensure(executable=new, locations=where)}
    assert states["menu"].status == "updated"
    assert f'Exec="{new}"' in Path(states["menu"].path).read_text()
    assert states["desktop"].status == "preserved"
    assert user_file.read_text() == "[Desktop Entry]\nName=Meu Fôlego\nExec=custom\n"


def test_symlinks_and_missing_desktop_folder_are_not_touched(tmp_path):
    exe = make_exe(tmp_path)
    menu = tmp_path / "share/applications"
    menu.mkdir(parents=True)
    other = tmp_path / "elsewhere.desktop"
    other.write_text("x")
    (menu / shortcuts.FILENAME).symlink_to(other)
    states = shortcuts.ensure(executable=exe, locations=(("menu", menu), ("desktop", tmp_path / "nope")))
    assert [s.status for s in states] == ["preserved", "skipped"]
    assert other.read_text() == "x" and not (tmp_path / "nope").exists()


def test_unsafe_paths_and_missing_executable_create_nothing(tmp_path, monkeypatch):
    where = locations(tmp_path)
    bad = make_exe(tmp_path, 'we"ird.sh')
    with pytest.raises(ValueError):
        shortcuts.entry_text(bad)
    monkeypatch.setattr(shortcuts, "launcher_executable", lambda: None)
    states = shortcuts.ensure(locations=where)
    assert {s.status for s in states} == {"skipped"}
    assert not list(where[0][1].parent.glob("**/*.desktop")) and not list(where[1][1].iterdir())


def test_desktop_dir_follows_localized_user_dirs_and_never_autostart(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg/user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/Área de trabalho"\n')
    assert shortcuts.desktop_dir() == tmp_path / "Área de trabalho"
    (tmp_path / "cfg/user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/"\n')
    assert shortcuts.desktop_dir() == tmp_path / "Desktop"
    (tmp_path / "Desktop").mkdir()
    shortcuts.ensure(executable=make_exe(tmp_path))
    assert not (tmp_path / "cfg/autostart").exists()


def test_template_matches_the_packaged_desktop_entry():
    packaged = (Path(__file__).resolve().parents[1] / "packaging/folego.desktop").read_text().splitlines()
    ours = shortcuts.TEMPLATE.splitlines()
    strip = lambda lines: [l for l in lines if not l.startswith(("Exec=", "TryExec=", "{marker}"))]
    assert strip(ours) == strip(packaged)


def test_checkout_launcher_is_run_sh():
    exe = shortcuts.launcher_executable()
    assert exe is not None and exe.name in {"run.sh", "folego"}


def test_installed_module_child_finds_venv_entrypoint_without_shell_path(tmp_path, monkeypatch):
    executable = make_exe(tmp_path, "folego")
    monkeypatch.setattr(shortcuts, "__file__", str(tmp_path / "site-packages/folego/shortcuts.py"))
    monkeypatch.setattr(shortcuts.sys, "executable", str(executable.with_name("python")))
    monkeypatch.setattr(shortcuts.sys, "argv", [str(tmp_path / "site-packages/folego/__main__.py")])
    monkeypatch.setattr(shortcuts.shutil, "which", lambda _: None)
    assert shortcuts.launcher_executable() == executable
