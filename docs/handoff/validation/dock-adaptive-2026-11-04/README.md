# Barra adaptativa — validação de 04/11/2026

Janela e dados sintéticos próprios no KDE/Wayland, com HOME/XDG/áudio privados.
`tools/verify_window_navigation.py --dock-modes` confirmou pelo KWin as duas
laterais com **112 × 593** unidades lógicas e o topo com **948 × 142**. O retorno
ao widget compacto preservou a posição `(20, 120)` e acomodou o conteúdo atual
em 280 × 225. [Recibo integral](result.json) e capturas: [esquerda](dock-left.png),
[direita](dock-right.png), [topo](dock-top.png).

Com duas cotas confirmadas (90% e 69%), as duas laterais mostraram o indicador
principal maior, métricas centralizadas, espaço livre, pausa e os dois
indicadores de IA inteiros acima das seis ações em coluna. Sem cotas adicionais,
a barra de rolagem ficou oculta. O topo mostrou as cotas e as ações em linhas
horizontais. Cotas ausentes não apareceram. O retorno e a saída pelo controle
próprio foram confirmados. A primeira tentativa desta revisão falhou ao mover
o ponteiro nativo para a seta de retorno; a repetição integral passou. Essa
tentativa não conta como aceite.

`./dev test tests/test_ui_compact.py tests/test_ui_hover_actions.py
tests/test_ui_ai_quota_rings.py tests/test_ui_desktop_shortcuts.py -q`:
**38 passed**. `./dev check` final: **1242 passed, 2 skipped** headless;
**1574 passed, 2 skipped** Qt offscreen; diff check aprovado. Uma tentativa
anterior de `./dev check` foi interrompida após o headless verde e não conta
como gate completo. O teste nativo confirma uma saída de 948 × 593; não
certifica outras escalas, áudio real, clique físico em todos os monitores nem
uso prolongado. O posicionamento Wayland continua dependente da confirmação
do KWin; a interpolação de posição não é certificada por este fluxo.
