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


WINDOWS = ROOT / 'src/folego/windows'
FIXTURES = ROOT / 'tests/fixtures/windows'


def test_active_management_policy_is_opt_in_and_bounded():
    windows = builder.policy()['windows']
    thermal, processes = windows['thermal'], windows['processes']
    assert thermal['automatic_default'] is False and processes['automatic_executor'] is False
    assert windows['automatic_resource_executor'] is False
    assert thermal['recover_c'] < thermal['raise_average_c'] <= thermal['spike_c']
    assert 1 <= thermal['max_switches_per_hour'] <= 4 and thermal['poll_seconds'] <= 5
    assert thermal['recover_samples'] >= thermal['raise_samples']
    for profile in thermal['profiles'].values():
        assert 50 <= profile['throttle_max'] <= 100 and profile['boost_mode'] == 0
    assert not set(processes['agent_names']) & set(processes['protected_names'])
    for name in ('explorer', 'csrss', 'svchost', 'steam', 'msiexec', 'tiworker', 'dwm'):
        assert name in processes['protected_names']
    assert {'Steam Deck', 'Folego'} <= set(windows['startup']['protected_names'])


def test_manifest_lists_capabilities(tmp_path):
    manifest = builder.build(tmp_path / 'package')
    assert 'Folego.Manage.ps1' in manifest['files']
    assert set(manifest['capabilities']) >= {'thermal-profiles', 'process-triage', 'startup-approval'}


def _functions():
    import re
    defined, sources = set(), {}
    for path in WINDOWS.glob('*.ps1'):
        text = path.read_text(encoding='utf-8-sig')
        sources[path.name] = text
        defined |= set(re.findall(r'^\s*function ([A-Za-z]+-Folego[A-Za-z]*)', text, re.M))
    return defined, sources


def test_every_production_call_is_defined():
    import re
    defined, sources = _functions()
    for name in ('Folego.ps1', 'Collect.ps1', 'Folego.Core.ps1', 'Folego.Manage.ps1'):
        called = set(re.findall(r'\b([A-Z][a-z]+-Folego[A-Za-z]*)\b', sources[name]))
        assert called <= defined, (name, sorted(called - defined))


def test_effects_stay_within_the_documented_channels():
    import re
    _, sources = _functions()
    native = (WINDOWS / 'Native.cs').read_text(encoding='utf-8')
    text = '\n'.join(sources.values()) + native
    for forbidden in ('ryzenadj', 'WinRing0', 'inpout', 'DeviceIoControl', 'Set-Service', 'Stop-Service',
                      'Remove-AppxPackage', 'Set-MpPreference', r'Policies\Microsoft', 'EnableLUA', 'Stop-Process'):
        assert forbidden.lower() not in text.lower(), forbidden
    # Gentle close never forces; force only through the creation-time checked native call.
    assert not re.search(r"taskkill[^\n]*/F", text, re.I)
    assert native.count('TerminateProcess(process') == 1 and 'creation != startTicks' in native
    manage = sources['Folego.Manage.ps1']
    for effect in ('Set-FolegoStartupItem', 'Restore-FolegoStartupItem', 'Invoke-FolegoProcessAction', 'Confirm-FolegoThermalBoot'):
        body = manage.split('function ' + effect, 1)[1].split('\nfunction ', 1)[0]
        assert 'Assert-FolegoConfirmation' in body, effect


def test_replay_fixtures_preserve_the_reset_evidence():
    data = (FIXTURES / 'monitor-reset-2228.csv').read_bytes()
    assert data.endswith(b'\x00')  # truncated by the abrupt reset; replay must tolerate it
    rows = [line.split(b',') for line in data.replace(b'\x00', b'').split(b'\r\n')[1:] if line]
    assert rows[-1][0] == b'22:27:50' and float(rows[-1][7]) >= 90
    swing = (FIXTURES / 'monitor-swing-2252.csv').read_text(encoding='ascii').splitlines()[1:]
    temps = [float(line.split(',')[7]) for line in swing if line]
    assert max(temps) >= 90 and min(temps) <= 55


def test_health_level_is_not_reused_by_other_ui_blocks():
    # Regression: the thermal tab once overwrote $level, so the high-pressure notice
    # could never fire after the thermal block ran.
    import re
    ui = (WINDOWS / 'Folego.ps1').read_text(encoding='utf-8-sig')
    assert len(re.findall(r'\$level\s*=', ui)) == 1
