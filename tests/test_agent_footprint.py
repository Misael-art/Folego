"""Per-agent instances in the host history: the evidence for 'too many Codex instances'."""
from folego.core import agents
from folego.core.snapshot import ProcInfo


def proc(pid, comm, ppid=1, args=(), rss=1000, cpu=1.0):
    return ProcInfo(pid, comm, "S", ppid, pid, pid, 0, 0, pid, rss, 0, 1000, tuple(args), cpu_frac=cpu)


def host():
    electron = "/usr/lib/chatgpt/ChatGPT"
    return [
        proc(1, "systemd", 0, ("/usr/lib/systemd/systemd",)),
        # Official ChatGPT app (Codex Desktop): Electron joins argv into one string.
        proc(10, "ChatGPT", 1, (electron,), rss=500_000),
        proc(11, "ChatGPT", 10, (electron + " --type=renderer --enable-crash-reporter=x",), rss=400_000),
        proc(12, "browser_crashpa", 1, ("/usr/lib/chatgpt/browser_crashpad_handler", "--monitor-self")),
        proc(13, "codex", 11, ("/usr/lib/chatgpt/resources/codex", "-c", "x=1", "app-server")),
        proc(14, "codex", 10, ("/usr/lib/chatgpt/resources/codex", "exec-server"), cpu=None),
        # Terminal Codex with two non-interactive runs and an MCP bridge.
        proc(20, "codex", 1, ("/home/u/.local/bin/codex",)),
        proc(21, "codex", 20, ("/home/u/.local/bin/codex", "exec", "tarefa")),
        proc(22, "codex", 20, ("/home/u/.local/bin/codex", "exec", "outra")),
        proc(23, "node", 20, ("node", "/home/u/.npm/_npx/x/node_modules/.bin/mcp-remote", "https://x")),
        # Claude Code starts a Codex: the nested root counts as Codex, not Claude.
        proc(30, "claude", 1, ("/home/u/.local/bin/claude",), rss=300_000),
        proc(31, "bash", 30, ("/bin/bash", "-c", "grep MCP_WORD agents.py")),
        proc(32, "codex", 30, ("/home/u/.local/bin/codex", "exec", "revisão")),
        proc(40, "plasmashell", 1, ("/usr/bin/plasmashell",), rss=900_000),
    ]


def test_footprint_counts_instances_servers_and_size_per_agent():
    result = agents.footprint(host())
    codex, claude = result["codex"], result["claude"]
    # App 10, terminal 20 and the Codex started by Claude Code (32); helpers are not instances.
    assert codex["top"] == 3
    assert codex["main"] == 6 and codex["exec"] == 3
    assert codex["app_server"] == 1 and codex["exec_server"] == 1 and codex["mcp"] == 1
    assert codex["procs"] == 10 and codex["rss_kb"] == 500_000 + 400_000 + 8 * 1000
    assert claude == {"procs": 2, "main": 1, "top": 1, "app_server": 0, "exec_server": 0, "exec": 0,
                      "mcp": 0, "rss_kb": 301_000, "cpu_pct": 2.0}
    assert "plasmashell" not in str(result) and set(result) == {"codex", "claude"}


def test_footprint_is_empty_without_agents_and_cpu_unknown_until_measured():
    assert agents.footprint([proc(1, "systemd", 0), proc(2, "bash", 1)]) == {}
    only = agents.footprint([proc(5, "codex", 1, ("/x/codex",), cpu=None)])
    assert only["codex"]["cpu_pct"] is None and only["codex"]["top"] == 1


def test_helpers_and_mcp_detection_follow_program_names():
    assert agents.is_helper(proc(1, "browser_crashpa", 0, ("/usr/lib/chatgpt/browser_crashpad_handler",)))
    assert agents.is_helper(proc(2, "ChatGPT", 0, ("/usr/lib/chatgpt/ChatGPT --type=gpu-process",)))
    assert not agents.is_helper(proc(3, "ChatGPT", 0, ("/usr/lib/chatgpt/ChatGPT",)))
    assert agents.is_mcp_server(proc(4, "npx", 0, ("npx", "-y", "@modelcontextprotocol/server-filesystem")))
    assert agents.is_mcp_server(proc(5, "mcp-remote", 0, ("/x/bin/mcp-remote",)))
    assert not agents.is_mcp_server(proc(6, "bash", 0, ("/bin/bash", "-c", "echo mcp-remote")))
    assert not agents.is_mcp_server(proc(7, "ChatGPT", 0, ("/usr/lib/chatgpt/ChatGPT --type=utility mcp-x",)))
