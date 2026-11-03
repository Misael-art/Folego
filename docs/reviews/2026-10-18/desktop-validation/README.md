# Validação de compositor, instalação GUI e soak

Atualização posterior: [ensaio independente de 30/10 aprovado](../../../handoff/validation/session-resilience-2026-10-30/soak/README.md)
em perfil controlado de 7200 s. As tentativas históricas abaixo continuam
arquivadas sem aceite; nenhuma duração foi somada.

**Estado em 24/10/2026: ensaios arquivados; soak de duas horas NÃO aceito.**
A última tentativa (`soak-private-wayland/report.json`, início em
18/10/2026 15:08:08 UTC) parou com **2470,47 segundos** registrados, 42 workers
e sete cancelamentos concluídos. Não existe relatório final de 7200 segundos.
O PID/boot originais já não existem; `interruption.json` registra a inspeção.
`soak-private-interrupted-analysis.json` recusa o aceite. Não há processo ativo
a aguardar nem duração transferível para outro host. A passagem atual está em
[diagnóstico consolidado](../../../DIAGNOSTICO-2026-10-24.md).

O registro histórico abaixo preserva preparações, resultados e falhas de 18/10.
A tentativa de 10:46 terminou sem relatório final:
última amostra com 2.740 segundos, seguida de novo boot do host às 11:37:19 UTC.
`soak-interrupted-analysis.json` recusa seu aceite pela duração incompleta.
O processo atual foi iniciado em sessão independente do terminal; identidade,
boot e hashes estão em `soak-private-launch.json`. Nenhuma duração é somada entre ensaios.
O ensaio anterior de 760 segundos foi interrompido em repouso, sem filhos,
para usar o wheel corrigido.

A consulta após o novo boot (`previous-boot-recovery.json`) encontrou 31
intenções com resultados correspondentes e diário sem corrupção. O último
ajuste permaneceu aplicado na fixture; consulta por ID retornou esse sucesso
sem modificar o diário. Não se restaurou nem repetiu a operação na tentativa
interrompida. O relatório de métricas anterior parou antes do último efeito.

A tentativa `soak-retry-wayland` também não foi aceita: após 30 minutos, a janela
estava aberta e a aba de temporários havia carregado 52 itens protegidos. O total
de widgets saltou exatamente 52 (187 → 239), excedendo o orçamento fixo de 32;
`soak-workload-change.json` registra a janela e o inventário. Isso não prova
vazamento, mas muda a carga do ensaio de repouso. O PID próprio foi encerrado em
repouso, sem filhos; relatório e análise recusada (`soak-analysis.json`) foram
preservados. O harness agora desabilita entrada na janela de QA, mantém aviso
de métricas sintéticas, ignora fechamento acidental até seu prazo explícito e
registra classes de widgets/linhas de inventário. Dois smokes (25 s e 10 s)
terminaram sem falhas. Os limites não foram ampliados, e o wheel não mudou.

A tentativa `soak-controlled-wayland` encontrou uma recusa após 105 minutos:
`temporários: limite de execuções retidas; revisão manual necessária`. As
tentativas compartilhavam o TMPDIR externo e somaram exatamente 256 diretórios.
A proteção recusou antes de lançar o filho; não se converteu isso em sucesso.
`soak-controlled-analysis.json` e a interrupção ficam preservados. O harness
agora cria TMPDIR/PYTEST_DEBUG_TEMPROOT dentro de cada `--state` exclusivo,
calcula previamente o teto de filhos (141 para este ensaio, abaixo de 256) e
registra cada resultado de worker. Smoke de 25 s passou: nove workers e um
cancelamento, dez diretórios, todos do próprio PID; diário e bytes restaurados
também conferiram. Nenhum diretório anterior foi removido e o limite do produto
não mudou. Gestão/expiração desses temporários retidos continua pendente para
uso indefinido; uma raiz fresca para QA não resolve essa limitação do produto.

## Ambiente e escopo

- BigLinux, kernel Linux 6.18.49, sessão KDE/Wayland ativa, KWin **6.7.4**,
  Qt do compositor **6.11.2**. Detalhes em `os-release.txt` e `kwin-support.txt`.
