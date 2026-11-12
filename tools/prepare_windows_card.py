"""Deploy the reviewed native package to the existing offline Windows card.

Linux preparation only. Verify the actual mounted GPT partition against the
card's canonical inventory; preserve existing files and keep firmware untouched.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MARKER = '# Folego Windows: first-start bootstrap'


def digest(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def write_json(path, data):
    temp = path.with_name(path.name + '.folego-write.tmp')
    if temp.exists():
        raise ValueError('Escrita anterior interrompida: preserve e confira ' + str(temp))
    with temp.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, path)


def write_text(path, text):
    temp = path.with_name(path.name + '.folego-write.tmp')
    with temp.open('x', encoding='utf-8-sig') as stream:
        stream.write(text); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, path)


def parse_dispatcher(text):
    payload = base64.b64encode(text.encode('utf-8')).decode('ascii')
    command = "$t=$null;$e=$null;$s=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + payload + "'));$null=[Management.Automation.Language.Parser]::ParseInput($s,[ref]$t,[ref]$e);if($e.Count){$e;exit 1}"
    subprocess.run(['pwsh', '-NoLogo', '-NoProfile', '-Command', command], check=True, capture_output=True, text=True)


def verify_package(package):
    manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8-sig'))
    if manifest['product'] != 'Fôlego Windows' or manifest['schema'] != 1:
        raise ValueError('Pacote não reconhecido.')
    if {path.name for path in package.iterdir()} != set(manifest['files']) | {'manifest.json'}:
        raise ValueError('Há arquivos fora do manifesto; pacote preservado para revisão.')
    for name, record in manifest['files'].items():
        if Path(name).name != name or (package / name).is_symlink() or digest(package / name) != record:
            raise ValueError('Integridade/caminho inválido: ' + name)
    return manifest


def prepare(card, package):
    admin = card / 'SteamDeck'
    manifest = verify_package(package)
    inventory_path = admin / 'preparacao.json'
    inventory = json.loads(inventory_path.read_text(encoding='utf-8-sig'))
    source = subprocess.check_output(['findmnt', '-rn', '-T', str(card), '-o', 'SOURCE'], text=True).strip()
    actual = subprocess.check_output(['lsblk', '-dn', '-o', 'PARTUUID', source], text=True).strip().lower()
    if actual != inventory['optimization']['deployment']['partition_guid'].lower():
        raise ValueError('O volume montado não corresponde à identidade do cartão.')
    if not (card / 'Windows/System32/WindowsPowerShell/v1.0/powershell.exe').is_file():
        raise ValueError('Windows PowerShell 5.1 não encontrado no alvo.')
    target = card / 'Program Files/Folego'
    if target.parent.is_symlink() or not target.parent.resolve().is_relative_to(card):
        raise ValueError('Diretório de programas redirecionado; não será usado por suposição.')
    if target.parent.exists() and target.parent.stat().st_dev != card.stat().st_dev:
        raise ValueError('O diretório de programas pertence a outro volume.')
    if target.exists():
        raise ValueError('Fôlego já existe no destino. Revise uma atualização; não será sobrescrito.')
    launcher = admin / 'steam-deck.ps1'
    text = launcher.read_text(encoding='utf-8-sig')
    anchor = ". (Join-Path $PSScriptRoot 'scripts\\deck-common.ps1')"
    if text.count(anchor) != 1 or MARKER in text or "Button 'Teclado na tela'" not in text:
        raise ValueError('Dispatcher divergente ou já integrado; não aplicar novamente por suposição.')
    hook = '''
# Folego Windows: first-start bootstrap
if ($Startup -and [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
    try {
        $bootstrap = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'Folego\\DeckBootstrap.ps1'
        if (Test-Path -LiteralPath $bootstrap) { & $bootstrap -CardAdminRoot $PSScriptRoot }
    } catch { Write-Warning $_ }
}
'''
    button = '''Button 'Fôlego — recursos e estabilidade' {
    $exe = Join-Path $context.WindowsDirectory 'System32\\WindowsPowerShell\\v1.0\\powershell.exe'
    $app = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'Folego\\Folego.ps1'
    Start-Process -FilePath $exe -ArgumentList ('-NoProfile -STA -ExecutionPolicy Bypass -File "' + $app + '"')
}
'''
    updated = text.replace(anchor, anchor + '\n' + hook, 1).replace("Button 'Teclado na tela'", button + "Button 'Teclado na tela'", 1)
    parse_dispatcher(updated)
    with (admin / 'logs/maintenance.lock').open('r+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Re-read under the shared preparation lock to preserve later fields.
        inventory = json.loads(inventory_path.read_text(encoding='utf-8-sig'))
        recovery = admin / 'recovery/folego-startup-original'
        recovery.mkdir(parents=True, exist_ok=False)
        originals = {}
        for name in ['steam-deck.ps1', 'LEIA-ME.txt', 'preparacao.json']:
            shutil.copy2(admin / name, recovery / name)
            originals[name] = digest(recovery / name)
            if originals[name] != digest(admin / name):
                raise ValueError('Backup não confere: ' + name)
        write_json(recovery / 'manifest.json', {'origin': 'SteamDeck before Folego Windows startup integration', 'retention': 'Preserve until native startup and recovery acceptance', 'files': originals})
        inventory['folego_windows'] = {'status': 'preparing-offline', 'recovery': 'SteamDeck\\recovery\\folego-startup-original\\manifest.json'}
        write_json(inventory_path, inventory)
        shutil.copytree(package, target)
        verify_package(target)
        write_text(launcher, updated)
        guide = admin / 'LEIA-ME.txt'
        write_text(guide, guide.read_text(encoding='utf-8-sig') + '\nFÔLEGO NO WINDOWS\nMenu Steam Deck > Fôlego — recursos e estabilidade. No próximo login,\no primeiro início será solicitado com atraso de 30 segundos e bandeja.\nA entrada própria de inicialização assume depois; desligue nas Opções do Fôlego.\nMonitor passivo ligado; guarda de energia por carga desligado até habilitação.\nInstalação: Program Files\\Folego. Guia: LEIA-ME.md nessa pasta.\nEstado privado: LocalAppData\\Folego. Aceite nativo de GUI, APIs, sensores\ne login físico ainda pendente; não há promessa de impedir cortes do host.\n')
        inventory['folego_windows'] = {
            'status': 'prepared-for-first-native-start', 'version': manifest['version'],
            'prepared_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'relative_installation': 'Program Files\\Folego',
            'entry_point': 'Program Files\\Folego\\Folego.ps1',
            'startup': 'Existing Steam Deck dispatcher bootstraps once; Folego owns one HKCU Run entry after first successful launch, minimized with 30-second delay. User can disable it.',
            'runtime': manifest['runtime'], 'downloads_required': False,
            'automatic_charge_power_guard': 'disabled until per-hardware opt-in',
            'linux_only_adapters': 'not executed on Windows; see installed capability guide',
            'native_acceptance': 'pending Windows PowerShell 5.1, Forms, real sensors and physical login',
            'manifest_sha256': digest(target / 'manifest.json')['sha256'],
            'recovery': 'SteamDeck\\recovery\\folego-startup-original\\manifest.json',
        }
        for group in ['optimization', 'ecosystem']:
            files = inventory.get(group, {}).get('files', {})
            for name in ['steam-deck.ps1', 'LEIA-ME.txt']:
                if name in files:
                    files[name] = digest(admin / name)
        write_json(inventory_path, inventory)
    return {'target': str(target), 'version': manifest['version'], 'native_start': 'prepared, not exercised'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--card-root', type=Path, required=True)
    parser.add_argument('--package', type=Path, default=ROOT / 'dist/folego-windows')
    args = parser.parse_args()
    print(json.dumps(prepare(args.card_root.resolve(), args.package.resolve()), ensure_ascii=False))
