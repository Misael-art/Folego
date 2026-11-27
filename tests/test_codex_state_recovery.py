"""Rollback of an interrupted SQLite transaction left in the Codex home."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from folego.actions import codex_state_recovery as action
from folego.adapters import codex_state as backend
from folego.orchestration import Coordinator
from folego.orchestration.journal import Journal
from folego.orchestration.models import ActionResult, Outcome

CRASH = r'''
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute("pragma cache_size=1")
db.execute("begin")
db.execute("update kv set value = 'interrompido'")
db.execute("insert into kv select key || '-x', value from kv")
os._exit(0)
'''


def _crashed_database(path):
    """A real hot journal: the writer dies mid-transaction after spilling pages."""
    db = sqlite3.connect(path)
    db.execute('pragma journal_mode=delete')
    db.execute('pragma user_version=1')
    db.execute('create table kv(key text primary key, value text)')
    db.executemany('insert into kv values (?, ?)', ((f'k{i}', 'x' * 400) for i in range(400)))
    db.commit()
    db.close()
    subprocess.run([sys.executable, '-I', '-c', CRASH, str(path)], check=True, timeout=30)
    journal = Path(str(path) + '-journal')
    assert journal.read_bytes()[:8] == backend.MAGIC
    return journal


@pytest.fixture
def codex(fake_home, monkeypatch):
    home = fake_home / '.codex'
    home.mkdir(mode=0o700)
    monkeypatch.setenv('CODEX_HOME', str(home))
    monkeypatch.setattr(backend, 'read_mounts_checked', lambda: ((('/', 'btrfs'),), None))
    monkeypatch.setattr(backend, 'MARGIN', 0)
    return home


def _recovery(fake_home):
    journal = Journal(fake_home / 'operations.jsonl')
    return action.CodexStateRecovery(coordinator=Coordinator(journal=journal, lock_path=fake_home / 'lock'))


def _hashes(*files):
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}


def test_hot_journal_blocks_read_only_open_and_is_rolled_back(codex, fake_home):
    database = codex / '.codex-global-state.sqlite'
    journal = _crashed_database(database)
    before = _hashes(database, journal)
    with pytest.raises(sqlite3.OperationalError, match='readonly'):
        sqlite3.connect(f'file:{database}?mode=ro', uri=True).execute('pragma user_version')

    recovery = _recovery(fake_home)
    assert recovery.status()['state'] == 'pending'
    [report] = recovery.handle()

    assert report['outcome'] == Outcome.OK, report
    ro = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
    assert ro.execute('pragma user_version').fetchone() == (1,)
    assert ro.execute("select count(*) from kv where value = 'interrompido'").fetchone() == (0,)
    assert ro.execute('select count(*) from kv').fetchone() == (400,)
    ro.close()
    assert recovery.status()['state'] == 'clean'

    folder = Path(next(iter(backend.recovery_root().iterdir())))
    manifest = json.loads((folder / 'manifest.json').read_text())
    assert {k: v['sha256'] for k, v in manifest['files'].items()} == before
    assert _hashes(folder / database.name, folder / journal.name) == before
    assert recovery.handle() == []


def test_database_in_use_is_postponed_without_spending_an_attempt(codex, fake_home):
    database = codex / '.codex-global-state.sqlite'
    journal = _crashed_database(database)
    before = _hashes(database, journal)
    holder = subprocess.Popen([sys.executable, '-I', '-c',
                               'import sys,time; f=open(sys.argv[1],"rb"); print(1, flush=True); time.sleep(30)',
                               str(database)], stdout=subprocess.PIPE)
    try:
        holder.stdout.readline()
        [report] = _recovery(fake_home).handle()
    finally:
        holder.kill(); holder.wait()
    assert report['outcome'] == Outcome.REFUSED and 'em uso' in report['detail']
    assert _hashes(database, journal) == before
    assert not (fake_home / 'operations.jsonl').exists()
    assert not backend.recovery_root().exists()


def test_auditor_mode_preserves_the_files(codex, fake_home):
    from folego import audit_profile
    assert audit_profile.configure(True)['enabled']
    database = codex / '.codex-global-state.sqlite'
    journal = _crashed_database(database)
    before = _hashes(database, journal)
    [report] = _recovery(fake_home).handle()
    assert report['outcome'] == Outcome.REFUSED
    assert _hashes(database, journal) == before


def test_ram_destination_refuses_before_any_effect(codex, fake_home, monkeypatch):
    monkeypatch.setattr(backend, 'read_mounts_checked', lambda: ((('/', 'tmpfs'),), None))
    database = codex / 'sqlite' / 'codex.db'
    database.parent.mkdir()
    journal = _crashed_database(database)
    before = _hashes(database, journal)
    [report] = _recovery(fake_home).handle()
    assert report['outcome'] == Outcome.REFUSED and 'RAM' in report['detail']
    assert _hashes(database, journal) == before


def test_only_hot_rollback_journals_are_candidates(codex):
    wal = codex / 'state_5.sqlite'
    db = sqlite3.connect(wal)
    db.execute('pragma journal_mode=wal')
    db.execute('create table t(x)')
    db.commit()
    db.close()
    cold = codex / 'logs.sqlite'
    sqlite3.connect(cold).execute('create table t(x)').connection.commit()
    (codex / 'logs.sqlite-journal').write_bytes(b'\0' * 512)
    (codex / 'notes.txt-journal').write_bytes(backend.MAGIC + b'\0' * 64)
    assert backend.find_hot_journals(codex) == []


def test_previous_uncertain_repair_blocks_the_same_database(codex, fake_home):
    database = codex / '.codex-global-state.sqlite'
    journal = _crashed_database(database)
    recovery = _recovery(fake_home)
    [target] = backend.find_hot_journals(codex)
    earlier = recovery._plan(target)
    recovery.clock = lambda: time.time() + action.BUCKET
    recovery.coordinator.journal.append_intent(earlier)
    recovery.coordinator.journal.append_result(ActionResult(action.ACTION, Outcome.UNKNOWN,
                                                            operation_id=earlier.operation_id,
                                                            target_key=earlier.target.key, reason='incerto'))
    before = _hashes(database, journal)
    [report] = recovery.handle()
    assert report['outcome'] == Outcome.REFUSED and 'incerto' in report['detail']
    assert _hashes(database, journal) == before
