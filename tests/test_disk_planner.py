"""Disk hygiene M5 — dry-run plan: what could be reclaimed, and what is refused."""
import json
import os
import time

from folego.actions.disk.planner import DiskTarget, build_plan, format_report

DAY = 86_400


def _write(path, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"y" * size)


def _home(tmp_path):
    home = tmp_path / "home"
    (home / ".cache").mkdir(parents=True)
    return home


def _touch_age(path, days_ago: float, now: float):
    """Age every file and directory under `path`: staleness is what the content's
    newest mtime says, not the top-level directory's."""
    ts = now - days_ago * DAY
    for root, dirs, files in os.walk(path):
        for name in files + dirs:
            os.utime(os.path.join(root, name), (ts, ts))
    os.utime(path, (ts, ts))


def test_children_mode_reports_one_item_per_child(tmp_path):
    home = _home(tmp_path)
    now = time.time()
    _write(home / ".cache" / "pip" / "whl.bin", 300)
    _write(home / ".cache" / "npm" / "cacache.bin", 700)
    _touch_age(home / ".cache" / "pip", 1, now)
    _touch_age(home / ".cache" / "npm", 1, now)

    plan = build_plan(
        [DiskTarget("cache", "Caches do usuário", "{home}/.cache", mode="children",
                    stale_days=None)],
        home=home, now=now)

    by_path = {os.path.basename(i.path): i for i in plan.items}
    assert sorted(by_path) == ["npm", "pip"]
    assert by_path["pip"].bytes == 300
    assert by_path["npm"].bytes == 700
    assert plan.total_bytes == 1000


def test_stale_days_marks_recent_children_as_not_reclaimable(tmp_path):
    home = _home(tmp_path)
    now = time.time()
    _write(home / ".cache" / "oldproject" / "a.bin", 500)
    _write(home / ".cache" / "active" / "b.bin", 900)
    _touch_age(home / ".cache" / "oldproject", 40, now)
    _touch_age(home / ".cache" / "active", 2, now)

    plan = build_plan(
        [DiskTarget("cache", "Caches", "{home}/.cache", mode="children", stale_days=30)],
        home=home, now=now)

    by_path = {os.path.basename(i.path): i for i in plan.items}
    assert by_path["oldproject"].reclaimable is True
    assert by_path["active"].reclaimable is False
    assert plan.total_bytes == 500
    assert plan.scanned_bytes == 1400


def test_target_under_mnt_sdcard_is_refused_and_never_walked(tmp_path):
    home = _home(tmp_path)
    calls = []

    def spy_measure(path, **kw):
        calls.append(str(path))
        from folego.actions.disk.measure import TreeStat
        return TreeStat(str(path), 1, 1, int(time.time() * 10**9), (), False)

    plan = build_plan(
        [DiskTarget("sd", "Cartão SD", "/mnt/sdcard/.cache", mode="self", stale_days=None)],
        home=home, measure=spy_measure)

    assert plan.items[0].ok is False
    assert "blacklist" in plan.items[0].reason or "sdcard" in plan.items[0].reason
    assert plan.items[0].bytes == 0
    assert calls == [], "refused target must not be read at all (D-state hazard)"


def test_target_escaping_home_through_symlink_is_refused(tmp_path, monkeypatch):
    home = _home(tmp_path)
    outside = tmp_path / "outside"
    _write(outside / "secret.bin", 10)
    (home / ".cache" / "escape").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    plan = build_plan(
        [DiskTarget("esc", "Fuga", "{home}/.cache/escape", mode="self", stale_days=None)],
        home=home,
        allowed_roots=[home],
        resolve_fn=lambda p: str(outside))

    assert plan.items[0].ok is False
    assert "outside" in plan.items[0].reason


def test_missing_target_is_reported_not_reclaimable(tmp_path):
    home = _home(tmp_path)
    plan = build_plan(
        [DiskTarget("ghost", "Inexistente", "{home}/.cache/ghost", mode="self",
                    stale_days=None)],
        home=home)
    assert plan.items == ()


