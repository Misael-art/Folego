"""Payload for the desktop notifier shared by GUI and user services."""
from dataclasses import dataclass
from html import escape
from pathlib import Path

_ICONS = {name: f'notice-{name}.svg'
          for name in ('agent', 'service', 'resources', 'resources-critical', 'input', 'operation')}


@dataclass(frozen=True)
class DesktopNotice:
    category: str
    title: str
    body: str
    urgency: str = 'normal'

    @property
    def icon(self) -> Path:
        suffix = 'resources-critical' if self.category == 'resources' and self.urgency == 'critical' else self.category
        return Path(__file__).resolve().parents[1] / 'ui' / 'icons' / _ICONS[suffix]

    def arguments(self) -> list[str]:
        return ['--app-name=Fôlego', f'--urgency={self.urgency}',
                '--hint=string:desktop-entry:folego',
                f'--hint=string:image-path:{self.icon.as_uri()}',
                '--', self.title, escape(self.body, quote=False)]
