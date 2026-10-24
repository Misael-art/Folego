"""M7 na janela: a aba mostra o que o filho respondeu e não move nada sozinha.

O contrato é o do `disk_tab`: entram tuplas planas vindas do poller, sai argv de
filho matável. Nada aqui abre /proc, varre árvore ou escreve byte — e o ETA é
extrapolação das amostras que a própria aba guardou, nunca uma promessa.
"""
import sys

import pytest

from folego.core.tmpfs import TmpfsVolume
from folego.ui.tmpfs_tab import (LEDGER_COLUMNS, PLAN_COLUMNS, SAMPLES_KEPT,
                                        TmpfsTab, VOLUME_COLUMNS, argv_for)

pytest.importorskip("PySide6")

GIB = 1024 ** 3
MIB = GIB // 1024


def col(columns, key):
    return [k for k, _ in columns].index(key)


def headers(table):
    return [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]


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
                         "stored": "/home/u/.local/share/folego/tmp-quarantine/x",
                         "bytes": 4096, "sha256": "a" * 64, "age_days": 30.0,
                         "matched_pattern": "/tmp/qoder-cli-1000", "holder_pids": [1234],
                         "state": "released", "action_id": "tmpfs.release",
                         "audit_event_id": "e" * 32}],
            "budget": {"retained_bytes": 4096, "retained_count": 1, "oldest_days": 30.0,
                       "slack_bytes": 5 * GIB, "freed_bytes": 4096,
                       "by_volume": {"/tmp": 4096}, "max_bytes": 3 * GIB, "days": 14.0},
            "victims": [{"entry_id": "1700-abc", "bytes": 4096,
                         "src": "/tmp/qoder-cli-1000"}]}


def mutation_payload(acao="release", target=""):
    return {"acao": acao, "ok": True, "exit": 0, "outcome": "sucesso",
            "entry_id": "1700-abc", "reason": "ok",
            "bytes": 4096, "stored": "/ssd/1700-abc", "sha256": "a" * 64,
            "freed_bytes": 4096, "allocated_bytes": 4096,
            "ram_observed_bytes": 4096,
            "restored_to": "/tmp/qoder-cli-1000", "victims": [], "errors": []}


def recover_payload(acao="recover", target=""):
    return {"acao": acao, "ok": True, "exit": 0, "outcome": "sucesso",
            "reason": "recuperação: 1 clone descartado, 0 mantido",
            "dropped": ["1700-abc"], "kept": [], "notes": [], "errors": []}


ANSWERS = {"plan": plan_payload, "ledger": ledger_payload, "release": mutation_payload,
           "restore": mutation_payload, "expire": mutation_payload,
           "recover": recover_payload}


def test_unknown_tmpfs_result_remains_unknown_after_refresh_and_blocks_retry(qapp):
    layer = FakeJobs(answers)
    view = TmpfsTab(jobs=layer, confirm_fn=lambda *args: True)
    view.show_mutation({"ok": False, "outcome": "desconhecido",
                        "operation_id": "uncertain-tmpfs", "reason": "diário falhou"})
    view.refresh()
    before = len(layer.calls)
    view.release_clicked(view.plan_rows[0])
    view.restore_clicked(view.ledger_rows[0])
    view.expire_clicked()
    view.recover_clicked()
    assert len(layer.calls) == before
    assert "uncertain-tmpfs" in view.status.text() and "desconhecido" in view.status.text()
    assert "recusado" not in view.status.text()
    assert all(not button.isEnabled() for button in
        (*view.release_buttons, *view.restore_buttons, view.expire_button, view.recover_button))


def answers(acao, target):
    return ANSWERS[acao](acao, target)


@pytest.fixture
def jobs():
    return FakeJobs(answers)


@pytest.fixture
def tab(qapp, jobs):
    return TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)


def test_argv_is_the_same_headless_cli_a_tty_would_run():
    assert argv_for("plan") == [sys.executable, "-m", "folego", "tmpfs", "plan",
                                 "--json"]
    assert argv_for("ledger") == [sys.executable, "-m", "folego", "tmpfs",
                                  "ledger", "--json"]


def test_a_mutation_carries_the_target_and_the_right_flags():
    assert argv_for("release", "/tmp/qoder-cli-1000", True) == [
        sys.executable, "-m", "folego", "tmpfs", "release", "/tmp/qoder-cli-1000",
        "--json", "--confirmar"]
    assert argv_for("expire", "", True)[-2:] == ["--confirmar", "--irreversivel"]
    assert "--irreversivel" not in argv_for("expire", "", False)
    assert argv_for("recover", "", True) == [
        sys.executable, "-m", "folego", "tmpfs", "recover", "--json",
        "--confirmar"]


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


def test_a_fill_that_would_take_hours_is_read_in_hours(qapp, jobs):
    """Ramo `>= 1` de `_human_eta`: três horas não são lidas como 180 minutos."""
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)
    for ts, used in ((0.0, 8010 * MIB), (60.0, 8011 * MIB), (120.0, 8012 * MIB)):
        t.show_volumes((TmpfsVolume("/tmp", "tmpfs", 8 * GIB, used, 8 * GIB - used),),
                       ts=ts)
    assert t.volume_rows[0]["eta"] == "3,0 h"
    assert t.volume_table.item(0, col(VOLUME_COLUMNS, "eta")).text() == "3,0 h"
    assert "3,0 h" in t.pressure.text()


