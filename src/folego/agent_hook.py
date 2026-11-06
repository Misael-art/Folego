"""Opt-in Codex hook: deliver an advisory and report attention without transcripts."""
import json
import sys

from .core.agent_pressure import attention, current


def main():
    try:
        event = json.load(sys.stdin)
        kind = event.get("hook_event_name")
        if kind in ("PermissionRequest", "Stop"):
            attention(kind)
        if kind != "PreToolUse": return
        request = current()
        if request is None: return
        context = (f"Fôlego solicita alívio de carga (ID {request['id']}, {request['level']}): "
                   "reduza o paralelismo e adie tarefas pesadas no próximo checkpoint seguro. "
                   "Não interrompa operações de escrita no meio nem encerre outros processos. "
                   "Se não puder reduzir agora, preserve o trabalho e explique ao usuário.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                "additionalContext": context}}))
    except (OSError, ValueError, TypeError):
        # A broken optional advisory never blocks the agent's original tool.
        return


if __name__ == "__main__":
    main()
