"""O plano é a autoridade: cada item entra com veredito e a contagem tem de fechar.

reclaimable + protected == scanned_entries é a mesma reconciliação que o M5 provou
(141 = 34+85+22+0). Sem ela, "protegi tudo" pode significar "perdi itens".
"""
import json
import os

from deck_wellness.actions.tmpfs import plan
from deck_wellness.actions.tmpfs.inventory import TmpfsEntry
from deck_wellness.actions.tmpfs.policy import Policy
from deck_wellness.core.tmpfs import TmpfsVolume

NOW = 1_700_000_000.0
GIB = 1024 ** 3


def vol(path="/tmp", used=2 * GIB):
    return TmpfsVolume(path, "tmpfs", 8 * GIB, used, 8 * GIB - used)


def entry(name, *, path=None, kind="dir", age_days=10.0, bytes=100, uid=os.getuid(),
          holder_pids=(), truncated=False):
    return TmpfsEntry(path or f"/tmp/{name}", name, "/tmp", kind, uid, bytes, 1,
                      age_days, False, False, holder_pids, truncated, ())


def test_every_entry_lands_on_exactly_one_side():
    entries = [entry("qoder-cli-1000"), entry("novo", age_days=0.2),
               entry("desconhecido")]
    p = plan.build_plan((vol(),), entries, Policy(), now=NOW)
    assert p.scanned_entries == 3
    assert len(p.reclaimable) + len(p.protected) == p.scanned_entries
    assert [i.path for i in p.reclaimable] == ["/tmp/qoder-cli-1000"]
    assert all(i.reason.startswith("refused:") for i in p.protected)


def test_total_bytes_counts_only_the_reclaimable_side():
    entries = [entry("qoder-cli-1000", bytes=700), entry("desconhecido", bytes=5000)]
    p = plan.build_plan((vol(),), entries, Policy(), now=NOW)
    assert (p.total_bytes, p.scanned_bytes) == (700, 5700)


def test_digest_is_stable_for_the_same_plan_and_moves_with_age():
    entries = [entry("qoder-cli-1000")]
    assert (plan.build_plan((vol(),), entries, Policy(), now=NOW).digest ==
            plan.build_plan((vol(),), entries, Policy(), now=NOW).digest)
    older = plan.build_plan((vol(),), [entry("qoder-cli-1000", age_days=11.0)],
                            Policy(), now=NOW)
    assert older.digest != plan.build_plan((vol(),), entries, Policy(), now=NOW).digest


def test_json_round_trips_as_one_line_with_the_volume_attached():
    p = plan.build_plan((vol(),), [entry("qoder-cli-1000")], Policy(), now=NOW)
    text = p.to_json()
    assert "\n" not in text.strip()
    payload = json.loads(text)
    assert payload["scanned_entries"] == 1
    assert payload["volumes"][0]["path"] == "/tmp"
    assert payload["reclaimable"][0]["matched"] == "/tmp/qoder-cli-1000"
    assert payload["policy"]["min_age_days"] == 3.0


def test_find_accepts_the_short_id_and_the_exact_path():
    p = plan.build_plan((vol(),), [entry("qoder-cli-1000"), entry("desconhecido")],
                        Policy(), now=NOW)
    item = p.reclaimable[0]
    assert p.find(item.item_id).path == "/tmp/qoder-cli-1000"
    assert p.find("/tmp/desconhecido").ok is False
    assert p.find("nao-existe") is None


def test_holder_pids_and_truncation_reach_the_payload():
    p = plan.build_plan((vol(),), [entry("a", holder_pids=(9,), truncated=True)],
                        Policy(), now=NOW)
    assert p.protected[0].holder_pids == (9,)
    assert p.protected[0].to_dict()["truncated"] is True


def test_walk_errors_are_carried_into_the_plan():
    broken = TmpfsEntry("/tmp/morto", "morto", "/tmp", "missing", -1, 0, 0, 0.0,
                        False, False, (), False, ("/tmp/morto: no such file",))
    p = plan.build_plan((vol(),), [broken], Policy(), now=NOW)
    assert p.errors == ("/tmp/morto: no such file",)
    assert p.scanned_entries == 1 and p.reclaimable == ()


def test_an_empty_volume_yields_an_empty_but_honest_plan():
    p = plan.build_plan((vol(),), (), Policy(), now=NOW)
    assert (p.scanned_entries, p.total_bytes, p.reclaimable, p.protected) == (
        0, 0, (), ())
    assert p.digest and p.generated_at.startswith("2023-11-14")