def test_a_fill_that_would_take_days_is_read_in_days(qapp, jobs):
    """Ramo `>= 24` de `_human_eta`: a régua de minutos passa a ser absurda em 48 h."""
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)
    for ts, used in ((0.0, 5310 * MIB), (60.0, 5311 * MIB), (120.0, 5312 * MIB)):
        t.show_volumes((TmpfsVolume("/tmp", "tmpfs", 8 * GIB, used, 8 * GIB - used),),
                       ts=ts)
    assert t.volume_rows[0]["eta"] == "2 dias"
    assert t.volume_table.item(0, col(VOLUME_COLUMNS, "eta")).text() == "2 dias"
    assert "2 dias" in t.pressure.text()


def test_the_sample_series_keeps_only_the_window_the_eta_can_use(qapp, jobs):
    """O trim `del series[:-SAMPLES_KEPT]` é o único teto da série: sem ele ela cresce
    para sempre e nada neste arquivo avisa. Lê-se pelo `self._samples` que a aba já é;
    acrescentar um getter ao produto para satisfazer o teste é que não pode ser."""
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)
    fed = SAMPLES_KEPT + 50

    def sample(i):
        return float(i * 2), GIB + i * MIB  # o poller de 2 s da casa

    for i in range(fed):
        ts, used = sample(i)
        t.show_volumes((TmpfsVolume("/tmp", "tmpfs", 8 * GIB, used, 8 * GIB - used),),
                       ts=ts)
    series = t._samples["/tmp"]
    assert len(series) == SAMPLES_KEPT
    assert series[0] == sample(50), "o trim corta pela ponta errada"
    assert series[-1] == sample(fed - 1)


def test_repeated_volume_polls_reuse_the_same_bar_instead_of_orphaning_widgets(qapp, jobs):
    """Ensaio F8: `QProgressBar` novo a cada amostra deixava um widget órfão por
    volume (20 mil amostras → milhares de widgets e RSS crescendo)."""
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)
    first = TmpfsVolume("/tmp", "tmpfs", 8 * GIB, 2 * GIB, 6 * GIB)
    second = TmpfsVolume("/tmp", "tmpfs", 8 * GIB, 4 * GIB, 4 * GIB)

    t.show_volumes((first,), ts=0.0)
    bar = t.volume_table.cellWidget(0, col(VOLUME_COLUMNS, "bar"))
    t.show_volumes((second,), ts=2.0)

    assert t.volume_table.cellWidget(0, col(VOLUME_COLUMNS, "bar")) is bar
    assert bar.value() == 50


def test_a_new_plan_reuses_the_release_button_and_rebinds_it_to_the_new_row(tab, jobs):
    """O botão guarda linha/ação atuais em atributos: o callback não reconecta o
    sinal a cada atualização nem aponta para a linha antiga."""
    tab.show_plan(plan_payload())
    button = tab.release_buttons[0]

    item = plan_item(path="/tmp/codex-cli-1000", name="codex-cli-1000",
                     bytes=8192, matched="/tmp/codex-cli-1000")
    payload = plan_payload()
    payload["reclaimable"] = [item]
    payload["protected"] = []
    payload["scanned_entries"] = 1
    payload["total_bytes"] = 8192
    payload["scanned_bytes"] = 8192
    tab.show_plan(payload)

    assert tab.release_buttons[0] is button, (
        "recriar o botão a cada poll vaza um QPushButton por linha")
    button.click()
    assert jobs.calls[-1] == ("release", "/tmp/codex-cli-1000", True)


def test_the_three_tables_pin_their_header_on_their_own_declaration(tab):
    """`*_COLUMNS` não é enfeite de import: ela É a fonte do cabeçalho, e a cópia pt-BR
    fica presa por literal — mexer num título na produção quebra este teste."""
    for table, columns, copy in (
        (tab.volume_table, VOLUME_COLUMNS,
         ["volume", "tipo", "total", "usado", "livre", "ocupação", "lotar em"]),
        (tab.plan_table, PLAN_COLUMNS,
         ["item", "tamanho", "idade", "donos", "estado", ""]),
        (tab.ledger_table, LEDGER_COLUMNS, ["id", "estado", "tamanho", "origem", ""]),
    ):
        assert headers(table) == [title for _, title in columns] == copy


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


def test_a_protected_item_has_no_enabled_release_button(tab):
    """R07: a interface não oferece uma ação que o executor já sabe bloquear."""
    tab.show_plan(plan_payload())

    assert tab.release_buttons[0].isEnabled(), "o candidato segue liberável"
    blocked = tab.release_buttons[1]
    assert not blocked.isEnabled()
    assert "fora da allow-list" in blocked.toolTip()


def test_an_unreconciled_plan_disables_every_release(tab):
    """Leitura inconsistente bloqueia a execução do plano inteiro."""
    payload = plan_payload()
    payload["scanned_entries"] = 9
    tab.show_plan(payload)

    assert all(not b.isEnabled() for b in tab.release_buttons)
    assert all(b.toolTip() for b in tab.release_buttons if not b.isEnabled())


