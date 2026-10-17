"""M3 tunings tab: state comes from the child, and a click only follows a verdict.

The tab never reads the browser's files itself — it asks the worker and prints
what came back. That is what makes the confirmation path testable: a fake jobs
object can answer with exactly the payloads the real worker produces.
"""
import pytest

from folego.actions.tunings.registry import TUNINGS
from folego.ui.tunings_tab import TuningsTab

pytest.importorskip("PySide6")


class FakeJobs:
    """Stands in for the QProcess layer; answers synchronously unless deferred."""

    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}
        self.defer = False
        self.pending = []

    def run(self, acao, tuning_id, *, confirm=False, done):
        self.calls.append((acao, tuning_id, confirm))
        if self.defer:
            self.pending.append((acao, tuning_id, done))
            return
        done(self.answers.get(f"{acao}:{tuning_id}") or
             self.answers.get(acao) or
             {"acao": acao, "ok": True, "exit": 0, "changed": True})

    def flush(self, acao, tuning_id, payload):
        for index, (a, t, done) in enumerate(self.pending):
            if (a, t) == (acao, tuning_id):
                del self.pending[index]
                done(payload)
                return

    def payload(self, tuning, **over):
        base = {"acao": "detect", "ok": True, "exit": 0, "exists": True,
                "present": True, "current": True, "desired": False,
                "change_needed": True, "error": None,
                "file": f"/home/u/{tuning.id}", "key": tuning.key,
                "label": tuning.label, "why": tuning.why}
        base.update(over)
        return base


@pytest.fixture
def built(qapp):
    def build(answers=None, confirm=True):
        jobs = FakeJobs(answers or {})
        asked = []

        def confirm_fn(title, text):
            asked.append((title, text))
            return confirm

        tab = TuningsTab(jobs=jobs, confirm_fn=confirm_fn)
        return tab, jobs, asked
    return build


def test_refresh_asks_the_child_about_every_tuning(built):
    tab, jobs, _ = built()
    tab.refresh()
    assert [c for c in jobs.calls if c[0] == "detect"] == \
        [("detect", t.id, False) for t in TUNINGS]


def test_a_row_waits_for_its_child_before_offering_anything(built):
    tab, jobs, _ = built()
    jobs.defer = True
    tab.refresh()
    assert tab.rows[0].state_label.text() == "consultando…"
    assert not tab.rows[0].apply_button.isEnabled()
    jobs.flush("detect", TUNINGS[0].id, jobs.payload(TUNINGS[0]))
    assert tab.rows[0].apply_button.isEnabled()


def test_a_row_is_only_actionable_once_its_verdict_arrives(built):
    tab, jobs, _ = built()
    assert not tab.rows[0].apply_button.isEnabled()
    tab.refresh()
    tab.show_detect(TUNINGS[0], jobs.payload(TUNINGS[0]))
    assert tab.rows[0].apply_button.isEnabled()
    assert "ligado" in tab.rows[0].state_label.text()


def test_nothing_is_already_economical_and_says_so(built):
    tab, jobs, _ = built()
    tab.show_detect(TUNINGS[0], jobs.payload(TUNINGS[0], current=False,
                                             change_needed=False))
    assert "já econômico" in tab.rows[0].state_label.text()
    assert not tab.rows[0].apply_button.isEnabled()


def test_an_unreadable_file_is_reported_instead_of_hidden(built):
    tab, jobs, _ = built()
    tab.show_detect(TUNINGS[0], jobs.payload(TUNINGS[0], exists=False, present=False,
                                             change_needed=False,
                                             error="Local State não existe em /x"))
    assert "não existe" in tab.rows[0].state_label.text()
    assert not tab.rows[0].apply_button.isEnabled()


def test_a_denied_confirmation_never_reaches_the_child(built):
    tab, jobs, asked = built(confirm=False)
    tab.show_detect(TUNINGS[0], jobs.payload(TUNINGS[0]))
    tab.rows[0].apply_button.click()
    assert asked and "Edge" in asked[0][1]
    assert ("apply", TUNINGS[0].id, True) not in jobs.calls


def test_a_confirmed_apply_carries_the_flag_and_shows_the_verdict(built):
    tab, jobs, _ = built(answers={"apply": {"acao": "apply", "ok": True, "exit": 0,
                                            "changed": True, "sha": "abc123",
                                            "backup_id": "tunings.x/1-2",
                                            "file": "/home/u/Default/Preferences",
                                            "plan": {"before_sha": "old",
                                                     "after_sha": "abc123",
                                                     "blocked": None}}})
    tab.show_detect(TUNINGS[0], jobs.payload(TUNINGS[0]))
    tab.rows[0].apply_button.click()
    assert jobs.calls[-1] == ("apply", TUNINGS[0].id, True)
    assert "aplicado" in tab.rows[0].verdict.text()
    assert "abc123" in tab.rows[0].verdict.text()
    assert "tunings.x/1-2" in tab.rows[0].verdict.text()


def test_a_refusal_is_written_in_the_row_not_swallowed(built):
    tab, jobs, _ = built(answers={"apply": {"acao": "apply", "ok": False, "exit": 1,
                                            "changed": False, "backup_id": None,
                                            "sha": None, "file": "/x",
                                            "reason": "recusado: o Microsoft Edge está "
                                                     "aberto (pid 4321)"}})
    tab.show_detect(TUNINGS[0], jobs.payload(TUNINGS[0]))
    tab.rows[0].apply_button.click()
    assert "Edge está aberto" in tab.rows[0].verdict.text()
    assert "4321" in tab.rows[0].verdict.text()


def test_revert_is_confirmed_separately_and_restores(built):
    tab, jobs, asked = built(answers={"revert": {"acao": "revert", "ok": True,
                                                 "exit": 0, "sha": "deadbeef",
                                                 "backup_id": "tunings.x/1-2",
                                                 "file": "/x"}})
    tab.show_detect(TUNINGS[0], jobs.payload(TUNINGS[0]))
    assert tab.rows[0].revert_button.isEnabled(), "com veredicto lido, reverter pode ser pedido"
    tab.rows[0].revert_button.click()
    assert jobs.calls[-1] == ("revert", TUNINGS[0].id, True)
    assert "restaurado" in tab.rows[0].verdict.text() and "deadbeef" in tab.rows[0].verdict.text()


def test_a_tuning_the_browser_undoes_is_flagged_for_reapplying(built):
    tab, jobs, _ = built(answers={"apply": {"acao": "apply", "ok": True, "exit": 0,
                                            "changed": True, "sha": "abc",
                                            "backup_id": "b/1", "file": "/x"}})
    tab.show_detect(TUNINGS[0], jobs.payload(TUNINGS[0]))
    tab.rows[0].apply_button.click()
    tab.show_detect(TUNINGS[0], jobs.payload(TUNINGS[0], current=True))
    assert "sobrescrito — reaplicar" in tab.rows[0].state_label.text()


def test_refresh_mutates_nothing(built):
    tab, jobs, _ = built()
    tab.refresh()
    assert set(c[0] for c in jobs.calls) == {"detect"}
