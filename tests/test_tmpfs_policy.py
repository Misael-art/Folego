"""Recusar é o default; liberar precisa de dois filtros e de um motivo nomeado.

Filtro 1 — o item é algo que entendemos (regular, nosso, não-monte, sem holder,
lido por inteiro). Filtro 2 — o nome casa num padrão de sujeira de agente que
reconhecemos. A primeira regra que pega é a razão devolvida, na ordem do §5 da
spec.
"""
import os

from folego.actions.tmpfs import policy
from folego.actions.tmpfs.inventory import TmpfsEntry

GIB = 1024 ** 3


def entry(**kw):
    base = dict(path="/tmp/qoder-cli-1000", name="qoder-cli-1000", volume="/tmp",
                kind="dir", uid=os.getuid(), bytes=1024, files=3, age_days=10.0,
                is_mount_point=False, under_mount=False, holder_pids=(),
                truncated=False, errors=())
    base.update(kw)
    return TmpfsEntry(**base)


def test_a_plain_agent_scratch_directory_is_eligible():
    verdict = policy.classify(entry(), policy.Policy())
    assert verdict.ok is True
    assert verdict.matched == "/tmp/qoder-cli-1000"
    assert "casado com" in verdict.reason


def test_a_session_nested_inside_a_container_is_not_an_inventoried_item():
    """O padrão casa com o que o inventory mede; o caminho fundo não é unidade de plano."""
    verdict = policy.classify(entry(path="/tmp/qoder-cli-1000/abc/sessao",
                                    name="sessao"), policy.Policy())
    assert verdict.ok is False and "allow-list" in verdict.reason


def test_a_mount_point_is_refused_before_anything_else():
    verdict = policy.classify(entry(is_mount_point=True, age_days=0.0), policy.Policy())
    assert verdict.ok is False and verdict.reason.startswith("refused: ponto de montagem")


def test_a_directory_containing_a_mount_is_refused():
    assert policy.classify(entry(under_mount=True), policy.Policy()).ok is False


def test_sockets_fifos_symlinks_and_missing_are_refused_by_kind():
    for kind in ("socket", "fifo", "symlink", "other", "missing"):
        verdict = policy.classify(entry(kind=kind), policy.Policy())
        assert verdict.ok is False, kind
        assert kind in verdict.reason


def test_someone_elses_junk_is_refused():
    verdict = policy.classify(entry(uid=os.getuid() + 1), policy.Policy())
    assert verdict.ok is False and "uid" in verdict.reason


def test_a_live_holder_is_refused_and_named():
    verdict = policy.classify(entry(holder_pids=(4242, 4243)), policy.Policy())
    assert verdict.ok is False
    assert "4242" in verdict.reason and "4243" in verdict.reason


def test_a_holder_index_that_could_not_be_read_blocks_eligibility():
    """R02: sem prova de ausência de uso, o item não é liberável."""
    verdict = policy.classify(entry(holder_state="unavailable"), policy.Policy())
    assert verdict.ok is False
    assert "holder" in verdict.reason.lower() or "uso" in verdict.reason.lower()


def test_a_partial_holder_index_also_blocks_eligibility():
    verdict = policy.classify(entry(holder_state="partial",
                                    holder_errors=("800: permissão negada",)),
                              policy.Policy())
    assert verdict.ok is False
    assert verdict.reason.startswith("refused")


def test_a_truncated_walk_is_not_evidence_enough_to_delete():
    verdict = policy.classify(entry(truncated=True), policy.Policy())
    assert verdict.ok is False and "incompleta (truncada)" in verdict.reason


def test_a_walk_that_failed_to_read_a_child_is_not_evidence_enough_to_delete():
    """Sem `errors` na regra, um walk que não leu um filho libera o irmão legível
    contando com um `bytes` e um `age_days` que sabem por baixo."""
    verdict = policy.classify(entry(errors=("/tmp/x: Permissão negada",)),
                              policy.Policy())
    assert verdict.ok is False and "incompleta" in verdict.reason


def test_a_huge_item_is_refused_by_the_per_item_ceiling():
    verdict = policy.classify(entry(bytes=3 * GIB), policy.Policy())
    assert verdict.ok is False and "limite por item" in verdict.reason


def test_a_volume_outside_the_watch_list_is_refused():
    verdict = policy.classify(entry(volume="/run", path="/run/algo"), policy.Policy())
    assert verdict.ok is False and "watch-list" in verdict.reason


def test_younger_than_the_floor_is_protected():
    verdict = policy.classify(entry(age_days=0.5), policy.Policy())
    assert verdict.ok is False and "piso" in verdict.reason
    assert "0,5 d" in verdict.reason and ".5" not in verdict.reason


def test_the_x11_socket_directory_is_never_eligible_with_the_default_list():
    verdict = policy.classify(entry(path="/tmp/.X11-unix", name=".X11-unix"),
                              policy.Policy())
    assert verdict.ok is False and "allow-list" in verdict.reason


def test_nothing_in_run_user_is_eligible_without_an_explicit_pattern():
    """Em /run/user/1000 mora a sessão: só com padrão explícito algo ali sai elegível."""
    session = entry(volume="/run/user/1000", path="/run/user/1000/gnupg", name="gnupg")
    assert policy.classify(session, policy.Policy()).ok is False
    with_pattern = policy.Policy(allow_patterns=("/run/user/1000/gnupg",))
    assert policy.classify(session, with_pattern).ok is True


def test_holder_refusal_outranks_a_matching_pattern():
    verdict = policy.classify(entry(holder_pids=(7,), age_days=0.1), policy.Policy())
    assert "processo" in verdict.reason


def test_matches_reports_the_first_pattern_that_hits():
    assert policy.matches("/tmp/pytest-of-misael/pytest-3",
                          policy.DEFAULT_ALLOW_PATTERNS) == "/tmp/pytest-of-*"
    assert policy.matches("/tmp/de-outro-lugar", policy.DEFAULT_ALLOW_PATTERNS) is None
