#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
profile=${1:-gui}
[[ "$profile" == gui || "$profile" == headless ]] || exit 2
[[ $(uname -s) == Linux ]] || { echo 'Use Linux (WSL2 for headless development on Windows).' >&2; exit 2; }
for program in tar sha256sum stat df awk flock install; do
  command -v "$program" >/dev/null || { echo "Missing $program; run ./dev system-deps --apply" >&2; exit 2; }
done
[[ ! -L "$ROOT/.dev" && ! -L "$ROOT/.scratch" ]] || { echo 'Managed roots must not be symlinks.' >&2; exit 2; }
case $(stat -f -c %T "$ROOT") in tmpfs|ramfs) echo 'Move the project to a disk filesystem before setup.' >&2; exit 2 ;; esac
free_kib=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
[[ "$free_kib" =~ ^[0-9]+$ && "$free_kib" -ge 4194304 ]] || { echo 'Setup requires at least 4 GiB free on the project filesystem.' >&2; exit 2; }
umask 077
mkdir -p "$ROOT/.dev/bin" "$ROOT/.dev/cache" "$ROOT/.dev/tmp"
exec 9>"$ROOT/.dev/setup.lock"
flock 9
for path in bin cache tmp python "venv-$profile"; do
  [[ ! -L "$ROOT/.dev/$path" ]] || { echo "Refusing symbolic managed path: $path" >&2; exit 2; }
done
managed_kib=$(du -sk "$ROOT/.dev" | awk '{print $1}')
((managed_kib < 10485760)) || { echo '.dev reached the 10 GiB review budget; inspect before continuing. Nothing was removed.' >&2; exit 2; }
UV_VERSION=0.12.10
case $(uname -m) in
  x86_64) target=x86_64-unknown-linux-musl; digest=848d0e261119e5b8f35db10164635e46a48bec29ceb1f8ec14a6fc76004973ee ;;
  aarch64|arm64) target=aarch64-unknown-linux-musl; digest=3983cb642fae84eab33756109bb266f126eb61763d8d220dd662af589c5b3da5 ;;
  *) echo 'Supported bootstrap architectures: x86_64, aarch64.' >&2; exit 2 ;;
esac
uv="$ROOT/.dev/bin/uv"
if [[ ! -x "$uv" ]]; then
  archive="$ROOT/.dev/cache/uv-$UV_VERSION-$target.tar.gz"
  url="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$target.tar.gz"
  if [[ ! -f "$archive" ]]; then
    if command -v curl >/dev/null; then
      curl --fail --location --proto '=https' --tlsv1.2 --retry 2 "$url" -o "$archive.part"
    elif command -v wget >/dev/null; then
      wget --https-only "$url" -O "$archive.part"
    else
      echo 'curl or wget required; run ./dev system-deps --apply.' >&2; exit 2
    fi
    mv -- "$archive.part" "$archive"
  fi
  printf '%s  %s\n' "$digest" "$archive" | sha256sum -c -
  stage=$(mktemp -d "$ROOT/.dev/tmp/uv-XXXXXXXX")
  tar -xzf "$archive" -C "$stage" "uv-$target/uv"
  install -m 755 "$stage/uv-$target/uv" "$uv.new"
  mv -- "$uv.new" "$uv"
fi
[[ $("$uv" --version) == "uv $UV_VERSION"* ]] || { echo "Expected uv $UV_VERSION; inspect .dev/bin/uv before replacing it." >&2; exit 2; }
unset VIRTUAL_ENV CONDA_PREFIX PYTHONHOME PYTHONPATH
export UV_CACHE_DIR="$ROOT/.dev/cache/uv" UV_PYTHON_INSTALL_DIR="$ROOT/.dev/python"
export UV_PYTHON_BIN_DIR="$ROOT/.dev/bin" UV_PYTHON_INSTALL_BIN=0 UV_PYTHON_PREFERENCE=only-managed
export UV_TOOL_DIR="$ROOT/.dev/tools" UV_TOOL_BIN_DIR="$ROOT/.dev/bin"
export UV_CONCURRENT_BUILDS=1 UV_CONCURRENT_INSTALLS=2 UV_CONCURRENT_DOWNLOADS=3
export UV_DEFAULT_INDEX=https://pypi.org/simple TMPDIR="$ROOT/.dev/tmp"
export UV_PROJECT_ENVIRONMENT="$ROOT/.dev/venv-$profile"
"$uv" python install 3.14.7
options=(sync --locked --project "$ROOT" --python 3.14.7 --extra dev)
if [[ "$profile" == gui ]]; then options+=(--extra gui); fi
"$uv" "${options[@]}"
"$UV_PROJECT_ENVIRONMENT/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 14); assert sys.prefix != sys.base_prefix; print("Managed Python:", sys.executable)'