- Instalação GUI **não editable**, em venv novo sem system-site-packages:
  Python **3.14.7**, PySide6/Qt **6.12.0**, wheel `folego 0.1.0`.
  Manifesto e SHA-256 em `install-manifest.json`. Os **100 arquivos Python** do
  pacote instalado correspondem ao checkout (`source-wheel-comparison.json`).
- A sessão inicialmente expunha eDP/DP em 135%/100%; o monitor DP deixou de estar
  conectado durante a validação. Não se alteraram as saídas físicas. O caso
  físico final usou eDP-1 a **135%**, com razão fracionária da janela 1,35.
- Escalas **100%, 150% e 200%** foram exercitadas em KWin Wayland com saídas
  virtuais, em D-Bus/runtime próprios. X11 foi exercitado em Xvfb + KWin X11,
  com namespaces de PID/rede e `/tmp` privado; não é um login físico X11.
- HOME/configuração/dados/estado e temporários de teste ficam em `.scratch`,
  no btrfs de `/home`, inicialmente com 53,1 GiB livres. O caminho está em
  `workspace-path.txt`. O runtime da sessão física já estava a 97–98%; não se
  produziu saturação para provar o alerta, nem se fez limpeza no host.

Esta evidência demonstra instalação Python limpa **no mesmo BigLinux**, e uma
execução adicional com o restante do filesystem somente leitura. Não equivale a
instalar outra distribuição/VM Linux limpa, nem a certificar todos os drivers.

## Falhas reproduzidas e correções

1. O alerta real de runtime fazia o título sem quebra de linha impor largura de
   1.265 px à central. Agora o título quebra; os controles de grupos foram
   distribuídos em duas linhas, preservando nome, quantidade e RSS estimado.
2. O compacto cortava texto e mantinha frameless no Wayland. O fallback agora é
   uma janela decorada do compositor, com ações em grade e espaço para o texto.
   Posição absoluta não é restaurada/salva nesse backend. X11 mantém seu controle
   próprio, com clamp completo e reação a mudanças de tela.
3. Sem bandeja, fechar a central parava workers apesar de haver compacto aberto;
   ocultar o compacto podia tirar a última via de retorno. Agora o compacto
   visível conserva os workers e ocultá-lo devolve a central quando necessário.
4. Pausar antes da primeira amostra não atualizava o título. Agora central e
   compacto apresentam a pausa sem depender de uma leitura anterior.
5. A bandeja só aparecia depois da primeira coleta, embora já fosse considerada
   uma via de retorno. Ela agora é mostrada na instalação, com tooltip de espera.

Regressões em `test_ui_compact.py`, `test_ui_main_window_tabs.py`,
`test_ui_layout.py` e `test_ui_tray.py`; assertions de dados/quantidades anteriores
foram preservadas. Capturas antes da correção: `images-baseline/`. Capturas
físicas após correção: `images-wayland/`, incluindo
`compact-compositor.png`, obtida pelo Spectacle com decoração real do KWin.

## Matriz executada

