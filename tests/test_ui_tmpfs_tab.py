"""M7 na janela: a aba mostra o que o filho respondeu e não move nada sozinha.

O contrato é o do `disk_tab`: entram tuplas planas vindas do poller, sai argv de
filho matável. Nada aqui abre /proc, varre árvore ou escreve byte — e o ETA é
extrapolação das amostras que a própria aba guardou, nunca uma promessa.
"""
import sys

import pytest

from deck_wellness.core.tmpfs import TmpfsVolume
from deck_wellness.ui.tmpfs_tab import (LEDGER_COLUMNS, PLAN_COLUMNS, VOLUME_COLUMNS,
                                        TmpfsTab, argv_for)

pytest.importorskip("PySide6")

GIB = 1024 ** 3


def col(columns, key):
    return [k for k, _ in columns].index(key)


class FakeJobs:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def run(self, acao, target, *, confirm=False, done):
        self.calls.append((acao, target, confirm))
        done(self.answers(acao, target))

    def shutdown(self):
        self.calls.append(("shutdown", "*", False))


def plan_item(**over):
    base = {"item_id": "a" * 16, "path": "/tmp/qoder-cli-1000", "name": "qoder-cli-1000",
            "volume": "/tmp", "kind": "dir", "uid": 1000, "bytes": 4096, "files": 1,
            "age_days": 10.0, "holder_pids": [1234], "ok": True,
            "reason": "liberável: casado com /tmp/qoder-cli-1000",
            "matched": "/tmp/qoder-cli-1000", "truncated": False, "errors": []}
    base.update(over)
    return base


def plan_payload(acao="plan", target=""):
    refused = plan_item(item_id="b" * 16, path="/tmp/.X11-unix", name=".X11-unix",
                        ok=False, reason="refused: fora da allow-list de sujeira "
                                         "de agente", matched=None, holder_pids=[],
                        bytes=2048, files=1, age_days=9.0)
    return {"acao": acao, "ok": True, "exit": 0, "generated_at": "2026-10-15T00:00:00Z",
            "volumes": [], "policy": {},
            "reclaimable": [plan_item()], "protected": [refused],
            "total_bytes": 4096, "scanned_entries": 2, "scanned_bytes": 6144,
            "digest": "d" * 64, "errors": []}


def ledger_payload(acao="ledger", target=""):
    return {"acao": acao, "ok": True, "exit": 0,
            "records": [{"ts": "2026-10-01T00:00:00Z", "entry_id": "1700-abc",
                         "src": "/tmp/qoder-cli-1000", "volume": "/tmp",
                         "stored": "/home/u/.local/share/deck-wellness/tmp-quarantine/x",
                         "bytes": 4096, "sha256": "a" * 64, "age_days": 30.0,
                         "matched_pattern": "/tmp/qoder-cli-1000", "holder_pids": [1234],
                         "state": "released", "action_id": "tmpfs.release",
                         "audit_event_id": "e" * 32}],
            "budget": {"retained_bytes": 4096, "retained_count": 1, "oldest_days": 30.0,
                       "slack_bytes": 5 * GIB, "freed_bytes": 4096,
                       "by_volume": {"/tmp": 4096}, "max_bytes": 3 * GIB, "days": 14.0}}


def mutation_payload(acao="release", target=""):
    return {"acao": acao, "ok": True, "exit": 0, "entry_id": "1700-abc", "reason": "ok",
            "bytes": 4096, "stored": "/ssd/1700-abc", "sha256": "a" * 64,
            "freed_bytes": 4096, "restored_to": "/tmp/qoder-cli-1000", "victims": [],
            "errors": []}


ANSWERS = {"plan": plan_payload, "ledger": ledger_payload, "release": mutation_payload,
           "restore": mutation_payload, "expire": mutation_payload}


def answers(acao, target):
    return ANSWERS[acao](acao, target)


@pytest.fixture
def jobs():
    return FakeJobs(answers)


@pytest.fixture
def tab(qapp, jobs):
    return TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)


def test_argv_is_the_same_headless_cli_a_tty_would_run():
    assert argv_for("plan") == [sys.executable, "-m", "deck_wellness", "tmpfs", "plan",
                                 "--json"]
    assert argv_for("ledger") == [sys.executable, "-m", "deck_wellness", "tmpfs",
                                  "ledger", "--json"]


def test_a_mutation_carries_the_target_and_the_right_flags():
    assert argv_for("release", "/tmp/qoder-cli-1000", True) == [
        sys.executable, "-m", "deck_wellness", "tmpfs", "release", "/tmp/qoder-cli-1000",
        "--json", "--confirmar"]
    assert argv_for("expire", "", True)[-2:] == ["--confirmar", "--irreversivel"]
    assert "--irreversivel" not in argv_for("expire", "", False)


def test_the_volumes_come_from_the_poller_and_nothing_is_scanned(qapp, jobs):
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)
    t.show_volumes((TmpfsVolume("/tmp", "tmpfs", 8 * GIB, 7 * GIB, GIB),), ts=0.0)
    assert t.volume_rows[0]["path"] == "/tmp"
    assert t.volume_table.item(0, col(VOLUME_COLUMNS, "total")).text() == "8,0 GB"
    assert t.volume_table.item(0, col(VOLUME_COLUMNS, "used")).text() == "7,0 GB"
    assert t.volume_table.cellWidget(0, col(VOLUME_COLUMNS, "bar")).value() == 88
    assert t.volume_rows[0]["eta"] == "—"          # uma amostra não é tendência
    assert jobs.calls == []


