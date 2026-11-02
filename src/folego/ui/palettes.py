"""Console-inspired colour roles. Approximate references supplied by the user.

No Qt or I/O: original swatches identify the inspiration; readable text roles
are derived independently so branding never makes a diagnostic unreadable.
"""
from dataclasses import dataclass


def luminance(color):
    rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
    return .2126 * r + .7152 * g + .0722 * b


def contrast(a, b):
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + .05) / (dark + .05)


def on_color(background):
    return max(('#101010', '#ffffff'), key=lambda ink: contrast(ink, background))


def readable(color, surfaces, minimum=4.5):
    """Preserve hue, move towards the legible pole until every surface passes."""
    target = 0 if min(contrast('#000000', s) for s in surfaces) > min(contrast('#ffffff', s) for s in surfaces) else 255
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    for step in range(101):
        value = '#' + ''.join(f'{round(c + (target - c) * step / 100):02x}' for c in rgb)
        if min(contrast(value, s) for s in surfaces) >= minimum: return value
    raise ValueError('Incompatible theme surfaces')


@dataclass(frozen=True)
class Tokens:
    background: str
    surface: str
    surface_alt: str
    text: str
    muted: str
    accent: str
    accent_text: str
    ok: str
    warning: str
    danger: str
    focus: str
    border: str
    actions: tuple[str, ...]
    categories: tuple[str, ...]
    spacing: int = 8
    radius: int = 6


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    description: str
    swatches: tuple[str, ...]
    tokens: Tokens


def _theme(key, name, description, surfaces, text, muted, accent, border, colors):
    ink = lambda c: readable(c, surfaces)
    # Health colours keep their meaning in every theme, including light themes.
    tokens = Tokens(*surfaces, ink(text), ink(muted), ink(accent), on_color(ink(accent)),
                    ink('#278456'), ink('#aa6500'), ink('#c52c3b'), ink(accent),
                    border, tuple(colors), tuple(ink(c) for c in colors))
    return Theme(key, name, description, tuple(dict.fromkeys((*surfaces, accent, *colors))), tokens)


THEMES = {theme.key: theme for theme in (
    _theme('snes-us', 'SNES americano', 'Cinza e lavanda · botões roxos',
           ('#B2B4B2', '#CEC9CC', '#E2DEE1'), '#27252d', '#54585A', '#4F43AE', '#707372',
           ('#4F43AE', '#54585A', '#514689', '#A7A4E0', '#B5B6E4', '#707372')),
    _theme('super-famicom', 'Super Famicom', 'Cinza claro · vermelho, amarelo, azul e verde',
           ('#B3B2AD', '#C8C7C2', '#E2E1DC'), '#242424', '#5A5A5A', '#3B63D4', '#7A7A7A',
           ('#3B63D4', '#D43B3B', '#5A5A5A', '#49A84A', '#F2D23B', '#3B63D4')),
    _theme('mega-drive', 'Mega Drive / Genesis', 'Preto · vermelho e azul SEGA',
           ('#0D0D0D', '#1A1A1A', '#282828'), '#F2F2F2', '#B7B7B7', '#D61F26', '#575757',
           ('#0066CC', '#D61F26', '#383838', '#0066CC', '#383838', '#D61F26')),
    _theme('master-system', 'Master System III', 'Preto fosco · vermelho Tectoy',
           ('#0F0F0F', '#1B1B1B', '#292929'), '#EAEAEA', '#B5B5B5', '#D62027', '#5A5A5A',
           ('#3A3A3A', '#D62027', '#3A3A3A', '#D62027', '#3A3A3A', '#D62027')),
    _theme('pc-engine', 'PC Engine', 'Branco gelo · vermelho e laranja',
           ('#D8D8D4', '#F2F2EE', '#FFFFFF'), '#282827', '#666666', '#D63A2E', '#96968E',
           ('#666666', '#D63A2E', '#E85A2A', '#D8D8D4', '#E85A2A', '#666666')),
    _theme('nes', 'NES', 'Cinza industrial · preto e vermelho',
           ('#A8A8A8', '#C6C6C6', '#DEDEDE'), '#1F1F1F', '#505050', '#E60012', '#6B6B6B',
           ('#1F1F1F', '#E60012', '#6B6B6B', '#1F1F1F', '#A8A8A8', '#E60012')),
    _theme('turbografx', 'TurboGrafx-16', 'Grafite · vermelho e laranja',
           ('#111111', '#202020', '#303030'), '#F2F2F2', '#BCBCBC', '#F05A28', '#646464',
           ('#4A4A4A', '#D81F26', '#F05A28', '#4A4A4A', '#F05A28', '#D81F26')),
    _theme('ps2', 'PlayStation 2', 'Preto profundo · azul elétrico',
           ('#0A0A0A', '#1C1C1C', '#292929'), '#F2F2F2', '#B8BED1', '#245CFF', '#535D78',
           ('#245CFF', '#383F56', '#1C3C93', '#245CFF', '#383F56', '#1C3C93')),
)}

DEFAULT_THEME = 'snes-us'
