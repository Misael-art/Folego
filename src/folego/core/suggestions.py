"""Suggestion rules for the dashboard: fixed heuristics over one Snapshot.

No Qt, no filesystem, no /proc: the collector already did the reading, and the
UI must not decide anything by itself. Each suggestion names the tab that can
act on it, because a warning without a lever is noise.
"""
from dataclasses import dataclass

from .snapshot import Snapshot

MB_KB = 1024           # one megabyte, counted in kB like every Snapshot field
GB_KB = 1024 * MB_KB

CRITICO = "critico"
ALTO = "alto"
MEDIO = "medio"
_SEVERITY = {CRITICO: 0, ALTO: 1, MEDIO: 2}


@dataclass(frozen=True)
class SuggestionThresholds:
    zram_frac: float = 0.80
    available_frac: float = 0.10
    psi_memory_some_avg10: float = 10.0
    edge_kb: int = 2 * GB_KB
    self_rss_kb: int = 300_000
    thumbnails_kb: int = GB_KB


@dataclass(frozen=True)
class Suggestion:
    id: str
    level: str
    text: str
    why: str
    target: str


def fmt_gb(kb: float) -> str:
    return f"{kb / GB_KB:.1f}".replace(".", ",")


def suggest(snapshot: Snapshot, *, orphan_count: int = 0,
            thumbnails_kb: int | None = None,
            thresholds: SuggestionThresholds = SuggestionThresholds()
            ) -> tuple[Suggestion, ...]:
    out = []
    psi10 = snapshot.pressure_memory.some_avg10 if snapshot.pressure_memory else 0.0
    if psi10 > thresholds.psi_memory_some_avg10:
        out.append(Suggestion(
            "pressao", CRITICO,
            f"Pressão de memória {psi10:.1f} — o kernel está esperando páginas",
            "psi/memory some avg10 acima de "
            f"{thresholds.psi_memory_some_avg10:g}: fechando o Edge em background e "
            "limpando /tmp sobra respiração imediata.",
            "memoria"))

    if snapshot.mem and snapshot.mem.mem_total_kb:
        avail = snapshot.mem.mem_available_kb
        if avail / snapshot.mem.mem_total_kb < thresholds.available_frac:
            out.append(Suggestion(
                "memoria", ALTO,
                f"Sobrou {fmt_gb(avail)} GB livre de "
                f"{fmt_gb(snapshot.mem.mem_total_kb)} GB",
                "Menos de "
                f"{thresholds.available_frac * 100:g}% disponível: a troca para zram "
                "começa a custar frames.",
                "memoria"))

    if snapshot.swap_total_kb and snapshot.swap_used_kb / snapshot.swap_total_kb > thresholds.zram_frac:
        pct = snapshot.swap_used_kb * 100 // snapshot.swap_total_kb
        out.append(Suggestion(
            "zram", ALTO,
            f"zram/swap em {pct}% dos {fmt_gb(snapshot.swap_total_kb)} GB",
            "zram cheio comprime no lugar da CPU e aumenta o PSI; aliviar RAM "
            "estrutura o resto.",
            "memoria"))

    if snapshot.self_rss_kb > thresholds.self_rss_kb:
        out.append(Suggestion(
            "app", MEDIO,
            f"O próprio Fôlego está em {fmt_gb(snapshot.self_rss_kb)} GB",
            "Acima do orçamento medido no M1: fechar a janela libera a UI e a "
            "bandeja continua monitorando.",
            "memoria"))

    edge = next((a for a in snapshot.apps if a.group == "edge"), None)
    if edge and edge.rss_kb > thresholds.edge_kb:
        out.append(Suggestion(
            "edge", MEDIO,
            f"Microsoft Edge segura {fmt_gb(edge.rss_kb)} GB em {edge.procs} processo(s)",
            "Startup boost e aplicativos em segundo plano mantêm o Edge vivo sem "
            "janela aberta; desligar é reversível.",
            "ajustes"))

    if orphan_count:
        out.append(Suggestion(
            "orfaos", MEDIO,
            f"{orphan_count} processo(s) órfão(ãos) comprovado(s)",
            "Adotados pelo supervisor da sessão, sem filhos vivos e sem consumir "
            "CPU: encerrar devolve a RAM sem risco.",
            "orfaos"))

    if thumbnails_kb and thumbnails_kb > thresholds.thumbnails_kb:
        out.append(Suggestion(
            "thumbnails", MEDIO,
            f"Cache de miniaturas com {fmt_gb(thumbnails_kb)} GB",
            "Regenera sozinho; mover para quarentena é reversível até a purga.",
            "disco"))

    return tuple(sorted(out, key=lambda s: _SEVERITY[s.level]))
