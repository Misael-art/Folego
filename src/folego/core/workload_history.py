"""Human and machine summaries of measured workload. No I/O."""
import math


def _stats(values):
    known = sorted(v for v in values if type(v) in (int, float) and math.isfinite(v))
    if not known:
        return {"samples": 0}
    return {"samples": len(known), "min": known[0], "max": known[-1],
            "p95": known[math.ceil(len(known) * .95) - 1]}


def summarize(rows):
    """Aggregate a *single boot/window*. Missing fields in legacy rows stay missing."""
    fields = ("gui_tick_delay_ms", "collector_read_ms", "mem_available_kb", "psi_cpu_avg10", "psi_mem_avg10",
              "psi_io_avg10", "temperature_c")
    result = {k: _stats(row.get(k) for row in rows) for k in fields}
    for key in ("cpu_pct", "rss_kb", "io_write_bps"):
        result["monitor_" + key] = _stats((r.get("monitor") or {}).get(key) for r in rows)
    agents = {}
    for provider in ("codex", "claude", "automation"):
        found = [r["agents"][provider] for r in rows if provider in (r.get("agents") or {})]
        if found:
            group = {k: _stats(v.get(k) for v in found) for k in ("procs", "rss_kb", "top")}
            for field, count in (("cpu_pct", "cpu_measured"), ("io_read_bps", "io_read_measured"),
                                 ("io_write_bps", "io_write_measured")):
                group[field] = _stats(v.get(field) for v in found if v.get(count) == v.get("procs"))
            agents[provider] = group
    scopes = {}
    for row in rows:
        for group in row.get("scopes") or []:
            scopes.setdefault(group["unit"], []).append(group)
    return {"samples": len(rows), "agents": agents,
            "scopes": {unit: {key: _stats(v.get(key) for v in group) for key in ("memory_bytes", "cpu_pct")}
                       for unit, group in scopes.items()}, **result}


def describe(row):
    def number(value, scale=1):
        return "?" if value is None else f"{value / scale:.1f}"

    lines = [f"RAM disponível {number(row.get('mem_available_kb'), 1024**2)} GiB · "
             f"temperatura {number(row.get('temperature_c'))} °C",
             "Espera em 10 s · " + " · ".join(f"{label} {number(row.get(key))}%"
              for label, key in (("CPU", "psi_cpu_avg10"), ("RAM", "psi_mem_avg10"), ("I/O", "psi_io_avg10")))]
    for name, agent in (row.get("agents") or {}).items():
        count = agent["procs"]
        lines.append(f"{name} · {agent['top']} raiz(es), {count} processos · "
                     f"RSS somada {number(agent['rss_kb'], 1024)} MiB · CPU {number(agent.get('cpu_pct'))}% de um núcleo")
        for label, direction in (("Leitura", "read"), ("Escrita", "write")):
            measured = agent.get(f"io_{direction}_measured")
            coverage = "desconhecida" if measured is None else f"{measured}/{count}"
            lines.append(f"  {label} {number(agent.get(f'io_{direction}_bps'), 1024)} KiB/s · cobertura {coverage}")
    monitor = row.get("monitor") or {}
    lines.append(f"Fôlego · leitura {number(row.get('collector_read_ms'))} ms · "
                 f"RSS {number(monitor.get('rss_kb'), 1024)} MiB · CPU {number(monitor.get('cpu_pct'))}%")
    for scope in row.get("scopes") or []:
        lines.append(f"Grupo {scope['unit']} · {number(scope['memory_bytes'], 1024**2)} MiB · "
                     f"CPU {number(scope['cpu_pct'])}% (grupo completo)")
    cap = row.get("timeline_capacity") or {}
    if cap.get("estimated_seconds_this_boot") is not None:
        lines.append(f"Histórico deste boot · {cap['estimated_seconds_this_boot'] / 3600:.1f} h "
                     "até o teto do arquivo ao ritmo recente")
    return "\n".join(lines)


def describe_summary(summary):
    def percentile(key):
        value = summary.get(key, {}).get("p95")
        return "?" if value is None else f"{value:.1f}"

    if not summary["samples"]:
        return "Sem amostras de recursos na janela."
    lines = [f"{summary['samples']} amostras · espera p95 (10 s): CPU {percentile('psi_cpu_avg10')}%, "
             f"RAM {percentile('psi_mem_avg10')}%, I/O {percentile('psi_io_avg10')}%",
             f"Coletor p95 {percentile('collector_read_ms')} ms · atraso do timer da GUI p95 "
             f"{percentile('gui_tick_delay_ms')} ms"]
    for name, stats in summary["agents"].items():
        rss = stats["rss_kb"]
        if rss["samples"]:
            lines.append(f"{name} · RSS entre {rss['min']/1024:.0f} e {rss['max']/1024:.0f} MiB "
                         f"em {rss['samples']} amostras")
    return "\n".join(lines)
