"""O duplo filtro: o que é, e qual nome reconhecemos.

A allow-list default só cobre /tmp. /run/user/1000 é monitorado e nunca liberado
por padrão — ali vivem o socket do Wayland, o D-Bus, o PipeWire e o portal de
documentos; esvaziar aquilo derruba a sessão gráfica, não o agente. /dev/shm é
medido e permanece imutável porque o guard blacklista o prefixo /dev.

Os padrões são escritos na granularidade que o `inventory` mede — o filho direto
do volume. `/tmp/qoder-cli-1000` é a unidade, não a sessão dentro dela: a
ferramenta recria o próprio diretório-raiz, e a idade da árvore inteira (arquivo
mais novo dentro) é que decide. Um padrão `/tmp/qoder-cli-1000/*` nunca casaria
com nada que inventariamos.
"""
import fnmatch
import os
from dataclasses import dataclass

from ...core.tmpfs import WATCHED

MIN_AGE_DAYS = 3.0
MAX_ITEM_BYTES = 2 * 1024 ** 3

DEFAULT_ALLOW_PATTERNS = (
    "/tmp/qoder-cli-1000",
    "/tmp/node-compile-cache",
    "/tmp/tsx-1000",
    "/tmp/pytest-of-*",
    "/tmp/playwright_*",
    "/tmp/tmp*",
)


@dataclass(frozen=True)
class Policy:
    allow_patterns: tuple = DEFAULT_ALLOW_PATTERNS
    min_age_days: float = MIN_AGE_DAYS
    max_item_bytes: int = MAX_ITEM_BYTES
    volumes: tuple = WATCHED

    def to_dict(self) -> dict:
        return {"allow_patterns": list(self.allow_patterns),
                "min_age_days": self.min_age_days,
                "max_item_bytes": self.max_item_bytes,
                "volumes": list(self.volumes)}


@dataclass(frozen=True)
class Eligibility:
    ok: bool
    reason: str
    matched: str | None = None


def matches(path: str, patterns) -> str | None:
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return pattern
    return None


def classify(entry, policy: Policy) -> Eligibility:
    if entry.is_mount_point or entry.under_mount:
        return Eligibility(False, "refused: ponto de montagem (ou contém uma)")
    if entry.kind not in ("dir", "file"):
        return Eligibility(False,
                           f"refused: {entry.kind} não é arquivo nem árvore regular")
    if entry.uid != os.getuid():
        return Eligibility(False, f"refused: dono uid {entry.uid}, não deste usuário")
    if entry.holder_pids:
        pids = ", ".join(str(p) for p in entry.holder_pids)
        return Eligibility(False, f"refused: {len(entry.holder_pids)} processo(s) "
                                  f"com fd aberto: {pids}")
    if entry.truncated or entry.errors:
        por = ("truncada" if entry.truncated
               else f"{len(entry.errors)} erro(s) de walk")
        return Eligibility(False, f"refused: leitura incompleta ({por}) — "
                                  f"tamanho e idade não provam")
    if entry.bytes > policy.max_item_bytes:
        return Eligibility(False,
                           f"refused: {entry.bytes} bytes acima do limite por item")
    if entry.volume not in policy.volumes:
        return Eligibility(False, f"refused: volume {entry.volume} fora da watch-list")
    if entry.age_days < policy.min_age_days:
        idade = f"{entry.age_days:.1f}".replace(".", ",")
        piso = f"{policy.min_age_days:g}".replace(".", ",")
        return Eligibility(False, f"refused: {idade} d, mais novo que o piso "
                                  f"de {piso} d")
    matched = matches(entry.path, policy.allow_patterns)
    if matched is None:
        return Eligibility(False, "refused: fora da allow-list de sujeira de agente")
    return Eligibility(True, f"liberável: casado com {matched}", matched)
