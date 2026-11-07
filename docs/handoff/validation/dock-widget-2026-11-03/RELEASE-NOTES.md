# Fôlego v0.2.0b4 — prévia

O widget pode ocupar a lateral esquerda, a lateral direita ou a faixa superior.
As setas das bordas revelam o encaixe e permitem voltar ao formato flutuante.
O menu **Posição do widget**, disponível também na Central, oferece as quatro
posições diretamente. Ações coloridas aparecem ao passar o mouse e se recolhem
quando não estão em uso. Nas laterais, indicadores e ações continuam acessíveis
por rolagem em telas baixas.

O cabeçalho foi reorganizado para a barra superior fina. Cotas de IA aparecem
somente com disponibilidade positiva confirmada, ordenadas da maior para a
menor. Uma cota que reaparece recebe animação, e uma reposição confirmada usa
o som configurável. O widget também mostra bateria, cor por faixa e estimativa
restante quando o Linux fornece dados suficientes. Ao descarregar, os avisos
sonoros marcam 75%, 50% e 25%; em 10% ou menos, há aviso a cada minuto.

Esta revisão corrige o retorno da Central quando o KWin reaplica uma posição
antiga: o Fôlego confere o encaixe novamente e limita o flutuante à área útil.
O modo de encaixe vale para a janela atual; uma nova abertura começa no
compacto. A movimentação da janela pelo compositor não tem animação
certificada nesta prévia.

Os testes locais e o ensaio KDE/Wayland com janela própria cobrem o topo, as
duas laterais e o retorno na área útil 948 × 593. Outras resoluções e escalas
físicas, leitor de tela, descarga real da bateria e observação de longa duração
continuam pendentes. Esta é uma prévia, não uma versão estável.
