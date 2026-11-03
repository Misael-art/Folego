"""KWin's narrow, application-owned no-focus rule for the virtual keyboard.

Qt's Wayland no-focus hint alone is insufficient on Plasma. Install before
mapping our surface. No device, input owner, shared daemon or other rule changes.
"""
import shutil

GROUP = 'folego-virtual-keyboard'
DESCRIPTION = 'Fôlego — foco do teclado virtual'


def ensure(env, run, *, app_id='folego'):
    if app_id != 'folego':
        raise ValueError('Identidade do teclado desconhecida')
    write, read, dbus = (shutil.which(name) for name in ('kwriteconfig6', 'kreadconfig6', 'qdbus6'))
    if not all((write, read, dbus)):
        raise RuntimeError('Teclado indisponível: ferramentas de foco do KWin ausentes')
    def call(args):
        result = run(args, env=env, capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise RuntimeError('Foco do teclado não confirmado pelo KWin')
        return result.stdout.strip()
    def get(group, key):
        return call([read, '--file', 'kwinrulesrc', '--group', group, '--key', key])
    rules_text = get('General', 'rules')
    rules = [r for r in rules_text.split(',') if r]
    if len(rules) > 256 or len(set(rules)) != len(rules):
        raise RuntimeError('Inventário de regras do KWin desconhecido; preservado')
    owner = get(GROUP, 'Description')
    if owner and owner != DESCRIPTION or GROUP in rules and owner != DESCRIPTION:
        raise RuntimeError('Regra de teclado existente tem proprietário desconhecido; preservada')
    keys = dict(Description=DESCRIPTION, wmclass=app_id, wmclassmatch='1',
                title=r'^Fôlego — teclado [0-9a-f]{32}$', titlematch='3',
                acceptfocus='false', acceptfocusrule='2', above='true', aboverule='2',
                skiptaskbar='true', skiptaskbarrule='2', skipswitcher='true', skipswitcherrule='2')
    current = {key: get(GROUP, key) for key in keys}
    if not owner and any(current.values()):
        raise RuntimeError('Regra incompleta sem identidade; configuração preservada')
    for key, value in keys.items():
        if current[key] != value:
            call([write, '--file', 'kwinrulesrc', '--group', GROUP, '--key', key, value])
    if GROUP not in rules:
        if get('General', 'rules') != rules_text:
            raise RuntimeError('Regras mudaram durante a preparação; abra o teclado novamente')
        rules.append(GROUP)
        call([write, '--file', 'kwinrulesrc', '--group', 'General', '--key', 'rules', ','.join(rules)])
        call([write, '--file', 'kwinrulesrc', '--group', 'General', '--key', 'count', str(len(rules))])
    if any(get(GROUP, key) != value for key, value in keys.items()) or GROUP not in get('General', 'rules').split(','):
        raise RuntimeError('Regra de foco não foi confirmada; teclado não abriu')
    call([dbus, 'org.kde.KWin', '/KWin', 'reconfigure'])
    return 'Teclado preparado sem alterar o foco do campo'