def test_a_protected_row_clicked_directly_does_not_call_the_child(tab, jobs):
    tab.show_plan(plan_payload())
    tab.release_clicked(tab.plan_rows[1])

    assert jobs.calls == []
    assert "bloqueado" in tab.status.text().lower()


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
    # R15: "liberado" (saiu da RAM) e "transferidos" (ocupa na SSD) são medidas
    # diferentes — o veredito do ato nomeia as duas, e a 6b acrescenta o alocado
    # real e a variação observada quando o payload os traz
    assert "transferidos 4,0 KB" in t.status.text()
    assert "4,0 KB alocados" in t.status.text()
    assert "RAM +4096 bytes" in t.status.text()


def test_a_partial_release_is_shown_as_parcial_with_its_numbers(tab):
    """Entrega 7: parcial não é recusa — parte do efeito existe e tem números."""
    tab.show_mutation({**mutation_payload(), "ok": False, "exit": 3,
                       "outcome": "parcial", "freed_bytes": 0,
                       "ram_observed_bytes": None,
                       "reason": "parcial: o clone ficou e a origem não foi removida"})

    text = tab.status.text()
    assert text.startswith("parcial: ")
    assert "recusado" not in text, "clone na SSD não é uma recusa"
    assert "transferidos 4,0 KB" in text and "4,0 KB alocados" in text
    assert "RAM" not in text, "sem observação não se inventa a linha de RAM"


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


def test_a_staging_entry_enables_recovery_and_names_the_risk(qapp, jobs):
    payload = ledger_payload()
    payload["records"][0]["state"] = "staging"
    seen = []
    t = TmpfsTab(jobs=jobs,
                 confirm_fn=lambda title, text: seen.append(text) or True)
    t.show_ledger(payload)

    assert t.recover_button.isEnabled()
    t.recover_button.click()

    assert "staging" in seen[0]
    assert "/tmp/qoder-cli-1000" in seen[0]
    assert "origem sumiu" in seen[0]
    assert jobs.calls[-1] == ("recover", "", True)
    assert "descartados: 1" in t.status.text()
    assert "mantidos: 0" in t.status.text()


def test_recovery_stays_disabled_without_a_staging_record(qapp, jobs):
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)
    t.show_ledger(ledger_payload())
    assert not t.recover_button.isEnabled()
    t.recover_clicked()  # chamada direta também recusa, sem depender do enabled
    assert jobs.calls == []
    assert "nada a recuperar" in t.status.text()


def test_a_kept_staging_clone_is_named_for_manual_decision(tab):
    payload = recover_payload()
    payload.update(ok=False, exit=3, outcome="parcial",
                   dropped=[], kept=["1700-abc"],
                   notes=["1700-abc: a origem sumiu; o clone não foi tocado"])
    tab.show_mutation(payload)

    text = tab.status.text()
    assert text.startswith("parcial: ")
    assert "mantidos: 1" in text
    assert "manual:" in text and "única" not in text


def test_expiring_lists_the_effective_victims_not_the_retained_total(qapp):
    """R07: a confirmação de expiração diz *o que* será apagado — o registro que
    passou do orçamento —, não apenas o total retido."""
    seen = []
    jobs = FakeJobs(answers)
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda title, text: seen.append(text) or True)
    t.show_ledger(ledger_payload())
    t.expire_button.click()
    assert "irreversível" in seen[0]
    assert "1700-abc" in seen[0] and "4,0 KB" in seen[0]
    assert "/tmp/qoder-cli-1000" in seen[0]
    assert jobs.calls[-1] == ("expire", "", True)


def test_expiring_without_victims_asks_nothing_and_calls_nothing(qapp, jobs):
    payload = ledger_payload()
    payload["victims"] = []
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)
    t.show_ledger(payload)
    t.expire_button.click()
    assert jobs.calls == []
    assert "nada a expirar" in t.status.text()


def test_a_failed_ledger_read_clears_stale_victims(qapp, jobs):
    """Leitura que falha não é leitura antiga: sem ledger fresco, o expire não age."""
    t = TmpfsTab(jobs=jobs, confirm_fn=lambda *a: True)
    t.show_ledger(ledger_payload())
    t.show_ledger(None)
    t.expire_button.click()
    assert jobs.calls == []
    assert "sem leitura do ledger" in t.status.text()


def test_the_budget_line_separates_ssd_retained_from_bytes_that_left_ram(tab):
    tab.show_ledger(ledger_payload())
    # a linha inteira, por igualdade, e não três substrings soltas: o dia com vírgula é
    # regra de cópia do projeto (`policy.py:84-85`, e o `mais_velho` que a T12 acabou de
    # corrigir no `ledger` humano) -- com `in` soltos um `30.0 d` passaria despercebido
    assert tab.budget_label.text() == (
        "retido 4,0 KB na SSD em 1 item(ns) · o mais velho 30,0 d · "
        "saiu da RAM e não voltou 4,0 KB · folga 5,0 GB")


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
