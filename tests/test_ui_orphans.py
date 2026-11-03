"""M4 UI: the panel lives under the live readout and never touches /proc itself.

Everything arrives as data from the window; every mutation goes through an
injected callback, so the tests can drive it without a mouse and without the
risk of signalling a real process.
"""
import pytest

from folego.actions.orphans.reaper import TermResult
from folego.core.orphans import GroupMember, GroupTarget, OrphanCandidate
from folego.ui.orphans_panel import OrphansPanel
from fixtures_automation import stores
from fixtures_proc import proc_info, snapshot_of


def cand(pid=500, comm="esquecido", rss_kb=250_000, idle_s=600.0, ppid=1,
         starttime=None):
    return OrphanCandidate(pid=pid, comm=comm, state="S", uid=1000, rss_kb=rss_kb,
                           swap_kb=0, starttime=777 + pid if starttime is None
                           else starttime, idle_s=idle_s, ppid=ppid)


def group(members=((702, 333, 80_000), (701, 222, 200_000), (700, 111, 900_000))):
    return GroupTarget("edge", "Microsoft Edge",
                       tuple(GroupMember(pid, "msedge", rss, start, 700)
                             for pid, start, rss in members))


def signalled(pid):
    return TermResult(pid, "esquecido", True, 15, None)


def refused(pid, reason="pid reutilizado"):
    return TermResult(pid, "esquecido", False, 15, reason)


def survived(pid):
    return TermResult(pid, "esquecido", True, 15, None, exited=False)


@pytest.fixture
def panel(qapp):
    calls = {"terminate": [], "force": [], "group": [], "asked": []}

    def make(answer=True, results=None):
        state = {"answer": answer, "results": results or []}

        def confirm_fn(text):
            calls["asked"].append(text)
            return state["answer"]

        def terminate(candidates):
            calls["terminate"].append(tuple(candidates))
            return state["results"] or [signalled(c.pid) for c in candidates]

        def force(candidates, confirm, require_orphan):
            calls["force"].append((tuple(candidates), confirm, require_orphan))
            return [signalled(c.pid) for c in candidates]

        def on_group(target, confirm):
            calls["group"].append((target, confirm))
            return state["results"] or [signalled(m.pid) for m in target.members]

        widget = OrphansPanel(confirm_fn=confirm_fn, on_terminate=terminate,
                              on_force=force, on_group=on_group)
        widget._state = state
        return widget

    calls["make"] = make
    return calls


# ------------------------------------------------------------------ the listing

def test_the_panel_lists_each_orphan_with_its_cost(panel):
    widget = panel["make"]()
    widget.show_candidates([cand(), cand(611, "fantaio", rss_kb=1_024, idle_s=90.0)])

    rows = widget.rows()
    assert [r["pid"] for r in rows] == [500, 611]
    assert rows[0]["comm"] == "esquecido"
    assert "244,1 MB" in rows[0]["rss"]
    assert rows[1]["idle"] == "90 s"


def test_a_cpu_active_process_is_a_clue_not_a_terminable_orphan(panel):
    widget = panel["make"]()
    clue = OrphanCandidate(
        pid=731, comm="runaway", state="R", uid=1000, rss_kb=50_000,
        swap_kb=0, starttime=9_001, idle_s=0.0, ppid=1, cpu_frac=84.0,
        investigation=True)

    widget.show_investigation([clue])

    assert widget.tree.topLevelItemCount() == 0, "not offered as a proven orphan"
    assert "Investigação possível" in widget.investigation_text()
    assert "pid 731" in widget.investigation_text()
    assert "cpu 84%" in widget.investigation_text()

    widget.show_investigation([])
    assert widget.investigation_text() == ""
    assert widget.investigation_label.isHidden()


def test_the_row_says_who_adopts_it(panel):
    """A live app launched through a wrapper that exited also looks adopted; the
    row has to show whose care it is under so the user can tell the two apart."""
    widget = panel["make"]()
    widget.show_candidates([cand(), cand(612, "terminal64", ppid=1855)])

    rows = widget.rows()
    assert "pai 1" in rows[0]["state"]
    assert "pai 1855" in rows[1]["state"]


def test_a_repeated_poll_reuses_the_same_tree_item(panel):
    widget = panel["make"]()
    widget.show_candidates([cand()])
    item = widget.tree.topLevelItem(0)

    widget.show_candidates([cand()])

    assert widget.tree.topLevelItem(0) is item


