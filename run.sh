#!/usr/bin/env bash
# DeckWellness launcher — M1: RAM ao vivo no título · M4: painel de órfãos e grupo.
# Só encerra processo depois de um clique com confirmação; sem clique, nada é sinalizado.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH=src
exec .venv/bin/python -m deck_wellness "$@"
