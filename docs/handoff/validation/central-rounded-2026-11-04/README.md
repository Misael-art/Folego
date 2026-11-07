# Cantos reais da Central — 04/11/2026

A captura do usuário mostrou a janela sem moldura com os quatro cantos retos.
O tema preenchia o retângulo inteiro; depois do primeiro ajuste, a barra de
rolagem ainda cobria o canto inferior direito. A Central agora pinta um fundo
arredondado com alfa real e reserva espaço para a barra de rolagem no canto.

O teste focado `./dev test tests/test_ui_layout.py -q` passou com **9 testes**,
incluindo os quatro cantos em fundo opaco e com 50% de transparência. A
primeira execução falhou nos dois casos pelo canto inferior direito opaco e
está preservada em `.scratch/dev-tests-reviewed/central-rounded-first-failed-20261104`;
ela não conta como aprovação. O `./dev check` final passou com **1247 passed,
2 skipped** sem Qt e **1604 passed, 2 skipped** com Qt offscreen.

O [recibo KDE/Wayland](result.json) passou numa janela e HOME/XDG próprios:
frame e cliente coincidiram em 900 × 620, os quatro pixels extremos tiveram
alfa abaixo de 32, e o fluxo de retorno ao widget e de encaixe continuou
funcionando. A [captura da Central](central.png) mostra o resultado. O ensaio
usa dados sintéticos; o compositor confirma esta janela de QA, não uma sessão
longa nem todos os temas e escalas físicos.