| Caso | Evidência | Resultado |
|---|---|---|
| KDE Wayland físico, sem bandeja | `no-tray-wayland-final/report.json` | 6 casos passaram: abrir, fechar central sem parar workers, conservar retorno, pausa, fullscreen e saída |
| KDE Wayland físico, com bandeja | `with-tray-wayland-final2/report.json` | 6 casos passaram; SNI identificado pelo PID e Activate devolveu a central |
| Acessibilidade e teclado físico | `native-keyboard.json`, `launcher-accessibility.json` | AT-SPI acionou pausa/saída; Tab por uinput mudou o foco; Ctrl+Shift+F nativo abriu o compacto |
| Launcher fora do shell ativado | `gio-launcher-process.json` | GIO abriu o entrypoint absoluto; PATH somente `/usr/bin:/bin`, VIRTUAL_ENV/PYTHONPATH ausentes; encerramento pela GUI, código 0 |
| GUI com filesystem do host somente leitura | `readonly-native/report.json` | 6 casos passaram; escrita disponível somente no workspace e evidências |
| KWin Wayland, escalas 100/150/200 | `nested-wayland-{100,150,200}/report.json` | 6 casos por escala passaram; imagens de todas as abas |
| Remoção de saída virtual com compacto aberto | `nested-hotplug-verified/report.json` | Virtual-1 → Virtual-0; moldura inteira certificada dentro da saída restante pelo próprio KWin |
| KWin X11/Xvfb, escalas 100/150/200 | `x11-final/report.json` | 6 casos por escala, arraste nativo e Tab passaram |
| Posição/foco no X11 | `x11-final/position-and-focus.json` | Posição 280,260 persistida; foco passou de Abrir central para Ocultar controle; zero operações no diário |
| CLI por wheel, sem Qt | `installation-offline/report.json` | import/doctor passaram sem PySide6 |
| Remoção do pacote GUI | `installation-offline/state-{before,after}.json` | hashes de todo o HOME descartável preservados; entrypoint removido; nenhum autostart criado |

O helper de entrada usou um socket privado, foi encerrado e não deixou processo.
Nenhum serviço de input/autostart foi instalado. Captura ativa cuja janela
divergiu do alvo foi descartada. As capturas de cliente são identificadas como
tal; o Spectacle não produziu arquivo no compositor virtual, apesar de retornar
0. Não se usa esse retorno como prova de imagem. O hotplug foi verificado pela
geometria autoritativa do KWin: antes `(2862,564,420,408)`, depois
`(814,564,420,408)`, dentro de `2048×1536`, com decoração e workers ativos.

