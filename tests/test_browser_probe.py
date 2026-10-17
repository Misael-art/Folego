"""M2 guard probe: is the browser that owns this file actually running?

Edge rewrites Local State when it exits, so a tuning applied while it runs is
undone without a trace. The probe has to answer "open" only for the real browser:
the crashpad helper is alive from boot, and counting it would make the guard
refuse forever. Identity comes from the executable, not from comm or flags — the
same lesson the orphan scanner learned the hard way.
"""
import pytest

from folego.core.browser import edge_running
from fixtures_proc import build_proc


@pytest.fixture
def proc(fake_proc):
    def build(*pids):
        build_proc(fake_proc, pids=pids)
        return fake_proc
    return build


def test_a_running_browser_is_named_with_its_pid(proc):
    root = proc(dict(pid=4321, comm="msedge", uid=1000,
                     cmdline=["/opt/microsoft/msedge/msedge", "--profile-directory=Default"]))

    who = edge_running(proc_root=root, uid=1000)

    assert who is not None and "4321" in who and "msedge" in who


def test_no_browser_process_means_the_file_is_safe_to_write(proc):
    root = proc(dict(pid=10, comm="systemd", uid=1000),
                dict(pid=20, comm="kwin", uid=1000))

    assert edge_running(proc_root=root, uid=1000) is None


def test_the_crashpad_handler_is_alive_from_boot_and_is_not_the_browser(proc):
    root = proc(dict(pid=900, comm="msedge_crashp", uid=1000,
                     cmdline=["/opt/microsoft/msedge/msedge_crashpad_handler", "--no-monitor"]))

    assert edge_running(proc_root=root, uid=1000) is None


def test_a_chromium_browser_is_not_our_edge(proc):
    root = proc(dict(pid=700, comm="chrome", uid=1000,
                     cmdline=["/opt/google/chrome/chrome", "--profile-directory=Default"]))

    assert edge_running(proc_root=root, uid=1000) is None


def test_a_browser_owned_by_another_user_is_not_the_one_we_would_write(proc):
    root = proc(dict(pid=800, comm="msedge", uid=999,
                     cmdline=["/opt/microsoft/msedge/msedge"]))

    assert edge_running(proc_root=root, uid=1000) is None


def test_the_packagename_spelling_counts_too(proc):
    root = proc(dict(pid=810, comm="microsoft-edge", uid=1000,
                     cmdline=["/usr/lib/microsoft-edge/microsoft-edge"]))

    assert edge_running(proc_root=root, uid=1000) is not None
