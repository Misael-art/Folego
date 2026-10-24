"""F8 migration: copy, never move; conflicts preserved; interrupted is unknown."""
import json

import pytest

from folego.core.migrate import MigrationError, apply_plan, build_plan


def test_plan_is_read_only_and_copies_into_an_empty_destination(tmp_path):
    source = tmp_path / "legacy"
    (source / "nested").mkdir(parents=True)
    (source / "operations.jsonl").write_text("intent\n")
    (source / "nested" / "prefs.json").write_text('{"x": 1}')
    dest = tmp_path / "new"
    marker = tmp_path / "migration.json"

    plan = build_plan([("state", source, dest)], stamp="20261017T000000Z",
                      marker=marker)
    assert plan.ready and plan.entries[0].files == 2
    assert not dest.exists() and not marker.exists()

    apply_plan(plan, confirm=True)

    assert (dest / "nested" / "prefs.json").read_text() == '{"x": 1}'
    assert source.exists(), "a origem nunca é apagada"
    assert json.loads(marker.read_text())["status"] == "completed"


def test_conflicts_go_to_a_stamped_backup_and_never_overwrite(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "automation.json").write_text("legado")
    dest = tmp_path / "new"
    dest.mkdir()
    (dest / "automation.json").write_text("atual")

    plan = build_plan([("state", source, dest)], stamp="20261017T000000Z",
                      marker=tmp_path / "m.json")

    assert plan.ready
    assert plan.entries[0].destination == dest / "migrated" / \
        "deckwellness-20261017T000000Z"
    apply_plan(plan, confirm=True)
    assert (dest / "automation.json").read_text() == "atual"
    assert (dest / "migrated" / "deckwellness-20261017T000000Z" /
            "automation.json").read_text() == "legado"


def test_a_symlink_makes_the_plan_refuse_everything(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "target").write_text("x")
    (source / "link").symlink_to(source / "target")
    plan = build_plan([("state", source, tmp_path / "new")], marker=tmp_path / "m")

    assert not plan.ready
    assert "link simbólico" in plan.conflicts[0].errors[0]
    with pytest.raises(MigrationError, match="conflito"):
        apply_plan(plan, confirm=True)
    assert not (tmp_path / "new").exists()


def test_confirmation_is_required(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "a").write_text("x")
    plan = build_plan([("state", source, tmp_path / "new")], marker=tmp_path / "m")
    with pytest.raises(MigrationError, match="confirmação"):
        apply_plan(plan)
    assert not (tmp_path / "new").exists()


def test_a_completed_marker_prevents_repeating_the_migration(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "a").write_text("x")
    dest = tmp_path / "new"
    marker = tmp_path / "m"
    plan = build_plan([("state", source, dest)], marker=marker)
    apply_plan(plan, confirm=True)

    with pytest.raises(MigrationError, match="já concluída"):
        apply_plan(build_plan([("state", source, dest)], marker=marker),
                   confirm=True)


def test_an_unknown_or_corrupt_marker_is_not_retried(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "a").write_text("x")
    marker = tmp_path / "m"
    marker.write_text("lixo{")
    plan = build_plan([("state", source, tmp_path / "new")], marker=marker)

    with pytest.raises(MigrationError, match="ilegível"):
        apply_plan(plan, confirm=True)


def test_an_interrupted_marker_is_never_treated_as_success(tmp_path):
    source = tmp_path / "legacy"
    source.mkdir()
    (source / "a").write_text("x")
    marker = tmp_path / "m"
    marker.write_text(json.dumps({"status": "started"}))
    plan = build_plan([("state", source, tmp_path / "new")], marker=marker)

    with pytest.raises(MigrationError, match="sem resultado completo"):
        apply_plan(plan, confirm=True)
