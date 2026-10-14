#!/usr/bin/env bash
# DeckWellness launcher — M1: janela com sinal de RAM ao vivo na barra de título.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH=src
exec .venv/bin/python -m deck_wellness "$@"
