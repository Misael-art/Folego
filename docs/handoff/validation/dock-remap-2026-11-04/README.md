# Retorno das barras pelo KWin — 04/11/2026

Incidente observado na instância residente: barra de 948 × 132 em `(604, 368)`
na área útil `(0, 0, 948, 593)`. A regra própria `folego-widget` do KWin tinha
`position=604,368` e `positionrule=3`. Ao reexibir a barra depois da Central, o
KWin reaplicou essa posição inicial do widget flutuante. O código não pedia
novo encaixe porque a área útil e o alvo calculado não tinham mudado. A alça
superior, no centro da barra larga, ficou fora da área visível.

No [ensaio KDE/Wayland](result.json), uma janela própria com HOME/XDG privados
voltou da Central à barra superior em `(0, 0, 948, 132)`. O menu **Posição do
widget** na Central abriu a lateral esquerda em `(0, 0, 112, 593)`, e **Voltar**
recuperou o widget flutuante de 280 px. Os atalhos recolhíveis e as quatro
cotas continuaram alcançáveis. Capturas da janela própria:
[topo](dock-top-collapsed.png), [esquerda](dock-left-collapsed.png) e
[flutuante](dock-return.png).

Teste focado: `./dev test tests/test_ui_compact.py
tests/test_ui_main_window_tabs.py tests/test_ui_hover_actions.py -q`, aprovado.
Gate final `./dev check`: **1247 passed, 2 skipped** sem Qt;
**1597 passed, 2 skipped** Qt offscreen. A prova física cobre apenas a área
948 × 593 e a transição da janela própria, sem certificar HD, widescreen ou
outras escalas do compositor.
