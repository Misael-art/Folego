"""O que ficou na SSD é registro, não esquecimento: append-only e com teto.

Sem orçamento, "liberar RAM" só empurra o lixo para outro disco. Cada linha é uma
transição; o estado vigente é o da última linha de cada entry_id — igual ao audit,
só que aqui o tamanho do que está retido decide se a próxima liberação acontece.
"""
import json
import time

import pytest

from folego.actions.tmpfs import ledger as L

DAY = 86_400
NOW = 1_700_000_000.0
GIB = 1024 ** 3


@pytest.fixture
def book(tmp_path):
    return L.Ledger(tmp_path / "tmp-ledger.jsonl")


def rec(**over):
    base = dict(entry_id="1700-a", src="/tmp/velho", volume="/tmp",
                stored="/home/u/.local/share/folego/tmp-quarantine/x",
                bytes=1024, sha256="ab" * 32, age_days=4.0,
                matched_pattern="/tmp/tmp*", holder_pids=(), state=L.STATE_RELEASED,
                action_id="tmpfs.release", audit_event_id="e1")
    base.update(over)
    return base


def stamp(days_ago: float) -> str:
    """ts ISO-Z deslocada para trás a partir de NOW: o teste controla a idade."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - days_ago * DAY))


def test_append_writes_one_fsynced_line_per_transition(book):
    first = book.append(**rec())
    second = book.append(**rec(state=L.STATE_RESTORED, entry_id="1700-a"))
    lines = (book.path.read_text(encoding="utf-8")).splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["state"] == "released"
    assert first.entry_id == second.entry_id
    # 0o600: cada linha guarda caminhos absolutos do home do usuário
    assert book.path.stat().st_mode & 0o777 == 0o600


def test_append_refuses_a_line_that_cannot_be_attributed(book):
    """Sem entry_id/state/action_id a linha é arquivo morto: nada depois a lê."""
    for dropped in ("entry_id", "state", "action_id"):
        with pytest.raises(ValueError, match=dropped):
            book.append(**{k: v for k, v in rec().items() if k != dropped})


def test_to_dict_round_trips_back_into_a_new_line(book):
    """O T10 expira assim: append(**{**record.to_dict(), "ts": "", ...})."""
    origin = book.append(**rec(holder_pids=(4242,)))
    again = book.append(**{**origin.to_dict(), "ts": "", "state": L.STATE_DROPPED})
    assert set(origin.to_dict()) == set(L.FIELDS)
    assert again.entry_id == origin.entry_id
    assert again.src == origin.src
    assert again.bytes == origin.bytes
    assert again.holder_pids == (4242,)
    assert again.state == L.STATE_DROPPED
    assert again.ts != ""            # ts vazio pede relógio novo, não grava vazio


def test_the_current_state_is_the_last_line_for_an_entry(book):
    book.append(**rec(entry_id="1700-a"))
    book.append(**rec(entry_id="1700-a", state=L.STATE_RESTORED))
    book.append(**rec(entry_id="1700-b"))
    current = book.records()
    assert current["1700-a"].state == L.STATE_RESTORED
    assert current["1700-b"].state == L.STATE_RELEASED
    assert book.retained_count() == 1


def test_restored_and_dropped_stop_counting_against_the_budget(book):
    book.append(**rec(entry_id="1700-a", bytes=4096))
    book.append(**rec(entry_id="1700-b", bytes=8192))
    assert book.retained_bytes() == 12_288
    book.append(**rec(entry_id="1700-a", state=L.STATE_RESTORED))
    book.append(**rec(entry_id="1700-b", state=L.STATE_DROPPED))
    assert book.retained_bytes() == 0 and book.retained_count() == 0


def test_partial_counts_as_retained_because_it_occupies_the_ssd(book):
    book.append(**rec(state=L.STATE_PARTIAL, bytes=5_000_000))
    assert book.retained_bytes() == 5_000_000
    assert book.records()["1700-a"].state == L.STATE_PARTIAL


def test_over_budget_returns_victims_oldest_first(book):
    """A mais velha sai primeiro: é a única ordem que o usuário pode auditar."""
    book.append(**rec(entry_id="a", bytes=1024, ts=stamp(30)))
    book.append(**rec(entry_id="b", bytes=1024, ts=stamp(20)))
    book.append(**rec(entry_id="c", bytes=1024, ts=stamp(1)))

    due = book.over_budget(now=NOW)
    assert [r.entry_id for r in due] == ["a", "b"]
    assert book.oldest().entry_id == "a"


def test_the_age_limit_is_strictly_over_the_retention_days(book):
    """14 d contados não vencem; 14 d + 1 s vence. E bytes dentro do teto não contam."""
    book.append(**rec(entry_id="a", bytes=1024, ts=stamp(L.RETENTION_DAYS)))
    assert book.over_budget(now=NOW) == ()

    book.append(**rec(entry_id="b", bytes=1024, ts=stamp(L.RETENTION_DAYS + 0.00002)))
    assert [r.entry_id for r in book.over_budget(now=NOW)] == ["b"]


def test_bytes_over_the_ceiling_evict_oldest_until_it_fits(book):
    """O orçamento pede o conjunto mínimo: 6 GiB retidos, teto 5 GiB, um item sai."""
    for i, size in enumerate((2 * GIB, 2 * GIB, 2 * GIB)):
        book.append(**rec(entry_id=f"e{i}", bytes=size, ts=stamp(3 - i)))

    due = book.over_budget(max_bytes=5 * GIB, now=NOW)
    assert [r.entry_id for r in due] == ["e0"]   # sobram 4 GiB ≤ 5 GiB: nada mais sai


def test_an_age_victim_already_pays_for_the_excess(book):
    """Idade OU bytes, não as duas somas: o que a idade tirou abate o excesso."""
    book.append(**rec(entry_id="a", bytes=2 * GIB, ts=stamp(30)))
    book.append(**rec(entry_id="b", bytes=2 * GIB, ts=stamp(1)))

    # sem abater "a" do excesso, "b" (1 dia, saudável) seria expulso junto
    assert [r.entry_id for r in book.over_budget(max_bytes=3 * GIB, now=NOW)] == ["a"]


def test_budget_view_reports_ram_freed_against_ssd_retained(book):
    book.append(**rec(entry_id="a", bytes=3 * GIB, volume="/tmp", ts=stamp(3)))
    book.append(**rec(entry_id="b", bytes=1 * GIB, volume="/run/user/1000", ts=stamp(2)))
    book.append(**rec(entry_id="c", bytes=1 * GIB, volume="/tmp", ts=stamp(1),
                      state=L.STATE_PARTIAL))
    book.append(**rec(entry_id="a", bytes=3 * GIB, volume="/tmp", ts=stamp(0),
                      state=L.STATE_RESTORED))
    view = book.budget_view(now=NOW)
    assert view.retained_bytes == 2 * GIB        # b retido + c ainda clonando
    assert view.retained_count == 2
    assert view.freed_bytes == 1 * GIB           # RAM que não viu de volta: só b
    assert view.slack_bytes == L.MAX_RETAINED_BYTES - 2 * GIB
    assert view.oldest_days == 2.0               # b, o mais velho dos que ocupam a SSD
    assert view.by_volume == {"/tmp": 1 * GIB, "/run/user/1000": 1 * GIB}


def test_a_corrupt_line_is_skipped_not_fatal(book):
    book.append(**rec(entry_id="a"))
    with open(book.path, "a", encoding="utf-8") as f:
        f.write("{isto não é json}\n")
    assert book.retained_count() == 1


def test_a_new_line_carries_its_schema(book):
    book.append(**rec())
    row = json.loads(book.path.read_text(encoding="utf-8").splitlines()[0])
    assert row["schema"] == L.SCHEMA == 1


def test_a_legacy_line_without_schema_is_still_readable(book):
    """Migração: o formato antigo continua valendo; o campo novo não o invalida."""
    book.path.parent.mkdir(parents=True, exist_ok=True)
    book.path.write_text(json.dumps(rec()) + "\n", encoding="utf-8")

    assert book.records()["1700-a"].state == L.STATE_RELEASED
    assert book.problems() == []


def test_a_future_schema_is_a_problem_not_data(book):
    book.path.parent.mkdir(parents=True, exist_ok=True)
    book.path.write_text(json.dumps({**rec(), "schema": L.SCHEMA + 1}) + "\n",
                         encoding="utf-8")

    assert book.problems() and "schema" in book.problems()[0]
    assert book.records() == {}, "linha que esta versão não entende não vira dado"


def test_a_corrupt_line_is_reported_by_load_not_only_skipped(book):
    book.append(**rec(entry_id="a"))
    with open(book.path, "a", encoding="utf-8") as f:
        f.write("{isto não é json}\n")

    rows, problems = book.load()

    assert len(rows) == 1 and problems and "linha 2" in problems[0]
    assert book.problems(), "quem muta recusa; a leitura mostra o que dá para ler"
    assert book.retained_count() == 1


def test_a_wrong_typed_bytes_field_does_not_break_the_reading(book):
    """Edição à mão: campo numérico inválido não derruba contagem nem orçamento."""
    book.path.parent.mkdir(parents=True, exist_ok=True)
    book.path.write_text(json.dumps({**rec(entry_id="mau", bytes="muito")}) + "\n",
                         encoding="utf-8")


    assert book.records()["mau"].bytes == 0, "coagido, não um crash"
    assert book.retained_bytes() == 0
    assert book.over_budget(now=NOW) == ()


def test_a_row_without_the_optional_audit_field_hydrates_intact(book):
    """Remover `audit_event_id` à mão não pode blankar `stored`/`src`/`state`.

    Achado da entrega 6a: o campo sem default fazia a linha cair no fallback de
    "versão futura" e hidratar com `stored=""` — campos legíveis descartados em
    silêncio, e o clone vivo deixava de contar na cota conjunta do staging.
    """
    linha = rec(entry_id="manual", stored="/home/u/.local/share/folego/retida/x")
    linha.pop("audit_event_id")
    book.path.parent.mkdir(parents=True, exist_ok=True)
    book.path.write_text(json.dumps(linha) + "\n", encoding="utf-8")

    record = book.records()["manual"]
    assert record.stored == "/home/u/.local/share/folego/retida/x"
    assert record.src == "/tmp/velho" and record.state == L.STATE_RELEASED
    assert record.bytes == 1024 and record.action_id == "tmpfs.release"


def test_find_accepts_entry_id_or_the_tail_of_a_path(book):
    book.append(**rec(entry_id="1700-deadbeef", src="/tmp/qoder-cli-1000/x"))
    assert book.find("1700-deadbeef").entry_id == "1700-deadbeef"
    assert book.find("/tmp/qoder-cli-1000/x").entry_id == "1700-deadbeef"
    assert book.find("inexistente") is None


def test_find_prefers_the_active_cycle_over_an_old_restored_one(book):
    """R04: o mesmo caminho em dois ciclos não pode devolver o ciclo velho.

    `release_item` usa a busca para impedir duplicação ativa: devolver o ciclo
    restaurado liberava uma segunda cópia enquanto o clone ativo seguia na SSD.
    """
    src = "/tmp/qoder-cli-1000"
    book.append(**rec(entry_id="old", src=src, state=L.STATE_RESTORED, ts=stamp(10)))
    book.append(**rec(entry_id="new", src=src, state=L.STATE_RELEASED, ts=stamp(1)))
    assert book.find(src).entry_id == "new"


def test_three_cycles_on_the_same_path_follow_the_active_one(book):
    src = "/tmp/qoder-cli-1000"
    book.append(**rec(entry_id="c1", src=src, state=L.STATE_RESTORED, ts=stamp(30)))
    book.append(**rec(entry_id="c2", src=src, state=L.STATE_RESTORED, ts=stamp(20)))
    book.append(**rec(entry_id="c3", src=src, state=L.STATE_RELEASED, ts=stamp(2)))
    assert book.find(src).entry_id == "c3"

    # o ciclo ativo é restaurado: sem ativo, a busca segue o mais recente
    book.append(**rec(entry_id="c2", src=src, state=L.STATE_RELEASED, ts=stamp(1)))
    assert book.find(src).entry_id == "c2"


def test_find_with_no_active_cycle_returns_the_most_recent(book):
    src = "/tmp/qoder-cli-1000"
    book.append(**rec(entry_id="c1", src=src, state=L.STATE_RESTORED, ts=stamp(9)))
    book.append(**rec(entry_id="c2", src=src, state=L.STATE_EXPIRED, ts=stamp(3)))
    assert book.find(src).entry_id == "c2"
