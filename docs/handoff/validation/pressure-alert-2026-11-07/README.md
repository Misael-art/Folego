# Revisão leve da coleta e dos avisos — 07/11/2026

O monitor já registra, por boot ID, temperatura com origem, energia quando
disponível, RAM, swap, PSI e maior CPU a cada ~15 s. O observador lento reúne
até três boots encerrados com lacunas explícitas. Não há efeito no host associado
a estes avisos. A causa dos reinícios continua indeterminada.

## Evidência do host antes da mudança

- Boot atual `c9f3eb3d-9be5-4f13-8577-25880bfcc382`: 227 linhas schema 2,
  entre 10:45:20 e 11:59:21 -03, sem falha de fonte registrada nessa janela.
- `collector_read_ms`: média 238,14 ms, mediana 67,62 ms, p95 1.785,23 ms,
  p99 3.076,49 ms, máximo 3.705,67 ms. É tempo de parede da fase de leitura,
  não CPU total do Fôlego. O poll anterior era de 2 s; p95 próximo dele reduz
  a folga durante builds concorrentes. A GUI residente usava o código anterior.
- Histórico local total ~1,6 MiB em 12 boots; boot atual ~120 KiB. Não havia
  limite imediato, mas o aviso anterior só surgia nos últimos 2 KiB de cada
  teto, tarde demais para preservar continuidade num boot longo.
- RetroDev Studio compilava durante a revisão. RAM disponível permaneceu acima
  de 6 GiB nas leituras pontuais; não se provocou pressão nem calor para testar.

## Incremento

- Poll principal da GUI: 5 s. O gravador continua em 15 s, com 4 MiB por boot,
  32 MiB totais e a mesma política de fsync. Não há nova leitura de `/proc`,
  sysfs ou journal por causa do alerta. Três médias PSI `avg60`, em porcentagem,
  passam a ser incluídas na mesma linha privada para permitir reconstrução
  pós-boot; o tamanho maior reduz um pouco a duração coberta pelo teto fixo.
- PSI já presente nas amostras: memória ≥5%, I/O ≥10% ou CPU ≥25% em `avg60`.
  Exige pelo menos 15 s entre a primeira e a última leitura alta, sem lacuna
  superior a 20 s, origem `ok` e idade ≤15 s. A bandeja mostra fonte, janela,
  horário, idade da amostra e uma ação manual. Limita cada tipo a um aviso por
  5 min; coincidências aparecem juntas em um aviso por amostra. Uma leitura
  ainda enfileirada ao pausar o monitor não emite aviso. PSI é espera, não uso
  de CPU nem diagnóstico de causa.
- Capacidade: aviso em 85% do teto por boot ou total. Nenhum byte antigo é
  removido e a gravação continua a parar no teto.

## Verificação

`./dev test-headless tests/test_host_guard.py tests/test_host_timeline.py -q`:
18 aprovados. `./dev check`: núcleo 1.289 aprovados/2 ignorados; a primeira
rodada Qt terminou com segfault nativo do PySide6 durante a desmontagem de
uma janela de teste, sem resultado global. Um teste novo que só repetia o
encaminhamento entre objetos foi removido. Em seguida,
`./dev test tests/test_ui_tray.py tests/test_ui_main_window_tabs.py -q` passou
com 49 testes, e `./dev test` passou com 1.674 aprovados/2 ignorados. Após
um ajuste final no texto para reunir fontes simultâneas e mostrar a idade,
`./dev test-headless tests/test_host_guard.py tests/test_host_timeline.py -q`
passou com 19 testes e `./dev test tests/test_host_guard.py
tests/test_host_timeline.py tests/test_ui_tray.py -q` com 30. A suíte completa
não foi repetida após esse ajuste localizado.
Após incluir `avg60` no histórico, os testes focados de timeline/guardas
passaram novamente com 19 testes sem Qt, e host/avisos com 17 testes Qt.
Uma inspeção separada no KDE/Wayland real, com janela e estado próprios,
abriu o cartão de saúde, navegou até Disco e mostrou a orientação; não criou
pressão nem testou notificação real. `git diff --check` passou.

## Limites e pendências

A alteração só entra na GUI residente na próxima abertura normal; não se
reiniciou a sessão de trabalho. Offscreen não prova entrega de notificações pelo
Plasma. O boot curto continua sem amostras; pstore/boot e GPU têm owners
PhaseZero/SteamZero; SMART não tem sondagem periódica autorizada. Rotação
recuperável de histórico, alerta visível sem bandeja e confirmação de alívio
cooperativo permanecem no roadmap. O custo da nova frequência precisa ser
medido após uma próxima abertura normal da GUI. Não houve sinal, reparo, alteração de
perfil físico ou operação de disco.
