# Barras adaptativas — validação de 04/11/2026

Janela, telemetria e cotas sintéticas próprias no KDE/Wayland, com HOME/XDG/áudio
privados. `tools/verify_window_navigation.py --dock-modes` confirmou pelo KWin
laterais de **112 × 593** unidades lógicas e topo de **948 × 190**, incluindo
retorno à posição inicial `(20, 120)` e saída pelo próprio controle. O [recibo
integral](result.json) registra geometria, visibilidade e rolagem. Capturas:
[esquerda](dock-left.png), [direita](dock-right.png), [topo](dock-top.png),
[grip esquerdo](dock-left-grip.png), [grip direito](dock-right-grip.png),
[quatro cotas à esquerda](dock-left-scrolled.png), [à direita](dock-right-scrolled.png)
e [no topo](dock-top-scrolled.png).

O grip de retorno fica na borda **externa** de cada lateral e termina antes
das ações. RAM, CPU, temperatura, swap, tmpfs e espaço livre se alinham à
esquerda na barra esquerda e à direita na barra direita. Os quatro cantos da
janela renderizaram alfa transparente nos temas claro e escuro. Duas cotas
confirmadas (90% e 69%) couberam inteiras; com quatro cotas e badges, a área
de conteúdo rolou até Grok enquanto as seis ações permaneceram fixas abaixo,
sem sobreposição. O topo apresentou os quatro indicadores na segunda linha,
com ações horizontais na base. Cotas ausentes não apareceram.

`./dev test tests/test_ui_compact.py tests/test_ui_ai_quota_rings.py
tests/test_ui_hover_actions.py tests/test_ui_desktop_shortcuts.py -q`:
**47 passed**. Os testes Qt simulam áreas úteis de **948 × 593**, **1920 × 1080**
e **2560 × 1080** para ambas as laterais e o topo, com quatro cotas e badges.
`./dev check` final: **1242 passed, 2 skipped** headless e **1583 passed,
2 skipped** Qt offscreen. O diff check passou. A primeira execução completa
desta revisão falhou no teste de tema, que ainda procurava a cor na folha de
estilos após a superfície passar a ser pintada; o teste corrigido verifica o
pixel renderizado. Somente a execução posterior foi aprovada.

Limites: apenas a área 948 × 593 foi exercitada no compositor real; as áreas
HD e widescreen foram simuladas no Qt offscreen. A rolagem foi posicionada
programaticamente até o fim; não é teste de gesto físico no Steam Deck. A
geometria Wayland depende da confirmação do KWin, sem interpolação de posição
certificada. Não houve prova de leitor de tela, áudio real ou uso prolongado.
Uma tentativa nativa anterior desta revisão falhou no tamanho mínimo do botão
do topo; a correção e a execução integral posterior passaram. Uma tentativa
com QTest de hover sintético não acionou o evento de entrada; o recibo final
usa a pintura explícita do grip e o clique nativo separado. Essas tentativas
não contam como aceites.
