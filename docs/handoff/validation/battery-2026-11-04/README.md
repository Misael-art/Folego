# Bateria no widget — validação de 04/11/2026

A [validação KDE/Wayland](result.json) usou dados de bateria e cotas sintéticos,
HOME/XDG privados e saída de áudio inacessível; não houve reprodução no
alto-falante do usuário. A janela própria foi encaixada nas laterais
112 × 593 e no topo 948 × 132. O percentual laranja e a estimativa de 1h
apareceram nas três formas. Quatro cotas continuaram alcançáveis nas laterais;
no topo couberam sem rolagem. As ações recolhíveis e o retorno ao compacto
continuaram funcionais. Capturas da própria janela: [topo](dock-top-collapsed.png),
[esquerda](dock-left-collapsed.png), [direita](dock-right-collapsed.png).

Uma primeira tentativa nativa encontrou 17 unidades de conteúdo excedente no
topo com a bateria em uma linha nova. A leitura foi movida para a segunda linha
das métricas; a repetição integral passou. A tentativa falha foi preservada em
`.scratch/dev-tests-reviewed` e não conta como aceite. A prova nativa cobre só
a área útil 948 × 593; outras resoluções continuam simuladas em Qt offscreen.
Não houve prova acústica humana nem acompanhamento de uma descarga real por
75%, 50%, 25% e 10%.