def test_a_recycled_pid_gets_a_new_row_and_a_new_identity(panel):
    widget = panel["make"]()
    widget.show_candidates([cand()])
    old = widget.tree.topLevelItem(0)

    widget.show_candidates([cand(starttime=8_888)])

    assert widget.tree.topLevelItem(0) is not old
    assert widget.tree.topLevelItemCount() == 1


def test_a_candidate_that_disappears_is_removed_from_the_tree(panel):
    widget = panel["make"]()
    widget.show_candidates([cand(), cand(611, "fantaio")])

    widget.show_candidates([cand()])

    assert widget.tree.topLevelItemCount() == 1
    assert widget.rows()[0]["pid"] == 500


def test_the_dialog_shows_the_command_before_asking(panel):
    widget = panel["make"]()
    leftover = OrphanCandidate(pid=613, comm="cmd.exe", state="S", uid=1000,
                               rss_kb=15_000, swap_kb=0, starttime=900, idle_s=600.0,
                               ppid=1855,
                               cmdline=("C:\\windows\\system32\\cmd.exe", "/c",
                                        "mt5x_spawn.bat"))
    widget.show_candidates([leftover])
    widget.select(0)

    widget.terminate_clicked()

    asked = panel["asked"][0]
    assert "mt5x_spawn.bat" in asked, "the user must recognise what they are closing"
    assert "pid 1855" in asked


def test_no_candidates_is_said_out_loud(panel):
    widget = panel["make"]()
    widget.show_candidates([])

    assert widget.rows() == []
    assert "sem órfãos" in widget.status().lower()


def test_the_group_button_names_the_family_and_its_yield(panel):
    widget = panel["make"]()
    widget.show_groups([group()])

    assert "Microsoft Edge" in widget.group_text()
    assert "1,1 GB" in widget.group_text()
    assert "3" in widget.group_text()


def test_no_open_group_hides_the_group_button(panel):
    widget = panel["make"]()
    widget.show_groups([])

    assert not widget.group_button.isEnabled()


def test_every_open_group_is_reachable_not_only_the_first(panel):
    """On the Deck Edge matched one stale shell while the family with 21 processes
    and 3 GB was the second entry — and the panel could only ever offer entry one."""
    widget = panel["make"]()
    edge = group()
    chrome = GroupTarget("chrome", "Google Chrome/Chromium",
                         (GroupMember(800, "chrome", 3_000_000, 11, 800),))
    widget.show_groups([edge, chrome])

    assert widget.group_options() == ["Microsoft Edge", "Google Chrome/Chromium"]
    assert widget.current_group().group == "edge"

    widget.choose_group(1)

    assert widget.current_group().group == "chrome"
    assert "Google Chrome/Chromium" in widget.group_text()
    assert "2,9 GB" in widget.group_text()

    widget.group_clicked()

    assert panel["group"][0][0].group == "chrome", "the act follows the choice"


def test_a_poll_landing_keeps_the_group_the_user_chose(panel):
    widget = panel["make"]()
    edge = group()
    chrome = GroupTarget("chrome", "Google Chrome/Chromium",
                         (GroupMember(800, "chrome", 3_000_000, 11, 800),))
    widget.show_groups([edge, chrome])
    widget.choose_group(1)

    widget.show_groups([edge, chrome])

    assert widget.current_group().group == "chrome"


def test_a_group_disappearing_between_polls_does_not_raise(panel):
    """R05: a seleção é restaurada por identidade, nunca pelo índice antigo.

    Fechar o Chrome entre dois polls derrubava a atualização daquele snapshot
    inteiro com IndexError, congelando também a bandeja.
    """
    widget = panel["make"]()
    chrome = GroupTarget("chrome", "Google Chrome/Chromium",
                         (GroupMember(800, "chrome", 3_000_000, 11, 800),))
    widget.show_groups([group(), chrome])
    widget.choose_group(1)

    widget.show_groups([group()])          # o grupo escolhido sumiu

    assert widget.current_group().group == "edge"
    assert widget.group_button.isEnabled()


def test_the_last_group_disappearing_clears_the_button(panel):
    widget = panel["make"]()
    widget.show_groups([group(), GroupTarget("chrome", "Chrome",
                                             (GroupMember(800, "chrome", 1, 1, 800),))])
    widget.choose_group(1)

    widget.show_groups([])

    assert not widget.group_button.isEnabled()
    assert widget.group_options() == []


def test_candidates_appearing_update_the_stale_status_text(panel):
    """R05: o rodapé não pode continuar dizendo "sem órfãos" com linhas na tabela."""
    widget = panel["make"]()
    widget.show_candidates([])
    assert "sem órfãos" in widget.status().lower()

    widget.show_candidates([cand()])

    assert "sem órfãos" not in widget.status().lower()
    assert "possivelmente abandonado" in widget.status().lower()


