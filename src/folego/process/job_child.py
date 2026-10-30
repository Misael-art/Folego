"""Register the identity of our own disposable child before its command starts."""
import os
import sys
import json
from ..safely.jobtemp import begin_job


def main():
    args = sys.argv[1:]
    if len(args) < 3 or args[1] != "--":
        raise ValueError("manifesto e comando são obrigatórios")
    try:
        begin_job(args[0])
        os.execvpe(args[2], args[2:], os.environ)
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "outcome": "recusa", "exit": 1,
                          "reason": "não foi possível iniciar o comando: " + str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
