"""M3 disk tab: the M5 dry-run plan, shown as text the UI did not compute.

The plan comes from a child running the same headless CLI the terminal uses, so
the tab cannot accidentally grow its own filesystem code: it formats, it does not
measure. Refused targets stay visible — the guard saying "no" is information.
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

from folego.ui.disk_tab import DiskTab, plan_argv

pytest.importorskip("PySide6")

REPO = pathlib.Path(__file__).resolve().parent.parent
GIB = 1024 ** 3


def plan_payload():
    return {"acao": "plan", "ok": True, "exit": 0, "digest": "d1",
            "total_bytes": 5 * GIB, "scanned_bytes": 6 * GIB,
            "volumes": [{"mount": "/", "total_bytes": 465 * GIB,
                         "free_bytes": 159 * GIB, "used_frac": 0.68}],
            "items": [
                {"target_id": "thumbnails", "label": "Miniaturas",
                 "path": "/home/u/.cache/thumbnails", "bytes": 2 * GIB,
                 "files": 900, "age_days": 3.0, "reclaimable": True, "reason": "ok",
                 "errors": [], "truncated": False},
                {"target_id": "pip", "label": "Cache do pip", "path": "/home/u/.cache/pip",
                 "bytes": 3 * GIB, "files": 40, "age_days": 10.0,
                 "reclaimable": True, "reason": "ok", "errors": [], "truncated": False},
                {"target_id": "stale-caches", "label": "Caches antigos do usuário",
                 "path": "/mnt/sdcard/cache", "bytes": 0, "files": 0, "age_days": 0.0,
                 "reclaimable": False,
                 "reason": "refused: path is under blacklisted prefix /mnt",
                 "errors": [], "truncated": False},
            ]}


class FakeJobs:
    def __init__(self, answer=None, defer=False):
        self.calls = []
        self.answer = answer
        self.defer = defer
        self.pending = []

    def run(self, acao, tuning_id, *, confirm=False, done):
        self.calls.append((acao, tuning_id, confirm))
        if self.defer:
            self.pending.append(done)
            return
        done(self.answer)


@pytest.fixture
def tab(qapp):
    jobs = FakeJobs(plan_payload())
    view = DiskTab(jobs=jobs)
    return view, jobs


def test_the_tab_asks_the_child_for_a_dry_run_plan(tab):
    view, jobs = tab
    view.refresh()
    assert jobs.calls == [("plan", "disk", False)]
    assert view.status.text() != ""


def test_items_are_listed_biggest_first_with_their_size(tab):
    view, jobs = tab
    view.refresh()
    labels = [row["path"] for row in view.rows]
    assert labels == ["/home/u/.cache/pip", "/home/u/.cache/thumbnails",
                      "/mnt/sdcard/cache"]
    assert "3,0 GB" in view.rows[0]["size"]


def test_the_row_carries_the_raw_number_so_a_check_can_reconcile_it(tab):
    """The live verifier compares the tab against ``du``; text sizes cannot be
    compared without parsing them back, which would re-introduce the unit bug."""
    view, jobs = tab
    view.refresh()
    assert [row["bytes"] for row in view.rows] == [3 * GIB, 2 * GIB, 0]


def test_the_refused_target_is_shown_as_refused_not_dropped(tab):
    view, jobs = tab
    view.refresh()
    assert "blacklisted prefix /mnt" in view.rows[-1]["reason"]


def test_the_total_is_the_reclaimable_one_not_everything_read(tab):
    view, jobs = tab
    view.refresh()
    assert "5,0 GB" in view.summary.text()


def test_a_cache_too_young_to_free_says_so_instead_of_ok(qapp):
    """84 GB marked "ok" but not reclaimable would read like a bug: the row has
    to tell the user why the plan is holding off."""
    payload = {"acao": "plan", "ok": True, "exit": 0, "digest": "d",
               "total_bytes": 0, "scanned_bytes": GIB, "volumes": [],
               "items": [{"target_id": "stale-caches", "label": "Caches antigos",
                          "path": "/home/u/.cache/novo", "bytes": GIB, "files": 5,
                          "age_days": 4.0, "reclaimable": False, "reason": "ok",
                          "errors": [], "truncated": False},
                         {"target_id": "trash", "label": "Lixeira",
                          "path": "/home/u/.local/share/trash", "bytes": 0,
                          "files": 0, "age_days": 0.0, "reclaimable": False,
                          "reason": "ok", "errors": [], "truncated": False}]}
    view = DiskTab(jobs=FakeJobs(payload))
    view.refresh()
    assert [row["state"] for row in view.rows] == ["intacto há 4 dias", "vazio"]


def test_a_child_that_never_answers_leaves_no_fake_numbers(qapp):
    jobs = FakeJobs({"acao": "plan", "ok": False, "exit": 1,
                     "reason": "o filho não respondeu"})
    view = DiskTab(jobs=jobs)
    view.refresh()
    assert view.rows == []
    assert "não respondeu" in view.status.text()
    assert view.thumbnails_kb is None


def test_thumbnails_are_measured_for_the_dashboard(tab):
    view, jobs = tab
    view.refresh()
    assert view.thumbnails_kb == 2 * GIB // 1024


def test_a_plan_that_has_not_landed_measures_nothing(qapp):
    view = DiskTab(jobs=FakeJobs(None, defer=True))
    view.refresh()
    assert view.thumbnails_kb is None


def test_the_argv_the_tab_spawns_answers_with_one_json_line(fake_home):
    """A module without a main guard exits 0 and prints nothing — the deployed
    tab would then say "sem plano" forever. This runs the real command."""
    argv = plan_argv("plan", "disk", False)
    assert argv[:3] == [sys.executable, "-m", "folego"], argv

    result = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                            env=dict(os.environ, PYTHONPATH=str(REPO / "src")))
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.strip().splitlines()) == 1
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert set(payload) >= {"digest", "total_bytes", "scanned_bytes", "items", "volumes"}
    # a fresh home has nothing to reclaim: every target is a refusal, not a number
    assert payload["total_bytes"] == 0
    assert payload["items"] and not [i for i in payload["items"] if i["reclaimable"]]
    assert not pathlib.Path(fake_home / ".cache").exists(), "planear não pode criar nada"
