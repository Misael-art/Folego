#!/usr/bin/env bash
# Compatibility launcher; the portable wrapper prepares its private environment.
set -euo pipefail
exec "$(dirname "$0")/dev" run "$@"