# ---------------------------------------------------------------- the two acts

def test_terminating_asks_before_touching_anything(panel):
    widget = panel["make"]()
    widget.show_candidates([cand(), cand(611, "fantaio")])
    widget.select(0)

    widget.terminate_clicked()

    assert len(panel["asked"]) == 1
    assert "pid 500" in panel["asked"][0]
    assert "esquecido" in panel["asked"][0]
    assert [c.pid for c in panel["terminate"][0]] == [500], "only the selected row"


def test_a_declined_dialog_signals_nothing(panel):
    widget = panel["make"](answer=False)
    widget.show_candidates([cand()])
    widget.select(0)

    widget.terminate_clicked()

    assert panel["terminate"] == []
    assert "cancelado" in widget.status().lower()


def test_survivors_get_the_force_step_and_it_is_confirmed_separately(panel):
    widget = panel["make"](results=[refused(500)])
    widget.show_candidates([cand()])
    widget.select(0)

    widget.terminate_clicked()

    assert "reutilizado" in widget.status()
    assert widget.survivors() == [500]
    panel["asked"].clear()

    widget.force_clicked()

    assert len(panel["asked"]) == 1
    assert "SIGKILL" in panel["asked"][0]
    assert panel["force"][0][1] is True, "the second confirmation reaches the reaper"
    assert panel["force"][0][2] is True, "an orphan stays under the orphan rule"


def test_a_sigterm_survivor_is_observed_and_gets_the_manual_force_step(panel):
    """Entrega 8: o sinal saiu e o processo continuou — sobrevivente observado."""
    widget = panel["make"](results=[survived(500)])
    widget.show_candidates([cand()])
    widget.select(0)

    widget.terminate_clicked()

    status = widget.status()
    assert "continuam ativos após o sinal" in status
    assert "decisão manual" in status
    assert widget.survivors() == [500]
    assert widget.force_button.isEnabled()


def test_a_poll_keeps_the_survivor_while_the_identity_is_the_same(panel):
    widget = panel["make"](results=[survived(500)])
    widget.show_candidates([cand()])
    widget.select(0)
    widget.terminate_clicked()

    widget.show_candidates([cand()])  # poll: mesma identidade

    assert widget.survivors() == [500]
    assert widget.force_button.isEnabled()
    assert "sobreviveram" in widget.status()

    # PID reciclado: mesmo número, outro nascimento — não é mais o sobrevivente
    widget.show_candidates([OrphanCandidate(pid=500, comm="novo", state="S",
                                            uid=1000, rss_kb=1000, swap_kb=0,
                                            starttime=9_999, idle_s=10.0)])
    assert widget.survivors() == []
    assert not widget.force_button.isEnabled()


def test_an_observed_exit_is_reported_as_encerrado(panel):
    widget = panel["make"](results=[TermResult(500, "esquecido", True, 15, None,
                                               exited=True)])
    widget.show_candidates([cand()])
    widget.select(0)

    widget.terminate_clicked()

    assert "encerrado" in widget.status().lower()
    assert widget.survivors() == []
    assert not widget.force_button.isEnabled()


def test_group_survivors_survive_a_poll_while_the_member_is_the_same(panel):
    widget = panel["make"](results=[survived(701)])
    widget.show_groups([group()])
    widget.group_clicked()

    assert widget.survivors() == [701]

    widget.show_candidates([])     # o poll de órfãos não conhece a família
    widget.show_groups([group()])  # mesma família e mesma identidade

    assert widget.survivors() == [701]
    assert widget.force_button.isEnabled()

    # a família mudou: o pid 701 reciclado (outro starttime) perde o Forçar
    widget.show_groups([group(members=((701, 9_999, 200_000),
                                       (700, 111, 900_000)))])
    assert widget.survivors() == []
    assert not widget.force_button.isEnabled()


def test_group_survivors_are_forced_without_the_orphan_rule(panel):
    """A browser child always has a live parent, so SIGKILL must not re-demand orphanhood."""
    widget = panel["make"](results=[refused(701, "sem permissão para encerrar msedge")])
    widget.show_groups([group()])

    widget.group_clicked()

    assert widget.survivors() == [701]
    assert widget.force_button.isEnabled()

    widget.force_clicked()

    assert panel["force"][0][1] is True
    assert panel["force"][0][2] is False, "group members are never orphans by definition"


