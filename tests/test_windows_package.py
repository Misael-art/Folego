"""Windows data/build contracts are testable without a Windows desktop."""
import importlib.util
import json
from pathlib import Path

import pytest
from unittest.mock import patch

from folego.core.battery_alerts import battery_band
from folego.core.health import HealthThresholds

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_windows', ROOT / 'tools/build_windows.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
deploy_spec = importlib.util.spec_from_file_location('prepare_windows_card', ROOT / 'tools/prepare_windows_card.py')
deployer = importlib.util.module_from_spec(deploy_spec)
deploy_spec.loader.exec_module(deployer)


def test_windows_policy_is_compiled_from_shared_core():
    policy = builder.policy()
    core = HealthThresholds()
    assert policy['health']['yellow_available_frac'] == core.yellow_available_frac
    assert policy['health']['red_available_frac'] == core.red_available_frac
    assert policy['health']['recovery_samples'] == core.recovery_samples
    assert policy['battery_bands'] == [battery_band(value) for value in range(101)]
    assert policy['windows']['automatic_resource_executor'] is False


def test_builder_imports_without_linux_getuid_in_a_fresh_process():
    import subprocess
    import sys
    command = 'import os,runpy; del os.getuid; runpy.run_path(' + repr(str(ROOT / 'tools/build_windows.py')) + ', run_name="builder_import_test")'
    result = subprocess.run([sys.executable, '-c', command], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_build_is_self_contained_and_integrity_checked(tmp_path):
    import hashlib
    target = tmp_path / 'package'
    manifest = builder.build(target)
    assert set(manifest['files']) == {*builder.FILES, 'policy.json', 'LICENSE', 'LEIA-ME.md'}
    assert json.loads((target / 'manifest.json').read_text()) == manifest
    for name, record in manifest['files'].items():
        data = (target / name).read_bytes()
        assert len(data) == record['bytes']
        assert hashlib.sha256(data).hexdigest() == record['sha256']
        if name.endswith('.ps1'):
            assert data.startswith(b'\xef\xbb\xbf')
    assert not list(target.rglob('*.py'))  # no Python runtime/checkout dependency


def test_build_refuses_to_overwrite_any_existing_target(tmp_path):
    (tmp_path / 'keep.txt').write_text('user content')
    with pytest.raises(ValueError, match='já existe'):
        builder.build(tmp_path)
    assert (tmp_path / 'keep.txt').read_text() == 'user content'


def card_fixture(tmp_path):
    card = tmp_path / 'card'
    admin = card / 'SteamDeck'
    (admin / 'logs').mkdir(parents=True)
    (admin / 'logs/maintenance.lock').touch()
    (card / 'Windows/System32/WindowsPowerShell/v1.0').mkdir(parents=True)
    (card / 'Windows/System32/WindowsPowerShell/v1.0/powershell.exe').write_bytes(b'fixture-not-executable')
    (admin / 'preparacao.json').write_text(json.dumps({'preserve': 42, 'optimization': {'deployment': {'partition_guid': 'fixture-guid'}, 'files': {}}, 'ecosystem': {'files': {}}}))
    (admin / 'steam-deck.ps1').write_text("param([switch]$Startup)\n. (Join-Path $PSScriptRoot 'scripts\\deck-common.ps1')\nButton 'Teclado na tela' {}\n")
    (admin / 'LEIA-ME.txt').write_text('Existing guide\n')
    package = tmp_path / 'package'
    builder.build(package)
    return card, package


def test_deployment_preserves_bootstrap_backup_and_unknown_inventory(tmp_path):
    card, package = card_fixture(tmp_path)
    original = (card / 'SteamDeck/steam-deck.ps1').read_bytes()
    with patch.object(deployer.subprocess, 'check_output', side_effect=['/dev/fixture\n', 'fixture-guid\n']), patch.object(deployer, 'parse_dispatcher'):
        result = deployer.prepare(card, package)
    assert result['native_start'] == 'prepared, not exercised'
    assert (card / 'SteamDeck/recovery/folego-startup-original/steam-deck.ps1').read_bytes() == original
    inventory = json.loads((card / 'SteamDeck/preparacao.json').read_text())
    assert inventory['preserve'] == 42
    assert inventory['folego_windows']['automatic_charge_power_guard'].startswith('disabled')
    launcher = (card / 'SteamDeck/steam-deck.ps1').read_text(encoding='utf-8-sig')
    assert launcher.count(deployer.MARKER) == 1
    assert 'DeckBootstrap.ps1' in launcher
    assert deployer.verify_package(card / 'Program Files/Folego')['product'] == 'Fôlego Windows'


def test_wrong_card_guid_cannot_receive_the_package(tmp_path):
    card, package = card_fixture(tmp_path)
    with patch.object(deployer.subprocess, 'check_output', side_effect=['/dev/fixture\n', 'another-guid\n']):
        with pytest.raises(ValueError, match='identidade'):
            deployer.prepare(card, package)
    assert not (card / 'Program Files/Folego').exists()
    assert not (card / 'SteamDeck/recovery').exists()


def test_existing_installation_is_never_overwritten_blindly(tmp_path):
    card, package = card_fixture(tmp_path)
    target = card / 'Program Files/Folego'
    target.mkdir(parents=True)
    (target / 'user.txt').write_text('keep')
    with patch.object(deployer.subprocess, 'check_output', side_effect=['/dev/fixture\n', 'fixture-guid\n']):
        with pytest.raises(ValueError, match='já existe'):
            deployer.prepare(card, package)
    assert (target / 'user.txt').read_text() == 'keep'
