"""Build the native Windows package from this checkout, without downloads.

Windows shares Linux health/battery policy via generated data, not a second
hand-maintained copy of its thresholds. No Linux runtime/config is deployed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from folego.core.policy import battery_band, HealthThresholds

FILES = ('Folego.ps1', 'Folego.Core.ps1', 'Collect.ps1', 'Native.cs', 'Test-Folego.ps1', 'DeckBootstrap.ps1')


def policy() -> dict:
    return {
        'schema': 1,
        'health': asdict(HealthThresholds()),
        'battery_bands': [battery_band(value) for value in range(101)],
        'windows': {
            'commit_attention': 0.85, 'commit_critical': 0.95,
            'cpu_attention': 85, 'cpu_critical': 95,
            'disk_free_attention': 0.20, 'disk_free_critical': 0.10,
            'poll_seconds': 10, 'extended_seconds': 60,
            'persist_seconds': 60, 'notice_cooldown_seconds': 300,
            'automatic_resource_executor': False,
        },
    }


def build(output: Path) -> dict:
    if output.exists():
        raise ValueError('O destino já existe; preserve o pacote ou escolha o destino de build oficial vazio.')
    output.mkdir(parents=True)
    source = ROOT / 'src/folego/windows'
    for name in FILES:
        data = (source / name).read_bytes()
        if name.endswith('.ps1'):
            data = data.removeprefix(b'\xef\xbb\xbf')
            data = b'\xef\xbb\xbf' + data
        (output / name).write_bytes(data)
    (output / 'policy.json').write_text(json.dumps(policy(), indent=2) + '\n', encoding='utf-8')
    shutil.copyfile(ROOT / 'LICENSE', output / 'LICENSE')
    shutil.copyfile(ROOT / 'docs/WINDOWS.md', output / 'LEIA-ME.md')
    manifest = {
        'schema': 1,
        'product': 'Fôlego Windows',
        'version': tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version'],
        'runtime': 'Windows PowerShell 5.1 / .NET Framework / Windows Forms',
        'files': {file.name: {'bytes': file.stat().st_size, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}
                  for file in sorted(output.iterdir()) if file.is_file()},
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/folego-windows')
    args = parser.parse_args()
    manifest = build(args.output.resolve())
    print(json.dumps({'output': str(args.output), 'version': manifest['version'], 'files': len(manifest['files'])}))


if __name__ == '__main__':
    main()
