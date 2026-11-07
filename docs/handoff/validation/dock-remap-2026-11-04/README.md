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
**1602 passed, 2 skipped** Qt offscreen. Na instalação do host, a ação da
bandeja revelou que `QAction.triggered` enviava um booleano ao novo argumento
de posição; o valor passou a ser ignorado, e um teste específico cobre a
abertura pelo menu. A regra do KWin também posicionou o flutuante parcialmente
fora da tela quando sua altura aumentou; agora a posição é conferida e limitada
à área útil. Tentativas nativas intermediárias detectaram conflitos entre
a conferência e cliques de encaixe ou mudanças tardias do KWin. Elas estão
preservadas em `.scratch/dev-tests-reviewed` e não contam como aceite; a prova
final é o [recibo atual](result.json). A prova física cobre apenas a área
948 × 593 e a transição
da janela própria, sem certificar HD, widescreen ou
outras escalas do compositor.

Na instalação final do host, o item da bandeja abriu o widget flutuante em
`(604,331)`, com 280 × 256,3 dentro da área 948 × 593. A Central foi ocultada;
o serviço `app-folego@autostart.service` ficou ativo no PID 1674038. Os cliques
de encaixe foram validados na janela de QA própria.
