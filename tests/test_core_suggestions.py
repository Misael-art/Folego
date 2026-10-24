"""Suggestion rules (M3): fixed heuristics, no ML, each one actionable.

The plan's rule set is: zram almost full, the app itself over budget, Edge
holding gigabytes, thumbnail cache over 1 GB, memory pressure, and proven
orphans. A suggestion that cannot be acted on is noise, so every one of them
carries the tab it deep-links to.
"""
from folego.core.snapshot import AppRSS, MemInfo, Pressure, Snapshot
from folego.core.suggestions import SuggestionThresholds, suggest

GB = 1024 * 1024  # kB


def snap(*, available_kb=5_000_000, total_kb=14_374_304, psi10=0.0,
         swap_used_kb=0, swap_total_kb=7_208_724, self_rss_kb=96_000,
         apps=(AppRSS("edge", 400_000, 12),)):
    return Snapshot(ts=0.0, mem=MemInfo(total_kb, available_kb),
                    swap_used_kb=swap_used_kb, swap_total_kb=swap_total_kb,
                    pressure_memory=Pressure(psi10, psi10, psi10, 0),
                    pressure_io=None, pressure_cpu=None, load=None,
                    apps=apps, self_rss_kb=self_rss_kb)


def ids(snapshot, **kw):
    return [s.id for s in suggest(snapshot, **kw)]


# ------------------------------------------------------------------ the rules

def test_a_comfortable_machine_gets_no_suggestions():
    assert suggest(snap()) == ()


def test_zram_near_full_is_a_suggestion():
    s = snap(swap_used_kb=int(0.85 * 7_208_724))
    assert "zram" in ids(s)


def test_zram_with_room_to_breathe_is_left_alone():
    assert "zram" not in ids(snap(swap_used_kb=int(0.4 * 7_208_724)))


def test_edge_holding_gigabytes_points_at_the_tuning_that_stops_it():
    s = snap(apps=(AppRSS("edge", 2 * GB + 1, 21),))
    found = [x for x in suggest(s) if x.id == "edge"]
    assert len(found) == 1
    assert found[0].target == "ajustes"
    assert "2,0 GB" in found[0].text


def test_proven_orphans_are_suggested_with_their_count():
    found = [x for x in suggest(snap(), orphan_count=3) if x.id == "orfaos"]
    assert found and "3" in found[0].text
    assert found[0].target == "orfaos"
    # R09: o abandono não é "comprovado" e encerrar não é "sem risco" — a heurística
    # sozinha não prova que o processo morreu, e quem decide é o usuário.
    assert "possivelmente abandonado" in found[0].text.lower()
    assert "comprovado" not in found[0].text.lower()
    assert "sem risco" not in found[0].why.lower()


def test_the_app_itself_is_only_flagged_when_it_grows():
    assert "app" not in ids(snap(self_rss_kb=96_000))
    assert "app" in ids(snap(self_rss_kb=400_000))


def test_thumbnails_are_suggested_only_once_measured():
    assert "thumbnails" not in ids(snap())
    assert "thumbnails" in ids(snap(), thumbnails_kb=2 * GB)


def test_memory_pressure_is_the_critical_case():
    found = [x for x in suggest(snap(psi10=14.0)) if x.id == "pressao"]
    assert found and found[0].level == "critico"


def test_little_ram_left_is_suggested_with_the_number():
    found = [x for x in suggest(snap(available_kb=900_000)) if x.id == "memoria"]
    assert found and "0,9 GB" in found[0].text


# ------------------------------------------------------------- the invariants

def test_suggestions_are_ordered_with_the_urgent_first():
    s = snap(psi10=14.0, available_kb=900_000, self_rss_kb=400_000,
             swap_used_kb=7_000_000)
    levels = [x.level for x in suggest(s, orphan_count=2)]
    assert levels == sorted(levels, key=lambda l: {"critico": 0, "alto": 1,
                                                   "medio": 2}[l])


def test_every_suggestion_names_a_tab_the_user_can_be_sent_to():
    s = snap(psi10=14.0, available_kb=900_000, self_rss_kb=400_000,
             swap_used_kb=7_000_000, apps=(AppRSS("edge", 3 * GB, 30),))
    for item in suggest(s, orphan_count=2, thumbnails_kb=2 * GB):
        assert item.target in {"memoria", "ajustes", "orfaos", "disco"}
        assert item.text and item.why


def test_thresholds_are_injectable():
    strict = SuggestionThresholds(zram_frac=0.1)
    assert "zram" in [s.id for s in suggest(snap(swap_used_kb=GB),
                                            thresholds=strict)]
