from folego.orchestration.models import ResourceIdentity
"""F6 config: automatic needs a real grant; preset never writes grants."""
import json
import stat
from contextlib import contextmanager

import pytest

from folego.orchestration.config import ConfigError, ConfigStore
from folego.orchestration.grants import GrantStore


@pytest.fixture
def store(fake_home):
    return ConfigStore(clock=lambda: 1000.0)


def test_missing_config_means_manual_and_creates_nothing(store):
    config = store.read()
    assert config.mode == "manual" and config.preset == "equilibrado"
    assert config.paused is False
    assert not store.path.exists()
    assert not store.path.parent.exists()


def test_enabling_automatic_without_a_grant_is_refused(store):
    with pytest.raises(ConfigError, match="grant ativo"):
        store.set_mode("automatico", grant_store=GrantStore(clock=lambda: 1000.0))
    assert not store.path.exists()


def test_enabling_automatic_with_an_active_grant_persists_privately(store):
    grants = GrantStore(clock=lambda: 1000.0)
    grant = grants.add("tmpfs.release", {"bytes": 4096}, resources=(ResourceIdentity.entry("1700-abc"),), ttl_s=3600)

    config = store.set_mode("automatico", grant_store=grants, now=1000.0)

    assert config.mode == "automatico"
    assert store.read().mode == "automatico"
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert grants.find(grant.grant_id) is not None


def test_an_expired_grant_does_not_enable_automatic(fake_home):
    grants = GrantStore(clock=lambda: 1000.0)
    grants.add("tmpfs.release", {"bytes": 1}, resources=(ResourceIdentity.entry("1700-abc"),), ttl_s=10)
    store = ConfigStore(clock=lambda: 1100.0)
    with pytest.raises(ConfigError, match="grant ativo"):
        store.set_mode("automatico", grant_store=grants, now=1100.0)


def test_changing_preset_does_not_touch_the_grant_store(store, fake_home):
    grants = GrantStore(clock=lambda: 1000.0)
    grant = grants.add("tmpfs.release", {"bytes": 4096}, resources=(ResourceIdentity.entry("1700-abc"),), ttl_s=3600)
    before = grants.path.read_bytes()

    config = store.set_preset("manutencao")

    assert config.preset == "manutencao"
    assert grants.path.read_bytes() == before
    assert grants.find(grant.grant_id).limits == {"bytes": 4096}


def test_pause_is_persisted_and_independent_of_mode(store):
    store.set_mode("assistido")
    paused = store.set_paused(True)

    assert paused.paused is True
    assert store.read().mode == "assistido"
    assert store.read().paused is True


@pytest.mark.parametrize("change", ["preset", "mode"])
def test_a_pause_saved_by_another_instance_before_lock_is_preserved(store, monkeypatch, change):
    other = ConfigStore(store.path, clock=lambda: 1001.0)
    original_lock = store._locked

    @contextmanager
    def queued_lock():
        other.set_paused(True)
        with original_lock():
            yield

    monkeypatch.setattr(store, "_locked", queued_lock)
    if change == "preset":
        store.set_preset("conservador")
    else:
        store.set_mode("assistido")
    assert other.read().paused is True
    assert getattr(other.read(), change) == ("conservador" if change == "preset" else "assistido")


def test_invalid_mode_or_preset_changes_nothing(store):
    with pytest.raises(ConfigError, match="modo"):
        store.set_mode("turbo")
    with pytest.raises(ConfigError, match="preset"):
        store.set_preset("turbo")
    assert not store.path.exists()


def test_a_corrupt_or_future_config_fails_closed(store):
    store.path.parent.mkdir(parents=True)
    store.path.write_text("lixo{")
    with pytest.raises(ConfigError, match="ilegível"):
        store.read()

    store.path.write_text(json.dumps({"version": 9, "mode": "automatico"}))
    with pytest.raises(ConfigError, match="versão"):
        store.read()

    store.path.write_text(json.dumps({"version": 1, "mode": "turbo"}))
    with pytest.raises(ConfigError, match="modo inválido"):
        store.read()
