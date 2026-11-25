"""Exact Linux controller consumers. EmuDeck is a manager, its emulators are players."""
from pathlib import PurePosixPath
import re

# Also covers RetroArch cores and games launched by these frontends.
FRONTENDS = frozenset("""
retroarch retrofe gamescope es-de emulationstation emulationstation-de
pegasus-fe pegasus-frontend quiver-launcher quiverlauncher rocketlauncher steamzero-launcher attract attractplus
""".split())
EMULATORS = frozenset("""
azahar azahar-qt bigpemu bsnes cemu citra citra-qt daphne dolphin-emu
dolphin-emu-nogui dolphin-emu-qt2 dosbox dosbox-x dosbox-staging duckstation
duckstation-qt duckstation-nogui eden emulator_multicpu fbneo flycast gzdoom
mame mednafen melonds mgba mgba-qt mupen64plus pcsx2 pcsx2-qt pcsx2-qtx64
pico8 ppssppqt ppssppsdl primehack rmg rpcs3 ryubing ryujinx
ryujinx.ava scummvm shadps4 simple64-gui snes9x snes9x-gtk
solarus-run stella suyu sudachi supermodel vita3k xemu xenia xenia_canary
xenia_canary_netplay xenia-canary-linux kyty_emulator kyty_launcher ps5pcem sharpemu eglantine
eden-nx2 eden-nx2-launch shadps4-sdl hatari fs-uae vice x64sc easyrpg-player
model2emu yabause yabasanshiro mesen mesen2 sameboy ares openmsx residualvm yuzu yuzu-mainline yuzu-ea zesarux z64gl
""".split())
PROGRAMS = FRONTENDS | EMULATORS
# The kernel limits comm to 15 bytes. Consult executable identity for truncated names.
SHORT = {entry[:15] for name in PROGRAMS for entry in (name, name + '.exe', name + '.appimage')
         if len(entry) > 15}
FLATPAKS = frozenset("""
org.libretro.RetroArch org.DolphinEmu.dolphin-emu io.github.shiiion.primehack
org.duckstation.DuckStation org.flycast.Flycast org.mamedev.MAME
net.kuribo64.melonDS io.mgba.mGBA net.pcsx2.PCSX2 org.ppsspp.PPSSPP
com.github.Rosalie241.RMG net.rpcs3.RPCS3 org.scummvm.ScummVM
app.xemu.xemu org.citra_emu.citra org.azahar_emu.Azahar
org.yuzu_emu.yuzu org.ryujinx.Ryujinx info.cemu.Cemu
""".split())


def game_program(name):
    name = PurePosixPath(name.replace('\\', '/')).name.lower()
    if name.endswith('.appimage'):
        stem = name[:-9]
        if stem == 'dolphin':
            return True  # Portable emulator bundle. KDE Dolphin is a different executable.
        return any(stem == p or re.fullmatch(re.escape(p) + r'[-_](?:x64|x86_64|linux|steamdeck|v?\d)[\w.\-]*', stem)
                   for p in PROGRAMS)
    return name == 'dolphin.exe' or name.removesuffix('.exe') in PROGRAMS


def game_environment(data, additional=()):
    if not any(tag in data for tag in (b'SteamGameId=', b'SteamAppId=', b'FLATPAK_ID=', b'APPIMAGE=')):
        return ''
    for field in data.split(b'\0'):
        key, _, value = field.partition(b'=')
        if key in (b'SteamGameId', b'SteamAppId') and value not in (b'', b'0', b'413080'):
            return 'aplicativo Steam ativo; perfil de desktop preservado'
        if key == b'FLATPAK_ID' and (value.decode(errors='replace') in FLATPAKS
                                     or value.decode(errors='replace').lower() in additional):
            return 'jogo/frontend Flatpak ativo'
        if key == b'APPIMAGE' and (game_program(value.decode(errors='replace'))
                                   or PurePosixPath(value.decode(errors='replace')).name.lower() in additional):
            return 'jogo/frontend AppImage ativo'
    return ''


def validate_alias(name):
    if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]{1,95}', name)
            or name.lower() in {'wine', 'wine64', 'bash', 'sh', 'python', 'python3', 'java', 'node',
                                'flatpak', 'bwrap', 'apprun', 'steam', 'dolphin', 'systemd'}):
        raise ValueError('Informe o executável específico do emulador ou seu ID Flatpak.')
    return name.lower()
