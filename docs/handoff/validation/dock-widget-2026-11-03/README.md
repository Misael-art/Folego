# Widget encaixável — validação de 03/11/2026

Janela própria em KDE/Wayland, com HOME/XDG e áudio privados e telemetria
sintética. `tools/verify_window_navigation.py --dock-modes` confirmou via KWin
direita `(728, 0, 220, 593)`, esquerda `(0, 0, 220, 593)`, topo
`(0, 0, 948, 118)` e retorno ao compacto na posição inicial
`(20, 120, 280, 185)`. Nenhuma conta, serviço ou janela de trabalho foi alvo.
O recibo integral está em [result.json](result.json); capturas da janela própria:
[direita](dock-right.png), [esquerda](dock-left.png), [topo](dock-top.png) e
[retorno](dock-return.png). A lateral esquerda e o topo foram conferidos no tema
escuro PS2; a direita, no tema claro SNES.

`./dev test tests/test_ui_compact.py tests/test_desktop_tools.py -q`:
**30 passed**. `./dev check` na versão `0.2.0b4`: **1242 passed, 2 skipped**
headless e **1574 passed, 2 skipped** Qt offscreen; diff check aprovado.
Antes disso, duas tentativas do gate combinado falharam: prazo variável de
Hypothesis em backup (319 ms na primeira amostra, 12 ms na repetição interna)
e ausência de `outcome` num teste de entrada. Os recibos foram preservados em
`.scratch/dev-tests/run-aep92j_i` e `.scratch/dev-tests/run-f5v8r38f`;
o teste de entrada passou isoladamente e as duas suítes passaram completas
depois, sem alterar limites.

O teste nativo verifica a janela e geometria compositoras em uma saída de
948 × 593 px. A matemática de área útil também foi coberta com painéis
simulados no teste Qt. Não prova arraste físico, leitores de tela, outros
monitores/escalas ou uso prolongado. No Wayland, a transição de posição é
solicitada ao KWin e o conteúdo reaparece suavemente após confirmação;
o compositor não oferece neste fluxo uma interpolação de posição certificada.
