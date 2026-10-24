from folego.orchestration.models import ResourceIdentity
"""F6 grants: persistent, limited, revocable and closed by default."""
import json
import os
import stat

import pytest

from folego.orchestration.grants import GrantError, GrantStore


@pytest.fixture
def store(fake_home):
    return GrantStore()


def test_a_missing_file_is_no_grant_and_creates_nothing(store):
    assert store.list() == []
    assert not store.path.exists()
    assert not store.path.parent.exists(), "ler não pode criar estado"


def test_add_persists_a_limited_grant_with_private_mode(store):
    grant = store.add("tmpfs.release", {"bytes": 4096}, resources=(ResourceIdentity.entry("1700-abc"),), ttl_s=3600)

    path = store.path
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    rows = json.loads(path.read_text())
    assert rows["version"] == 1
    assert rows["grants"][0]["grant_id"] == grant.grant_id
    assert grant.active()
    assert [g.grant_id for g in store.for_action("tmpfs.release")] == [grant.grant_id]
    assert store.for_action("disk.purge") == []


def test_add_refuses_non_json_limits_and_non_positive_ttl(store):
    with pytest.raises(GrantError, match="JSON"):
        store.add("tmpfs.release", {"x": object()}, resources=(ResourceIdentity.entry("1700-abc"),))
    with pytest.raises(GrantError, match="positivo"):
        store.add("tmpfs.release", {}, resources=(ResourceIdentity.entry("1700-abc"),), ttl_s=0)
    assert store.list() == []


def test_revoke_keeps_the_record_but_deactivates_it(store):
    grant = store.add("tmpfs.release", {"bytes": 10}, resources=(ResourceIdentity.entry("1700-abc"),))

    revoked = store.revoke(grant.grant_id)

    assert revoked.revoked_at is not None
    assert not revoked.active()
    assert store.for_action("tmpfs.release") == []
    assert store.find(grant.grant_id).revoked_at is not None
    assert store.revoke(grant.grant_id) == revoked, "revogar de novo é idempotente"


def test_revoking_an_unknown_grant_changes_nothing(store):
    store.add("tmpfs.release", {"bytes": 10}, resources=(ResourceIdentity.entry("1700-abc"),))
    before = store.path.read_bytes()

    with pytest.raises(GrantError, match="não existe"):
        store.revoke("missing")

    assert store.path.read_bytes() == before


def test_a_corrupt_or_future_file_fails_closed(store):
    store.path.parent.mkdir(parents=True)
    store.path.write_text("lixo{")
    with pytest.raises(GrantError, match="ilegível"):
        store.list()

    store.path.write_text(json.dumps({"version": 99, "grants": []}))
    with pytest.raises(GrantError, match="versão"):
        store.list()


def test_a_grant_with_bad_schema_is_not_silently_accepted(store):
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps({
        "version": 1,
        "grants": [{"grant_id": "g", "action": "tmpfs.release",
                    "limits": {}, "issued_at": 1.0}]}))
    with pytest.raises(GrantError, match="ilegível"):
        store.list()


def test_expired_grants_are_kept_but_not_active(fake_home):
    clock = [1000.0]
    store = GrantStore(clock=lambda: clock[0])
    grant = store.add("tmpfs.release", {"bytes": 1}, resources=(ResourceIdentity.entry("1700-abc"),), ttl_s=10)
    clock[0] = 1020.0

    assert store.find(grant.grant_id) is not None
    assert store.for_action("tmpfs.release") == []


@pytest.mark.parametrize("limits", [{}, {"bytes": -1}, {"bytes": float("nan")},
                                    {"bytes": 1, "unexpected": True}])
def test_unbounded_or_unrecognized_grants_never_persist(store, limits):
    with pytest.raises(GrantError):
        store.add("tmpfs.release", limits, resources=(ResourceIdentity.entry("managed"),))
    assert not store.path.exists()


def test_missing_resource_scope_is_not_inferred(store):
    with pytest.raises(GrantError, match="identidades"):
        store.add("tmpfs.release", {"bytes": 1})
    assert not store.path.exists()
