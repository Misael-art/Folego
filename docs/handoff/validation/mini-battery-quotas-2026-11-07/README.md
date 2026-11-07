# Bateria e franquias na mini horizontal — 07/11/2026

O usuário aprovou as células de CPU, temperatura e RAM e pediu o mesmo
tratamento para bateria e franquias, com pequenos lembretes de entregas e
resets. A largura pode crescer conforme o conteúdo; a altura permanece em
46 px lógicos. O [registro de design](../../../DESIGN.md) e o
[guia do compacto](../../../COMPACTO.md) descrevem os contratos.

As fontes são o Snapshot e o AIMonitor compartilhados. Não há outro coletor,
varredura de processos, chamada de rede ou efeito de recurso. Os contadores
são entregas para revisitar e resets resgatáveis, como no widget completo;
não indicam quantidade de agentes em execução. Uma pergunta opcional sobre
esse significado não recebeu resposta durante a implementação.

Percentual da bateria, cor própria e autonomia na dica usam o monitor de
bateria existente. Cotas positivas seguem a ordem decrescente. A cota zerada
exibe tempo de reposição somente quando todas as janelas que a bloqueiam são
confirmadas de cinco horas. Bloqueio semanal não mostra contagem. Expiração
retira a leitura até nova observação; não repõe crédito por inferência.
Lembretes confirmados podem permanecer com cota desconhecida em `—`.

O [recibo](result.json) contém **48 cenários** de uma janela própria no
KDE/Wayland, nos oito temas e seis estados: disponível, reset de cinco horas,
bloqueio semanal, pausa, desconhecido e recuperação. Dados sintéticos,
HOME/XDG privados, áudio isolado e pedidos dos coletores desativados na QA.
A tela real forneceu área útil de 948 × 593 px lógicos. Células, marcadores e
controles ficaram dentro da faixa e sem sobreposição. A faixa voltou ao
compacto e à mini usando o canal de posicionamento existente. Ao retirar as
cotas, encolheu de 676 para 410 px no ensaio final.

| Estado | Claro | Escuro |
| --- | --- | --- |
| Disponível | [SNES](snes-us-available-wayland.png) | [PS2](ps2-available-wayland.png) |
| Reset de cinco horas | [SNES](snes-us-reset-5h-wayland.png) | [PS2](ps2-reset-5h-wayland.png) |
| Bloqueio semanal | [SNES](snes-us-weekly-wayland.png) | [PS2](ps2-weekly-wayland.png) |
| Leitura desconhecida | [SNES](snes-us-unknown-wayland.png) | [PS2](ps2-unknown-wayland.png) |

A primeira inspeção revelou texto cortado: o cálculo de tamanho do botão Qt
ignorava o layout de rótulos e marcadores. O piso agora mede esse conteúdo
após aplicar o estilo, e os marcadores permanecem pequenos mesmo quando o
texto de reset exige uma célula mais larga. A fixture inicial também permitia
ao worker substituir os dados sintéticos; os pedidos foram isolados antes
de gerar estas capturas finais.

O painel de contas abre imediatamente pelo botão, mas o clique Qt simulado
no Wayland o dispensa; o menu de controles preexistente tem o mesmo resultado
nesse ensaio. Isso não certifica interação física com menus. O teste Qt
offscreen verifica despacho, seleção e owner visível do painel. Toque,
arraste físico, outras escalas e alimentação real da bateria têm aceite
próprio. A regra de 948/1920/2560 px recebe teste de geometria controlada;
isso não equivale a três monitores físicos conectados.