def test_a_partial_group_signal_is_reported_as_partial(panel):
    """R10: envio e recusa na mesma leva não podem ser resumidos a um dos dois."""
    widget = panel["make"](results=[signalled(700), refused(701, "sem permissão")])
    widget.show_groups([group()])

    widget.group_clicked()

    status = widget.status()
    assert "sinal enviado" in status and "parcial" in status
    assert "sem permissão" in status
    assert widget.survivors() == [701]


def test_no_survivors_means_the_force_button_stays_off(panel):
    widget = panel["make"]()
    widget.show_candidates([cand()])
    widget.select(0)

    widget.terminate_clicked()
    panel["asked"].clear()
    widget.force_clicked()

    assert panel["force"] == []
    assert panel["asked"] == []


def test_group_confirmation_names_every_pid_before_signalling(panel):
    widget = panel["make"]()
    widget.show_groups([group()])

    widget.group_clicked()

    asked = panel["asked"][0]
    assert "Microsoft Edge" in asked
    assert {"700", "701", "702"} <= set(asked.split())
    assert panel["group"][0][1] is True


def test_a_declined_group_dialog_signals_nothing(panel):
    widget = panel["make"](answer=False)
    widget.show_groups([group()])

    widget.group_clicked()

    assert panel["group"] == []


# ------------------------------------------------------ wired into the window

def a_window(**kw):
    from folego.ui.main_window import MainWindow
    kw.setdefault("config_store", stores()[0])
    kw.setdefault("grant_store", stores()[1])
    return MainWindow(collector_factory=None, **kw)


def test_the_window_feeds_the_panel_from_its_own_snapshots(qapp):
    from folego.core.orphans import OrphanTracker

    procs = (proc_info(500, comm="esquecido", ppid=1, pgid=900, session=901,
                       uid=1000, starttime=777, rss_kb=250_000),)
    asked, killed = [], []
    win = a_window(tracker=OrphanTracker(min_idle_s=0.0, uid=1000, self_pid=10),
                   reaper_factory=lambda: Killed(killed),
                   confirm_fn=lambda text: asked.append(text) or True)

    win.apply_snapshot(snapshot_of(*procs, ts=1_000.0))
    win.apply_snapshot(snapshot_of(*procs, ts=1_060.0))

    assert [r["pid"] for r in win.orphans.rows()] == [500]
    assert killed == [], "listing is not signalling"


def test_the_reaper_is_only_built_when_the_user_acts(qapp):
    built = []

    class Factory:
        def __call__(self):
            built.append(1)
            return Killed([])

    procs = (proc_info(500, comm="esquecido", ppid=1, pgid=900, session=901,
                       uid=1000, starttime=777),)
    from folego.core.orphans import OrphanTracker

    win = a_window(tracker=OrphanTracker(min_idle_s=0.0, uid=1000, self_pid=10),
                   reaper_factory=Factory(), confirm_fn=lambda text: True)
    win.apply_snapshot(snapshot_of(*procs, ts=1_000.0))
    win.apply_snapshot(snapshot_of(*procs, ts=1_060.0))

    assert built == []
    win.orphans.select(0)
    win.orphans.terminate_clicked()

    assert built == [1]


def test_the_window_forces_group_survivors_without_the_orphan_rule(qapp):
    killed, asked = [], []
    win = a_window(reaper_factory=lambda: Killed(killed, refuse=[701]),
                   confirm_fn=lambda text: asked.append(text) or True)
    win.orphans.show_groups([group()])

    win.orphans.group_clicked()
    win.orphans.force_clicked()

    assert [k for k in killed if k[0] == "kill"] == [("kill", 701, True, False)], \
        "a browser child always has a live parent; requiring orphanhood would make SIGKILL unusable"


class Killed:
    """Stand-in reaper: records what the window asked it to signal."""

    def __init__(self, sink, refuse=()):
        self.sink = sink
        self.refuse = tuple(refuse)

    def terminate(self, candidate):
        self.sink.append(("term", candidate.pid))
        return TermResult(candidate.pid, candidate.comm, True, 15, None)

    def force(self, candidate, confirm=False, require_orphan=True):
        self.sink.append(("kill", candidate.pid, confirm, require_orphan))
        return TermResult(candidate.pid, candidate.comm, True, 9, None)

    def terminate_group(self, target):
        self.sink.append(("group", target.group))
        return [TermResult(m.pid, m.comm, m.pid not in self.refuse, 15,
                           None if m.pid not in self.refuse else "sem permissão")
                for m in target.members]
