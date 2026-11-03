#!/usr/bin/env bash
# Preview by default. No services, shell profiles or distro upgrades are changed.
set -euo pipefail
mode=${1:---plan}
(( $# <= 1 )) || { echo 'Use --plan or --apply.' >&2; exit 2; }
[[ "$mode" == --plan || "$mode" == --apply ]] || { echo 'Use --plan or --apply.' >&2; exit 2; }
[[ $(uname -s) == Linux ]] || { echo 'Use a Linux host or WSL2.' >&2; exit 2; }
source /etc/os-release
family=" ${ID:-} ${ID_LIKE:-} "
if [[ "$family" =~ (debian|ubuntu) ]]; then
  commands=(apt)
  packages=(bash curl ca-certificates git tar coreutils util-linux libegl1 libgl1 libdbus-1-3 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 libwayland-client0 libwayland-cursor0 libwayland-egl1)
elif [[ "$family" =~ (arch|manjaro|biglinux) ]]; then
  commands=(pacman)
  packages=(bash curl ca-certificates git tar coreutils util-linux libglvnd dbus libxkbcommon libxkbcommon-x11 libxcb xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-wm wayland)
elif [[ "$family" =~ (fedora|rhel) ]]; then
  commands=(dnf)
  packages=(bash curl ca-certificates git tar coreutils util-linux mesa-libEGL mesa-libGL dbus-libs libxkbcommon libxkbcommon-x11 libxcb xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-wm wayland-libs)
else
  echo "Unsupported automatic package manager: ${ID:-unknown}. See docs/NOVO-HOST.md." >&2; exit 2
fi
case "${commands[0]}" in
  apt) update=(apt-get update); install=(apt-get install -y --no-install-recommends "${packages[@]}") ;;
  pacman) update=(); install=(pacman -S --needed --noconfirm "${packages[@]}") ;;
  dnf) update=(); install=(dnf install -y --setopt=install_weak_deps=False "${packages[@]}") ;;
esac
printf 'Native dependencies for %s:\n' "${PRETTY_NAME:-$ID}"
if ((${#update[@]})); then printf '%q ' "${update[@]}"; printf '\n'; fi
printf '%q ' "${install[@]}"; printf '\n'
[[ "$mode" == --apply ]] || exit 0
privilege=()
if ((EUID != 0)); then
  command -v sudo >/dev/null || { echo 'Administrator access required for native packages; managed Python needs no sudo.' >&2; exit 2; }
  privilege=(sudo)
  if [[ ! -t 0 ]]; then privilege+=(-n); fi
fi
if ((${#update[@]})); then "${privilege[@]}" "${update[@]}"; fi
"${privilege[@]}" "${install[@]}"
