"""Startup boost, as measured on this host (not as documented elsewhere).

Edge 155.0.4283.45 on BigLinux keeps a ``startup_boost`` object in Local State
holding only ``last_browser_open_time``; the ``enabled`` key is absent, which is
how a signed-in profile runs the boost without ever saying so. The key name is
not invented: ``strings`` over /opt/microsoft/msedge/msedge contains
``startup_boost.enabled`` next to ``startup_boost.last_browser_open_time``, so
the browser does read it.
"""
from .... import paths
from ..model import Tuning

STARTUP_BOOST = Tuning(
    id="edge.startup_boost",
    label="Startup boost do Microsoft Edge",
    why="mantém um processo do Edge vivo depois de fechar a última janela para "
        "a próxima abrir mais rápido; desligado, a RAM volta quando o Edge fecha",
    key_path=("startup_boost", "enabled"),
    desired=False,
    target=paths.edge_local_state,
)