def test_overlapping_targets_count_a_path_only_once(tmp_path):
    """/home/.cache/uv is both a named target and a child of /home/.cache: the
    total must not double-count it."""
    home = _home(tmp_path)
    now = time.time()
    _write(home / ".cache" / "uv" / "wheel.bin", 600)
    plan = build_plan([
        DiskTarget("uv", "Cache do uv", "{home}/.cache/uv", mode="self", stale_days=None),
        DiskTarget("caches", "Caches antigos", "{home}/.cache", mode="children",
                   stale_days=None),
    ], home=home, now=now)

    uv_items = [i for i in plan.items if i.path.endswith("/uv")]
    assert len(uv_items) == 1
    assert plan.total_bytes == 600
    assert plan.scanned_bytes == 600


def test_digest_is_stable_and_changes_with_content(tmp_path):
    home = _home(tmp_path)
    now = time.time()
    _write(home / ".cache" / "a" / "x.bin", 100)
    targets = [DiskTarget("cache", "Caches", "{home}/.cache", mode="children",
                          stale_days=None)]

    p1 = build_plan(targets, home=home, now=now)
    p2 = build_plan(targets, home=home, now=now)
    _write(home / ".cache" / "b" / "y.bin", 222)
    p3 = build_plan(targets, home=home, now=now)

    assert p1.digest == p2.digest
    assert p1.digest != p3.digest
    assert len(p1.digest) == 64


def test_digest_covers_paths_and_sizes_only(tmp_path):
    home = _home(tmp_path)
    now = time.time()
    _write(home / ".cache" / "a" / "x.bin", 100)
    targets = [DiskTarget("cache", "Rótulo A", "{home}/.cache", mode="children",
                          stale_days=None)]
    p1 = build_plan(targets, home=home, now=now)
    p2 = build_plan([DiskTarget("cache", "Rótulo B totalmente diverso", "{home}/.cache",
                                mode="children", stale_days=None)], home=home, now=now)
    assert p1.digest == p2.digest


def test_format_report_is_portuguese_and_lists_totals(tmp_path):
    home = _home(tmp_path)
    now = time.time()
    big = home / ".cache" / "big" / "f.bin"
    big.parent.mkdir(parents=True)
    # sparse: the report path must be testable at multi-GB scale without writing 3 GB
    with open(big, "wb") as handle:
        handle.truncate(3 * 1024**3)
    plan = build_plan(
        [DiskTarget("cache", "Caches", "{home}/.cache", mode="children", stale_days=None)],
        home=home, now=now)

    text = format_report(plan)

    assert "Caches" in text
    assert "3,0 GB" in text
    assert "3,0 GB" in text.splitlines()[-1] or "total recuperável" in text
    assert "," in text and "·" in text


def test_plan_items_are_sorted_biggest_first(tmp_path):
    home = _home(tmp_path)
    now = time.time()
    _write(home / ".cache" / "small" / "f.bin", 10)
    _write(home / ".cache" / "huge" / "f.bin", 100_000)
    plan = build_plan(
        [DiskTarget("cache", "Caches", "{home}/.cache", mode="children", stale_days=None)],
        home=home, now=now)
    assert [os.path.basename(i.path) for i in plan.items] == ["huge", "small"]


def test_walk_errors_are_surfaced_in_the_item(tmp_path):
    home = _home(tmp_path)
    now = time.time()
    _write(home / ".cache" / "part" / "f.bin", 10)
    locked = home / ".cache" / "part" / "locked"
    _write(locked / "g.bin", 20)
    os.chmod(locked, 0o000)
    try:
        plan = build_plan(
            [DiskTarget("cache", "Caches", "{home}/.cache", mode="children",
                        stale_days=None)],
            home=home, now=now)
    finally:
        os.chmod(locked, 0o755)
    assert plan.items[0].errors
    assert plan.items[0].ok is True


def test_default_targets_never_point_outside_home(tmp_path):
    from folego.actions.disk.planner import default_targets

    home = _home(tmp_path)
    plan = build_plan(default_targets(), home=home, now=time.time())
    for target in default_targets():
        assert target.path.format(home=home).startswith(str(home))
    assert plan.items == () or all(i.ok for i in plan.items if i.bytes)


def test_plan_is_json_serialisable_for_the_ui(tmp_path):
    home = _home(tmp_path)
    _write(home / ".cache" / "a" / "x.bin", 5)
    plan = build_plan(
        [DiskTarget("cache", "Caches", "{home}/.cache", mode="children", stale_days=None)],
        home=home, now=time.time())
    payload = json.loads(plan.to_json())
    assert payload["digest"] == plan.digest
    assert payload["items"][0]["bytes"] == 5
