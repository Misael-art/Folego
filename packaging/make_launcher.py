#!/usr/bin/env python3
"""Generate an optional launcher pinned to an installed entrypoint, never autostart."""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    executable = args.executable.absolute()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        parser.error("entrypoint must be an executable installed file")
    # This generator intentionally accepts the common desktop-path subset;
    # refuse ambiguous Exec escaping instead of creating a broken launcher.
    if any(character in str(executable) for character in '\n\r\x00"\\`$%'):
        parser.error("entrypoint path needs unsupported desktop Exec escaping")
    text = Path(__file__).with_name("folego.desktop").read_text()
    text = text.replace("Exec=folego\n", f'Exec="{executable}"\nTryExec={executable}\n')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as out:
        out.write(text)
    print(args.output.absolute())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