O observador usa a [API oficial de scripting do KWin](https://develop.kde.org/docs/plasma/kwin/api/),
sempre na sessão privada, filtrando PID e título. Não se carregou esse script na
sessão física. Leitura AT-SPI e navegação por teclado não certificam narração de
um leitor de tela real, que não foi executado. Arraste físico Wayland não foi
certificado; o fallback decorado e seus controles foram verificados, e o gesto
foi testado no X11 isolado. A política do Plasma pode ocultar um SNI; registro e
ativação por D-Bus não afirmam que o ícone estava permanentemente pintado.

## Soak prolongado

`tools/soak_session.py` roda tempo real, com janela Wayland minimizada para não
ocupar o desktop de trabalho. O coletor é sintético, a cada dois segundos, com
pressão alternada e coletas lentas injetadas. O event loop/Qt, histórico e filhos
QProcess são reais. A cada minuto, o worker instalado detecta/aplica/reverte um
ajuste apenas no perfil descartável; periodicamente cancela um filho próprio
que só dorme. Não há sinais em processos do usuário, inventário destrutivo,
daemons de trabalho ou alteração de grants/automação do host.

`retry-environment.json` confirma a sessão após o reboot. A leitura do KWin em
`soak-private-window.json` identificou o PID do ensaio atual com `hidden: true` e
`focused: false`; não se ativou a janela para fazer essa confirmação.
Nesse backend, a propriedade Qt de minimização difere da visibilidade relatada
pelo KWin; usa-se a observação do compositor para afirmar que estava oculta.
`tools/watch_soak.py` acompanha a identidade de processo/boot e roda o analisador
quando ele termina; não envia sinais nem repete a carga em caso de interrupção.

O relatório registra RSS inicial/baseline/pico/tendência, CPU, contadores de I/O,
descritores, widgets, filas, amostras, QProcesses, filhos, resultados e atrasos
de heartbeat. Histogramas e acumuladores têm tamanho limitado. `soak-budget.json`
define os limites, incluindo crescimento de RSS, CPU, descritores, filas e
latência; `tools/analyze_soak.py` recusa uma duração incompleta.

Checkpoint da tentativa `soak-controlled-wayland`, com 3.640 segundos
(`soak-halfway-analysis.json`): CPU UI+filhos
0,87%, crescimento de pico de RSS 3,27 MiB, p99 de heartbeat até 5 ms e escrita
25,5 MiB/h. A tendência de RSS parcial era 4,54 MiB/h, acima do teto de 4;
esse checkpoint não passou e não substitui o intervalo completo. Não se
ampliou o orçamento. A verificação de ausência de filhos após saída só pode
valer no relatório final; a amostra parcial apenas não tinha filhos naquele instante.

Leitura adicional da mesma tentativa aos 5.410 segundos
(`soak-memory-checkpoint.json`), somente
do PID identificado: RSS 52.104 KiB, PSS 32.403 KiB e swap 18.104 KiB. A queda
de RSS tem participação de paginação; uma tendência residente negativa não é
apresentada como RAM liberada nem como prova de ausência de vazamentos. O
orçamento usa RSS observado, contagens de objetos/filas e os demais recursos
registrados; não houve profiling de todas as alocações ou baseline de swap.

O heartbeat mede atraso de despacho Qt, não tempo de composição de frames.
Minimização não equivale a duas horas de renderização visível/fullscreen.
Coletor sintético não certifica custo de inventariar milhares de processos,
sessões ou entradas reais. O teste não simula estado D de kernel nem promete
encerrá-lo. Esses limites permanecem separados do resultado medido.

## Regressões e reprodução

- Qt/PySide6 **6.11.2** do ambiente anterior: **1134 passed in 19.74s**,
  `suite-qt611.log`.
- Qt/PySide6 **6.12.0** em venv novo: **1134 passed in 21.09s**,
  `suite-qt612.log` (pytest 9.1.1, Hypothesis 6.170.1).
- Venv sem PySide6/shiboken6: **917 passed in 12.92s**,
  `suite-headless.log`.
- `git diff --check` passou. CI remota não executada.

Cada suíte usa `mktemp -d` em `.scratch`, `TMPDIR`/`PYTEST_DEBUG_TEMPROOT`
fora de `base`, e `pytest -o addopts= --basetemp=... -q`. Para headless,
acrescentar `--without-qt`. Os venvs de QA não foram ativados no shell.

Ferramentas reproduzíveis adicionadas: `desktop_probe.py`,
`verify_desktop_flow.py`, `verify_x11_session.py`, `verify_virtual_hotplug.py`,
`record_kwin_geometry.py`, `verify_installation.py`, `soak_session.py`, `watch_soak.py` e
`analyze_soak.py`, em `tools/`. `packaging/make_launcher.py` gera um desktop
file com Exec/TryExec absolutos; não instala autostart.

Para repetir o soak com um venv contendo o wheel GUI, usando diretórios novos:

```bash
rtk proxy env TMPDIR=/caminho/persistente/general PYTEST_DEBUG_TEMPROOT=/caminho/persistente/pytest-root /caminho/venv/bin/python -I tools/soak_session.py --state /caminho/persistente/novo-soak --output /caminho/evidencias --duration 7200 --warmup 120 --job-interval 60 --sample-interval 10 --platform wayland
```

O diretório `--state` precisa não existir, e o destino deve ser verificado como
persistente. Use `--platform offscreen` para regressão sem desktop; isso muda o
escopo da evidência. Não reproduzir scripts de saída/escala no compositor físico:
os controladores de hotplug exigem a sessão privada com nomes Virtual-0/Virtual-1.

Falhas de preparação preservadas: fixture inicial sem mounts recusou os filhos;
hash de remoção inicialmente incluía cache novo do instalador no HOME (corrigido
fixando cache fora dele, mantendo comparação integral); resolução em cache vazio
expirou; execução offline com os mesmos pacotes verificados passou. A seleção
X11 inicialmente combinava PID/título com OR; foi corrigida para AND. Essas
falhas do harness não foram convertidas em aceites do produto.

F8 avançou em instalação/launcher, regressões e validação de desktop, mas não é
aceite universal: outras distribuições, leitor de tela, login físico X11,
orçamento total/compactação do histórico e estado D continuam pendentes.
F6/arquivamento automático de fixtures permanecem desligados. Nenhum commit,
push, limpeza do host ou instalação de autostart foi realizado.
