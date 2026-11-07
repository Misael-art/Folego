# Barra superior compacta e ações recolhíveis — 04/11/2026

A [validação KDE/Wayland](result.json) usou janela, dados e áudio próprios, com
HOME/XDG privados, sem contas reais nem efeito sobre recursos. Na área útil
948 × 593, o KWin confirmou as laterais 112 × 593 e o topo 948 × 132. O
indicador de folga ficou à esquerda das cotas; RAM, CPU, temperatura, swap,
tmpfs e espaço livre ficaram depois; teclado/menu e Pausar formaram um grupo à
direita. Quatro cotas positivas com badges couberam inteiras no topo mesmo com
as seis ações expandidas (`scroll_max=0`).

O ponteiro nativo mostrou e recolheu as seis ações em cada lateral e no topo.
O botão de retorno no centro da borda superior permaneceu no mesmo lugar ao
expandir/recolher e restaurou o compacto. As duas laterais conservaram rolagem
para quatro cotas quando as ações estavam abertas, sem sobreposição. O teste
focado `./dev test tests/test_ui_compact.py tests/test_ui_hover_actions.py -q`
passou com **35 testes**. `./dev check` final: **1242 passed, 2 skipped**
headless e **1586 passed, 2 skipped** Qt offscreen; `git diff --check` limpo.

Capturas da janela própria: [topo recolhido](dock-top-collapsed.png),
[topo expandido com quatro cotas](dock-top-scrolled.png),
[alça de retorno no topo](dock-top-grip.png),
[esquerda recolhida](dock-left-collapsed.png), [esquerda expandida](dock-left.png),
[direita recolhida](dock-right-collapsed.png) e [direita expandida](dock-right.png).

Limites: esta sessão física cobre apenas a área útil 948 × 593 e o tema de QA;
HD e widescreen são exercitados nos testes Qt offscreen. A rolagem lateral até
a quarta cota foi posicionada por código; não prova gesto físico de scroll.
Tentativas anteriores falharam por alvo encoberto pelo Plasma e por alça de
retorno móvel no topo. Seus recibos foram preservados em
`.scratch/dev-tests-reviewed`; não contam como aceites.
