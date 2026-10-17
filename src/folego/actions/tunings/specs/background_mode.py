"""Background mode ("continuar rodando aplicativos em segundo plano").

Measured on this host: the installed binary contains the key name
``background_mode.enabled``; the profile's Preferences has no such key at all,
while ``Local State`` carries ``profile.info_cache.Default.background_apps =
true`` — the browser's own record that this profile keeps running after the last
window closes. The other profile on the machine reads ``false``, which is what
makes the key worth writing instead of guessing.

Limit, on purpose: this spec only knows the ``Default`` profile. A machine with
more profiles gets the picker in the UI; writing one profile's file is never a
claim about the others.
"""
from .... import paths
from ..model import Tuning

BACKGROUND_MODE = Tuning(
    id="edge.background_mode",
    label="Aplicativos em segundo plano do Microsoft Edge",
    why="depois de fechar a última janela o Edge mantém serviços vivos (sincronização, "
        "extensões, notificações) ocupando RAM que o jogo precisaria",
    key_path=("background_mode", "enabled"),
    desired=False,
    target=lambda: paths.edge_profile_preferences("Default"),
)
