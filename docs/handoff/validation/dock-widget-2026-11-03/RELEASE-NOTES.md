# Fôlego v0.2.0b4 — prévia

O widget agora oferece três encaixes por setas que surgem nas bordas: barra
vertical à direita, barra vertical à esquerda e barra horizontal no topo.
Cada barra reorganiza os mesmos controles e indicadores, respeita a área útil
informada pelo desktop e tem uma seta de retorno ao compacto. As laterais
mantêm o rodapé na base e permitem rolar o conteúdo em telas baixas.

O cabeçalho compacto também recebeu marca, ícones e grupos de controles
refinados. A faixa de contas mostra apenas cotas positivas confirmadas,
ordenadas da maior disponibilidade para a menor. A entrada de uma cota durante
o monitoramento anima o indicador; uma reposição confirmada usa o som
configurável existente.

No KDE/Wayland, o encaixe usa o KWin apenas para a janela do próprio Fôlego e
confirma a posição antes de concluir. O conteúdo reaparece suavemente após o
reposicionamento. A movimentação da janela pelo compositor não tem animação
certificada nesta prévia. O modo de encaixe vale para a janela atual; uma nova
abertura começa no compacto.

Validação local: `./dev check` com 1242 testes sem interface e 1574 testes Qt
aprovados, 2 ignorados em cada perfil; posicionamento das três barras e retorno
conferidos numa sessão KDE/Wayland com janela e dados sintéticos próprios.
Permanecem pendentes os aceites físicos e de longa duração registrados na
passagem do projeto. Esta é uma prévia, não uma versão estável.
