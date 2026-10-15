"""A tuning is one declarative description: which file, which key, which value.

The engine below never learns what Startup boost is; it reads these fields. That
is what keeps "1 arquivo = 1 tuning" honest — adding a tuning means adding a
spec, not touching the mutation code.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Tuning:
    id: str
    label: str
    why: str
    key_path: tuple[str, ...]
    desired: object
    target: Callable[[], Path]
    requires_target_closed: bool = True

    @property
    def action_id(self) -> str:
        return f"tunings.{self.id}"

    @property
    def key(self) -> str:
        return ".".join(self.key_path)