def test_the_eta_column_extrapolates_the_samples_this_tab_collected(qapp, jobs):
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)
    for ts, used in ((0.0, 1 * GIB), (60.0, 2 * GIB), (120.0, 3 * GIB)):
        t.show_volumes((TmpfsVolume("/tmp", "tmpfs", 8 * GIB, used, 8 * GIB - used),),
                       ts=ts)
    assert t.volume_rows[0]["eta"] == "5 min"
    assert t.volume_table.item(0, col(VOLUME_COLUMNS, "eta")).text() == "5 min"
    assert "5 min" in t.pressure.text()


def test_refresh_asks_the_child_for_plan_and_ledger_only(tab, jobs):
    tab.refresh()
    assert [c[0] for c in jobs.calls] == ["plan", "ledger"]
    assert all(c[2] is False for c in jobs.calls), "leitura nunca leva --confirmar"
    assert tab.plan_rows[0]["path"] == "/tmp/qoder-cli-1000"
    assert tab.ledger_rows[0]["entry_id"] == "1700-abc"
    assert "impressão" in tab.summary.text()


def test_the_plan_table_keeps_the_refused_side_with_its_reason(tab):
    tab.show_plan(plan_payload())
    states = [tab.plan_table.item(r, col(PLAN_COLUMNS, "state")).text()
              for r in range(tab.plan_table.rowCount())]
    assert states[0] == "candidato"
    assert "fora da allow-list" in states[1]


def test_an_unreconciled_count_is_announced_not_hidden(tab):
    payload = plan_payload()
    payload["scanned_entries"] = 9
    tab.show_plan(payload)
    assert "não fechou" in tab.status.text()


def test_releasing_asks_with_path_bytes_and_holder_pids(qapp, jobs):
    seen = []
    t = TmpfsTab(jobs=jobs,
                 confirm_fn=lambda title, text: seen.append((title, text)) or True)
    t.show_plan(plan_payload())
    t.release_buttons[0].click()
    title, text = seen[0]
    assert "/tmp/qoder-cli-1000" in text
    assert "4,0 KB" in text and "1234" in text
    assert jobs.calls[-1] == ("release", "/tmp/qoder-cli-1000", True)
    assert "1700-abc" in t.status.text()


def test_a_declined_dialog_moves_nothing(qapp, jobs):
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: False)
    t.show_plan(plan_payload())
    t.release_buttons[0].click()
    assert jobs.calls == []
    assert "cancelado" in t.status.text()


def test_a_refusal_from_the_child_is_printed_as_a_refusal(qapp):
    def refused(acao, target):
        return {"acao": acao, "ok": False, "exit": 1,
                "reason": "refused: 1 processo com fd aberto: 1234"}
    t = TmpfsTab(jobs=FakeJobs(refused), confirm_fn=lambda *a: True)
    t.show_plan(plan_payload())
    t.release_buttons[0].click()
    assert "recusado" in t.status.text() and "1234" in t.status.text()


def test_restoring_is_per_entry_and_needs_confirmation(qapp, jobs):
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)
    t.show_ledger(ledger_payload())
    t.restore_buttons[0].click()
    assert jobs.calls[-1] == ("restore", "1700-abc", True)
    assert "devolvido" in t.status.text()


def test_expiring_says_it_is_irreversible_before_running(qapp):
    seen = []
    jobs = FakeJobs(answers)
    t = TmpfsTab(jobs=jobs,
                 confirm_fn=lambda title, text: seen.append(text) or True)
    t.show_ledger(ledger_payload())
    t.expire_button.click()
    assert "irreversível" in seen[0] and "4,0 KB" in seen[0]
    assert jobs.calls[-1] == ("expire", "", True)


def test_the_budget_line_shows_ram_freed_against_ssd_retained(tab):
    tab.show_ledger(ledger_payload())
    # a linha inteira, por igualdade, e não três substrings soltas: o dia com vírgula é
    # regra de cópia do projeto (`policy.py:84-85`, e o `mais_velho` que a T12 acabou de
    # corrigir no `ledger` humano) -- com `in` soltos um `30.0 d` passaria despercebido
    assert tab.budget_label.text() == (
        "retido 4,0 KB na SSD em 1 item(ns) · o mais velho 30,0 d · "
        "RAM liberada 4,0 KB · folga 5,0 GB")


def test_the_budget_line_marks_a_burst_retention(tab):
    """Retenção acima do orçamento tem de aparecer na aba, não só no stderr do CLI."""
    payload = ledger_payload()
    payload["budget"].update(retained_bytes=4 * GIB, slack_bytes=0)
    tab.show_ledger(payload)
    assert tab.budget_label.text().startswith("retido 4,0 GB na SSD")
    assert tab.budget_label.text().endswith("· a retenção estourou o orçamento")


def test_the_budget_line_stays_quiet_inside_the_budget(tab):
    """O marcador não pode virar ruído de fundo: dentro do orçamento, ele não existe."""
    tab.show_ledger(ledger_payload())
    assert "estourou" not in tab.budget_label.text()


def test_a_child_that_answered_nothing_is_not_a_success(qapp):
    t = TmpfsTab(jobs=FakeJobs(lambda acao, target: None), confirm_fn=lambda *a: True)
    t.show_plan(None)
    t.show_ledger(None)
    assert t.plan_rows == [] and t.ledger_rows == []
    assert t.summary.text() == "sem plano"
    assert "sem leitura do ledger" in t.budget_label.text()
