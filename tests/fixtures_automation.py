"""In-memory automation stores for UI tests.

The window reads mode/preset/grants at construction. Tests must never read the
developer's real ``~/.local/state/folego`` just to open a window, so every UI
test injects these tiny stores instead. They deliberately contain no mutation
surface: the production window only needs ``read``/``for_action``.
"""
from types import SimpleNamespace


class StaticConfig:
    def __init__(self, *, mode="manual", preset="equilibrado", paused=False):
        self.value = SimpleNamespace(mode=mode, preset=preset, paused=paused,
                                     updated_at=0.0)

    def read(self):
        return self.value


class StaticGrants:
    def __init__(self, grants=()):
        self.grants = list(grants)

    def for_action(self, action, *, now=None):
        return [grant for grant in self.grants
                if getattr(grant, "action", None) == action]


def stores():
    return StaticConfig(), StaticGrants()
