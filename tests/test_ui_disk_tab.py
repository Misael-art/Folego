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
    payload = {"acao": "plan", "ok": True, "exit": 0, "digest": "d1",
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

    from folego.orchestration.models import ActionPlan, ResourceIdentity
    for item in payload["items"]:
        if item["reclaimable"]:
            item["action_plan"] = ActionPlan("disk.quarantine", ResourceIdentity.path(
                item["path"], dev=8, ino=42)).to_dict()
    return payload



from review_jobs import ReviewJobs


class FakeJobs(ReviewJobs):
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


def test_unknown_disk_result_preserves_reviewed_id_and_blocks_new_mutation(tab):
    view, jobs = tab
    view._reviewed_operation = "uncertain-disk"
    view._mutation_done({"ok": False, "outcome": "desconhecido", "reason": "filho caiu"})
    view.show_plan(plan_payload())
    view.table.selectRow(0)
    before = len(jobs.calls)
    view.quarantine_selected()
    view.restore_selected()
    view.purge_selected()
    assert len(jobs.calls) == before
    assert "uncertain-disk" in view.status.text() and "desconhecido" in view.status.text()
    assert not view.quarantine_button.isEnabled()


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


def test_the_tab_starts_as_not_analyzed_not_as_a_fake_job(qapp):
    view = DiskTab(jobs=FakeJobs(None, defer=True))
    assert "ainda não analisado" in view.summary.text()
    assert "consultando" not in view.summary.text()
    view.refresh()
    assert "consultando" in view.summary.text()


class RouteJobs(ReviewJobs):
    """Answers each action with its own payload and records the argv contract."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def run(self, acao, target, *, confirm=False, done):
        self.calls.append((acao, target, confirm))
        done(self.answers[acao])


def _quarantine_payload():
    return {"acao": "disk.list", "ok": True, "exit": 0, "outcome": "sucesso",
            "entries": [{
                "entry_id": "1700000000-deadbeef",
                "original": "/home/u/.cache/pip",
                "stored": "/home/u/.local/share/folego/quarantine/x",
                "bytes": 3 * GIB, "observed_bytes": 3 * GIB, "state": "stored",
                "moved_at": "2026-10-17T00:00:00Z", "action_id": "a",
            }],
            "reclaimable_bytes": 3 * GIB}


def test_quarantine_moves_the_selected_reclaimable_item_after_confirmation(qapp):
    jobs = RouteJobs({"plan": plan_payload(), "list": _quarantine_payload(),
                      "quarantine-reviewed": {"acao": "quarantine", "ok": True,
                                     "exit": 0, "outcome": "sucesso",
                                     "reason": None}})
    seen = []
    view = DiskTab(jobs=jobs, confirm_fn=lambda text: seen.append(text) or True)
    view.refresh()
    view.table.selectRow(0)  # pip, the biggest item

    view.quarantine_selected()

    assert jobs.calls[0] == ("plan", "disk", False)
    mutation = next(call for call in jobs.calls if call[0] == "quarantine-reviewed")
    reviewed = json.loads(mutation[1])
    assert reviewed == jobs.answers["plan"]["items"][1]["action_plan"]
    assert reviewed["operation_id"] in seen[0]
    assert mutation[2] is True
    assert "reversível" in seen[0] and "pip" in seen[0]
    assert "operação concluída" in view.status.text()
    # after the act the plan and the quarantine inventory are re-read
    assert [call[0] for call in jobs.calls[-2:]] == ["plan", "list"]


def test_a_cancelled_quarantine_does_not_spawn_a_mutation(qapp):
    jobs = RouteJobs({"plan": plan_payload(), "list": _quarantine_payload()})
    view = DiskTab(jobs=jobs, confirm_fn=lambda text: False)
    view.refresh()
    view.table.selectRow(0)

    view.quarantine_selected()

    assert not [call for call in jobs.calls if call[0].startswith("quarantine")]
    assert "Cancelado" in view.status.text()


def test_repeated_clicks_reuse_one_review_and_spawn_at_most_one_mutation(qapp):
    jobs = FakeJobs(defer=True)
    view = DiskTab(jobs=jobs, confirm_fn=lambda text: True)
    payload = plan_payload()
    view.show_plan(payload)
    view.table.selectRow(0)
    expected = view.rows[0]["action_plan"]
    view.quarantine_selected()
    view.quarantine_selected()
    assert len(jobs.calls) == 1
    assert jobs.calls[0][0] == "quarantine-reviewed"
    assert json.loads(jobs.calls[0][1]) == expected
    argv = plan_argv(*jobs.calls[0])
    assert json.loads(argv[argv.index("--reviewed-plan") + 1]) == expected


def test_restore_and_purge_are_offered_only_for_stored_entries(qapp):
    jobs = RouteJobs({"plan": plan_payload(), "list": _quarantine_payload(),
                      "restore": {"acao": "restore", "ok": True, "exit": 0,
                                  "outcome": "sucesso"},
                      "purge": {"acao": "purge", "ok": True, "exit": 0,
                                "outcome": "sucesso"}})
    seen = []
    view = DiskTab(jobs=jobs, confirm_fn=lambda text: seen.append(text) or True)
    view.refresh_quarantine()
    assert len(view.quarantine_rows) == 1
    assert view.restore_button.isEnabled() is False

    view.quarantine_table.selectRow(0)
    assert view.restore_button.isEnabled() and view.purge_button.isEnabled()
    view.restore_selected()
    assert ("restore", "1700000000-deadbeef", True) in jobs.calls
    assert "volta ao caminho original" in seen[0]

    view.quarantine_table.selectRow(0)
    view.purge_selected()
    assert ("purge", "1700000000-deadbeef", True) in jobs.calls
    assert "IRREVERSÍVEL" in seen[1]


def test_an_unreadable_quarantine_offers_no_restore(qapp):
    jobs = RouteJobs({"plan": plan_payload(),
                      "list": {"acao": "disk.list", "ok": False, "exit": 1,
                               "outcome": "recusa", "reason": "manifesto ilegível"}})
    view = DiskTab(jobs=jobs)
    view.refresh()
    view.refresh_quarantine()

    assert view.quarantine_rows == []
    assert view.restore_button.isEnabled() is False
    assert view.purge_button.isEnabled() is False
    assert "ilegível" in view.quarantine_summary.text()


def test_the_argv_for_list_and_mutations_is_machine_readable():
    assert plan_argv("list", "quarantine", False) == [
        sys.executable, "-m", "folego", "disk", "list", "--json"]
    assert plan_argv("quarantine", "/home/u/.cache/pip", True) == [
        sys.executable, "-m", "folego", "disk", "quarantine",
        "/home/u/.cache/pip", "--json", "--confirmar"]
    purge = plan_argv("purge", "entry-1", True)
    assert purge[-2:] == ["--confirmar", "--irreversivel"]
    assert "--json" in purge


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
