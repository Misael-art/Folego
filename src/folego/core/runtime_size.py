"""Tamanho do runtime privado (/run/user/<uid>): opções, drop-in do logind e comando privilegiado.

O systemd-logind monta esse tmpfs com `RuntimeDirectorySize` (padrão 10% da RAM). Quando
agentes legítimos precisam de mais espaço ali (sockets, D-Bus de sandboxes, sessões
efêmeras), a saída organizada é aumentar o volume — não espalhar arquivos pelo disco.

Este módulo só calcula e descreve. A aplicação é sempre um pedido explícito do usuário,
autenticado pelo polkit (`pkexec`): grava um drop-in persistente e remonta o volume com
o novo tamanho, sem perder o conteúdo (remount de tmpfs preserva os arquivos).
"""
import os
import re
import uuid
from dataclasses import dataclass

DROPIN_DIR = "/etc/systemd/logind.conf.d"
DROPIN_PATH = f"{DROPIN_DIR}/60-folego-runtime-size.conf"
MULTIPLIERS = (1, 2, 3, 4)
# Teto como fração da RAM: tmpfs só consome o que for gravado, mas um volume maior que
# isso deixaria um agente descontrolado empurrar o host inteiro para swap.
MAX_RAM_FRACTION = 0.65
MIB = 1024 ** 2


@dataclass(frozen=True)
class SizeOption:
    multiplier: int
    bytes: int
    allowed: bool
    reason: str = ""

    @property
    def mib(self) -> int:
        return self.bytes // MIB

    def to_dict(self) -> dict:
        return {"multiplier": self.multiplier, "bytes": self.bytes, "mib": self.mib,
                "allowed": self.allowed, "reason": self.reason}


def mem_total_bytes(meminfo: str = "/proc/meminfo") -> int:
    with open(meminfo, encoding="ascii") as stream:
        for line in stream:
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    raise ValueError("MemTotal ausente em /proc/meminfo")


def options(current_bytes: int, ram_bytes: int) -> tuple:
    """Múltiplos do tamanho atual, arredondados para MiB; acima do teto ficam recusados."""
    if current_bytes <= 0 or ram_bytes <= 0:
        raise ValueError("tamanho atual e RAM precisam ser positivos")
    cap = int(ram_bytes * MAX_RAM_FRACTION)
    result = []
    for factor in MULTIPLIERS:
        size = (current_bytes * factor) // MIB * MIB
        if size > cap:
            result.append(SizeOption(factor, size, False,
                                     f"acima de {int(MAX_RAM_FRACTION * 100)}% da RAM ({cap // MIB} MiB)"))
        else:
            result.append(SizeOption(factor, size, True))
    return tuple(result)


def dropin_text(size_bytes: int) -> str:
    if size_bytes < 64 * MIB:
        raise ValueError("tamanho mínimo de 64 MiB")
    return ("# Gerado pelo Fôlego a pedido do usuário; remova este arquivo para voltar ao padrão.\n"
            "[Login]\n"
            f"RuntimeDirectorySize={size_bytes // MIB}M\n")


def apply_command(size_bytes: int, *, uid: int | None = None, runtime: str | None = None,
                  operation_id: str | None = None, expected_identity: str = "",
                  before_bytes: int = 0) -> list:
    """Um único `pkexec` com argumentos validados: drop-in persistente + remount imediato."""
    uid = os.getuid() if uid is None else uid
    runtime = runtime or f"/run/user/{uid}"
    if runtime != f"/run/user/{uid}" or not isinstance(uid, int) or uid <= 0:
        raise ValueError("só o runtime do próprio UID pode ser redimensionado")
    text = dropin_text(size_bytes)
    mib = size_bytes // MIB
    if not re.fullmatch(r"\d+", str(mib)):
        raise ValueError("tamanho inválido")
    operation_id = operation_id or uuid.uuid4().hex
    if not re.fullmatch(r"[a-f0-9]{32}", operation_id):
        raise ValueError("ID de operação inválido")
    # The final receipt is written only when the privileged shell exits. A
    # missing receipt never proves cancellation (pkexec may still be waiting).
    script = '''set -eu
umask 077
configured=0
mounted=0
receipt="$3.result-$6"
operation="$6"
target_mib="$4"
finish() {
    code=$?
    trap - EXIT
    printf '%s %s %s %s %s\n' "$operation" "$code" "$configured" "$mounted" "$target_mib" > "$receipt.tmp"
    chmod 0644 "$receipt.tmp"
    mv "$receipt.tmp" "$receipt"
    exit "$code"
}
test ! -L "$5"
test "$(stat -c %u "$5")" = "$9"
test "$(findmnt -n -M "$5" -o FSTYPE)" = tmpfs
if test -n "$7"; then test "$(stat -c %d:%i "$5")" = "$7"; fi
if test "$8" -gt 0; then
    blocks=$(stat -f -c %b "$5")
    blocksize=$(stat -f -c %S "$5")
    test "$((blocks * blocksize))" = "$8"
fi
mkdir -p "$1"
test ! -L "$3"
test ! -e "$receipt"
trap finish EXIT
if test -e "$3"; then
    test -f "$3"
    cp -p "$3" "$3.before-$6"
fi
printf %s "$2" > "$3.tmp-$6"
chmod 0644 "$3.tmp-$6"
mv "$3.tmp-$6" "$3"
configured=1
printf 'configured\n'
mount -o remount,size="$4"M "$5"
mounted=1
'''
    return ["pkexec", "/bin/sh", "-c", script, "folego-runtime-size",
            DROPIN_DIR, text, DROPIN_PATH, str(mib), runtime, operation_id,
            expected_identity, str(before_bytes), str(uid)]


def configured_size(dropin: str = DROPIN_PATH) -> int | None:
    """O tamanho que o Fôlego deixou configurado, se houver (bytes)."""
    try:
        text = open(dropin, encoding="utf-8").read()
    except OSError:
        return None
    match = re.search(r"^RuntimeDirectorySize=(\d+)M\s*$", text, re.MULTILINE)
    return int(match.group(1)) * MIB if match else None
