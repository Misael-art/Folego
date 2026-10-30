import json
import time

from folego.ui.options_tab import OptionsTab
from folego.ui.tune_jobs import TuneJobs
from test_ui_tune_jobs import sandbox, pump


def test_options_defaults_on_and_can_disable_without_changing_effect_policy(qapp):
    class Jobs:
        calls = []
        def run(self, action, target, **kwargs): self.calls.append(action)
        def shutdown(self): pass
    jobs = Jobs()
    tab = OptionsTab(jobs=jobs)
    assert tab.choice.isChecked()
    tab.choice.click()
    assert jobs.calls == ["startup-disable"]
    tab.done({"enabled":False,"outcome":"sucesso","reason":"saved"})
    assert not tab.choice.isChecked()


def test_real_review_queue_confirms_exact_id_then_applies_once(qapp, sandbox):
    jobs = TuneJobs(env=sandbox, timeout_ms=10000)
    asked, result = [], []
    try:
        jobs.review_and_run("apply", "edge.startup_boost", title="Confirmar", text="Revisar",
            confirm_fn=lambda title, text: asked.append(text) or True, done=result.append)
        assert pump(qapp, lambda: bool(result), timeout_ms=15000)
        assert result[0]["ok"], result
        assert result[0]["operation_id"] in asked[0]
        assert "Alvos da revisão atual:" in asked[0]
        from pathlib import Path
        path = Path(sandbox["HOME"]) / ".config/microsoft-edge/Local State"
        assert json.loads(path.read_text())["startup_boost"]["enabled"] is False
    finally:
        jobs.shutdown()


def test_real_review_declined_never_changes_fixture(qapp, sandbox):
    jobs = TuneJobs(env=sandbox, timeout_ms=10000)
    result = []
    try:
        jobs.review_and_run("apply", "edge.startup_boost", title="Confirmar", text="Revisar",
                            confirm_fn=lambda *_: False, done=result.append)
        assert pump(qapp, lambda: bool(result), timeout_ms=15000)
        assert result[0]["outcome"] == "cancelamento", result
        from pathlib import Path
        path = Path(sandbox["HOME"]) / ".config/microsoft-edge/Local State"
        assert json.loads(path.read_text())["startup_boost"]["enabled"] is True
    finally:
        jobs.shutdown()


def test_changed_frontend_scope_is_refused_before_confirmation(qapp, sandbox):
    jobs = TuneJobs(env=sandbox, timeout_ms=10000)
    result, asked = [], []
    try:
        jobs.review_and_run("apply", "edge.startup_boost", title="Confirmar", text="Revisar",
            expected_scope=[{"key":"/old/list/path"}],
            confirm_fn=lambda *args: asked.append(args) or True, done=result.append)
        assert pump(qapp, lambda: bool(result), timeout_ms=15000)
        assert not asked and result[0]["outcome"] == "recusa"
        from pathlib import Path
        path = Path(sandbox["HOME"]) / ".config/microsoft-edge/Local State"
        assert json.loads(path.read_text())["startup_boost"]["enabled"] is True
    finally: jobs.shutdown()


def test_options_cannot_verify_an_answer_for_another_operation(qapp):
    class Jobs:
        def run(self, *args, **kwargs): pass
        def shutdown(self): pass
    tab = OptionsTab(jobs=Jobs())
    verified = []
    tab.operation_verified.connect(verified.append)
    tab.operation_result("expected", {"operation_id":"foreign","outcome":"sucesso"})
    assert not verified and "outro código" in tab.operation_status.text()
    tab.operation_result("expected", {"operation_id":"expected","outcome":"sucesso","reason":"verified"})
    assert verified[0]["operation_id"] == "expected"


def test_late_option_responses_cannot_touch_deleted_widgets(qapp):
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid
    class Jobs:
        callbacks = []
        def run(self, *args, **kwargs): self.callbacks.append(kwargs["done"])
        def shutdown(self): pass
    jobs = Jobs()
    tab = OptionsTab(jobs=jobs)
    tab.start()
    tab.stop()
    tab.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(tab)
    for done in jobs.callbacks:
        done({"enabled":True,"pending":[],"runs":1,"limit":256})


def test_large_confirmation_stays_scrollable_and_defaults_to_cancel(qapp):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QPlainTextEdit, QDialogButtonBox
    from folego.ui.confirmation import confirm_text
    text = "\n".join(f"/fixture/<literal>/{index}" for index in range(64))
    failures = []
    def inspect():
        dialog = QApplication.activeModalWidget()
        try:
            assert dialog.height() <= 480
            assert dialog.findChild(QPlainTextEdit).toPlainText() == text
            buttons = dialog.findChild(QDialogButtonBox)
            assert buttons.button(QDialogButtonBox.StandardButton.No).isDefault()
        except Exception as exc:
            failures.append(repr(exc))
        finally:
            if dialog is not None: dialog.reject()
    QTimer.singleShot(0, inspect)
    assert confirm_text("Revisão", text) is False
    assert not failures
