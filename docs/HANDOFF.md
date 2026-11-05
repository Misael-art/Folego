# Passagem para o próximo agente — atualizada em 05/11/2026

## Recuperação NTFS pelo Linux e registro de incidentes — 05/11/2026

Incremento integrado no commit `e051952e4e0bbe0fdaf13bf48a5e17e3b60766f9`.
O pedido de recuperação real do cartão foi autorizado, mas a pré-checagem
somente leitura ainda bloqueia qualquer efeito: `/dev/mmcblk0p1`, UUID
`58D14C064972BE55`, está montado `rw` em `/mnt/sdcard`; não há outro disco
persistente conectado, o NVMe oferece apenas cerca de 124 GiB livres para um
volume NTFS com cerca de 285 GiB ocupados, a conta não tem leitura bruta sem
autenticação e `ddrescue` não está instalado. Uma imagem integral da partição
exige **538.345.104.998 bytes livres** com a margem adotada pelo plano. Nenhuma
desmontagem, correção, scrub ou cópia do cartão ocorreu. O processo
`lowntfs-3g` PID 3504 confirma a origem `/dev/mmcblk0p1` dos avisos; três
inodes de índices se repetiram no boot atual. Isso confirma erro de metadados
NTFS, mas não a causa do reinício nem uma falha física específica.

O Fôlego agora orienta uma recuperação Linux: preservar dados, criar imagem
retomável do volume desmontado, investigar/corrigir somente cópias e restaurar
após verificação. A aba Disco agrupa os inodes de índice distintos visíveis no
journal limitado, sem percorrer o SD. `disk recovery` faz pré-checagem de
identidade, montagem, leitura bruta, ferramenta, ancestral físico e espaço do
destino; não cria imagem nem autoriza um efeito futuro. `disk timeline` lê
amostras privadas de RAM, swap, PSI, temperatura e maior CPU que o worker da
GUI grava a cada 15 s, até 4 MiB por boot e 32 MiB no total. Sem GUI ativa,
fonte válida ou espaço no histórico, o dado fica ausente/desconhecido; não se
infere estabilidade. A escrita fica no estado XDG do Fôlego, nunca no cartão.
`disk timeline --boot-id <ID>` consulta amostras de um boot preservado mesmo
depois de avançar o histórico recente; ID inválido é recusado.

Validação em HOME/XDG e QA privados: testes focados de núcleo **8 passed**;
teste GUI focado **5 passed**; `./dev check` sequencial **1259 passed, 2 skipped**
headless e **1630 passed, 2 skipped** Qt offscreen. A primeira tentativa ampla
teve uma falha na simulação de permissão do destino, corrigida sem afrouxar o
guard; o registro dela foi preservado em `.scratch/dev-tests-reviewed`.
Após a consulta por boot e a recusa de eventos malformados, as suítes finais
repetiram **1260 passed, 2 skipped** com `./dev test-headless` e
**1631 passed, 2 skipped** com `./dev test`. Nenhum gate foi afrouxado.
`disk recovery /dev/mmcblk0p1 --destination /home/misael/Projects/Folego --json`
retornou `can_image=false` com quatro bloqueios: origem montada, leitura bruta,
ferramenta ausente e espaço insuficiente. Próximo: obter destino externo
persistente independente com ao menos 539 GB livres, identificar consumidores,
autenticar pelo fluxo oficial e instalar a ferramenta necessária pelo método
revisado. Revalidar tudo antes de copiar; não reparar o original antes de cópia
certificada. A verificação visual KDE/Wayland e o registro do monitor real
foram realizados após reabrir somente `app-folego@autostart.service`. Após o
commit, a unit foi reiniciada para carregar a correção final: PID **536652**,
`active/running`, `Result=success`; `disk timeline --json` leu 58 amostras do
boot atual. O fluxo real Central → Disco →
Verificar agora mostrou três índices NTFS, o contador Btrfs estável e a última
amostra local com horário curto. O histórico incluiu um pico ACPI de 94 °C
durante um `rustc` de outra tarefa e, após o último restart, 97 °C às 19:54:35.
Uma leitura direta do sensor indicou 80 °C às 19:54:49, com pressão de memória
e I/O baixa; a relação com os reinícios anteriores permanece desconhecida. A
captura foi inspecionada no KDE/Wayland pela ferramenta de desktop; não há
aceite de duração longa. Em uma imagem NTFS descartável de 32 MiB na área de
QA revisada, `mkntfs -F -Q`, `ntfsfix --no-action` e
`ntfsresize --check --no-action` terminaram com código 0; esse ensaio não
certifica a recuperação dos índices corrompidos do cartão.

## Travamento observado em 05/11/2026 e correção da leitura de boots

Investigação somente leitura do host, sem reproduzir o travamento. O `last -x`
marca o boot iniciado às 04:42 como interrompido antes do seguinte, às 16:03;
o journal desse boot só reteve mensagens de 14:56 a **15:18:46**. Não há pedido
de desligamento no recorte final. A máquina ainda emitia logs às 15:18:46;
o intervalo até 16:03 não revela quando deixou de responder nem quem a
reiniciou. Os boots seguintes terminaram de modo **ordenado**: às 16:16:01 o
`systemd-logind` registrou pressão curta da tecla de energia e às 17:29:29 o
`sddm` recebeu `PowerOff` do greeter. `last -x` confirmou os dois shutdowns.

No boot interrompido, `plasmashell` abortou às 15:01, 15:03, 15:08 e 15:12;
três relançamentos relataram falha de inicialização do plugin Qt, sem core
disponível. O diário continuou ativo depois disso, então essas falhas explicam
instabilidade visual, mas não comprovam o colapso do kernel. Entre 15:00 e
15:18, o `lowntfs-3g` emitiu 319 avisos de fixup e 319 de índice corrompido
no cartão `/dev/mmcblk0p1` montado em `/mnt/sdcard`. O `systemd-swap` expandiu
o pool com `zram2` às 15:04, usou backing `/dev/loop12` e registrou writeback
de 32.707 páginas frias às 15:18:19. São correlações temporais, sem prova
causal. No journal retido não há OOM, panic, lockup ou erro de controlador
NVMe/MMC na janela final. O Btrfs seguiu com `corruption_errs=6741` e os
contadores de leitura, escrita, flush e geração em zero, sem delta novo.

Os boots anteriores usavam `nowatchdog` e `nosoftlockup` em `/etc/default/grub`,
o que reduz a chance de um travamento gerar uma pilha útil. O boot atual usa
`quiet splash steamzero.gamemode=1` e registrou o NMI watchdog habilitado;
essa diferença também impede comparação controlada de estabilidade. Acesso
sem privilégio não permitiu ler `/sys/fs/pstore` nem SMART do NVMe. Não houve
alteração de boot, swap, serviços, mounts, nem tentativa de reparo. Próximo:
preservar os dados insubstituíveis do SD, obter SMART/pstore por autenticação
oficial se disponível e observar um novo episódio com registro persistente de
temperatura, PSI, swap e I/O, sem provocar carga para reproduzi-lo.

O monitor de boots do Fôlego foi corrigido em `11923d2`: procurar só nas últimas 40 linhas
classificava os dois desligamentos limpos como inconclusivos, pois o ruído de
shutdown escondia o evento. Agora consulta o evento específico do `logind`
em cada boot; ausência permanece inconclusiva. A consulta real passou a
mostrar **1 boot inconclusivo e 2 com desligamento registrado**. Teste focado
passou em HOME/XDG privados. `./dev check` sequencial: **1255 passed, 2 skipped**
sem Qt em 26,44 s; **1626 passed, 2 skipped** Qt offscreen em 106,36 s. As
árvores de QA concluídas foram preservadas em `.scratch/dev-tests-reviewed`.
A prova de desligamento não atribui causa ao boot inconclusivo.

## Saúde do host e guarda preventiva — 05/11/2026

O incremento `59c5ff5` na branch canônica e no PR #3 acrescenta monitoramento
passivo, integrado à Central, ao início da aba Disco e à CLI (`disk health` e
`disk guide`). O [mockup e a validação visual](handoff/validation/host-guard-2026-11-05/README.md)
precederam a implementação. A Central resume itens para revisar e leva à aba
Disco; a aba apresenta temperatura atual/pico em quatro minutos, limite do
mesmo sensor, RPM quando disponível, PSI CPU/I/O, avisos NTFS em dez minutos,
contadores e diferenças Btrfs, units de usuário em falha ou reinício, e quatro
boots registrados. O botão Orientação só explica um próximo passo manual.
Verificar agora usa o worker de cinco minutos; Copiar dados copia o diagnóstico
observado. Nenhum reparo, scrub, fsck, sinal, ajuste de ventoinha ou reinício de
serviço/host foi acrescentado.

`./dev check` passou sequencialmente: **1254 passed, 2 skipped** sem Qt em
23,41 s; **1625 passed, 2 skipped** Qt offscreen em 114,94 s. Python 3.14.7,
HOME/XDG privados, QA em `.scratch/dev-tests-reviewed/host-guard-20261105-*`.
Os seis jobs de produto do PR #3 passaram no SHA `609ab45`; o revisor
automático foi pulado.
O teste focado final da GUI passou; os recibos de janela própria KDE/Wayland
clara/escura confirmam navegação Central → Disco, ausência de rolagem horizontal
em 800 × 600, abertura da orientação e acesso à análise antiga por rolagem.
Dados dessa prova visual são sintéticos e não medem o dispositivo físico.

A consulta real somente leitura `./dev run disk health --json` em 05/11 às
06:03 -03 observou ACPI 78 °C com limite passivo 100 °C, RPM indisponível,
PSI CPU 3,65% e I/O 0% em 60 s, 12 avisos NTFS em dez minutos com `/mnt/sdcard`
como candidato, e 6.741 erros de corrupção acumulados no Btrfs sem baseline
do Fôlego para datar a diferença. Os três boots anteriores do diário não
mostraram encerramento nas últimas 40 mensagens de cada um; **a causa é
desconhecida**. `codex-quota-panel.service` não estava na lista de units em
falha/ativação nessa consulta; isso não prova correção, e o owner continua o
SteamZero. O Fôlego não percorre nem repara o volume NTFS, e um único mount
`fuseblk` é apenas candidato. Journal, sensores e baseline ausentes aparecem
como desconhecidos, sem inferência de saúde. Leitor de tela, tacômetro físico,
integridade dos dados e duração longa ainda não foram certificados. Próximo:
observar o painel por horas reais e correlacionar novos eventos com evidência
do owner de cada recurso. Após o push, a unit gráfica existente foi reiniciada
com owner/cgroup conferidos: novo PID **427632**, `active/running`,
`Result=success`. A primeira coleta criou o baseline Btrfs no estado XDG do
usuário com modo 0600. Entrada e Desempenho continuaram `active/running` nos
PIDs **4233** e **4236**. A prova de pixels permanece a das janelas próprias;
o serviço residente ainda não tem evidência de uso prolongado.

## Prévia v0.2.0b5 e registro de design — 05/11/2026

A rodada entregou as melhorias da auditoria de `8033b0f` e a documentação
consolidada. A apresentação pertence a `src/folego/ui`, na branch
`codex/prompt-implantation-20261104` e no [PR #3](https://github.com/Misael-art/Folego/pull/3).
O incremento `9d67aa3` usa os componentes Qt, o snapshot e o posicionamento
KWin existentes. `02ea5d6` sincroniza os testes de remapeamento com a exposição
da janela. O PR é draft e depende do #2. No #2, um job Qt da revisão documental
posterior da b4 está cancelado, com o outro job Qt verde. O CI do SHA da b5 é
independente desses resultados.

O widget lateral mantém cabeçalho e gaveta de ações fora da área rolável.
O conteúdo cabe horizontalmente mesmo com trilho e a última cota fica
acessível por rolagem. O topo tem 120 px a partir de 900 px úteis, com a
marca e a folga em uma coluna, quatro cotas em faixa própria, leituras
agrupadas e controles à direita. Ao remapear, a confirmação só lê geometria
depois que o Qt expõe a janela própria. O fade usa animação com vida própria,
separada do efeito gráfico substituído durante as transições.

Atividade recente separa ação, resultado e horário, com detalhes expansíveis
e diagnóstico integral. Disco, Temporários e Órfãos mostram os estados antes
das tabelas. Desempenho prioriza apps observados, Acessibilidade aproxima
verificação e estado, Opções agrupa preferências e recuperação, e Prompts
quebra títulos longos em até duas linhas, com dica integral.
O [registro de design](DESIGN.md) reúne conceitos, mockups e revisões com
detalhes técnicos, evidências e propostas ainda em aberto.

- **Local.** 228 focados na revisão intermediária, 15 regressões de encaixe
  no código final e `./dev check` final com **1250 passed, 2 skipped** sem Qt
  e **1616 passed, 2 skipped** Qt offscreen. Python 3.14.7 e HOME/XDG privados.
  A primeira suíte completa falhou em dois testes de exposição do widget.
  As tentativas de validação com falhas foram preservadas integralmente
  em `.scratch/dev-tests-reviewed` e não integram as contagens finais.
- **Compositor.** [19 casos KDE/Wayland em janela própria](handoff/validation/design-b5-2026-11-05/README.md).
  Central em 900 × 620 na saída widescreen. Encaixes na área útil 948 × 593,
  laterais 112 × 593 e topo 948 × 120, quatro cotas com badges, atalhos
  recolhíveis e retorno. O teste de topo mediu rolagem zero com atalhos
  abertos. As capturas offscreen complementam o ensaio em 800 × 600.
- **Host.** A GUI PID 4173 saiu pelo item da própria bandeja, com owner e
  identidade conferidos. `./dev setup` instalou a fonte `0.2.0b5` e a unit
  gráfica existente iniciou em PID **155844**, `active/running`,
  `Result=success`, com janela confirmada pelo KWin. Entrada e Desempenho
  mantiveram os PIDs 4233 e 4236. A prova de pixels pertence às janelas de QA.
- **Distribuição.** O SHA `02ea5d650cbd535406359d58507ebf8d0baf40c8`
  passou nos seis jobs de produto do PR, com revisor automático skipped.
  O fonte arquivado conferiu 941 blobs do Git, o wheel 159 arquivos do pacote,
  e os metadados de wheel/sdist conferiram a versão b5. O teste de instalação
  em ambientes descartáveis confirmou CLI sem Qt e preservação do estado
  ao remover a GUI. Artefatos locais em `.scratch/release-b5-ilmYqx`.

A [prévia pública v0.2.0b5](https://github.com/Misael-art/Folego/releases/tag/v0.2.0b5)
foi publicada em 05/11/2026 às 08:21:56 UTC. A tag anotada e a página da
release apontam para `02ea5d650cbd535406359d58507ebf8d0baf40c8`.
Os [três jobs da tag](https://github.com/Misael-art/Folego/actions/runs/41993576302)
passaram antes da publicação. Os quatro downloads públicos foram conferidos
contra os arquivos locais. O primeiro push da branch usou `HEAD` e foi
recusado pelo guard. O refspec da branch registrada passou pelo guard, assim
como a tag aprovada no registro central. O PR mantém a base #2.

| Arquivo | Bytes | SHA-256 |
| --- | ---: | --- |
| `Folego-0.2.0b5-source.tar.gz` | 19.694.640 | `29ab7245f0636d9079cf930e7c1ffac4c31c96835eb4398ab99b9a98f8adf923` |
| `folego-0.2.0b5-py3-none-any.whl` | 457.029 | `e170d83a4a249e539bccc6bd31c1039ede3ee305ed3e2dd8aba5fe19ef0f0928` |
| `folego-0.2.0b5.tar.gz` | 640.463 | `3ef2d88786b89920c5a296242ecda7ebf42315135d014a53e756466d9ce3d83a` |
| `SHA256SUMS` | 281 | `03c2c827b656dde83cbd24c9c0dd35610204005e5dbcdbea540d4a50d3c4f86b` |

Próximo incremento de design: validar toque, leitor de tela e escalas físicas
adicionais. A documentação registra como propostas a largura dos caminhos
longos e a densidade de tabelas com conteúdo realista. O aceite de bateria
física, tacômetro em hardware compatível e uso prolongado continua separado.

## Texto do quadro superior organizado — 05/11/2026

O pedido mencionava um quadro sem nova captura; foi solicitado esclarecimento
e, sem resposta durante a janela de trabalho, adotado explicitamente o quadro
superior da última captura. Owner: `ui/dashboard_tab.py`, na branch/PR #3
atuais. Aceite: separar estado geral dos valores de memória/app, manter alertas
e ação recomendada visíveis, preservar a cópia do diagnóstico e limpar os
valores quando a saúde perde validade, com layout ainda compatível com 800 × 600.

`af3da6f` troca a frase grande por título FÔLEGO + estado e três linhas
alinhadas: Disponível, Em uso e Aplicativo. Explicação, alertas e ação têm
espaços próprios. O sinal integral permanece no tooltip; a cópia recebe as
linhas em texto simples. Os widgets continuam apresentando dados do snapshot,
sem nova coleta ou efeitos de recursos. O fixture Wayland passou a declarar
as fontes sintéticas de memória/swap para exibir um resumo coerente.

`./dev test tests/test_ui_dashboard.py tests/test_ui_layout.py
tests/test_ui_main_window_tabs.py tests/test_ui_console_themes.py
tests/test_ui_transparency.py -q`: **103 passed** na execução final. Uma falha
anterior de coleta ausente foi corrigida mantendo "Coleta indisponível";
o teste de retorno ao widget foi sincronizado com a solicitação enfileirada
e o sinal de término, mantendo a exigência da duração de 260 ms. Houve uma
tentativa intermediária com importação incorreta no teste, corrigida. Logs
dessas falhas foram retidos em `.scratch/dev-tests-reviewed/hero-text-*` e
não contam como gates aprovados. O [recibo e capturas Wayland](handoff/validation/hero-summary-2026-11-05/README.md)
passaram nos oito temas em janela própria; a prova não certifica todas as
escalas físicas nem leitor de tela.

O SHA `af3da6f` passou nos seis jobs de produto do PR #3; revisor automático
skipped. A GUI antiga PID 94795 saiu pelo próprio item Sair do Fôlego da
bandeja, após revalidar o owner D-Bus. A unit ficou inativa com sucesso;
`./dev setup` sincronizou a fonte e a unit existente iniciou novamente em
PID 226852, `active/running`, `Result=success`. Os monitores de entrada e
desempenho mantiveram os PIDs 4501/4502. A nova instância usa o entrypoint do
ambiente gerenciado; o resultado visual medido em pixels é da janela QA,
não uma introspecção do processo residente. Próximo: uso normal do resumo
na Central e revisão do PR empilhado após #2. A tag b4 permanece anterior.

## Cooler junto à temperatura — 04/11/2026

Pedido: monitorar o cooler e mostrar RPM junto à temperatura; o usuário viu
CPU e cooler com apresentação estranha. Owner: `core/sysfs.py` →
`core/collector.py`/`Snapshot` → `ui/compact.py`, na branch canônica e PR #3.
O coletor lê `fan*_input` do hwmon, prioriza rótulo CPU, ignora GPU/disco e
mantém ausência/valor inválido como desconhecido; zero RPM é leitura válida.
Nenhum controle de ventoinha é acionado. O widget flutuante usa uma terceira
linha de duas colunas para ACPI/temperatura e RPM, sem encostar no percentual
de CPU; laterais e topo também exibem a rotação perto da temperatura.

Neste host, `/sys/class/hwmon` e `sensors` mostram somente temperatura `acpitz`
para o sistema, além de GPU/NVMe; não há `fan*_input` nem sensor específico da
CPU. O percentual CPU vem de `/proc/stat`, a leitura ACPI é explicitamente
rotulada e não comprova a temperatura da CPU. O cooler aparece **— RPM**, com
tooltip de indisponibilidade. A [captura Wayland própria](handoff/validation/cooler-monitor-2026-11-04/README.md)
mostra CPU 44%, ACPI 83 °C e — RPM sem quebra ou sobreposição; a janela QA foi
fechada pelo próprio aplicativo. Após o push, a instância residente antiga
PID 4436, confirmada na unit própria, saiu por **Sair do Fôlego** da sua
bandeja. A unit chegou a `inactive/dead`, `Result=success`, e foi iniciada
novamente em PID 94795, `active/running`, usando o entrypoint deste checkout.
Os monitores de entrada/desempenho mantiveram PIDs 4501/4502. A aparência
medida por pixels é da janela QA; a revisão carregada na residente é inferida
da reinicialização após o bootstrap do ambiente, não consultada dentro dela.

`./dev test tests/test_temperature.py tests/test_ui_compact.py -q`: **44 passed**.
`./dev check` sequencial, Python 3.14.7 gerenciado, HOME/XDG privados:
**1250 passed, 2 skipped** headless; **1612 passed, 2 skipped** Qt offscreen.
O hardware real não oferece RPM para aceite físico; os testes do sensor usam
sysfs descartável. Uma primeira rodada de UI falhou por quebra da tabela,
foi corrigida e está retida em `.scratch/dev-tests-reviewed`. Três execuções
antigas concluídas foram movidas integralmente à mesma área, sem exclusão,
para liberar slots de QA.

Código/evidência estão no commit `16fd251`. Uma corrida de stage chegou a
misturar o incremento com `ui/orphans_panel.py` num commit transitório;
o ajuste alheio ficou isolado em `d1fd7a6` e o código do cooler no commit acima.
O diff, a captura e os testes desta tarefa foram revisados. O PR #3 no SHA
`d39ace0` passou nos seis jobs de produto do CI; o revisor automático foi
skipped. Próximo: validar a rotação física numa máquina que exporte tacômetro
e revisar o PR empilhado após #2, sem merge ou release nesta tarefa.

## Controles modernos e navegação da Central — 05/11/2026

Pedidos integrados: modernizar a rolagem e revisar controles destoantes; dar
folga igual aos botões laterais, usar inicial maiúscula nos rótulos, marca
FÔLEGO e retirar Voltar do cabeçalho. Owner: checkout canônico, branch
`codex/prompt-implantation-20261104`, PR #3 empilhado sobre #2. Dependências:
tema central Qt e navegação já existente para o widget. Aceite: 6 px dos dois
lados das abas, marca em caixa alta, retorno por Modo widget/menu funcional,
rolagem vertical/horizontal utilizável e estilos coerentes nos oito temas.

Código em `cb5f16b`: uma receita global para barras de rolagem, com área de
12 px e polegar arredondado de 6 px que ganha destaque no hover/pressão; as
receitas locais de prompts e widget foram removidas. Medidores têm trilho e
preenchimento em cápsula, seletores usam chevrons vetoriais de contraste
claro/escuro e o menu da janela tem alvo de 32 × 32. As abas mostram Central,
Ajustes etc., com margens laterais iguais. A marca visual é FÔLEGO, inclusive
no compacto e na chamada da Central; os identificadores/captions usados pelo
KWin foram preservados. O botão Voltar e seu callback exclusivo saíram;
Modo widget e o menu Posição do widget mantêm a navegação.

Os **111 testes focados** finais passaram em `./dev test` (abas, dashboard,
layout, temas, transparência, hover e prompts), incluindo arraste e teclado
nas barras e os caminhos de retorno após remover Voltar. O
[ensaio KDE/Wayland e a revisão visual](handoff/validation/modern-controls-2026-11-04/README.md)
passaram em janela/HOME/XDG próprios nos oito temas, com captura atual da
Central sem Voltar. Abertura de seletores e do menu final foi nativa; seleção
no popup usa eventos Qt locais. O roteiro agora reconfere posição KWin antes
do clique e aguarda o clamp do widget. Tentativas anteriores que falharam
nessa entrada/saída ficaram preservadas e não contam como jornadas aprovadas.

Uma tentativa local de `./dev check` anterior ao último ajuste aprovou 1247
testes headless, mas perdeu o processo Qt antes do recibo final. O log parcial
e o registro de interrupção permanecem em `.scratch/dev-tests-reviewed`;
não declarar essa tentativa como gate completo. O CI do SHA publicado é a
verificação integral. Os seis jobs de produto da revisão conjunta `d39ace0`
passaram no GitHub; o revisor automático foi skipped. As execuções de
`d1fd7a6` foram canceladas pelo avanço da mesma branch e não são contadas
como aprovadas separadamente.

O primeiro CI de `cb5f16b` encontrou uma regressão real no Ubuntu: o seletor
com nome longo de grupo de processos exigia largura de 826 px. `d1fd7a6`
limita sua dica de conteúdo para permitir encolhimento sem perder a lista de
escolha. Os 46 testes de layout/abas passaram depois disso; o limite de
800 px no teste existente foi preservado. Um commit local temporário incluiu
por engano os arquivos que a outra atividade havia acabado de preparar;
antes de publicar, ele foi dividido com preservação do working tree e do
stage alheio. O commit enviado contém só as duas linhas do seletor. Nenhum
histórico remoto foi reescrito.

Preservação: outra atividade tratou CPU/temperatura/cooler em
README, COMPACTO, collector, snapshot, sysfs, compacto e testes correspondentes.
Esses hunks foram preservados fora de `cb5f16b`/`d1fd7a6`; o stage do compacto e dos
documentos foi seletivo. O owner registrou esse trabalho separadamente em
`16fd251` e `d39ace0`. Suítes locais dessa outra atividade não foram
interrompidas nem rodadas em paralelo com a verificação focada deste lote.
A GUI antiga PID 4436 foi preservada neste lote para não disputar a atualização
do host. A outra atividade concluiu a troca: a unit existente agora está
`active/running`, `Result=success`, PID 94795, iniciada às 00:02:42 de 05/11,
depois das alterações visuais. O KWin confirmou seu widget 280 × 253. A nova
instância usa o ambiente gerenciado do checkout atualizado; a prova de pixels
do cabeçalho/abas continua sendo a janela QA própria. Próximo: inspecionar a
Central residente pelo uso normal e revisar o PR #3 após #2.

## Cantos reais da Central — 04/11/2026

Pedido: a janela aberta da Central continuava quadrada, conforme captura do
usuário. Owner: checkout canônico `codex/prompt-implantation-20261104`, PR #3
empilhado sobre #2. Dependências: pintura Qt da `MainWindow`, alfa da janela
sem moldura no KWin e barra de rolagem da Central. Aceite: quatro cantos com
alfa real inferior a 32, borda central opaca ou com a transparência escolhida,
controles preservados e fluxo Central/widget funcional.

O tema preenchia todo `QMainWindow` como retângulo. `43d95bb` deu à janela
principal um seletor próprio, removeu esse preenchimento retangular e pinta o
fundo em um caminho arredondado com a cor/alfa do tema. O primeiro teste
focado ainda encontrou o canto inferior direito opaco: a barra de rolagem
chegava até ele. A janela passou a reservar 12 px à direita e embaixo para
manter essa barra dentro do contorno. A execução falha ficou preservada em
`.scratch/dev-tests-reviewed/central-rounded-first-failed-20261104` e não
conta como gate aprovado.

Depois do ajuste, `./dev test tests/test_ui_layout.py -q` passou com **9 testes**,
incluindo quatro cantos em fundos opaco e 50% transparente. `./dev check`
sequencial, Python 3.14.7 gerenciado, HOME/XDG privados: **1247 passed,
2 skipped** sem Qt e **1604 passed, 2 skipped** Qt offscreen. O
[recibo KDE/Wayland](handoff/validation/central-rounded-2026-11-04/README.md)
passou em janela própria: quatro cantos transparentes, frame/cliente 900 × 620,
volta ao widget e encaixes. Captura e JSON são sintéticos e versionados. O CI
do SHA `43d95bb` aprovou os seis jobs de produto do PR #3; revisor automático
skipped. `git diff --check` limpo.

Host: a GUI antiga PID 214646 tinha apenas o widget próprio mapeado. Depois de
confirmar bandeja `folego` no mesmo PID e item habilitado **Sair do Fôlego**,
ela saiu pelo evento DBusMenu; a unit existente ficou `inactive/dead`,
`Result=success`, sem sinal manual. `./dev setup` sincronizou o ambiente e a
unit `app-folego@autostart.service` iniciou novamente em PID **312387**,
`active/running`, `Result=success`. O KWin mostra a Central dessa instância em
`(1779,230)`, 900 × 620. Os monitores de entrada e desempenho permaneceram
nos PIDs 6654/6657. A nova instância usa o entrypoint do ambiente sincronizado
com o checkout corrigido; não houve consulta do módulo dentro do processo. A
medição de alfa foi feita na janela QA própria, não diretamente nos pixels da
residente. Nenhum outro serviço ou processo foi interrompido.

PR #3 segue draft e empilhado; b4 publicada permanece na tag anterior. Próximo:
inspeção visual pelo usuário na Central residente e revisão do PR após #2.
Outras escalas físicas e leitor de tela continuam com aceite próprio.

## Prompt de implantação entre diagnóstico e continuação — 04/11/2026

Pedido: incluir no menu **Prompts** o roteiro genérico de implantação escrito
nesta sessão, como segundo modelo, sem substituir o modelo existente de melhoria
pontual. Owner: catálogo único `core/development_prompts.py`; a GUI deriva dele
ordem, texto copiado e contagem. A ordem agora é **Diagnosticar o estado real do
projeto → Implantar o diagnóstico item a item → Continuar de onde o agente
anterior parou**; o menu tem 13 modelos. O novo texto orienta a reconferir o
diagnóstico, coordenar agentes em checkout único, concluir cada incremento com
regressão, gates, handoff, commit, push e PR, e preservar aceites físicos ou
incertos como pendências explícitas. O preâmbulo comum de autorização continua
aplicado; selecionar um título apenas copia, sem executar o pedido.

Base: `7293222`, branch b4 e PR #2 draft, ainda sem merge. Esta alteração usa
branch própria empilhada, `codex/prompt-implantation-20261104`; o PR dela deve
ter a branch b4 como base até que o PR #2 seja integrado. Testes focados
`./dev test tests/test_development_prompts.py tests/test_ui_prompt_panel.py -q`:
**7 passed**, Python 3.14.7 gerenciado, Qt offscreen, HOME/XDG privados.
`./dev test-headless tests/test_development_prompts.py -q`: **3 passed**, sem
Qt. Em sessão KDE/Wayland, painel próprio 480 × 540 mostrou 13 modelos e os
três primeiros na ordem correta; captura em
`.scratch/dev-tests-reviewed/prompt-implantation-20261104/prompt-panel.png`.
O ensaio Wayland verificou apresentação, não clique físico nem área de
transferência de outro aplicativo. A seleção/cópia integral foi exercitada no
teste Qt. Os 20 workspaces de QA ocupam o orçamento atual do wrapper; não
foram apagados para repetir as suítes completas. CI do PR é o gate completo.

O commit `92ecf9f` foi publicado na branch própria e abriu o
[PR #3](https://github.com/Misael-art/Folego/pull/3) como draft, com base na
branch do PR #2. O SHA `92ecf9f6b7c22ab8d8039ac5e11042b16c9f89f8`
passou nos seis jobs de produto do CI (dois núcleo/CLI, dois contratos CLI e
dois Qt offscreen); um revisor automático foi skipped. A GUI residente antiga
PID 6584 saiu pelo item **Sair do Fôlego** de sua própria bandeja, com
`Result=success`. `./dev setup` reconfirmou o ambiente b4 e a unit existente
`app-folego@autostart.service` foi iniciada novamente: PID 214646,
`active/running`, executando o launcher da raiz canônica. O ambiente GUI
carrega os 13 modelos na ordem aprovada. Não houve alteração de outros
serviços, sessão física, tag ou assets da prévia b4.

Próximo: conferir o painel pelo uso físico da instância residente; o ensaio
Wayland isolado já aprovou a apresentação, e os testes Qt aprovaram a cópia.
Revisar o PR #3 após o PR #2, sem promover a b4 a release estável por isso.

## Prévia v0.2.0b4 publicada — 04/11/2026

Pedido explícito desta rodada: resolver a continuidade e publicar a versão mais
atual. Owner: checkout canônico `codex/compact-header-quota-20261103`. O GitHub
não tinha essa branch; ela foi criada pelo fluxo de referência do GitHub a
partir do `main` integrado `3eabb6b`, conferida e avançada por push normal.
O guard de conteúdo aprovou todos os objetos enviados. O [PR #2](https://github.com/Misael-art/Folego/pull/2)
está aberto como draft, com base `main`; não houve merge.

O guard administrativo de tag em `.workspace/workspace.py` exigia apenas
`version.json`, ausente neste projeto. Ele agora lê `pyproject.toml` quando
`version.json` não existe; continua exigindo tag anotada, versão correspondente,
SHA aprovado no registro e commit já publicado na branch registrada. Os 19
testes descartáveis de `.workspace/test_workspace.py` passaram. O registro
central fixou `refs/tags/v0.2.0b4` em
`cc0f8133f66bc437ff839780c3d13207d70110d0` antes do push da tag.

O primeiro CI do PR falhou no Qt offscreen: no Ubuntu, as seis ações coloridas
mediam de 88 a 91 px apesar das colunas iguais. `cc0f813` deixa a grade
distribuir a largura, independente da dica de tamanho de cada botão. O teste
focado passou. Depois da correção, `./dev check` no código final passou:
**1247 passed, 2 skipped** headless e **1602 passed, 2 skipped** Qt offscreen,
com Python 3.14.7 gerenciado e HOME/XDG privados. O ensaio KDE/Wayland final,
em janela própria, aprovou topo `(0,0,948,132)`, laterais `112 × 593`, ações
recolhíveis, retorno flutuante e retorno da Central ao topo; recibo em
`.scratch/dev-tests-reviewed/release-b4-native-20261104/result.json`. As duas
execuções CI do PR no SHA final passaram com seis jobs de produto; o CI da tag
passou com três jobs. As falhas anteriores seguem registradas no GitHub e não
contam como aprovação do SHA final.

A tag anotada remota `v0.2.0b4` aponta para `cc0f813`; o campo de destino da
[release b4](https://github.com/Misael-art/Folego/releases/tag/v0.2.0b4) também
foi fixado nesse SHA. Ela é uma **prerelease**. Os pacotes de
`.scratch/release-b4-current` foram regenerados do SHA da tag: 916 blobs do
arquivo fonte conferidos contra o Git, 157 arquivos de `folego/` no wheel
idênticos aos fontes, metadados b4 em wheel/sdist e CLI do wheel aprovado em
venv isolada. Os quatro downloads públicos foram conferidos por tamanho e
SHA-256; `SHA256SUMS` público é idêntico ao local:

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `Folego-0.2.0b4-source.tar.gz` | 18.924.007 | `c547f11db1a75d806531804a702a59a20cb9072fbbee4f92feec4eb88ec56916` |
| `folego-0.2.0b4-py3-none-any.whl` | 451.029 | `12b97d5d23a84a0fcc22116a21ff174d7b7a1725f5a9ab9600632eac15f9fb4b` |
| `folego-0.2.0b4.tar.gz` | 634.228 | `cb78d63e665fc040d72e795d95016eb14c1809f828d8ba00064839c3a1173197` |
| `SHA256SUMS` | 281 | `9463998dfa242c4150aa544d414f77b9e5637eb9d2f9a21269bb3e4799d984ef` |

A GUI residente do host permaneceu ativa no PID 1674038; não foi reiniciada
por este lote de publicação. Limites: HD/widescreen e outras escalas físicas,
leitor de tela, cruzamento e áudio real de limiares da bateria e observação
longa ainda não têm aceite. O PR permanece draft; revisão e eventual merge são
passos separados. Próximo incremento: validar essas experiências no alvo real
sem perturbar trabalhos em execução. A versão b4 publicada é prévia, não
declaração de estabilidade.

## Barra fora da tela ao voltar da Central — 04/11/2026

Incidente reportado pelo usuário na instância residente: a barra superior
948 × 132 reaparecia em `(604, 368)` na área útil `(0, 0, 948, 593)`, fora do
topo e com a alça de retorno fora da tela. A regra própria `folego-widget` do
KWin ainda tinha `position=604,368`, `positionrule=3`; ao remapear a mesma
janela após visitar a Central, o compositor reaplicava essa posição inicial.
O código anterior conferia apenas se o alvo calculado tinha mudado, então não
reposicionava a barra. Owner: checkout canônico na branch
`codex/compact-header-quota-20261103`. Dependências: controlador de posição
KWin já usado pelo produto e geometria da área útil Qt. Aceite: reabrir o topo
em `(0,0,948,132)`, poder escolher laterais e flutuante pela Central, não perder
clique durante conferência de posição, e deixar o flutuante inteiro na tela.

Commits locais: `b2d189f` reconcilia o encaixe ao exibir a janela e acrescenta
o menu **Posição do widget** na Central e no widget; **Voltar** na Central abre
o flutuante. `7645b26` corrige o booleano enviado por `QAction.triggered` ao
abrir o widget pela bandeja, detectado na primeira instalação do host.
`8f7a42e` confere a posição flutuante com o KWin, limita a janela à área útil
quando sua altura muda e, após remapear uma barra, verifica mudanças tardias
do compositor antes de considerar a posição estável. As correções tardias são
limitadas e ocorrem somente após uma leitura confirmada de divergência. A
escolha de lateral feita durante a conferência é preservada.

Teste focado final `./dev test tests/test_ui_compact.py
tests/test_ui_main_window_tabs.py tests/test_ui_hover_actions.py -q` passou;
após o último ajuste de limpeza de estado, `./dev test tests/test_ui_compact.py
-q` passou. `./dev check` com Python 3.14.7 gerenciado, HOME/XDG privados e
suítes sequenciais: **1247 passed, 2 skipped** headless;
**1602 passed, 2 skipped** Qt offscreen. `git diff --check` limpo.
[Recibo e capturas KDE/Wayland](handoff/validation/dock-remap-2026-11-04/README.md)
confirmam topo 948 × 132 ao voltar da Central, laterais 112 × 593, menu da
Central para esquerda e retorno flutuante. Tentativas nativas intermediárias
encontraram corrida com a conferência de geometria e reposicionamento tardio;
foram preservadas em `.scratch/dev-tests-reviewed`, não somadas ao aceite.

Host: a GUI original PID 1163759 era a unit transitória do launcher. Ela foi
encerrada pelo item **Sair do Fôlego** da sua própria bandeja, sem sinal manual.
Uma abertura por `gtk-launch` caiu no escopo do Codex; essa instância temporária
foi encerrada pelo mesmo item, e a aplicação passou a ser iniciada pela unit
existente `app-folego@autostart.service`. A primeira tentativa nessa unit
exibiu a falha do booleano da bandeja; depois da correção, o PID 1591351 foi
encerrado pelo próprio menu. `./dev setup` sincronizou a revisão final e a
unit foi iniciada novamente: PID **1674038**, `active/running`, `Result=success`.
O item da bandeja abriu o widget flutuante; KWin confirmou `(604,331)`,
280 × 256,3, inteiro na área útil 948 × 593. A Central foi ocultada pelo menu
da própria aplicação e o widget ficou visível. Os monitores de entrada e
desempenho permaneceram ativos nos PIDs 6593/6597. Nenhum outro processo ou
serviço foi interrompido.

Limites: a instância residente final teve a abertura flutuante conferida no
KWin; os cliques de encaixe/retorno da revisão final foram exercitados na
janela de QA própria, não na instância residente. HD, widescreen e outras
escalas no compositor físico seguem sem aceite. O remoto não contém esta
branch nem PR. O push normal de `8f7a42e` foi recusado pelo guard local:
“criação, exclusão ou destino de branch fora da continuidade registrada”. Não
contornar o guard. Próximo owner: criar a branch remota pelo fluxo oficial,
conferir base/SHA, enviar por push normal, abrir/reutilizar PR e aguardar os
checks. Release depende dos gates e artefatos do SHA elegível; pacotes b4
locais são de revisão anterior.

## Monitoramento de bateria — 04/11/2026

Pedido autorizado: percentual por cor (verde, amarelo, laranja, vermelho),
toques nas passagens de 75%, 50% e 25%, aviso recorrente a cada minuto em 10%
ou menos e estimativa de tempo restante quando comprovável. Owner: checkout
canônico, branch `codex/compact-header-quota-20261103`. Dependências: leitura
somente de `/sys/class/power_supply`, coletor existente, worker de avisos e
componentes do widget/Central. Critérios de aceite: leitura inválida/antiga
não mostra percentual nem produz aviso; descarregamento cruza uma faixa de
cada vez, sem repetição acidental; barra superior conserva 132 unidades com
quatro cotas e laterais conservam rolagem/ações acessíveis.

Código nos commits locais `ca93ef3` e `e00b86a`: `BatteryInfo` no snapshot,
leitura da ABI do kernel com qualidade de fonte, estimativa nativa ou por
energia/potência (ou carga/corrente), estado puro de limiares e quatro melodias
curtas no worker de áudio existente. O percentual do widget fica verde de
51–100 (inclusive 75), amarelo de 26–50, laranja de 11–25, vermelho até 10.
O primeiro valor de descarga acima de 10 estabelece referência silenciosa;
em 10 ou menos há aviso inicial e depois a cada 60 s de observação válida.
Carregamento, leitura perdida ou pausa não emitem sons de descarga. A Central
mostra o valor em texto e a estimativa quando há dados. As opções permitem
testar os quatro toques e o interruptor de som existente também os governa.
Fonte da semântica de `capacity`, `status`, energia/carga e tempo:
[documentação da classe power_supply do Linux](https://cdn.kernel.org/doc/html/latest/power/power_supply_class.html).

Validação focada final: `./dev test tests/test_ui_main_window_tabs.py
tests/test_ui_compact.py tests/test_battery.py -q` passou. `./dev check`
final, Python 3.14.7 gerenciado, HOME/XDG privados e suítes sequenciais:
**1247 passed, 2 skipped** headless; **1594 passed, 2 skipped** Qt offscreen.
`git diff --check` limpo. A primeira tentativa do gate falhou porque o teste
antigo esperava exatamente sete melodias; a asserção foi atualizada para exigir
que todas as 11 sejam distintas, curtas e suavizadas. Essa tentativa não conta
como aprovada. [Recibo e capturas KDE/Wayland](handoff/validation/battery-2026-11-04/README.md)
confirmam laterais 112 × 593 e topo 948 × 132 com percentual/estimativa
sintéticos, quatro cotas e ações recolhíveis. A primeira tentativa nativa
detectou 17 unidades excedentes no topo; após colocar a bateria junto das
métricas, a repetição integral passou com `scroll_max=0`. A falha foi preservada.

O leitor real deste host retornou `ok`, estado `Not charging` e sem estimativa;
portanto os cruzamentos de limiares e a acústica não foram observados numa
descarga real. Não há prova nativa de HD/widescreen, outras escalas, leitor de
tela ou horas de monitoramento. Múltiplas baterias ficam em estado desconhecido
até haver uma regra de agregação comprovada. `./dev setup` sincronizou o
ambiente GUI; a GUI residente já estava `inactive/dead` e assim permaneceu.
Os monitores de entrada/desempenho permaneceram ativos nos PIDs 6593/6597;
nenhum recurso do usuário foi alterado para criar uma descarga de teste.

O remoto segue sem a branch e sem PR desta linha. O push normal de `ca93ef3`
foi recusado pelo guard local: “criação, exclusão ou destino de branch fora da
continuidade registrada”. Não contornar o guard. Próximo owner: resolver a
criação da branch remota pelo fluxo oficial, conferir base/SHA, enviar os commits
por push normal, abrir/reutilizar PR e aguardar gates remotos. Release depende
de versão, artefatos e notas do SHA elegível e autorização vigente; os pacotes
b4 locais são de SHA anterior e não representam esta revisão. A GUI residente
pode ser aberta pelo usuário para verificar o monitoramento real; não foi
reiniciada durante a QA para preservar o estado encontrado.

## Barra superior fina e ações recolhíveis — 04/11/2026

Pedido aprovado após mockup: folga primeiro à esquerda, depois cotas de IA/CLI,
métricas sem intercalar cotas, teclado/menu na ponta direita com Pausar abaixo;
seis atalhos coloridos recolhíveis também nas barras esquerda, direita e
superior. Owner: checkout canônico, branch
`codex/compact-header-quota-20261103`. Dependências: os mesmos componentes Qt,
observações de cota e geometria KWin existentes; nenhum novo grant ou efeito
de recurso. Aceite: topo mais baixo sem corte de quatro cotas com badges,
atalhos revelados/recolhidos por hover nos três encaixes e retorno funcional.

Em largura útil a partir de 900, a barra superior tem 132 unidades lógicas de
altura (antes 190 em 948). O cabeçalho, indicador principal, cotas, leituras e
três controles à direita são reorganizados numa faixa compacta; as margens
internas do medidor e das métricas são reduzidas só nesse modo. A alça de
retorno fica no centro da borda superior, estável durante a animação dos
atalhos. Os seis botões começam recolhidos em qualquer encaixe, abrem em 140 ms
ao entrar com o ponteiro e se recolhem após sair; nas laterais, o conteúdo
continua rolando separadamente dos botões. Larguras abaixo de 900 mantêm o
arranjo superior em duas linhas e 190 unidades de altura.

Validação da fonte: `./dev test tests/test_ui_compact.py
tests/test_ui_hover_actions.py -q` **35 passed**. `./dev check` final com Python
3.14.7, HOME/XDG privados e perfis sequenciais: **1242 passed, 2 skipped**
headless; **1586 passed, 2 skipped** Qt offscreen. `git diff --check` limpo.
Testes Qt simulam áreas úteis de 948 × 593, 1920 × 1080 e 2560 × 1080.
[Recibo e capturas KDE/Wayland](handoff/validation/top-hover-2026-11-04/README.md)
confirmam 948 × 132 no topo, quatro cotas com badges sem rolagem mesmo com
atalhos abertos, hover físico de entrada/saída nas três barras e retorno ao
compacto. As tentativas nativas anteriores pararam por sobreposição do Plasma
ao alvo do ponteiro e pela alça superior que mudava de posição; foram
preservadas e não contam como aceites. Uma suíte focada falhou por observações
reais sobrepondo dados sintéticos após reexibição da faixa; o teste passou a
isolar o coletor sintético e o gate final passou. O primeiro teste da altura
de 130 detectou corte; a versão de 132 com margens próprias eliminou a rolagem
superior de quatro cotas.

Limites: a sessão física só cobre 948 × 593, sem QA de gesto real de scroll
lateral, outras escalas/monitores, áudio, leitor de tela ou soak. HD/widescreen
seguem simulados no Qt offscreen. Código, testes, documentação e capturas:
commit local `a2b2d53`. `./dev setup` sincronizou o ambiente GUI; o entrypoint
importa `src/folego/ui/compact.py` deste checkout e calcula topo 948 × 132.
A GUI residente já estava encerrada às 08:33, antes da instalação; não foi
reiniciada para preservar esse estado. `app-folego@autostart.service` continuou
`inactive/dead`, `Result=success`, sem outra GUI própria mapeada. Os monitores
de entrada/desempenho permaneceram ativos nos PIDs 6593/6597; Modo Desempenho
seguia `paused=false`, sem disjuntor ou falhas, com 21 eventos. A nova GUI foi
exercitada somente na janela de QA isolada; não há prova visual da instância
residente desta revisão.

O remoto continua sem a branch `codex/compact-header-quota-20261103` e sem PR.
O push normal de `a2b2d53` foi recusado pelo guard local por criar branch fora
da continuidade registrada. Nenhum push, PR, tag, release ou merge ocorreu;
não contornar o guard. Próximo passo: owner criar a branch remota pelo fluxo
oficial, conferir base/SHA, push normal, PR/CI; só então avaliar nova versão,
artefatos/notas e elegibilidade de release. Os pacotes locais b4 anteriores
não representam esta revisão. Depois validar a barra superior na GUI
residente e em outras resoluções/fatores de escala físicos.

## Alinhamento, cantos e cotas nas barras — 04/11/2026

Owner: checkout canônico, branch `codex/compact-header-quota-20261103`.
Dependências: componentes Qt existentes, cotas confirmadas e geometria da
área útil informada pelo compositor. Aceite do incremento: grip de retorno na
borda externa de cada lateral, cantos realmente recortados, métricas alinhadas
na direção da barra, quatro cotas alcançáveis sem serem cobertas pelas ações e
recomposição do topo para Steam Deck, HD e widescreen.

O grip esquerdo agora fica em `x=0`, o direito em `largura-16`, e ambos terminam
antes das seis ações fixas. As leituras de RAM, CPU, temperatura, swap, tmpfs e
espaço livre se alinham à esquerda ou à direita conforme o lado; o scroll fica
na borda interna. A superfície é pintada dentro de um caminho arredondado e a
janela recebe máscara com o mesmo raio. O topo usa duas linhas na área útil
de 948 × 593 e uma linha de informação em larguras a partir de 1200; a área
de leitura pode rolar, com ações fixas abaixo. Altura do topo curto: 190.

Validação: `./dev test tests/test_ui_compact.py tests/test_ui_ai_quota_rings.py
tests/test_ui_hover_actions.py tests/test_ui_desktop_shortcuts.py -q`:
**47 passed**. `./dev check`, Python 3.14.7, HOME/XDG privados, perfis
sequenciais: **1242 passed, 2 skipped** headless e **1583 passed, 2 skipped**
Qt offscreen; `git diff --check` limpo. Os testes Qt cobrem as áreas úteis
948 × 593, 1920 × 1080 e 2560 × 1080 com quatro cotas. [Recibo e capturas
KDE/Wayland](handoff/validation/dock-adaptive-2026-11-04/README.md) confirmam
na área real 948 × 593 ambas as laterais 112 × 593, topo 948 × 190, grip na
borda externa, alfa transparente nos quatro cantos, última cota após rolagem,
ações sem sobreposição e retorno/saída pelo próprio controle. Uma tentativa
anterior de `./dev check` falhou porque o teste de tema procurava a cor na
folha de estilos após a pintura ter passado para o widget; o teste corrigido
confere o pixel renderizado. Essa tentativa não é gate aprovado.

Limites: HD e widescreen foram simulados no Qt offscreen, sem compositor real
nessas resoluções. A rolagem foi posicionada por código, sem gesto físico;
não há novo aceite de leitor de tela, áudio, outros fatores de escala ou uso
prolongado. Código, documentação e evidência: commit local `4e7be98`.

Instalação no host: `./dev setup` reutilizou o ambiente GUI e o entrypoint
continua apontando para `src/folego/ui/compact.py` deste checkout. Antes da
troca, a única janela própria mapeada era o widget à direita, sob
`app-folego@autostart.service`, PID 84943, UID 1000 e starttime 149690.
`performance auto-off --json` pausou temporariamente o fechamento automático.
Após revalidar unit, PID e comando, o item **Sair do Fôlego** da bandeja desse
processo foi acionado; a unit ficou `inactive/dead`, `Result=success` e o PID
saiu. A unit própria foi iniciada novamente como PID 270899, `active/running`.
Pelo menu da bandeja do novo PID, o widget foi exibido e seu controle esquerdo
foi acionado após validar janela, owner e alvo do ponteiro. O KWin confirmou a
barra direita em `(836, 0, 112, 593)` (valores lógicos arredondados), como
antes da troca. Os monitores de entrada/desempenho permaneceram ativos com os
mesmos PIDs 6593/6597. `performance auto-on --json` restaurou `paused=false`,
disjuntor vazio, zero falhas e histórico de 17 eventos. Nenhum outro app,
serviço ou sessão foi parado. A revisão carregada pelo processo é inferida do
entrypoint e do reinício posterior ao setup; não foi consultada dentro dele.

Próximo passo: publicação da branch, PR e release dependem do guard remoto
descrito abaixo, sem autorização de merge. O comportamento visual em outros
monitores e fatores de escala ainda precisa de verificação nativa.
Após o commit de passagem `28385cb`, `git ls-remote --heads` continuou sem
essa branch, `gh pr list --head` retornou vazio e o push normal foi recusado
pelo guard local por criar branch fora da continuidade registrada. Nenhum
push, PR, tag ou release b4 foi criado; não contornar o guard.
Prévia local em `.scratch/release-b4-responsive`: wheel e sdist b4 gerados
offline; os 156 arquivos `folego/` do wheel coincidem byte a byte com as fontes.
O wheel foi instalado sem dependências numa venv descartável própria e
`python -I -m folego --help` passou. O arquivo fonte sai de `git archive` do
commit final; `SHA256SUMS` dos três pacotes foi conferido. Artefatos permanecem
locais e precisam corresponder ao SHA elegível quando a publicação for possível.

## Refinamento das barras adaptativas — 04/11/2026

Pedido mais recente: a barra encaixada continuava larga e apenas transportava
o layout compacto. Owner: o checkout canônico, branch
`codex/compact-header-quota-20261103`. Dependências: layout Qt existente,
observações de cota já confirmadas e posicionamento do próprio widget via
KWin; sem novo grant ou efeito sobre recursos. Aceite nesta saída: laterais
estreitas com indicador principal centralizado, estado/métricas/espaço livre
em coluna, pausa abaixo da coleta, cotas positivas ordenadas e menores que o
indicador principal, seis ações individuais na base, cantos arredondados;
topo organizado na largura útil, retorno funcional e dados sem recorte.

As laterais passaram de 180–220 para 112–128 unidades lógicas conforme a tela.
O cabeçalho e as métricas se rearranjam para a largura disponível; o indicador
de saúde mantém 68 unidades e os anéis de cota passam a 42 nas laterais. Ações
ficam em coluna visível no rodapé, ou numa linha no topo. Espaçamentos,
tipografia e aviso de espaço livre foram ajustados para caberem junto das
duas cotas de demonstração na saída menor. A barra de rolagem só aparece se
o conteúdo exceder a altura. Badges sem entregas ou resgates confirmados não
reservam altura. O efeito de chegada da cota é removido após a animação, o que
também permite que a composição aninhada apareça na captura do widget.

Validação: teste focado **38 passed**; `./dev check` final, com Python 3.14.7
gerenciado e HOME/XDG privados, **1242 passed, 2 skipped** headless e **1574
passed, 2 skipped** Qt offscreen. [Recibo e capturas KDE/Wayland](handoff/validation/dock-adaptive-2026-11-04/README.md)
confirmam direita/esquerda 112 × 593, topo 948 × 142, duas cotas inteiras,
seis ações acessíveis e retorno à posição anterior. Uma tentativa do gate
combinado foi interrompida após a suíte headless; ela não foi contada como
aprovada. O primeiro ensaio nativo desta revisão falhou no alvo do ponteiro;
a repetição integral passou. Outras escalas/saídas, leitor de tela, som real e
soak permanecem sem aceite. O remoto ainda não contém esta branch nem PR;
publicação continua sujeita ao guard local descrito abaixo.

Commit de código e evidência: `34ed8d4` (local). A GUI do host estava na unit
`app-folego@autostart.service`, PID 6531, com apenas o widget próprio mapeado;
o Modo Desempenho tinha `paused=false`, disjuntor vazio e 17 eventos no histórico.
`performance auto-off` confirmou a pausa temporária. Após conferir unit, PID,
UID, comando e starttime 8362, o item **Sair do Fôlego** da bandeja pertencente
à mesma GUI foi acionado. O PID saiu e a unit ficou `inactive/dead`, com
`Result=success`; nenhum sinal manual foi enviado. `./dev setup` reutilizou o
ambiente GUI sem alterar dependências. A unit própria foi reiniciada: PID
84943, `active/running`, nova bandeja do mesmo PID e widget compacto visível.
O código instalado no ambiente gerenciado aponta para a fonte desta branch;
como não houve consulta de revisão dentro do processo, a revisão carregada é
inferida do início posterior ao setup e do entrypoint, não medida diretamente.
Os monitores de entrada e desempenho permaneceram ativos nos mesmos PIDs
6593/6597. `performance auto-on` restaurou `paused=false`, disjuntor vazio e
17 eventos. O encaixe da borda não persiste entre reinícios, logo o widget
residente reabriu no modo compacto; a nova barra encaixada foi exercitada na
janela própria da validação, sem mover o ponteiro da sessão de trabalho para
reencaixar a instância residente. Nenhum outro serviço, app ou sessão foi parado.

## Prévia b4 instalada no host — 04/11/2026

Pedido explícito: atualizar a aplicação neste host. O checkout estava limpo em
`221e7ca819f653fa8cd52ee16beb285b334e91e6`; a instalação local já tinha
metadados `0.2.0b4` nos ambientes GUI/headless, mas os processos residentes
tinham sido iniciados antes da atualização. Antes da troca, início com a sessão
estava ativo, `folego-performance.service` tinha `paused=false`, sem disjuntor,
e histórico com 16 resultados; a revisão `accessibility.activate` para toque
(`58176bdf86c94e759e43f661630c5ce8`) seguia pendente. GUI e monitores
próprios tinham PIDs 5889, 5936 e 5944. Carga e espaço foram conferidos; não
houve instalação global nem alteração de grant.

`performance auto-off --json` confirmou a pausa temporária. O item habilitado
**Sair do Fôlego** da bandeja DBusMenu foi acionado depois de confirmar que o
owner da bandeja, PID 5889 e starttime 6295 pertenciam à GUI própria. A unit
da janela ficou `inactive/dead`, `Result=success`, e o PID desapareceu sem
sinal manual. Apenas `folego-performance.service` e
`folego-accessibility.service` foram parados; ambos ficaram inativos e seus
PIDs antigos saíram. A revisão pendente manteve o mesmo ID.

`./dev setup` sincronizou o ambiente GUI b4 usando o lockfile existente. As
duas units próprias e depois a unit gerada `app-folego@autostart.service`
foram iniciadas, sem habilitar nova automação. Na verificação inicial após a troca,
as três estavam `active/running`, `Result=success`, com PIDs novos 747308
(entrada), 747571 (desempenho) e 747850 (GUI). Os entrypoints apontam para o
ambiente gerenciado b4; isto sustenta a inferência de que os processos novos
carregaram b4, sem uma consulta de versão dentro de cada processo. A bandeja
registrada pertencia ao PID 747850 e mostrava telemetria atual. Pelo item
próprio **Mostrar controle compacto**, abriu-se uma superfície KWin
`Fôlego — widget` de 280 px, sem tocar em outras janelas. `performance auto-on`
restaurou `paused=false`; disjuntor vazio e histórico ainda com 16 resultados.
`startup status` permaneceu ativo, unit de entrada active/enabled e
`effects_authorized=false`. O monitor de entrada ficou em observação, com
baseline 5 e política de efeito desligada; a revisão durável de toque continua
pendente. Nenhum outro app, agente ou serviço foi encerrado e a sessão gráfica
não foi reiniciada.

Observação posterior, que substitui o estado da GUI no parágrafo anterior:
`app-folego@autostart.service` encerrou às 05:10:14 com código 0 e sem erro no
jornal; a causa do encerramento não foi observada. Às 05:10:22, o lançador
`~/.local/share/applications/folego.desktop` iniciou outra instância própria,
PID 761910, sob a unit transitória
`app-folego@6e32f6b0ccac441d959b5ba76aabf7bc.service`, que ficou
`active/running`. Bandeja e superfície `Fôlego — widget` pertencem a esse PID.
Uma única tentativa de iniciar a unit de autostart depois disso saiu com código
0 e informou que a instância 761910 já controlava o aplicativo; nenhuma janela
duplicada foi criada. Os monitores continuam ativos com PIDs 747308/747571.
Não atribuir a primeira saída a crash ou ação do usuário sem evidência.

Validação: estados do systemd, owner da bandeja, título/geometria nativos da
janela, metadados b4 nos dois ambientes, preferência de inicialização,
automação restaurada e ID da revisão foram conferidos no host. O `./dev check`
de b4 aprovado no lote anterior cobre 1242 testes headless e 1574 Qt, com 2
skips em cada perfil; não foi repetido para esta troca sem alteração de código.
Não há novo aceite de clique físico, múltiplas saídas/escalas, áudio real,
leitor de tela ou soak. A branch remota continua ausente; PR e release b4
continuam pendentes conforme a seção seguinte.

## Widget encaixável e prévia b4 local — 03/11/2026

Pedido explícito: bordas escuras com seta ao passar o mouse, barra vertical
direita/esquerda, barra horizontal superior, reorganização dos controles,
transição suave, testes, commit, PR e release. Owner da implementação: este
checkout único, branch `codex/compact-header-quota-20261103`, commit
`18da024` sobre `93906da`. A versão em `pyproject.toml` e `uv.lock` é
`0.2.0b4`. O commit inclui código, testes, documentação, capturas sintéticas e
notas da prévia. A GUI residente instalada no host não foi reiniciada.

O widget usa as mesmas seções nas quatro formas. As bordas esquerda/direita e
superior mostram faixa de dois tons e seta no hover. As laterais ocupam a altura
útil, ordenam as cotas em coluna, põem o rodapé na base e permitem rolagem; o
topo ocupa a largura útil em uma ou duas linhas. O cálculo usa
`availableGeometry()` para respeitar painéis informados pelo desktop. Em X11,
a geometria anima por 260 ms. No KDE/Wayland, o worker consulta a posição real
da própria janela pelo KWin, solicita a geometria final uma vez, confirma a
posição e faz o conteúdo reaparecer suavemente. Falha ou unicidade desconhecida
bloqueia o encaixe; resultado incerto não dispara repetição automática.
Retornar restaura a posição original confirmada. O modo não persiste ao reiniciar.

Validação final da fonte b4: `./dev test tests/test_ui_compact.py
tests/test_desktop_tools.py -q` **30 passed**; `./dev check` com Python 3.14.7,
HOME/XDG privados e perfis separados: **1242 passed, 2 skipped** headless e
**1574 passed, 2 skipped** Qt offscreen, diff check aprovado. QA na sessão
KDE/Wayland real, janela/dados/áudio próprios: direita `(728, 0, 220, 593)`,
esquerda `(0, 0, 220, 593)`, topo `(0, 0, 948, 118)`, retorno exato a
`(20, 120, 280, 185)`, temas claro e escuro, saída explícita. [Recibo e
capturas](handoff/validation/dock-widget-2026-11-03/README.md). A primeira
tentativa nativa de retorno revelou que o Qt informava `(0, 0)` no Wayland;
a consulta ao KWin corrigiu o erro, e uma rodada posterior passou. Duas
tentativas anteriores de `./dev check` falharam em testes sem interface fora do
incremento (prazo variável do backup e resultado intermitente da supervisão de
entrada); seus workspaces `run-aep92j_i` e `run-f5v8r38f` foram preservados e
não contam como gates verdes. O teste de entrada passou isolado, as duas suítes
passaram completas separadamente e o `./dev check` final passou sem mudar
limites. Workspaces concluídos e revisados foram movidos integralmente para
`.scratch/dev-tests-reviewed` para respeitar o teto; nenhum payload foi apagado.

Prévia local: `.dev/bin/uv lock --offline` avançou só a versão do pacote;
`.dev/bin/uv build --offline --out-dir .scratch/release-b4` gerou wheel e sdist.
Os **156** arquivos de `folego/` no wheel correspondem byte a byte aos fontes.
O wheel foi instalado sem dependências numa venv descartável própria, e
`python -I -m folego --help` e metadados `0.2.0b4` passaram. Os artefatos
ficam em `.scratch/release-b4`, fora do Git. O arquivo fonte completo de um
commit exato foi gerado por `git archive`, com 989 entradas e sem `.dev` ou
`.scratch`; `SHA256SUMS` passou para os três pacotes. O arquivo fonte e os
hashes precisam ser regenerados do SHA desta passagem antes da publicação.
A tag e a conferência remota dependem da branch publicada; nenhuma tag foi
criada agora.

Publicação pendente: em 03/11 a branch remota ainda não existia. O guard
`/home/misael/Projects/.workspace/workspace.py prepush` recusa criar branch
remota por push. `git push -u origin codex/compact-header-quota-20261103`
foi recusado novamente após os commits locais, sem publicar dados. O owner
precisa criar no GitHub a branch
`codex/compact-header-quota-20261103` a partir do `main` integrado; então
confirmar base/SHA, fazer push normal, abrir PR, conferir CI, criar tag da
revisão elegível e publicar a prerelease b4 com os artefatos e notas preparados.
Não contornar o guard nem presumir PR/CI/release publicados. A release foi
autorizada pelo usuário neste lote, mas ainda não aconteceu. Sem merge
autorizado. Aceites físicos, outras escalas/saídas e soak continuam abertos;
o Qt offscreen e a sessão de QA não os substituem.

## Cabeçalho compacto e cotas disponíveis — 03/11/2026

O PR #1 foi integrado antes deste lote: `main` local/remoto estava limpo em
`3eabb6bb8d783a458fa1694bb911c71ab95dbd9f`. O novo incremento está na
mesma raiz canônica, branch `codex/compact-header-quota-20261103`, commit de
código `c3274fec9950d450a93abfd954637b515ea94426`. A GUI b3 residente no
host não foi reiniciada nem substituída; a mudança foi exercitada numa janela
própria com dados sintéticos, sem interromper supervisores ou agentes.
O commit de passagem é `2508ecc4cc638d025aa451c55c21ac675d7b3af5`.
O working tree estava limpo após os dois commits.

O cabeçalho do widget de 280 px tem marca em Noto Sans, teclado e seta unidos,
e ícone da Central com seta para ocultar, sair e consultar todas as contas.
A faixa mostra somente cotas positivas confirmadas, da maior porcentagem
disponível para a menor; empate tem ordem estável. A conta padrão é usada quando
elegível, senão aparece uma conta verificada do provedor, com clique e painel
coerentes. Zero e desconhecido ficam fora da faixa, mas continuam distintos no
menu. Expiração retira o indicador imediatamente; uma nova cota entra com
animação curta quando o estilo Qt permite. Reabrir o widget não repete a
descoberta. O som existente de reposição só toca numa transição confirmada pelo
monitor; primeira leitura, falha e data de reset vencida não o disparam.

Validação final do código: `./dev check` com Python 3.14.7 gerenciado, perfis
separados e HOME/XDG privados: **1241 passed, 2 skipped** headless e **1570
passed, 2 skipped** Qt offscreen. Teste focado de ordenação, conta alternativa,
retorno e animação: **7 passed** após a última revisão do teste. QA em
KDE/Wayland real, janela e HOME/XDG/áudio próprios: oito casos aprovados,
incluindo Central/Voltar, três combinações de tema/transparência, ocultação e
retorno de cota, hover e clique nativos no indicador, e saída pelo menu.
[Captura e recibo](handoff/validation/compact-header-quota-2026-11-03/README.md).
O cliente de IA foi interceptado em memória; nenhum som real nem conta pessoal
foi usado como fixture.

A primeira tentativa visual falhou no clique do menu após o widget crescer sob
o ponteiro; registro em `.scratch/dev-tests/run-header-quota-20261103`. A
segunda passou após estabilizar o drawer antes desse clique. A execução final
após a última revisão do código também passou, com captura/recibo publicados no
link acima. Uma execução de
`./dev check` foi interrompida antes de registrar o resultado Qt quando houve
uma nova mensagem do usuário; seu workspace `run-2iu_gd3o` permanece preservado
e não conta como gate. O headless dessa tentativa tinha recibo verde; a suíte
Qt foi repetida e aprovada. Workspaces concluídos com recibo e runner ausente
foram movidos integralmente a `.scratch/dev-tests-reviewed` para respeitar o
teto de 20, sem apagar payloads nem alterar limites.

Limites: a captura e o Qt offscreen não certificam leitor de tela, clique físico
em todos os monitores/escalas, áudio real nem uso prolongado. Os aceites de
entrada, retenção de temporários e Modo Desempenho abaixo seguem abertos.
Publicação pendente: `git push -u origin codex/compact-header-quota-20261103`
foi recusado pelo guard `.workspace/workspace.py prepush`, que bloqueia criar
branches remotas por push mesmo após registrar a branch de continuidade. A
branch remota ainda não existe; nenhum PR ou CI deste incremento foi criado ou
observado. Os commits e a evidência estão preservados localmente. O owner deve
criar a branch remota de mesmo nome a partir do `main` integrado, pelo fluxo
oficial do GitHub; depois confirmar SHA/base, enviar os commits sem forçar,
abrir o PR e observar os checks.
Após integração, reiniciar o
Fôlego pelo fluxo do próprio aplicativo para testar a nova faixa com contas
reais, sem usar credenciais como fixtures nem presumir que uma data de reset
confirma cota. Não gerar release por este ajuste visual isolado.

## Instalação no host e aceites ainda pendentes — 03/11/2026

Antes da instalação, a GUI e as units próprias estavam ativas no ambiente
`0.2.0b2`; início com a sessão habilitado e Modo Desempenho automático sem
pausa/disjuntor. A revisão pendente `accessibility.activate` foi preservada.
Para evitar fechamento durante a troca, `performance auto-off --json` pausou o
supervisor e o histórico continuou em nove registros após um ciclo. A GUI antiga
foi encerrada pelo item **Sair do Fôlego** da sua própria bandeja DBusMenu,
após conferir PID 8370, starttime 18115, owner e item habilitado. Sua saída foi
acompanhada; nenhum sinal manual foi enviado. Somente
`folego-performance.service` e `folego-accessibility.service` foram paradas.

`./dev setup` sincronizou a GUI de b2 para **b3**; a consulta
`./dev run startup status --json` sincronizou a CLI headless para b3. As duas units próprias foram
reativadas, seguidas da unit gerada `app-folego@autostart.service`; os três
serviços ficaram `active/running`, sem reinício automático e com novos PIDs
811491, 809642 e 814766, respectivamente. A GUI nova registrou uma bandeja
própria no Wayland e 11 superfícies consultáveis; `importlib.metadata` em ambos
os ambientes confirma `0.2.0b3`. Não há diferença em `src`, `pyproject.toml`
ou `uv.lock` entre a tag b3 e a branch instalada. `performance auto-on --json`
restaurou `paused=false`; disjuntor vazio, histórico com nove registros.
`startup status` confirma preferência/autostart ativos e unit de entrada
`active/enabled`, sem novo grant de efeito. Nenhum outro app, agente ou serviço
foi encerrado; a sessão gráfica não foi reiniciada.

O host está pronto para testar a prévia instalada. A instalação e a inspeção
da bandeja/superfícies não substituem os aceites seguintes:

| Pendente | Estado observado e prova necessária |
| --- | --- |
| Retenção real de temporários | O inventário **atual** do host mostrou 3 runs `complete` e 0 retidos; os 192 runs e cinco leituras `/proc/environ` negadas pertencem à inspeção anterior. Revalidar identidade, término, consumidores e referências de cada candidato no ato. Sem essa prova, preservar origem e payload. |
| Entrada física e acessibilidade | Supervisor atual em `waiting`, backend KWin, baseline 5, dois bloqueios, zero erro e zero operação ativa na consulta; uma revisão durável `accessibility.activate` segue pendente. Toque FTS3528 não estava disponível; reconciliar o ID, sem repetição cega, e testar toque/leitor de tela com hardware e sessão própria. |
| Desktop e interação | Central/Desempenho/Opções foram vistas anteriormente em janelas próprias Wayland; a GUI b3 registra bandeja e superfícies agora. Faltam arraste e cliques físicos sobre o fluxo atual, login/SDDM, logout, suspend/resume, dock, Steam e Orca em janela de QA que não interrompa trabalho. |
| Modo Desempenho | Regras automáticas e unit ficaram como antes da instalação. Os 225 s de observação anterior não provam horas reais; fazer soak contínuo da fonte b3 com orçamento, duração e alvos descartáveis próprios, incluindo foco, áudio, downloads, arquivos de projeto, agentes, carência e disjuntor. |
| Gate local | O gate histórico da b3 teve uma falha de deadline preservada; o novo incremento passou `./dev check` com 1241/1570 testes aprovados (2 skips por perfil) após revisão manual e preservação integral dos workspaces concluídos. O CI deste novo SHA ainda precisa ser observado após push. |

Próximo: executar esses aceites no alvo apropriado, preservando o diário e as
políticas atuais. A prévia publicada não é aceite físico ou produto estável.

## Prévia v0.2.0b3 publicada — 03/11/2026

Pedido explícito de release: `pyproject.toml` e `uv.lock` avançaram juntos para
`0.2.0b3`; commit/tag `172bbc1f5837fbcd3c7e00ec614738e52dda7397`.
[Release v0.2.0b3](https://github.com/Misael-art/Folego/releases/tag/v0.2.0b3)
publicada em 03/11/2026 19:37:39 UTC como **prerelease**, com o PR #1 ainda
draft e sem merge **naquele momento**; o PR foi integrado posteriormente em
`main` no SHA `3eabb6b`. A versão b2 e sua tag permanecem imutáveis. O CI do commit
teve seis jobs de produto aprovados. Na referência da tag, nove checks success
(incluindo os do PR e os três novos do tag), dois revisores skipped e nenhum
check ativo ou falho na consulta final.

`uv lock --offline` alterou apenas a versão do pacote; `uv build --offline`
gerou sdist e wheel com Python gerenciado. Os 156 arquivos `folego/` do wheel
correspondem byte a byte aos fontes. Wheel instalado em venv descartável sem
Qt: versão `0.2.0b3` e `python -I -m folego --help` aprovados. A fonte completa
foi criada por `git archive` do commit exato, inclui `dev` e `uv.lock` e não
inclui `.dev`, `.scratch` nem dados de sessão. Os quatro assets públicos foram
baixados sem autenticação e conferidos por tamanho e SHA-256:

| Asset | Bytes | SHA-256 |
| --- | ---: | --- |
| `Folego-0.2.0b3-source.tar.gz` | 17.949.442 | `cbf0944fa3bedfb5716ba1e4382f960bd246987b5985d3581db06819c100c73c` |
| `folego-0.2.0b3-py3-none-any.whl` | 438.941 | `0b2d62d2d403ae71129d27ef33c936d553c7a32162aaa1cfd1c2f5fb81386669` |
| `folego-0.2.0b3.tar.gz` | 619.726 | `212c21f593714f31ebb4b7986f92a052f9488e077c1e33c2efdfb7bbd06b9240` |
| `SHA256SUMS` | 281 | `f43451ecfbac2742e65e4e0c3036beb293cf65124683d452cd9b9766e9691dc8` |

O gate local headless falho por prazo e seus dados em
`.scratch/dev-tests/run-b4jvfeyr` continuam preservados; não houve novo gate
local completo após a versão porque os 20 workspaces de QA já estão ocupados.
Os aceites físicos e de retenção abaixo seguem pendentes nesta prévia. Nenhum
app real, grant, unit de trabalho ou sessão física foi alterado para publicar.
Próximo: concluir a matriz em sessão própria e o soak desta fonte; não promover
esta prévia a estável por inferência.

Ferramenta Rust solicitada depois do release: `rustup 1.29.3`, `rustc 1.99.1`
e `cargo 1.99.1` instalados exclusivamente em `.dev/rustup` e `.dev/cargo`,
perfil mínimo e `--no-modify-path`. O `rustup-init` oficial de 21.347.088 bytes
foi conferido pelo SHA-256 publicado
`b1c8cb14e30889e7e2999e6b69e62d9e9b9ffc0f4df8180564d306d9680e6c55`.
`rustup show active-toolchain` apontou para `1.99.1-x86_64-unknown-linux-gnu`;
um programa mínimo compilou e executou (`rust-ok`). `.dev` ficou em 3,6 GiB,
abaixo do limite de revisão de 10 GiB. Nenhum perfil de shell foi alterado.
O Fôlego permanece um projeto Python/Qt e não ganhou dependência Rust.

## Estado vigente e matriz de aceite — 03/11/2026

Na branch `codex/portable-handoff-20261024`, os incrementos publicados
`98bd49c`, `e199e24`, `a7edb43`, `c363363`, `9981fd9`, `e5dfb5c`,
`9fcbbd2` e `426ae39` cobrem, respectivamente, diário incompleto, oráculo Qt,
swap parcial, corrida de início, recibo reconciliado, proteção de uso incerto
no Desempenho, inventário/recuperação de temporários e revisão pelo mesmo ID
em “Dar fôlego”. O SHA `426ae39` passou nos seis jobs de produto do CI (dois
headless, dois Qt e dois de contratos CLI; revisores automáticos skipped).
Último gate local de código: `./dev test-headless` **1241 passed, 2 skipped** e
`./dev test` **1569 passed, 2 skipped**, Python 3.14.7 gerenciado, HOME/XDG
privados e Qt offscreen. As seções abaixo guardam reproduções, comandos,
contagens, evidências e limites de cada incremento.

Neste lote de passagem e texto da aba Opções, `./dev test-headless` terminou
**1240 passed, 2 skipped, 1 failed**: `test_backup.py::test_roundtrip_property`
excedeu o deadline existente de 200 ms na primeira tentativa (329 ms) e levou
9 ms ao repetir internamente; uma repetição focada no mesmo workspace próprio
teve o mesmo tipo de falha (334 ms e depois 115 ms). O código de backup não foi
alterado e nenhum limite foi elevado. A execução e o log falhos foram
preservados em `.scratch/dev-tests/run-b4jvfeyr`; o limite de 20 workspaces
impediu abrir outro pelo wrapper sem remover evidências alheias ou incertas.
Com o ambiente privado do wrapper e base exclusiva dentro desse workspace,
`test_ui_options.py` deu **9 passed** no Qt offscreen. `git diff --check` passou.
Uma janela própria de Opções foi mostrada no plugin Wayland da sessão KDE real,
com HOME/XDG privados; o novo texto ficou visível e a captura
`run-b4jvfeyr/options-wayland.png` foi inspecionada. A captura do widget não
certifica entrada física nem o login.
O CI do incremento `b9aac10` passou nos seis jobs de produto.

| Aceite | Evidência nesta fonte | Dependência ainda aberta |
| --- | --- | --- |
| Diário, swap, início e revisão | Regressões pelos fluxos oficiais CLI/GUI; CI verde em `426ae39` | Nenhuma para o contrato simulado; comportamento físico segue linhas abaixo. |
| Desempenho | Unit e regras atuais consultadas; cinco fechamentos históricos no diário; 225 s de observação somente leitura, 16 amostras; aba inspecionada em janela própria no KDE/Wayland; desligar/ligar testado em estado privado | Soak de horas com orçamento definido na fonte atual e efeito seguro apenas em alvos descartáveis próprios. Não fechar apps reais para prova. |
| Temporários | Inventário, localização de recuperação e bloqueios testados em árvores próprias; 192 runs vivos observados, nenhum movido | Cinco processos do mesmo UID negam `/proc/environ`; sem prova de ausência de consumidores, retenção real fica bloqueada. Não mudar permissões ou ignorar a incerteza. |
| “Dar fôlego” | CTA e aba vistos no Wayland; plano, confirmação, efeito em filho próprio, consulta e repetição pelo mesmo ID validados pela CLI; clique duplo e arraste cobertos por Qt | Entrada física de arraste/clique no compositor não foi ensaiada. |
| Entrada e acessibilidade | Sessão Wayland real; supervisor de entrada ativo; consulta mostrou cinco entradas no baseline, dois bloqueios e uma operação pendente sem efeito novo | Toque FTS3528 ausente; concluir operação pendente e testar hardware em QA própria. Leitor de tela Orca está instalado, mas não foi operado. |
| Desktop e sessão | Janelas próprias da central abertas e inspecionadas no KDE/Wayland; startup da central/unit consultado como ativo e habilitado | Login/SDDM, logout, suspend/resume, dock, Steam e leitor de tela exigem janela de QA física sem interromper a sessão de trabalho. |
| Soak de duas horas | 7200,057 s aprovados em 30/10 para fonte congelada `a65b5f7`; relatório histórico abaixo | Repetir na fonte atual, em janela real de duas horas e com orçamento/telemetria próprios. Não somar tentativas nem tratar 225 s como soak. |

Próximo passo executável em ambiente apropriado: resolver a leitura dos
consumidores pelo owner sem ampliar permissões às cegas; depois testar retenção
de runs próprios elegíveis. Agendar QA física de entrada/login e soak da fonte
atual. A prévia b3 foi publicada com estes aceites ainda abertos; a instalação
local no host está documentada acima.

## Dar fôlego: análise, revisão e resultado pelo mesmo ID — 03/11/2026

Reprodução do caminho anterior: a recomendação prioritária de memória voltava
à própria central; o fechamento Assistido no Desempenho confirmava texto antes
de criar o `ActionPlan`, então o usuário não revisava o ID que seria executado.
A ação principal agora abre a aba Desempenho para investigar consumidores, e
as mensagens de PSI/swap não prometem alívio de Edge ou `/tmp` sem medição.
No fechamento manual, o worker usa `review.plan` para registrar plano, alvo e
ID duráveis; só então apresenta esses bytes para confirmação e chama
`review.execute` com o mesmo bundle. O `Coordinator` grava a intenção antes do
closer, revalida o alvo no ato e acompanha a saída. `review.reconcile <ID>` na
CLI e a consulta em Opções retornam o mesmo resultado. Resultado desconhecido
mantém a revisão pendente e bloqueia nova revisão do mesmo alvo; não atribui
saída do processo ao Fôlego sem resultado no diário. Clique repetido durante a
revisão fica bloqueado; arrastar o botão não navega nem pede operação.

Teste integrado com **filho descartável próprio** percorreu CLI real do plano
ao fechamento: nenhum closer na revisão, intenção presente antes do pedido,
saída acompanhada, repetição pelo mesmo ID sem segundo efeito e consulta CLI.
Regressões adicionais cobrem resultado desconhecido sem retry, GUI antes/depois
da confirmação, CTA de memória e arraste. Focados: `test_performance_close.py`
**7 passed**, `test_session_resilience.py` **25 passed**, UI Desempenho **6
passed**, UI janela **34 passed**. Host `./dev test-headless` **1241 passed,
2 skipped**; `./dev test` **1569 passed, 2 skipped**. QA na sessão KDE/Wayland real com HOME/XDG
privados: captura da central com “Dar fôlego: investigar memória”, clique
levando à aba Desempenho, ambos inspecionados. Nenhum app/unit real foi fechado;
entrada física e efeito real pelo compositor não foram ensaiados.

Próximo: matriz física e continuidade do item 8; retenção real permanece
bloqueada por `/proc/environ` inacessível em cinco processos do UID.

## Temporários próprios: inventário e localização de recuperação — 03/11/2026

Reprodução descartável: após arquivar uma execução concluída, `jobs status`
não listava o diretório retido, e o manifesto do item movido não podia ser
validado em `.retained` porque a leitura tomava essa pasta como a raiz original.
Agora o inventário lista IDs e estados dos itens retidos, preservando entradas
desconhecidas; `jobs recover <run-id>` e o seletor em Opções localizam o payload
certificado pelo mesmo ID e mostram seu caminho persistente. A recuperação é
somente leitura: não recoloca o item no limite de 256 execuções, não sobrescreve
conteúdo e pode ser consultada repetidamente. Manifesto, UID, inode da raiz e
do run, sessão/filho encerrados e persistência são verificados antes de indicar
o caminho. `jobs retain` informa recusa ou parcialidade se alguma prova faltar.
Inventário incompleto não inicia movimento; a varredura de tamanho agora propaga
erros, e o rename recusa destino já existente mesmo se vazio.

No host, `jobs status --json` mostrou 192 runs ativos: 108 `complete`, 84
`unknown`, zero retidos. Cinco processos do mesmo UID negam leitura de
`/proc/environ`; a ausência de consumidores e referências não é comprovável.
Nenhum run vivo foi movido ou apagado para produzir aceite. Testes de árvore
descartável: ciclo arquivo → inventário → CLI/GUI de localização → conteúdo
preservado; consumidor ilegível produz recusa e nenhum movimento. Focados
`test_session_resilience.py` **23 passed** e `test_ui_options.py` **9 passed**;
suíte `./dev test-headless` **1238 passed, 2 skipped**; `./dev test` **1564
passed, 2 skipped**. Aba Opções aberta em janela própria no KDE/Wayland real:
seletor, contagem, estado desconhecido e botão de localização visíveis; captura
inspecionada com HOME/XDG privados, sem entrada física ou retenção real.
Python 3.14.7 gerenciado, HOME/XDG privados, sem fixtures pytest adotadas.
CI de `9fcbbd2` passou nos dois jobs Qt, dois headless e dois contratos CLI.
Próximo: integrar a revisão do mesmo plano/ID no caminho Dar fôlego e encerrar
aceites físicos disponíveis. Retenção real segue bloqueada pela leitura dos
cinco processos; não há autorização para mudar permissões ou ignorá-los.

## Modo Desempenho: uso desconhecido protege o alvo — 03/11/2026

Reconfirmação viva, somente leitura: `folego-performance.service` está enabled e
active, sem reinícios; as regras Steam, Edge e autostarts seguem em `automatic`,
as duas regras de conselho em `suggest`. O diário automático registra **cinco**
fechamentos com sucesso (três autostarts, um Steam e um Edge), zero falhas e
disjuntor fechado; o resumo de apenas um fechamento abaixo é histórico.
Observação, regra, proteção, aviso/carência, plano, Coordinator, acompanhamento
e orçamento foram conferidos nos caminhos de produção. Nenhum app real foi
fechado nesta revisão.

Reprodução descartável antes da correção: `kdotool` com saída vazia e áudio
ativo sem PID davam resposta de uso livre; inventário de `fd` negado ou
`fdinfo` ausente também era ignorado. `core/usage.py` agora devolve motivo
desconhecido nesses casos, inclusive PID inválido, linha `flags` malformada e
arquivo de download aberto marcado como deleted. O plano e a revalidação já
bloqueavam qualquer motivo de uso; nenhum grant foi ampliado. Regressões
focadas `tests/test_usage.py`: **5 passed**; antes da correção duas falhavam.

QA em janela própria na sessão KDE/Wayland real: aba Desempenho aberta no
`MainWindow`, plataforma `wayland`, captura da janela inspecionada com navegação,
estado, cards e regras visíveis. HOME/XDG privados, sem iniciar supervisor ou
executor da sessão. Desligar/ligar pela CLI sobre esse estado privado mostrou
`paused=true` e depois `false`, sem falhas ou histórico; os testes de UI cobrem
o botão e o pedido de confirmação. Observação contínua somente de leitura:
**16 amostras em 225 s**, uma a cada 15 s, todas `interactive`, CPU protegida
entre 19,3% e 78,1% de um núcleo após a primeira amostra sem taxa; PSI de
memória máximo 0,02%. O gatilho `busy` visto durante build/testes não persistiu
com a carga menor. Isto não é um soak de horas nem valida entrada física,
leitor de tela ou a unit real por alternância forçada.

Host: `./dev test-headless` **1237 passed, 2 skipped**; `./dev test` **1562
passed, 2 skipped** após o ajuste final de parsing. Python 3.14.7 gerenciado, HOME/XDG privados e
suítes sequenciais; nenhuma unit, app ou estado automático real foi alterado.
CI de `e5dfb5c` passou nos dois jobs Qt, dois headless e dois de contratos CLI.
Próximo: retenção de temporários administrados e fluxo Dar fôlego. A retenção
viva segue bloqueada por cinco processos do mesmo UID com `/proc/environ`
inacessível: não interpretar a ausência de referência como comprovada.

## Revisões: recibo reconciliado libera slot ativo — 03/11/2026

Reprodução em HOME descartável antes da correção: `review.reconcile(id)`
retornava o resultado já conhecido no diário, mas mantinha o bundle `started`
em `reviews/`; uma segunda chamada repetia a resposta e o arquivo ainda
ocupava um dos 256 slots. Agora a reconciliação compara plano/ID/resultado,
fecha o recibo e só então devolve o resultado. O fechamento grava a cópia
`closed`, cria o destino sem sobrescrever (`link` exclusivo), sincroniza o
diretório e remove a cópia ativa; se uma queda deixou ambas, confere conteúdo
antes de terminar. Recibo conflitante preserva os dois lados e gera erro.
Clique repetido com resultado conhecido passa pela mesma reconciliação; o
efeito não é reaplicado. Cancelamento com recibo fechado continua consultável.

Testes focados `test_session_resilience.py`: **22 passed**, incluindo resultado
conhecido, repetição, queda entre link/unlink e conflito. Host:
`./dev test-headless` **1236 passed, 2 skipped**; `./dev test` **1561 passed,
2 skipped**. HOME/XDG privados, efeito somente em fixtures. Próximo: Modo
Desempenho no host e aceites físicos seguros. CI de `9981fd9` passou nos dois
jobs Qt, dois headless e dois de contratos CLI.

## Início com a sessão: escolha e unit em ordem única — 03/11/2026

Reprodução descartável antes da correção: habilitação A pausada em `install`,
desabilitação B gravou preferência/autostart e terminou, A ligou a unit por
último; teste falhou com preferência falsa e unit ligada. `startup.configure`
agora mantém uma trava própria, entre processos, durante a escolha durável e o
efeito da unit. O lock global do Coordinator continua restrito às escritas de
preferência/autostart; a GUI permanece em worker. Desabilitar usa
`systemctl --user disable --now` para encerrar também o monitor atual. Após
cada efeito, o estado da unit é consultado; timeout, falha ou estado não
comprovado devolvem `desconhecido`, preservando a escolha gravada e exibindo o
motivo na CLI/GUI. Unit pessoal e destino inesperado continuam protegidos.

Teste concorrente e teste de timeout usam apenas mocks e HOME privado. Host:
focados `test_session_resilience.py` + `test_cli_operations.py` **24 passed**;
`./dev test-headless` **1234 passed, 2 skipped** e `./dev test` **1559 passed,
2 skipped**. CI de `c363363` passou nos dois jobs Qt, nos dois headless e nos
contratos CLI. Nenhuma unit real foi alterada; confirmar o comportamento na
sessão KDE apenas por escolha normal do usuário, sem reinício de sessão como
QA. Próximo: recibo de revisão reconciliada.

## Swap: inventário parcial ou ausente — 03/11/2026

No coletor anterior, qualquer arquivo `/proc/swaps` existente marcava a fonte
`ok`, mesmo quando `read_swaps` descartava a única linha inválida e devolvia
total/uso zero. `procfs.SwapRead` agora distingue `ok` (inclusive cabeçalho
válido sem entradas), `missing`, `partial` e `error`, com motivo. O coletor
propaga a qualidade; snapshot, saúde, card, detalhes, compacto, bandeja,
sugestões e `doctor --json` não inferem “sem swap/zram” de inventário
incompleto. `doctor` marca a falha como erro e `healthy=false`; a saúde fica
desconhecida quando os demais sinais não indicam condição pior. Entradas
legíveis de um inventário parcial permanecem nos dados diagnósticos, sem
autorizar percentual ou veredito de folga.

Fixtures descartáveis cobrem vazio válido, ausente, ilegível, cabeçalho
inválido, linha malformada e cauda sem terminador. Host: focados headless
**60 passed**, UI Qt **52 passed**; suíte `./dev test-headless` **1232 passed,
2 skipped** e `./dev test` **1557 passed, 2 skipped**. CI de `a7edb43`
passou nos dois jobs Qt, nos dois headless e nos contratos CLI. Python 3.14.7 gerenciado,
HOME/XDG privados; nenhum efeito em swap real. Próximo: corrida da preferência
de início com a sessão.

## Oráculo de texto Qt no runner Ubuntu — 03/11/2026

No SHA `98bd49c` o CI repetiu as duas falhas anteriores do Qt offscreen;
`tests/test_ui_transparency.py` exigia que algum pixel do glifo chegasse a
alpha 255. O código aplica cor de texto opaca (`theme.apply_theme`,
`AccountPanel.line`) e mantém `windowOpacity() == 1`. O Qt desenha texto com
antialiasing por padrão e a cobertura depende da fonte/renderizador
([QPainter](https://doc.qt.io/qt-6/qpainter.html)); alpha máximo 250/244 na
fonte do Ubuntu não prova uma camada de texto translúcida. Captura offscreen
local inspecionada: texto presente sobre fundo transparente, alpha máximo 255
no painel e na renderização isolada do mesmo label, cor do palette alpha 255.

O teste agora compara a composição do painel com o mesmo glifo renderizado
isoladamente, usando a cobertura da própria fonte, e verifica separadamente
cor de texto e opacidade da janela. Mantém a prova de ausência de caixa de
fundo na linha. Host: `./dev test tests/test_ui_transparency.py` **15 passed**;
`./dev test` **1544 passed, 2 skipped**, Qt offscreen, HOME/XDG privados,
Python 3.14.7. CI de `e199e24` passou nos dois jobs Qt offscreen, além de
headless e contratos CLI. Offscreen não prova
compositor, leitor de tela ou entrada física. Próximo: swap parcial.

## Diário: cauda JSON sem terminador — 03/11/2026

Em `395cfd6`, `Journal.load()` usava `splitlines()` e aceitava uma última linha
JSON válida sem `\n`. O próximo append poderia colar registros e o Coordinator
atingir o executor antes de descobrir a corrupção. A leitura agora exige o
terminador em toda linha; não altera nem trunca o diário. Teste descartável pelo
Coordinator: duas tentativas com o mesmo ID recusadas antes do efeito, bytes
preservados e consulta explicitamente bloqueada. Após completar manualmente a
linha **somente na fixture**, o mesmo ID permanece intenção pendente; registrar
resultado permite consulta sem reaplicar. Testes no host: `./dev test-headless`
**1220 passed, 2 skipped**; `./dev test` (Qt offscreen) **1544 passed, 2 skipped**.
Linux/Python 3.14.7, HOME/XDG privados, suítes sequenciais; nenhum efeito real.
O runner Ubuntu ainda tinha duas falhas Qt no SHA anterior; verificar no novo
SHA. Próximo: investigar o oráculo de transparência Qt no CI.

## Pontes MCP: inventário e finalização assistida — 03/11/2026

Investigação: o servidor MCP real é o `ai-memory` (:49374). As duas
"instâncias" eram pontes `mcp-remote` do próprio Claude Desktop (entrada
`ai-memory` em `claude_desktop_config.json`, `npx -y mcp-remote@latest`),
iniciadas às 08:22 e 08:28, ambas ainda conectadas ao Desktop e ociosas. As
sessões do Claude Code e o `hermes` não usam essas pontes. Finalizar uma não
afeta o servidor; no máximo o chat do Desktop perde as ferramentas até
reiniciar o servidor nele.

`core/mcp_bridges.py`: inventário (npm + node, cliente dono depois dos
wrappers, endpoint, conexão stdio pelo `ss -xp`), status única/duplicada/órfã;
sem leitura do `ss` nada vira órfã nem pode ser finalizado. `stoppable` só aceita
órfã ou duplicada com outra ponte conectada do mesmo cliente.
`actions/performance/bridges.py`: plano/diário, revalidação no ato, SIGTERM via
`Reaper.terminate_group` (pidfd, filho antes do npm) e reverificação: 1 ponte
conectada + servidor local respondendo = "MCP OK". É a única ação do Modo
Desempenho com sinal, sempre manual. CLI `performance bridges` e
`bridge-stop --pid N [--confirmar]`. A aba ganhou a seção **Pontes MCP**, com
Finalizar por ponte e a mais antiga marcada como recomendada. Testes de efeito só
com filhos do próprio teste. Host: inventário correto e dry-run; nenhuma ponte
real foi finalizada. Testes: headless **1218 passed, 2 skipped**; Qt **1542
passed, 2 skipped**. A pedido do usuário, a ponte 125124 (08:22) foi finalizada
pela CLI (operação 0ec684ac…): `sucesso`, npm, node e wrapper saíram; a 143281
ficou "única" e conectada, e o servidor :49374 continua escutando. Pendente:
fixar a versão do `mcp-remote` no Desktop.

## Interruptor simples do automático — 03/11/2026

Pedido do usuário: desligar o automático de forma simples pela UI. Botão no topo
da aba desempenho ("Automático: ligado — clique para desligar"); desligar não
pede confirmação, ligar pede. A chave `paused` fica no estado automático
(schema 1, campo opcional validado). Desligado: nada é anunciado nem fechado;
sugestões e **Fechar** manual continuam. A chave também é relida no ato do
fechamento; desligar durante a carência gera recusa sem contar no disjuntor.
CLI `performance auto-off|auto-on`. Host: serviço reiniciado com o código novo,
chave alternada para desligado e de volta para ligado. Testes: headless **1214
passed, 2 skipped**; Qt **1537 passed, 2 skipped**. Pendente: conferência visual.

## Modo Desempenho ativado no host — 03/11/2026

A pedido do usuário, `steam-idle`, `edge-after-login` e `autostart-extras` foram
postas em `automatic`; os dois conselhos continuam em `suggest`. Unit instalada
com `performance install --confirmar`:
`~/.config/systemd/user/folego-performance.service`, enabled e active, ~21 MB.
Primeiro fechamento automático real às 09:53, com resultado `sucesso`: o
`biglinux-welcome.service` foi parado pelo systemd do usuário e todos os
processos revisados saíram. O gatilho foi "agentes em build/teste". Os outros
autostarts aguardam o orçamento de 1/h por regra. Observação: com o Claude
Desktop ativo, o gatilho por agentes ocupados fica quase sempre ligado; avaliar
o limiar (`agents.BUSY_CPU`) após uso real. Desfazer:
`performance uninstall --confirmar` ou o modo das regras na aba.

## Modo Desempenho, incremento 5 (endurecimento) — 03/11/2026

`core/usage.py`: janela em foco (`kdotool`), áudio por PID (`pactl`), download em
andamento e arquivo de projeto aberto para escrita (`/proc/<pid>/fd`); foco ou
áudio desconhecido protege. `PerfView.in_use` é sondado só para grupos
candidatos e bloqueia plano e revalidação. Navegador real com CDP/Marionette
conta como agente. `WindowClose`/`GroupTerm` e portas ficaram fora por decisão
registrada em `docs/MODO-DESEMPENHO.md`.

Soak a seco no host (executor trocado por registrador, regras de fechamento em
automático, suítes completas como carga de agente): 36 ciclos/6 min, 4,4 s de
CPU, 24 MB, ciclo máx. 200 ms, sem erro; gatilho "agentes em build/teste"
observado, aviso e carência funcionaram e um fechamento foi planejado a seco.
**Achado e corrigido:** o `steamwebhelper` usa CDP interno e tornava o Steam
"agente"; a regra de CDP agora vale só para navegadores. Segundo soak (18
ciclos/3 min): Steam observado, sem erro. Nada foi fechado no host. Nota: uma
recusa na revalidação conta para o disjuntor (conservador). Testes: headless
**1212 passed, 2 skipped**; Qt **1534 passed, 2 skipped**. Pendente: ativação
pelo usuário (regras em automático e `performance install --confirmar`),
primeiro fechamento real e soak real de horas com efeito.

## Modo Desempenho, incremento 4 (Automático) — 03/11/2026

Modo `automatic` por regra. `core/perf_auto.py` (puro) decide: disjuntor
fechado; pressão (PSI memória ≥ 5% em 60 s, RAM disponível < 15% ou agentes em
build/teste); sem adiamento; app não fechado com sucesso neste boot (reabertura =
repouso até o próximo boot); orçamento 3/h no total e 1/h por regra; aviso e
carência de 60 s; no máximo um fechamento por ciclo. Duas falhas seguidas abrem o
disjuntor; só `resume` fecha. Estado versionado com trava em
`performance-auto.json`; ilegível desliga o automático.
`actions/performance/auto.py`: ciclo (mesmo executor, gatilho `auto`, que exige
regra em automático na revalidação), `notify-send` no aviso, `watch` com trava
de instância única e unit opcional `folego-performance.service`
(`install|uninstall --confirmar`; **não instalada no host**). CLI `auto`,
`watch`, `resume`, `snooze`, `protect` (exclusão `app` do processo raiz). Aba:
estado do automático, motivo de espera por card, **Adiar 30 min**, **Proteger
sempre** e **Retomar automático**. Host real com estado privado e regras no
padrão: `watch` 3 ciclos sem efeito; segundo executor recusado. Testes:
headless **1208 passed, 2 skipped**; Qt **1530 passed, 2 skipped**. GUI
reaberta pela bandeja: 50 ticks/10 s. Pendente: o usuário escolher regras em
Automático e instalar a unit; primeiro fechamento real; conferência visual.
Próximo: incremento 5 (WindowClose/foco, downloads e CDP, soak com agentes).

## Modo Desempenho, incremento 3 (Assistido) — 03/11/2026

Modo `assisted` por regra. `actions/performance/closers.py`: `tray_quit` aciona
o item de saída do menu dbusmenu do próprio app, só em ícones cujo dono no
barramento é membro do grupo (ensaio a seco no host achou "Exit Steam");
`unit_stop` pede `systemctl --user stop --no-block` (Edge e autostarts).
`executor.py` usa `perform`/Coordinator: intenção no diário antes do pedido,
revalidação no ato (boot, identidade raiz, regra em assistido, agente/exclusão,
condição atual), acompanhamento de 20 s; app que fica é `parcial` sem repetição.
CLI `performance close <regra> --unit U [--confirmar] [--json]`; aba mostra
**Fechar** só em card pronto de regra assistida, com confirmação e `TuneJobs`.
Corrigido: gravar modos em HOME novo criava o diretório de estado. Testes de
efeito só com filho Python do próprio teste. Host real: ensaio sem
`--confirmar` contra o Steam respondeu dry-run; nada foi fechado. Testes:
headless **1198 passed, 2 skipped**; Qt **1519 passed, 2 skipped**. GUI
reaberta pela bandeja: 57 ticks/10 s. Pendente: primeiro fechamento real
confirmado pelo usuário e conferência visual da aba. Próximo: incremento 4
(Automático: gatilho por pressão, orçamento, disjuntor, carência e aviso).

## Modo Desempenho, incremento 2 (regras e sugestões) — 03/11/2026

`core/perf_rules.py`: regras embutidas e só de permissão (`steam-idle` com
marcadores de jogo, `edge-after-login`, `autostart-extras` por units exatas,
`mcp-duplicate` e `electron-bloat` como conselho). O usuário escolhe só o modo
por regra (`off`/`suggest`) em `performance-rules.json` (state, schema 1);
arquivo ilegível, regra desconhecida ou modo assistido/automático desligam tudo.
Espera contínua por identidade (`ConditionTracker`); qualquer intervalo reinicia.
Exclusões/`keep_active` agora protegem grupos (`snapshot_checker` movido para
`core/process_protection.py`, mesmo uso no CLI). CLI `performance plan|rules|set`;
aba com cards de sugestão e seletor por regra. Host real (CLI): Edge 2,4 GB,
Steam 550 MB, ponte MCP duplicada e quatro autostarts sugeridos. Testes:
headless **1193 passed, 2 skipped**; Qt **1513 passed, 2 skipped**. GUI reaberta
pela bandeja: 51 ticks/10 s. Pendente: conferência visual da aba no KDE. Próximo:
incremento 3 (Assistido: closers bandeja/unit, journal, revalidação, seguimento).

## Modo Desempenho, incremento 1 (observação) — 03/11/2026

`core/agents.py` protege árvores de agentes (Claude/Codex/Desktop/Web) e todo
processo com cwd em work tree Git, com ancestrais; `core/perf_model.py` agrupa
por unit/scope folha da sessão: só `app-*` sem agente fica **observado**; sessão,
sistema, não identificado e classes fixas ficam protegidos. CLI
`folego performance status [--json]` e aba **desempenho** somente leitura, com
coleta própria em worker apenas enquanto visível. Host real: Edge 2,5 GB e Steam
586 MB observados; Claude, Codex Web e Browser pane como agente. Testes:
headless **1188 passed, 2 skipped**; Qt **1507 passed, 2 skipped**. GUI reaberta
pela bandeja: 54 ticks/10 s. Pendente: conferir visualmente a aba no KDE real.
Próximo: incremento 2 (schema de regras e cards de sugestão).

## CPU da GUI no pulso de entregas — 03/11/2026

A thread da GUI consumia ~35% de CPU: o pulso infinito de entregas redesenhava o
anel a cada quadro, inclusive minimizado. `_pulse_deliveries` agora redesenha em
passos de 1/8 e pausa com a janela minimizada. Host real (KDE/Wayland), GUI
reaberta pela bandeja e `./dev gui`: 353 → 55–57 ticks/10 s (inferência causal,
sem A/B). Removidos, com aprovação, 9 runs anônimos `passed` de QA. Testes:
headless **1185 passed, 2 skipped**; Qt **1503 passed, 2 skipped**. Próximo:
oportunidades levantadas no host (agrupar árvores Electron/navegador, MCP
duplicado, units falhadas, PSI, inventário de cache).

## Limits do Codex Web alinhado ao 6.1.17 — 03/11/2026

- `web_limits` passou a exigir `initializedAt` válido e a recusar eventos anteriores a ele, como faz o store do app.
- Janelas que começam antes do início da contagem mostram "contagem iniciada em …".
- A fonte informa que o número é um piso: só conta mensagens Pro enviadas pelo app.
- O motivo `unsupported` avisa que, se a verificação falhar, o app precisa de atualização. Hoje o seletor do composer no 6.1.17 está quebrado no ChatGPT, e a correção fica no upstream.
- A tabela do 6.1.17 confere com `WEB_LIMITS` (gpt6Weekly 200, solDaily 170, combinedDaily 200, combinedWeekly 50).
- Testes: headless 1185 passed/2 skipped; Qt offscreen 1502 passed/2 skipped.

## Atalho e data do Limits do Codex Web — 03/11/2026

O launcher não tem deep link nem API externa para a verificação de plano do
Limits; ela continua um clique do usuário no aplicativo (modo Automatic exigido,
conferido como `automatic` no host). Hover agora mostra data e resultado da
última verificação; botão direito do Codex Web ganhou **Abrir Limits no Codex Web**,
pelo mesmo abridor existente (`agent-open`). Menu separado em `options_menu`
para teste sem `exec`. Testes HOME novo: headless **1183 passed, 2 skipped**;
Qt **1500 passed, 2 skipped**. GUI reaberta pela bandeja, compacta.

## Codex Web pelo Limits e renovação do Claude — 03/11/2026

Correção do usuário: Codex Web é túnel da cota ChatGPT Web da conta Principal
(Pro), não a cota Codex da conta logada na raiz (MHMAIL). A leitura Codex da
raiz Web foi removida. Fonte agora: `launcher-data/limits.json` do próprio
aplicativo (mesma tabela oficial: GPT-6 Pro 200/7 d, GPT-5.6 Pro 170/24 h,
combinado 200/24 h; Pro 5x 50/7 d), janelas móveis contadas como no app.
No host o arquivo está `unsupported`, sem eventos desde 19/10: **?** até o usuário
refazer a verificação em Limits no aplicativo com a conta Pro.
Claude: token vencido com renovação válida pede ao cliente oficial
`claude doctor` (sem inferência, cwd temporário, variáveis `CLAUDE_CODE_*` do host
removidas), no máximo uma vez a cada 10 min por raiz; falha mantém **?**. Só no
coletor nativo; testes nunca executam o cliente. Host: Claude 70%, Grok 0%.
Testes com HOME novo: headless **1182 passed, 2 skipped**; Qt **1498 passed,
2 skipped**. Falha de `test_ui_capture_alerts` vista antes era resíduo de QSettings
de HOME reaproveitado pelo agente, não do código.

## Leitura de cota Codex Web, Claude e Grok — 02/11/2026

Sobre `51e3fed8ea5c728163f094feef9ca8288f6a954f`, mesma raiz/branch/PR #1.
**Grok:** o próprio CLI responde `_x.ai/billing` via ACP stdio (`initialize` +
billing, sem prompt, cwd temporário vazio, sai no EOF). `creditUsagePercent`
e `currentPeriod` viram janela (Semana/Mês/Dia) com reset; plano do
`subscription_tier`. Cache de 5 min por raiz/auth; troca de auth descarta.
**Codex Web:** a raiz Web usa a mesma consulta oficial do Codex da sua conta;
fonte rotulada como cota Codex da conta (turnos `chatgpt-web/` não trazem limite).
**Claude:** token de acesso vencido com renovação local válida não é mais
"login expirado"; mostra plano, validade da renovação e pede uso do Claude Code.
Fôlego continua sem renovar credenciais; a cota volta quando o cliente renovar.

No host (CLI, mesmo `collect`): Codex 30%, Web 18%, Grok 0% SuperGrok
(semana até 07/11), Claude **?** com token local vencido em 01/11. Sem processo
Grok remanescente. Testes: headless **1176 passed, 2 skipped**; Qt offscreen
**1492 passed, 2 skipped**, sequenciais, HOME/XDG/TMP privados no scratchpad
do agente — `./dev test` recusou por 20 workspaces retidos em `.scratch/dev-tests`
(nada apagado; inspecionar antes de liberar). GUI em execução ainda carrega o
código anterior até ser reaberta pela bandeja. Reaberta depois: "Sair do Fôlego"
via DBusMenu (PID 1827618, starttime conferido) e uma chamada `./dev gui`; novo
PID **2275351**, starttime **10748131**, compacto restaurado pela bandeja.
Anéis na GUI real: Codex 30, Codex Web 11, Claude ?, Grok 0.

## Medidores circulares animados de IA — 02/11/2026

Sobre `0239f4921e144ac839c5a4ead86c5d315bbf921d`, mesma raiz/branch/PR #1.
Código, testes e provas em `604f1f515cfcc929133d4393177addc0fd9baa47`.
Codex, Codex Web, Claude e Grok seguem o medidor circular do PhaseZero:
disco de identificação, percentual disponível no centro e arco de cota.
Nome completo Codex Web, entregas/presentes abaixo e largura de 280 px.
Dados vêm do monitor existente, sem importar/iniciar PhaseZero. Fontes sem
percentual, antigas ou incompletas mostram **?** com anel cinza; zero mostra
**0** com arco vazio. Padrão de cores da referência preservado entre temas
e transparência. Contas, hover, cliques e presentes mantêm seus contratos.

Transição de 450 ms entre valores conhecidos; número/descrição atuais desde
o início. Expiração/falha cancelam imediatamente. Entregas confirmadas fazem
a borda interna pulsar em 1,8 s, separada de cota/tickets. Sem contagem
confirmada ou widget visível, não pulsa; ocultação para todas as animações.
O monitor de consultas continua independente da visibilidade.

Focados **16 passed**, 1,48 s. `./dev check`: **1168 passed, 2 skipped**
headless, 25,31 s; **1484 passed, 2 skipped** Qt, 97,45 s. Python 3.14.7,
sequencial, HOME/XDG/TMP/Pulse privados. Oito cenários KDE/Wayland aprovados:
três combinações de tema/transparência, animações, expiração, clique/hover
nativos, presente por Qt, ocultação, Central/Voltar e saída. Inspeção visual
das capturas próprias em 135%, nomes inteiros e contadores sem sobreposição.
Abertura do cliente interceptada em memória; métricas/contas sintéticas.
[Provas, comandos e limites](handoff/validation/ai-quota-rings-2026-11-02/README.md).

Primeiro QA nativo não aprovado: hover abriu o painel durante calibração e
interceptou o clique. Corrigida a sequência do harness, mantendo 45 s e a
tentativa anterior. Baseline remoto já tinha Qt vermelho em duas variantes
de transparência de texto com fonte Ubuntu (alpha 250/244, linha 31).
Asserção preservada e nenhuma alegação de CI inteiramente verde.

GUI real atualizada pela saída da bandeja e uma chamada `./dev gui`, com
lock liberado e posição/preferências preservadas. Novo PID **1827618**,
starttime **10085542**, widget (2902,197;33,954), 280×217, central oculta.
Recibo privado `.scratch/dev-tests/run-ta5pjkkq/host-replacement/replacement-primary.json`,
com boot/identidade observados após a saída do launcher. Revalidar antes de
agir. QA/auxiliares encerrados, nenhum trabalho alheio sinalizado e nenhum
diretório anterior apagado. Sem release/merge/grant; b2 imutável.
Próximo passo: usuário conferir os sinais nas suas contas; Web/Grok continuam
sem fonte percentual confirmada. Matriz geral de desktop permanece parcial.

## Transparência dos fundos e painel contínuo — 02/11/2026

Sobre `fdceab8095c62a68e3efdc32f942b959a91608ce`, mesma raiz/branch/PR #1.
Código, testes e provas em `c28b8d4eedd763fb72b82922f87c1e6f6d4aa87e`.
Complemento do preenchimento primário e focados em `6c653cd20d6c984cc6717631444f660ae746fb89`.
Corrigidos estilos genéricos que pintavam rótulos/contêineres como caixas no
painel de contas. Popup sem moldura preta, superfície única arredondada,
filhos transparentes e cartão de janela de uso com seletor próprio.
Barra em opções/Aparência, 0% opaco a 100% sem fundo, padrão 0%. Muda pinturas
de fundo de todas as superfícies; conteúdo/contornos/indicadores continuam
opacos e windowOpacity fica 1. Prévia durante arraste sem I/O de configuração,
salvamento ao soltar e por teclado/acessibilidade, preservação entre temas e
restauração ao abrir. QSettings existente, `appearance/background_transparency`.
Inválido é informado sem sobrescrever; falha de gravação restaura o estado.

ARGB preparado antes de mapear. Raízes com WA_NoSystemBackground pintam QSS
explicitamente; diálogos e superfícies novas seguem o tema. Checkbox desmarcado
mantém contorno e estado distinto. Nenhum novo serviço, grant ou operação de
recurso. Fontes e dados das contas permanecem nos seus owners existentes.

`./dev check`: **1168 passed, 2 skipped** headless (50,68 s) e **1473 passed,
2 skipped** Qt (142,25 s). Após a regressão de checkbox, Qt final `./dev test`:
**1478 passed, 2 skipped**, 126,64 s. Focados finais **15 passed**, 3,84 s, incluindo preenchimento primário
e estados de checkbox.
Python 3.14.7, sequencial, HOME/XDG/TMP/Pulse privados. Host com carga 18–20,
sem encerrar trabalhos alheios. Duas execuções KDE/Wayland de sete cenários,
SNES/PS2 com 0/50/100%, cinco superfícies, salvamento, navegação e saída.
Composição real por portal sobre fundo próprio: alpha 8 bits, mistura de 50%
coincidiu exatamente nos dois pixels medidos; textos e indicadores opacos.
Captura pública retém somente recorte interno do fundo próprio na escala 135%.
[Provas e limites](handoff/validation/background-transparency-2026-11-02/README.md).

Tentativas interrompidas preservadas. Oráculo corrigido para medir popup nativo,
em vez de QWidget filho com preenchimento sintético de raiz. Perfis finais
separados para respeitar os 45 s existentes, sem somar tentativas como aprovação
ou ampliar watchdog. QA/auxiliares encerrados. Sem release/merge; b2 imutável.
GUI real substituída por Sair na bandeja e `./dev gui`, lock liberado e sem
sinais manuais/outros clientes encerrados. PID **586685**, starttime **7047120**,
widget (2702;32,885), 280×219, central oculta; posição e tema atuais preservados.
Recibo final privado `.scratch/background-transparency/replacement-primary.json`.
Revalidar identidade/boot antes de agir. Próximo passo: usuário regular a barra
em Central → opções → Aparência · consoles clássicos.

## Temas de consoles em toda a interface — 02/11/2026

Sobre `1cf92789aa10eaad608956cab6d5c9eb4799d82c`, mesma raiz/branch/PR #1.
Código, testes e provas em `4f64b091e04b62303f5b3848c14b2dee2ce681eb`.
Seletor no topo de opções: oito temas do anexo (SNES americano, SFC, Mega Drive,
Master System III, PC Engine, NES, TurboGrafx-16 e PS2). Padrão SNES americano.
Tokens compartilhados, receitas nos próprios widgets e atualização em uso de
central, compacto, prompts/submenus/Custom, contas e teclado, mesmo ocultos.
Ícones de controles e sinais redesenhados com a paleta; alertas preservam
semântica/texto. Sem recriar monitores, alterar grants ou fontes de conta.
Preferência `appearance/theme` na autoridade QSettings existente; restauração,
chave desconhecida informada sem sobrescrever e falha de gravação explícita.

Focados finais **46 passed**, 16,09 s. `./dev check`: **1168 passed, 2 skipped**
headless (48,15 s), **1465 passed, 2 skipped** Qt (120,81 s), Python 3.14.7,
sequencial, HOME/XDG/TMP/Pulse privados. Contraste texto/semântico/categorias
4,5:1 nas três superfícies, tinta dos botões, foco, persistência e views abertas,
ocultas e futuras. Doze cenários KDE/Wayland, oito temas selecionados e salvos
com clique nativo e navegação Qt no popup; capturas de quatro superfícies por
paleta. Inspeção visual das matrizes de widget/prompts/teclado e central.
Dados de demonstração, sem clipboard/processos/textos do usuário como fixtures;
teclado validado na apresentação, sem repetir efeitos de digitação/volume.
[Provas e limites](handoff/validation/console-themes-2026-11-02/README.md).

CI anterior do SHA base tinha Qt vermelho por larguras 91/88 na fonte Ubuntu;
política horizontal dos seis botões corrigida para preservar colunas iguais,
sem afrouxar a asserção. Núcleo/CLI anteriores verdes. Tentativas de QA
interrompidas preservadas; harness ajustado para clique nativo no seletor e
navegação no popup próprio. Sem novo release/merge; b2 continua imutável.
GUI real substituída pela ação Sair na bandeja e `./dev gui`, com lock
liberado, sem sinais manuais ou outros clientes encerrados. PID **389475**,
starttime **6736851**, widget (3108,315;187,814), 280×219, central oculta.
Posição atual do usuário preservada. Recibo privado
`.scratch/console-themes/replacement.json`; revalidar identidade/boot.
Consulta ampla lslocks excedeu o prazo antes da intenção, sem efeito; autoridade
confirmada por flock não bloqueante e fdinfo do inode exato, evitando varrer
outros processos. Próximo passo: usuário escolher a paleta em
Central → opções → Aparência · consoles clássicos.

## Atalhos recolhíveis e temperatura — 02/11/2026

Sobre `b2969ac5280cc2ed477b258ddbe13701264c3332`, mesma raiz/branch/PR #1.
Código, testes e provas em `ee4a756203d7e1708e0ecda0d31d5383a88195ee`.
Seis atalhos pareados em duas linhas iguais, ocultos em repouso, animação
descendente de 140 ms e espera de 200 ms ao sair; menus preservam a escolha.
Teclado no cabeçalho, padrão embaixo e seta separada para cima. CPU/Tmp
alinhados e temperatura em °C à direita da CPU. O antigo Temp era ocupação
de tmpfs: agora Tmp, sem inventar relógio. CPU/SoC preferenciais, ACPI de
sistema como fallback identificado; ausente/ilegível permanece — °C. Leitura
no coletor, somente sysfs, sem Qt no núcleo ou ajuste de ventoinhas.

`./dev check`: **1168 passed, 2 skipped** headless (21,64 s) e **1453 passed,
2 skipped** Qt (45,89 s), Python 3.14.7 gerenciado, HOME/XDG/TMP/Pulse privados,
sequencial. Doze cenários finais KDE/Wayland: recolher/revelar, prompt e seis
macros com foco preservado, navegação e saída. Corrigida reconciliação de Enter
sintético do Qt ao fechar popup e entrar em outra superfície. Guardas de PID
e posição mantidos; tentativas anteriores preservadas e não somadas como
aprovação. Inspeção visual das capturas próprias: botões iguais, teclado
disponível, métricas legíveis e alinhadas. Temperatura da captura é demonstração.
[Provas e limites](handoff/validation/hover-actions-2026-11-02/README.md).
Sem release/merge ou ampliação de grants. GUI real substituída por Sair na
bandeja e `./dev gui`, com lock liberado, sem sinais manuais/outros clientes.
PID **234379**, starttime **6504957**, widget (3108,315;187,814), 280×219,
central oculta. Preservada a posição atual do usuário; revalidar identidade/boot
antes de agir. Recibo privado `.scratch/hover-actions/replacement.json`.
Sensor de sistema `acpitz` disponível no host, leitura real somente leitura;
não tratado como prova de temperatura de CPU. Próximo passo: usuário validar
o hover e a disposição dos controles na instância atual.

## Seletor com faixas laterais aprovado — 02/11/2026

Sobre `1512658a885c6574b1525bd69401c893a3c3be77`, mesma raiz/branch/PR #1.
Código, testes e provas em `0c592a162f0ed2c97ef0d769bc83861bea05b86b`.
Opção aprovada implementada no próprio Qt: 12 títulos em seis categorias com
faixas coloridas, cabeçalhos horizontais e copiar por linha. Painel até 480×540,
rolagem e rodapé fixo com Janelas/Edição/Terminal/Custom. Setas/Tab/Enter/Escape;
nomes longos quebram linha. Categorias no catálogo Qt-free, sem mudar os corpos
dos prompts. Custom preservado, carregado no worker e sem migração/regravação.
Menus fecham antes de copiar/solicitar macros para retornar o foco ao destino.

Focados finais **20 passed**, 5,61 s. `./dev check`: **1165 passed, 2 skipped**
headless (21,16 s), **1448 passed, 2 skipped** Qt (44,62 s). Python 3.14.7,
sequencial, HOME/XDG/TMP/Pulse privados. Onze cenários finais KDE/Wayland com
cliques em prompt e seis macros, foco e navegação. Clipboard/colagem integral
em Xvfb próprio; Custom/Mostrar área de trabalho em KWin/Xvfb/D-Bus isolados.
Guardas de ponteiro mantidos; rota entre saídas com escalas distintas corrigida
no harness após bloqueios. Auxiliares de QA encerrados.

Comparação visual conjunta e detalhe em [design-qa.md](../design-qa.md), resultado
passed. Corrigidos separadores/ícones afetados pelo estilo herdado e densidade
inicial. Último título pode exigir rolagem na fonte nativa, com rodapé preservado.
Ícones de tema com fallback Tabler/MIT incluídos no wheel; offline build e bytes
de todas as fontes/assets verificados, sem dados privados no pacote. Sem release,
merge, regra persistente ou ampliação de grants. [Provas e limites](handoff/validation/prompt-groups-2026-11-02/README.md).

Após o commit, GUI real substituída por Sair na bandeja e `./dev gui`, com lock
liberado, sem sinais manuais ou encerramento de outros clientes. Nova GUI
**126200**, starttime **6331748**, widget (439,695;97,407), 280×274,815, central
oculta; posição atual do usuário preservada. Recibo privado
`.scratch/prompt-groups/replacement.json`. Revalidar lock/PID/starttime/boot antes
de agir novamente. Próximo passo: usuário validar o seletor em Prompts. Publicação
de b2 continua imutável.

## Prompt de Product Design para seleção — 02/11/2026

Sobre `f82e9974937de69ce312ff5149551f13c12b33d6`, mesma raiz/branch/PR #1.
Código, testes e provas em `9b138147918266e3f725fb87d79c1dd5d530c72a`.
Incluído **Design e mockups para aprovação**, ID `design-mockups`, logo após
usabilidade. Texto integral do anexo do usuário, 9866 bytes UTF-8, SHA-256
`679b411c224337653971fe662e62a854f704a703203310f393c59bed06b0e8a9`.
Sem adicionar o preâmbulo genérico neste item; contexto dos demais preservado.
Biblioteca com 12 títulos, corpo embutido no Python, sem depender do caminho
do anexo. O conteúdo é um prompt para copiar, não uma instrução executada neste
lote. Não foram produzidos mockups nem alterado o design por causa do texto.

Focados: **11 passed** Qt (1,54 s) e **2 passed** headless (0,27 s), Python
3.14.7, sequenciais, HOME/XDG/TMP/Pulse privados. Cópia real do menu e colagem
Shift+Insert em Xvfb próprio preservaram texto/hash e Custom `123`. KDE/Wayland:
cinco cenários incluindo clique nativo no novo título; clipboard interceptado
somente no QA para não usar o físico como fixture. Aguardar escala do popup e
posicionar seu próprio widget corrigiu o oráculo sem afrouxar guardas. Não
repetidas suítes integrais neste incremento de conteúdo. [Provas e limites](handoff/validation/design-prompt-2026-11-02/README.md).

Fôlego substituído pela bandeja e launcher oficial, lock liberado e sem sinais
manuais. GUI **4108311**, starttime **5992098**, compacto (2958,549;116,584),
280×275, central oculta; posição do usuário preservada. Recibo privado
`.scratch/design-prompt/replacement.json`; revalidar identidade/boot. QA e
auxiliar encerrados. Sem release/merge; próximo passo: usuário selecionar o
novo título e colar o prompt no agente desejado.

## Atalhos padrão em Janelas, Edição e Terminal — 02/11/2026

Sobre `dca7f88b5608f83a4eebbe8ac0e55692dee84e26`, mesma raiz/branch/PR #1.
Código, testes e provas em `dc5ba8a6116bb2e988c780c6a20075207af4fad6`.
Pedido atual implementado: dez atalhos sugeridos, em três submenus de Prompts,
antes de Custom (continua o último). Janelas: Alt+Tab, Meta+W, Meta+Left/Right.
Edição: Ctrl+Z, Ctrl+Shift+Z, Ctrl+S, Ctrl+F. Terminal: Ctrl+Shift+C/V.
Catálogo Qt-free com IDs estáveis, exibe combinações sem registrar atalhos
globais; escolha solicita uma combinação pelo worker/backend existente.
Custom não é migrado nem regravado: padrões disponíveis também em instalação
existente, sem recriar exemplos removidos ou bloquear por arquivo inválido.
Editor da central informa onde encontrar os novos grupos.

Focados **44 passed**, 2,87 s. `./dev check`: **1162 passed, 2 skipped** headless
(28,75 s), **1441 passed, 2 skipped** Qt (57,80 s). Python 3.14.7, sequencial,
HOME/XDG/TMP/Pulse privados, limites do wrapper mantidos. KDE/Wayland: quatro
cenários de navegação mais seis macros por clique nativo. Desfazer/refazer
alteraram campo próprio; demais combinações chegaram a bindings Qt próprios,
com retorno do foco, sem arquivo/clipboard físico. As quatro associações globais
de Janelas foram conferidas somente por leitura. [Provas e limites](handoff/validation/default-shortcuts-2026-11-02/README.md).

Fôlego substituído pela bandeja e launcher oficial, sem sinais manuais. GUI
**4071137**, starttime **5940425**, widget (2958,549;116,584), 280×275, central
oculta; posição do usuário preservada. Recibo `.scratch/default-shortcuts/replacement.json`.
Revalidar identidade/boot antes de qualquer ação. QA e auxiliar encerrados.
Sem release/merge neste lote; próximo passo é o usuário validar os atalhos nos
aplicativos usados. Outros aplicativos podem remapear combinações.

## Presente verde para tickets de redefinição — 02/11/2026

Incremento sobre `0c1ca41f9c2eb9f75d146b8e0e9cadec8ea510fe`, mesma raiz/branch/PR #1.
Código, testes e provas em `a475b005fb7e0aff1795b4351d99a2eefc773a73`.
Pedido atual: pequeno presente verde piscando com quantidade ao lado das entregas.
Implementado na linha existente de 14 px, mantendo largura de 280 px. Soma
somente tickets confirmados das contas daquele provedor; 9+ no badge e número
exato/contas no tooltip. O clique escolhe uma conta com tickets, preferindo a
padrão. Hover comum continua na padrão; sem resgate ou alteração de cota.

Um timer de 800 ms alterna intensidade sem sumir com o número e para ao ocultar
ou encerrar. Validação única Qt-free, usada por badge/painel/CLI: desconhecido,
futuro, malformado, mais de 15 minutos ou validade conhecida passada não exibem
presente. Corrigido parser que descartava expiração passada de ticket disponível,
perdendo o limite de validade. Suporte visual comum aos quatro indicadores;
atualmente a fonte confirmada de tickets é Codex. Não criar ofertas por inferência.

Focados **43 passed** (2,02 s). `./dev check`: **1151 passed, 2 skipped** headless
(28,95 s), **1429 passed, 2 skipped** Qt (49,21 s). Python 3.14.7, sequencial,
HOME/XDG/TMP/Pulse privados. KDE/Wayland: cinco cenários com dados próprios,
timer real, clique nativo em presente, conta secundária e invalidação, sem
credenciais/resgate ou efeitos em outros clientes. Prova inicial detectou o
min-height do tema cortando o botão; corrigido e coberto. Evidência final aguarda
escala/DeferredDelete antes de fotografar o painel. [Provas e limites](handoff/validation/reset-gifts-2026-11-02/README.md).

GUI real substituída pela bandeja e `./dev gui`, sem sinais manuais: PID **3445610**,
starttime **5247515**, compacto (2804,553;185,362), 280×275, central oculta e
posição do usuário preservada. Recibo `.scratch/reset-gifts/replacement.json`;
revalidar identidade/boot antes de ações futuras. QA e seu auxiliar encerrados.
Sem merge/release; b2 publicado continua imutável. Próximo passo: usuário conferir
o presente nas contas cujas fontes confirmem tickets; demais fontes permanecem
sem aviso em vez de receber contagem inventada.

## Voltar e cabeçalhos sem controles de janela — 01/11/2026

Sobre `c2b67d5c013ecd712fc06f54b67fc6cb54b36399`, mesma raiz/branch/PR #1.
Código, testes e provas em `8494fd57945401dcbbbc8aeeb26e123d9dac3795`.
Pedido implementado nas duas interfaces, conforme hipótese comunicada durante
o lote (pergunta opcional de escopo não recebeu resposta). Central sem barra
nativa de minimizar/maximizar/fechar, com **Voltar** no cabeçalho. Mostra o widget
e oculta a central sem perder a aba/draft nem parar monitoramento. O widget usa
**Central** e **Controles**, com Ocultar widget e Sair do Fôlego. Encerramento
explícito pelo menu ou bandeja; fallback sem bandeja preserva rota de retorno.
Nenhum grant, operação de recursos ou regra persistente do KWin novo.

Verificação: `./dev check` com **1148 passed, 2 skipped** headless (22,62 s).
Qt final `./dev test`: **1424 passed, 2 skipped** (40,24 s); ajuste só visual
do ícone Central seguido de **51 passed** focados (4,50 s). Python 3.14.7,
sequencial, HOME/XDG/TMP/Pulse privados. Guarda de 20 workspaces respeitada;
sessões concluídas revisadas e preservadas em
`.scratch/dev-tests-reviewed/20261101-navigation`, sem remoção ou ampliação.

KDE/Wayland real: quatro casos aprovados, central sem moldura (frame=client no
compositor), Voltar sem bandeja, retorno à mesma aba com worker ativo e saída
por clique nativo em Controles. Menu sem foco usa popup após soltar o botão;
InstantPopup não manteve o menu aberto neste compositor. O primeiro oráculo
`noBorder` era inadequado ao KWin 6.7.4: representa política, não moldura
efetivamente desenhada. Ensaios incompletos preservados, sem virarem aprovação.
[Provas e screenshots](handoff/validation/navigation-2026-11-01/README.md).

Instância real substituída por Sair na bandeja e launcher oficial, sem sinais
manuais ou encerramento de clientes de IA. Nova GUI **1543441**, starttime
**2203999**, compacto (2946,635;121,240), 280×275; posição do usuário preservada,
central oculta. Acessibilidade nativa confirmou Voltar, Central e Controles na
instância nova. Recibo `.scratch/navigation-host/replacement.json`; identidade e
boot precisam ser revalidados antes de qualquer ação futura. Auxiliares de QA
encerrados. Versão não avançada, sem novo release/merge. Próximo passo: validação
do usuário; arraste físico e outro compositor não foram certificados neste lote.

## Apagar em Chromium, opção de captura e sons — 01/11/2026

Sobre `cc2f3bf993d0e49726da399ae16bc6c24c2f39d5`, mesma raiz/branch/PR #1.
Edição corrigida em `6396a527c03e1ed7e44a74a7ce5e8f2e942241ee`.
Captura, sons e gates finais em `c59670d8fcaa9ea65784a1a4cccb89ca1d10a018`.
Chrome próprio reproduziu a falta de EditableText apesar de Text/entry editável.
Agora seleciona o campo exato por AT-SPI, aguarda a seleção inteira, revalida
foco/identidade/tamanho e envia um Backspace. Sem Ctrl+A global, clipboard ou
conteúdo em logs; confirmação trata o terminador de campo vazio. Quatro casos
DOM passaram: contenteditable com estado controlado/textarea, com/sem seleção.

Opções, com rolagem e controles legíveis: **Incluir widget flutuante no print**
marcado por padrão. Desmarcado oculta widget/teclado antes do Spectacle próprio
e os restaura ao fechar/cancelar, inclusive posição confirmada no KWin. Somente
Print do Fôlego; não afeta atalhos/capturas externas. Falha de abertura restaura.

Sons ligados por padrão: quatro melodias de conclusão e três de franquia (20%,
zero, reposição confirmada), preview e opt-out na GUI. Monitor único compartilhado
com central/widget, ativo enquanto o app estiver aberto. Todas as contas;
desconhecido/vencido não cria transição, histórico antigo não toca ao iniciar e
primeira conclusão nativa posterior à abertura ainda avisa mesmo se o provedor
antes era indisponível. IDs deduplicados e fila limitada a sete identidades.

Volume temporário de pelo menos 85%, desmute e restauração por canal/mudo,
preservando ajuste concorrente do usuário. Usa saída já padrão, sem mudar perfil,
serviço ou grants. Intenção privada antes do efeito, servidor/saída/boot revalidados,
registro pendente reconciliado na abertura; desconhecido bloqueia restauração
cega. Registro em `~/.local/state/folego/audio-volume.json`. Código Qt só na UI;
núcleo/CLI continuam independentes. O wrapper de testes agora isola também Pulse.

`./dev check` final: **1148 passed, 2 skipped** headless (29,23 s), **1422 passed,
2 skipped** Qt (52,45 s), Python 3.14.7 gerenciado, sequencial, HOME/XDG/TMP
privados. KDE/Wayland: **11 casos** com captura incluída/oculta, fechamento do
filho Spectacle sem salvar região e retorno do widget/teclado/posição. Áudio:
sete sons reais em PipeWire/Pulse/WirePlumber próprios, saída nula, namespaces,
runtime físico e dispositivos ocultos; canais/mudo originais restaurados.
Leitura somente consulta de recibo na instância real também confirmou restauração
e igualdade com os valores anteriores. Não foi disparado preview físico pelo QA.
[Provas, screenshots, falhas e limites](handoff/validation/editing-capture-audio-2026-11-01/README.md).

GUI substituída por saída normal da bandeja, lock liberado e launcher oficial.
Instância final **1211686**, starttime **1722544**, compacto em (19;132,185),
280×274,815, central oculta; posição escolhida pelo usuário preservada. Histórico
de substituição em `.scratch/capture-sounds/final/replacement.json`; nunca usar
PID deste registro sem nova identidade/boot. Nenhum cliente de IA, agente ou
serviço de áudio/entrada físico foi encerrado. Auxiliares de QA encerrados.

Versão continua posterior à tag v0.2.0b2, sem novo release/merge. Próximo passo:
usuário validar o campo específico do Codex e audibilidade/identidades com
**opções → Testar som**. Provas não certificam todos os clientes, saída física,
imagem final salva ou capturas externas. Limites do motor de recursos permanecem.

## Custom: textos e macros pessoais — 01/11/2026

Incremento sobre `eeba357f287da7a4f18c879d6a8665e810d02954`, na mesma raiz,
branch e PR #1. Código/QA em `2f80a594f27b6d93725c152f0c2e6e12fea02d39`.
Pedido atual implementado: último item **Custom** em Prompts,
submenu de textos/macros e editor na aba **prompts** da janela principal, com
**+ Texto**, **+ Macro**, Salvar, Remover e Atualizar. O exemplo inicial é
literalmente **123**, sem espaços, tanto no título quanto no clipboard.
Macro inicial **Mostrar área de trabalho**; outras macros aceitam um atalho
de teclado. A pergunta opcional sobre comandos de terminal não foi respondida;
adotado o modelo de atalho, conforme o exemplo do usuário. Não há shell.

Configuração própria privada e limitada, defaults só quando ausente, vazio
persistido respeitado, revisão contra gravação concorrente/menu antigo e
arquivo desconhecido preservado. Leitura/gravação/desktop fora do loop Qt.
No ensaio nativo, qdbus transitório desfazia Mostrar área de trabalho ao sair;
corrigido com QtDBus persistente fornecido pela GUI, mantendo core/CLI sem Qt.
Já visível não alterna, efeito enviado uma vez e estado confirmado.

Gates finais: headless **1133 passed, 2 skipped**, 39,93 s; Qt **1402 passed,
2 skipped**, 52,08 s. Python 3.14.7 gerenciado, sequencial, HOME/XDG/TMP privados.
Tentativas anteriores preservadas: deadline variável no teste Hypothesis de
backup (repetição focada passou sem mudar limite) e expectativa antiga das abas,
atualizada para incluir prompts. Workspaces completos revisados/preservados
em `.scratch/dev-tests-reviewed/20261101-custom`, sem excluir fixtures.

KDE/Wayland real: nove casos aprovados, widget 280×275, edição/salvamento em
HOME próprio, contas e teclado com cliques/AT-SPI em campos descartáveis.
Clipboard Xvfb confirmou cópia/colagem exata de 123. Macro desktop e Ctrl+A
acionadas pelo submenu no KWin/Xvfb/D-Bus em namespaces privados, runtime
físico oculto: desktop confirmado, repetição não alterna, seleção do alvo
próprio confirmada. Não minimizou janelas físicas nem reiniciou serviços.
[Provas, screenshots e limites](handoff/validation/custom-prompts-2026-11-01/README.md).

A instância anterior 710222 já estava ausente, sem lock GUI, antes da tentativa
de substituição; nenhum efeito de encerramento foi enviado. `./dev gui` lançado
uma vez, instância **935427** com starttime **1403407**, lock e bandeja confirmados.
Compacto aberto e central oculta; posição atual do compositor apenas limitada à
área útil (604;318,185; 280×274,815), sem alterar regra do KWin. AT-SPI confirmou
o botão Prompts e a nova aba na instância real. Metadados locais e log em
`.scratch/custom-prompts`. Não encerrar PID só por este registro histórico.

Este incremento ainda não integra a tag imutável v0.2.0b2 publicada abaixo;
versão não avançada e sem novo release/merge. Próximo passo: validar Custom
nas aplicações usuais do usuário; publicar outro marco somente com versão,
artefatos e gates de distribuição correspondentes. Demais limites continuam.

## Release 0.2.0b2 publicada e instância substituída — 01/11/2026

[Release v0.2.0b2](https://github.com/Misael-art/Folego/releases/tag/v0.2.0b2),
prévia publicada em **01/11/2026 22:14:25 UTC**, tag/commit exato
`4802b79217390e4b6eb6f350ed0c0ab37a5ae005`. Autorização explícita do usuário
para substituir a versão atual, testar e distribuir. Sem merge. PR #1 existente
atualizado; permanece draft pelas pendências gerais fora deste marco de UI.

Fonte completa (11.505.841 bytes, com dev/uv.lock), wheel (356.243), sdist
(511.498) e SHA256SUMS (281) enviados. Digests GitHub iguais aos locais; os
quatro downloads públicos foram baixados sem autenticação e conferidos por
SHA-256/tamanho; manifesto aprovado e tag remota no SHA esperado.
[Recibo dos assets](handoff/validation/ai-accounts-keyboard-prompts-2026-11-01/release-b2.json),
[downloads](handoff/validation/ai-accounts-keyboard-prompts-2026-11-01/public-downloads-b2.json)
e [CI do tag](handoff/validation/ai-accounts-keyboard-prompts-2026-11-01/ci-b2.json).
Seis checks de código aprovados; CodeRabbit/Sourcery skipped. v0.2.0b1 preservada.

`./dev check` b2: **1113 passed, 2 skipped** headless (25,78 s),
**1378 passed, 2 skipped** Qt (40,00 s), Python 3.14.7 gerenciado, sequencial e
isolado. Wheel: 129 módulos idênticos ao checkout, nenhum arquivo privado;
CLI instalada sem Qt e remoção GUI preservando todos os hashes do HOME de teste.
Qt reaproveitado offline por requisitos com hashes do lock. Wheel final instalado
sem editable/PYTHONPATH passou nos oito casos KDE/Wayland. Contadores por conta,
clipboard isolado e abertura/deduplicação de Print também verificados. Fonte de
runtime `eda22c9` é byte a byte igual ao tag; commits posteriores são QA/docs.

AT-SPI restaurado após autorização e intenção/owner revalidados. GUI anterior
saiu pela bandeja sem sinal manual e liberou o lock. A b2 oficial está aberta no
compacto, na posição anterior (25,39; 280×275 lógicos), com central oculta.
Acessibilidade nativa confirmou sete botões e quatro indicadores visíveis na
instância nova. Nenhum agente, terminal ou sessão de trabalho encerrado;
preferências/grants do produto preservados. Auxiliares de QA encerrados.

Limites: Web/Grok sem fonte de percentual/reset/tickets; Claude sem percentual
atual na observação real anterior. Datas estimadas/pessoais não confirmam cobrança.
O teste de Print cobre abertura e deduplicação, sem salvar região. Não certifica
todos os clientes de destino, arraste físico, login X11, hardware ou outra
distribuição. Motor de recursos, matriz física e pendências gerais permanecem
no escopo anterior; não declarar o produto estável ou o executor automático ativo.
Próximo passo: validação do usuário nas aplicações que utiliza; continuar as
pendências gerais sem alterar a tag publicada. Registros abaixo preservam a
preparação e tentativas históricas; a pendência AT-SPI foi resolvida.

## Recuperação autorizada e preparação 0.2.0b2 — 01/11/2026

Pedido posterior autoriza substituir a instância, validar e publicar nova release.
O AT-SPI foi restaurado por um único reinício da unit registrada, após conferir
owner/PID/starttime e gravar intenção. Endpoint e owner D-Bus voltaram a responder;
nenhum agente/cliente de IA foi encerrado. A pendência abaixo está resolvida.

QA completo KDE/Wayland: hover por ponteiro real, troca de conta, teclado embaixo/
topo/embaixo, cliques A/B em campo próprio, selecionar/apagar via AT-SPI e
C/Shift+D/apagar em editor de outro processo descartável. Contadores 3/5/1,
abertura da padrão preserva 1 entrega da segunda conta e abertura desta conclui
só os avisos Codex, com recibo durável. Lookup de cliente substituído por janela
própria; não certifica todas as aplicações reais. Print abriu Spectacle próprio,
não duplicou pedido e foi encerrado sem salvar região; não prova arraste/salvar.
Clipboard: produção copiou e colou prompt integral em Xvfb próprio sem D-Bus físico.

Versão e lock avançam a **0.2.0b2**. `./dev check`: **1113 passed, 2 skipped**
headless (25,78 s), **1378 passed, 2 skipped** Qt (40,00 s), sequencial e isolado.
Instalação offline inicial sem metadata Qt no cache falhou; com requisitos com
hashes exportados do lock em ambientes novos passou, CLI sem Qt e remoção GUI
preservando todos os hashes do HOME de teste. Python gerenciado, sem downloads
novos. Nove workspaces anteriores foram preservados em revisão; os finais
são `run-fqx12mll` e `run-1i0zasue`.

[Provas e limites](handoff/validation/ai-accounts-keyboard-prompts-2026-11-01/README.md).
O wheel final tem 129 módulos idênticos ao checkout, sem arquivos privados.
Instalado sem editable/PYTHONPATH, passou nos oito casos KDE/Wayland. O harness
agora sincroniza geometria/movimento e confere a superfície própria antes de
clicar; falhas intermediárias de hover foram preservadas. A GUI antiga saiu pela
bandeja, liberou o lock; b2 oficial foi aberta e deixada no compacto na posição
anterior (25,39; 280×275 lógicos), sem sinal manual e sem encerrar clientes de IA.
SHA do tag, checks remotos e URL do release serão registrados após publicar. Sem merge; o executor automático de
recursos e a matriz física geral continuam nos limites anteriores.

## Contas, teclado por clique e biblioteca de prompts — 01/11/2026

Código: `3aae6c9692b2b5b312561e7a90cd8b4e01778f5b`, sobre `b5e400330495d1ca42985f519b4c5044ab07de2e`,
mesma branch e PR #1. Pedido atual: contas padrão/adicionais, painel legível,
teclado que digita nos campos e prompts robustos para copiar. Inventário nativo
compartilhado por cotas/entregas/abertura; registro opcional PhaseZero somente
leitura para labels e raízes, sem importar/executar o outro projeto. Inclui
perfis inativos, preserva Web local coexistente e exclui arquivados automáticos.
Referência mensal e recibos passam a respeitar a conta selecionada; abertura
sem vínculo comprovado não cai no perfil de outra conta. Neste host: três
Codex e três Web; as três Codex retornaram cotas/tickets. Web/Grok continuam
sem percentual verificável; Claude não retornou cota atual nesta observação.

Hover abre painel interativo com padrão primeiro, seletor à esquerda, consumo
em destaque, tickets/assinatura próximos ao topo e resets por janela. Widget
mantém 280 px. **Prompts**, junto de selecionar/apagar, oferece 11 textos de
boas práticas genéricos; escolher copia, sem colar/enviar automaticamente.

Clique real reproduziu o teclado tomando foco (texto vazio), lacuna do teste
anterior que apenas chamava o envio da tecla. Regra própria KWin restrita a
app-id/título do teclado, preparada em worker, impede foco. Confirmação nativa
inclui posição em pixels físicos e recusa de foco; sem ela, teclas não são
enviadas. QA real passou com A/B em campo próprio e C, Shift+D e apagar em
editor de outro processo descartável, sem o teclado ficar ativo, inclusive no
topo. Nenhuma permissão/serviço de entrada novo. Prompts também foram copiados
e colados integralmente em Xvfb próprio; clipboard físico não foi fixture.

`./dev check` final: **1113 passed, 2 skipped** headless (18,19 s),
**1378 passed, 2 skipped** Qt (33,00 s), Python 3.14.7 gerenciado, sequencial,
HOME/XDG/TMP privados. Sete workspaces concluídos foram revisados e preservados
integralmente em `.scratch/dev-tests-reviewed/20261101-ai-ui`, sem descarte nem
ampliação dos limites. [Evidências/manifesto](handoff/validation/ai-accounts-keyboard-prompts-2026-11-01/README.md).

**Pendência de reparo do ambiente causada pelo QA:** ensaios exploratórios de
Xvfb/D-Bus privados iniciaram o daemon antes de isolar seu ambiente de ativação.
Um subserviço adotou o pathname físico `/run/user/1000/at-spi/bus_0`; o owner
original `at-spi-dbus-bus.service` permaneceu vivo, mas novas conexões ficaram
recusadas. A tentativa Wayland posterior confirmou hover por ponteiro real e
teclas, depois recusou selecionar/apagar por indisponibilidade AT-SPI. Não é
aprovação integral nem se soma a tentativas anteriores. Autorização específica
foi pedida via pergunta assíncrona para `systemctl --user restart
at-spi-dbus-bus.service`; **aguardar resposta antes do reinício**. Não executar
novamente os ensaios exploratórios. O verificador dedicado de clipboard usa
D-Bus desconectado e Xvfb próprio; passou sem acessar esses canais físicos.

Instância real anterior do Fôlego preservada enquanto o reparo aguarda resposta;
não declarar reabertura da versão nova. Próximo passo: com autorização, conferir
owner/identidade, restaurar somente a unit registrada, validar seu endpoint,
repetir o fluxo Wayland em campos próprios e só então sair/reabrir Fôlego pela
bandeja nativa. Não reiniciar sessão, clientes de IA, agentes, drivers ou outros
serviços. Sem novo release/merge; v0.2.0b1 continua no código anterior.

## Comparação com PhaseZero e contexto Claude — 01/11/2026

Código: `ae87aaad7e751c9151cbbd601fd8b4e2032d9c4c`, sobre
`64313445e25f9fff4d932b2dc702889e0f7a77b6`, mesma branch/PR #1. O usuário
indicou `/home/misael/Projects/PhaseZero/` como referência da solicitação de IAs.
Comparados quota_meter.py/tray e handoff na revisão PhaseZero `53d62e2d`:
Web conta mensagens locais de 3/24 h; Grok usa dia mensal informado. Não há ali
fonte adicional de percentual de franquia desses serviços. Alterações existentes
do outro projeto foram preservadas; Fôlego não depende dele em execução.

Adaptada a identidade do cache Claude aos metadados nativos `oauthAccount`:
conta/organização em `~/.claude.json`, além da credencial/diretório. Baseline
reproduziu 90% de A herdados por B (esperado 40%) com o mesmo token. Contexto
alterado agora descarta uso/perfil anteriores e respostas durante a troca;
metadata ilegível bloqueia reutilização. Retry-After continua válido para o
mesmo token, inclusive A → B → A, sem compartilhar a cota entre organizações.

`./dev check` final: **1099 passed, 2 skipped** headless (18,25 s),
**1360 passed, 2 skipped** Qt (32,86 s). Suítes sequenciais, Python 3.14.7,
HOME/XDG/TMP privados; conta/organização reais não foram trocadas para QA.
Quatro novas regressões e reprodução da base com fonte imutável do Git.
[Evidências e limites](handoff/validation/ai-details-editing-2026-11-01/README.md).

A inspeção do plugin AT-SPI não respondeu e foi cancelada antes de qualquer ação.
Reabertura pela bandeja nativa/DBusMenu com owner/PID conferidos: **Sair** encerrou
GUI e seu próprio auxiliar de entrada normalmente, com liberação do flock e sem
sinais. Nova GUI oficial deixada no modo compacto, posição dentro da tela.
Nenhum agente/serviço alheio encerrado; regras KWin e grants preservados.
Web/Grok e validação física por aplicação continuam nos limites abaixo.
Sem novo release/merge; a prévia v0.2.0b1 continua no código anterior.

## Hover das IAs, edição de campo e saída real — 01/11/2026

Código: `079d39e08a2b8261649a36152cf3a50959ffc33b`, sobre
`cb7857479c71c89dc4aa70ebdfce2d26a93708cd`, na branch/PR #1 existentes.
Pedido do usuário: corrigir dados do hover, manter contadores/abertura das IAs,
acrescentar Selecionar tudo/Apagar tudo e reabrir para validação. O trecho final
da transcrição foi considerado conversa incidental.

Widget sem foco habilita agora dicas em janela inativa. Codex consulta GETs
de uso/tickets do próprio provedor, com credencial existente válida, sem refresh
ou resgate; fallback local continua limitado. Descobre/deduplica diretórios
nativos ativos no HOME selecionado. Hover separa uso e reposição com contagem
regressiva, tickets/validade, créditos extras e referência mensal. Botão direito:
atualizar, detalhes com rolagem, referência mensal pessoal persistente e site.
Dias 29–31 respeitam meses curtos; referência não confirma cobrança.

Claude inclui uso extra/perfil quando disponíveis. Mensalidade pelo início da
assinatura ativa é estimativa identificada. Cache em memória com chave de
credencial/diretório, uso por 5 min e perfil por 6 h; HTTP 429 respeita
Retry-After, sem encurtar espera superior a uma hora. Revalida conta, validade
e reset inclusive na CLI. Nenhum token/conversa é persistido nesse cache.
**Limite remanescente:** Web/Grok continuam sem percentual/reposição/tickets
verificáveis nas fontes desta integração; campo desconhecido e link para
consultar o provedor. Não declarar completas todas as funções dos quatro serviços.
No host, Codex retornou janelas/tickets em três raízes; Claude respondeu HTTP 429
na consulta de uso posterior à leitura do perfil. Sem contornar ou ignorar o limite.

Dois botões finos, largura preservada em 280 px. AT-SPI de produção altera
somente o campo editável em foco, com proprietário/identidade/estado/tamanho
revalidados. Não lê conteúdo, toca clipboard ou substitui a edição por atalhos
globais de terminal. Aplicação sem interface editável informa indisponibilidade.
Também corrigida a saída: central oculta + widget Tool não encerravam o loop Qt;
o shutdown normal agora solicita `QGuiApplication.quit()` explicitamente.

`./dev check` final: **1095 passed, 2 skipped** sem Qt (20,83 s),
**1356 passed, 2 skipped** Qt (39,30 s), Python 3.14.7 gerenciado, sequencial,
HOME/XDG/TMP privados. Skips seguem exigindo Edge real. KDE/Wayland próprio:
evento de ajuda Qt mostra os campos, teclado embaixo/topo/embaixo e edição de
texto em campo próprio sem perder foco. Teste de saída reproduziu a falha antes
e saiu sem watchdog após a correção. Wrapper de QA remove agora as três
variáveis de caminho nativas dos provedores; HOME privado não adota HOME físico.
Falhas intermediárias e workspaces revisados preservados integralmente, sem
remover regressões ou afrouxar limites. [Evidências](handoff/validation/ai-details-editing-2026-11-01/README.md).

A instância antiga fechou o widget, mas manteve o processo/lock pelo defeito
reproduzido. SIGTERM único por pidfd após conferir argv/starttime; flock liberado.
Nova GUI oficial aberta, modo widget acionado por AT-SPI, botões e novos campos
confirmados visíveis, posição ajustada à área disponível sem mudar regras KWin.
Fôlego deixado aberto para validação. Nenhum agente/terminal encerrado, grant ou
opção de início alterado. Sem novo release/merge; v0.2.0b1 permanece anterior.
Próximo passo: validação física do usuário no hover e nos campos das aplicações
que usa; não presumir cobertura de todos os clientes nem do compositor X11.

## Avisos de entregas e Fôlego reaberto — 01/11/2026

Implementação: `91125ecb4417293f8fdf4f9773b9ea0c7009f3c5`, sobre
`c9d1af66b0466ed751f718cbbde231d444b67d33`, na mesma branch/PR #1. Pedido
posterior do usuário autoriza os contadores e o encerramento/reabertura somente
do Fôlego para validação. Nenhuma aplicação de agente ou terminal foi encerrada.

O widget conserva 280 px de largura e acrescenta 14 px acima das franquias:
contagem por sessões principais concluídas, desde a primeira ativação do novo
monitor, deduplicada e persistente. Fontes nativas Codex/Web, Claude e Grok,
worker separado a cada 5 s; ferramentas/subagentes não contam. Ausência de
evidência aparece como `?`; mínimo positivo parcial como `2+`. O próximo pedido
retira o aviso antigo; nova conclusão gera novo aviso. Recibos em hash próprios,
sem conversas/credenciais. Estado desconhecido não é substituído.

Clique abre a aplicação desktop ou seu terminal ancestral identificado, com
revalidação de PID/starttime e confirmação de foco antes de marcar somente os
avisos exibidos como vistos. Falha preserva a contagem; conclusão posterior ao
clique permanece. Nenhum comando é enviado aos agentes. Um atalho nativo pode
ser aberto uma vez quando não há janela identificada. Não seleciona conversa
ou aba interna. Dependências e orçamentos no [guia](COMPACTO.md).

`./dev check` no código final: **1079 passed, 2 skipped** headless (20,57 s) e
**1339 passed, 2 skipped** Qt (37,21 s), sequenciais, Python 3.14.7 gerenciado,
HOME/XDG/TMP privados. Skips ainda exigem Edge real. KDE/Wayland real: sessões
sintéticas 2/5/1, clique do widget → foco de janela própria → recibo persistente,
sem apagar avisos dos demais provedores. A busca de produção somente leitura
encontrou janelas locais dos quatro provedores; o foco real de cada um fica para
validação do usuário. Tentativa inicial sem isolamento de `CODEX_HOME` preservada
e roteiro corrigido. [Evidências e limites](handoff/validation/agent-deliveries-2026-11-01/README.md).

A instância antiga, oculta e sem SNI registrado, não respondeu à saída AT-SPI.
Após conferir identidade/argv, SIGTERM único por pidfd e liberação de flock
confirmada; `./dev gui` lançou a atual uma vez. Modo widget acionado pela GUI;
AT-SPI confirmou os quatro indicadores novos visíveis. Fôlego deixado aberto
no HOME real para o usuário validar, sem mudar grants ou opções de início.

Este incremento pertence ao código/PR; **v0.2.0b1 continua apontando ao código
anterior**. Sem novo release ou merge nesta rodada. Limites gerais e próximos
contratos pendentes abaixo permanecem. Os workspaces de QA próprios concluídos
foram preservados integralmente quando revisados para retenção, sem afrouxar
orçamentos. Próximo passo: validação do usuário no widget deixado aberto.

## Widget compacto, monitor de IAs e prévia publicada — 01/11/2026

Implementação: `5ce16b1c05001ad3552c3cd26cd30ccdbfc73f63`, na branch
`codex/portable-handoff-20261024`. O usuário aprovou os mockups e autorizou
implementação, commit, push, PR e release nesta rodada. Essa autorização permite
esta prévia de distribuição, sem merge ou ampliação de grants/automação.

Entregue: widget de **280 × 216 px** no estado normal, controles de janela no
cabeçalho, recursos em duas linhas, faixa de IAs com detalhes por hover e abas
coloridas Copiar/Colar/Print/Teclado. A aba abre sempre embaixo; só a seta abre
no topo. Teclado próprio sem foco, posição confirmada pelo KWin e auxiliar de
entrada transitório próprio quando o host já permite uinput. Copiar usa
Ctrl+Insert, evitando Ctrl+C que interromperia tarefas de terminal. Captura abre
seleção de região do Spectacle e preserva a instância em andamento.

IAs têm coleta própria, independente do PhaseZero, também disponível em
`folego ai status --json`: Codex local e Claude por endpoint de uso de primeira
parte. Orçamentos de leitura, descarte por troca de conta, falha e vencimento;
reset passado não significa cota cheia. Web/Grok sem percentual confirmado
ficam desconhecidos. Token presente não prova renovação válida; não há refresh
ou cópia/gravação de credenciais. Consulte [configuração e dependências](COMPACTO.md).

Validação neste host: `./dev check` **1061 passed, 2 skipped** headless (18,47 s)
e **1320 passed, 2 skipped** Qt (34,04 s). Após tipografia final, nova suíte Qt:
**1320 passed, 2 skipped** (32,88 s); foco de 63 casos aprovado. Skips exigem
Edge real. Corrigido o isolamento do teste antigo de tuning que ligava o
argumento padrão antes do monkeypatch; produção não perdeu nenhuma proteção.

KDE/Wayland real: embaixo → topo → embaixo, geometria fracionária e digitação
em campo próprio. X11 privado: entrada, copiar/colar e Spectacle. Bootstrap
oficial: central → widget → central → saída, exit 0, HOME/XDG próprios e
systemctl simulado. Wheel instalado sem modo editable, CLI sem Qt e GUI com
runtime Qt 6.12.0 já gerenciado. Consulta real Codex/Claude aprovada somente
leitura; nenhum metadado de conta publicado. Tentativas falhas foram preservadas,
com correções de IPC curto, pixels fracionários e encerramento explícito de Qt.

[Release **v0.2.0b1**](https://github.com/Misael-art/Folego/releases/tag/v0.2.0b1)
publicada como **prévia** em 01/11/2026 14:04 UTC, tag/SHA remoto conferidos:
`5ce16b1c05001ad3552c3cd26cd30ccdbfc73f63`. Assets: fonte completo, wheel,
sdist e SHA256SUMS; tamanhos e digests SHA-256 remotos comparados aos locais.
O fonte completo de 11.072.417 bytes foi revisado como artefato de distribuição,
sem cache, estado ou credenciais; não virou blob novo do Git. A CLI/GUI do wheel
foram verificadas fora do checkout; dependências grandes não foram baixadas.

CI desse SHA: **seis jobs de código success**, CodeRabbit/Sourcery skipped.
PR de continuidade [#1](https://github.com/Misael-art/Folego/pull/1) reutilizado,
ainda draft, sem merge. Este registro posterior conserva o mesmo código da tag.
[Logs, capturas, comparação visual, recibos e limites](handoff/validation/compact-ui-2026-11-01/README.md).

Limites: esta prévia não resolve os quatro defeitos de contrato da avaliação
abaixo, nem certifica hardware/login/transições, todas as aplicações de destino
ou soak desta revisão. O executor automático de recursos permanece desligado.
A sessão de trabalho e os serviços reais não foram reiniciados para QA; reabrir
o Fôlego carrega a interface nova. Workspaces de QA concluídos revisados foram
preservados integralmente em `.scratch/dev-tests-reviewed`, sem apagar fixtures
ou aumentar limites. Próximo incremento recomendado continua sendo o P1 da cauda
do diário e os demais contratos abaixo, com regressões e aceite próprios.

## Avaliação de filosofia, contratos e oportunidades — 01/11/2026

Base examinada: `6732c4e140d714d2e06a7f95a2a44a0747823fbe`, conferida na
branch remota `codex/portable-handoff-20261024`; working tree inicialmente limpo.
Pedido de entendimento e avaliação, sem correção de código de produção nesta
rodada. As correções de 29/10 e o soak controlado de 30/10 foram considerados;
os achados históricos já corrigidos não foram reapresentados como bugs atuais.
PR #1 conferido aberto/draft, sem merge, com a mesma branch/SHA. Checks da base:
seis jobs de código `success`; CodeRabbit e Sourcery `skipped`. Esse estado remoto
não substitui a suíte local impedida pelo orçamento de QA descrito abaixo.

Propósito observado: tornar a pressão de recursos compreensível e permitir
intervenções revisadas que preservem trabalho e recuperação. A supervisão de
entrada amplia esse propósito para a continuidade do desktop, com owner e
autorização próprios. A arquitetura separa coleta/decisão de Qt, usa o
coordenador comum e conserva a distinção entre recusa, efeito parcial e resultado
desconhecido. O executor automático de recursos continua desligado.

Achados atuais, reproduzidos em memória com I/O e efeitos externos simulados:

1. **P1 — diário aceita cauda JSON sem terminador e autoriza novo executor.**
   `orchestration/journal.py:Journal.load` usa `splitlines()` sem recusar a última
   linha sem `\n`, ao contrário de `HistoryReader`. Uma escrita interrompida após
   o JSON e antes do terminador é aceita sem problemas; o próximo append cola
   dois objetos na mesma linha. Prova pelo `Coordinator.run`: diário inicial
   com um registro aceito, executor chamado, resultado `desconhecido` e diário
   final com JSON ilegível. Caminhos diretos pelo coordenador podem atingir o
   efeito sem uma intenção novamente interpretável. Recusar a cauda antes de
   qualquer append/efeito; cobrir a fronteira com regressão no coordenador.
2. **P2 — swap ilegível ou malformada é apresentada como ausente e válida.**
   `core/procfs.py:read_swaps` retorna lista vazia em falha e ignora linhas
   inválidas; `core/collector.py` marca a fonte `ok` apenas porque o arquivo
   existe. Nas duas provas: total/uso zero, qualidade `ok`, saúde `green` com as
   demais métricas normais. O card de swap apresenta “sem swap/zram”. Diferenciar
   inventário vazio comprovado de erro/parcialidade até a apresentação.
3. **P2 — corrida pode contrariar a preferência de início do monitor.**
   `startup.py:configure` solta a trava após salvar preferência/autostart e antes
   de instalar/desabilitar a unit. Prova com duas threads e serviço simulado:
   habilitação pausa antes de instalar; desabilitação termina; habilitação
   antiga retoma. Resultado: preferência false, `Hidden=true`, monitor habilitado
   e ambas as chamadas com `sucesso`. Serializar/revalidar também a etapa da unit
   para que uma escolha anterior não se sobreponha à preferência mais recente.
4. **P2 — reconciliação não arquiva revisão cujo resultado já está no diário.**
   Se o executor cai após gravar o resultado e antes de `_close`,
   `orchestration/review.py:reconcile` retorna o resultado conhecido sem encerrar
   o bundle `started`. Prova: sucesso devolvido e `_close` não chamado. A revisão
   deixa de aparecer em `pending()`, mas continua ocupando a pasta limitada a
   256 entradas em `prepare`. Finalizar o recibo de modo idempotente, preservando
   evidência e conflitos; consultar/reexecutar o mesmo ID não deve vazar slots.

Lacunas/oportunidades de produto e operação:

- “Resolver agora: memória” apenas solicita `memoria`, mapeada para a própria
  central; falta uma investigação útil como próximo passo. Concluir “Dar fôlego”
  preservando análise → mesmo plano/ID → confirmação → verificação → recuperação.
- O motor de saúde usa sobretudo RAM/PSI de memória e tmpfs; CPU e PSI de I/O
  já são coletados, mas não compõem o veredito. Tornar explícito o alcance do
  indicador e desenvolver diagnósticos desses recursos com evidência.
- Algumas sugestões prometem alívio ao fechar Edge/limpar `/tmp` apenas a partir
  de PSI alto. Vincular a orientação ao consumidor medido e distinguir hipótese
  de efeito verificado, sem ampliar grants ou habilitar automação de recursos.
- Retenção própria já existe, mas a passagem registra zero movimentos no ensaio
  com consumidores reais por observação incompleta. Fechar esse aceite e a
  recuperação de capacidade sem ignorar consumidores, adotar fixtures ou apagar
  estados desconhecidos. O diário autoritativo ainda é relido integralmente em
  consultas/appends; o leitor incremental de apresentação não resolve esse custo.
- A passagem conserva uma tabela histórica de “próximos incrementos” com itens
  posteriormente atendidos. Distinguir um resumo vigente do histórico para
  reduzir retrabalho; matriz física de entrada/desktop continua pendente.

Validação desta avaliação: quatro categorias de prova (duas variantes para
swap), usando `.dev/venv-headless/bin/python` 3.14.7, mocks e estado em memória;
nenhum efeito real de arquivo de usuário, systemd, processo alheio ou compositor.
`./dev test-headless tests/test_orchestration_journal.py
tests/test_snapshot_quality.py tests/test_session_resilience.py` foi recusado
**antes de coletar testes**, pelo teto preexistente de **20 workspaces de QA**.
Não se elevou limite, removeu evidência nem substituiu essa suíte por pytest fora
do wrapper. Espaço observado antes: 187 GiB livres, 4,1 GiB de RAM disponível;
nenhuma operação pesada foi iniciada. As provas em memória não certificam efeitos
reais nem uma correção. Revisão documental e `git diff --check` são os gates deste
incremento. Próximo lote recomendado: corrigir o P1 do diário e os três P2 com
regressões focadas, após revisão apropriada da capacidade de QA existente.

## Teclado virtual e tela de toque (30/10, tarde)

Contrato confirmado pelo operador: **só o toque na tela abre o teclado**; clique
pelo trackpad continua funcionando como ponteiro e não abre o painel. Tentativa
de modo 2 (abrir ao clicar) foi revertida em PhaseZero `a32add23`; KWin observado
em `mode=1`, kwinrc=1. Card do Fôlego indica quando, sem touchscreen, o clique não
abre (`degraded`, sugere Abrir teclado).

Causa da ausência do toque: `FTS3528:00` existe no ACPI/I²C, mas sem driver;
`i2c_hid_acpi` carregado e `AMDI0010:01` repete `controller timed out` desde o
boot (IRQ 11 com 4 interrupções; `AMDI0010:00` registra `lost arbitration`). Visto
também nos boots de 30/10 09:06 e 12:15. `intremap=off` existe no GRUB desde
julho; sem prova de relação, boot não foi alterado. O ID incerto
`58176bdf86c94e759e43f661630c5ce8` continua bloqueando repetição de reset I²C.
Próximo passo: desligamento completo pelo operador (não reinício), conferir
`FTS3528` em `/proc/bus/input/devices`; se persistir, comparar com boot SteamOS
para separar hardware de kernel. Gates: `./dev check` 1038/1292 passed.

## Retomada prioritária: incidente de entrada e autenticação sem dock

Base Fôlego `acbe99ee182d6a8bb00f98d5489fe194c1272672`. Cards agora são botões,
com habilitação manual por capacidade, resultado vinculado ao ID, verde só por
configuração verificada e amarelo em conflito/falha. Habilitar tudo, verificação
com horário/resumo e registro persistente ficam fora da rolagem. CLI/GUI usam o
coordenador existente, recibo de etapas, revalidação e consulta sem reaplicar.

Integração opcional PhaseZero: `reconcile-input` evita restaurar áudio ao clicar
em uma entrada; recuperação FTS delegada somente ao helper dedicado. Orçamento
manual de hardware usa os mesmos 60 s/três por hora. Abertura explícita de teclado
é permitida como escape durante pendência anterior, sem liberar seu ID. O pedido
de senha sem teclado relatado pelo operador motivou `recover-touch`/`persist-touch`:
confirmam teclado visível, mantêm modo temporário na troca de foco e restauram
após a autenticação; watcher cede pela trava comum. PhaseZero publicado em
`9ebb6487f036d052ddfa7837bc4200d2bfbfa63a`, PR #129, sem merge/release.

Host: teclado virtual visível confirmado pelo KWin, inclusive com ID de reparo
incerto; retorno ao modo 1. FTS continua ausente após reset dedicado e novo
timeout I²C. Tentativa posterior do operador sem dock perdeu autenticação e
terminou desconhecida (`58176bdf86c94e759e43f661630c5ce8`): preservar ID, não
repetir hardware nem declarar que nada ocorreu. Campo de teste não grava texto.
Cinco identidades habilitadas foram salvas; autostart continua true. GUI oficial
reaberta por saída semântica; monitor próprio e owner atualizados, Steam/RetroFE
preservados. Digitação no polkit sem dock ainda precisa de aceite do operador.

Gate final `./dev check`: **1037 passed, 2 skipped** headless (29,94 s),
**1291 passed, 2 skipped** Qt offscreen (50,21 s). PhaseZero focal **22 passed**
(6,37 s), runtime compatível gerenciado; wrapper core indisponível. Uma tentativa
intermediária falhou por deadline flutuante de backup; falha preservada, sem
relaxar limite. QA Wayland própria com efeitos simulados: cards/Tab/Espaço,
800×600/1280×800, estados e resumo; não homologa toque/login/auth física.
[Relatório, capturas e alcance](handoff/validation/accessibility-incident-2026-10-30/README.md).

Próximo aceite: operador confirmar teclado e digitação sem dock; investigar FTS
sem reiniciar a sessão de trabalho para QA, mantendo pendência desconhecida até
prova de término/revisão apropriada. O soak histórico abaixo não aprova esta nova
implementação. Limites do executor automático de recursos continuam inalterados.

Checkpoint de produto publicado: `617c2ad3b6ab3982094a261a1f0a8f2bdcd05bbd`,
SHA remoto conferido na branch padrão; PR #1 atualizado e ainda draft. CI desse
SHA: seis jobs de código success; CodeRabbit/Sourcery skipped. Repositório público
e MIT conferidos. PhaseZero `9ebb6487` remoto conferido, PR #129 atualizado;
CI ainda em andamento no último marco (a base tinha falha ShellCheck 0.9).
Esta nota posterior muda somente documentação/metadados de validação. Nenhuma
pendência física ou incerta foi liberada para obter esse checkpoint.

## Registro histórico: resiliência e início com a sessão

Base deste incremento: `26b1567db77648c7a8a0fdbc4c41bd0884cbb2ac`. O usuário
autorizou todas as recomendações da revisão posterior de entrada e pediu uma
opção de início com a sessão **ligada por padrão**. O estado abaixo substitui
as pendências históricas equivalentes, sem promover aceites físicos antigos.

- **Opções:** sétima aba, preferência durável e autostart XDG gerenciado;
  sincronização da unit própria de observação no login. Desligar persiste após
  reabrir; a implementação atual para a unit própria imediatamente, sem encerrar
  a central aberta. Entradas/units pessoais são
  preservadas. Nenhum grant de reparo/recursos é ampliado pelo início automático.
- **Leases:** limite de 32 considera participantes ativos; liberações validadas
  saem para recibos fechados. `accessibility lease-run` registra filhos antes
  de abrir o gate do comando; conclusão incerta preserva a propriedade, inclusive
  se o launcher morrer. PhaseZero continua opcional.
- **Temporários próprios:** manifesto ligado à raiz/diretório e processo/sessão;
  somente encerrados certificados, com ausência de consumidores/referências comprovada,
  podem ir por rename a `.retained`. Payloads não são apagados, legado/ambíguo
  permanece protegido. Cap 256, inventário limitado e orçamento de 1 GiB
  permanecem; esgotamento exige revisão. Não é retenção integral de dados do host.
- **Revisão e recuperação:** ajustes, tmpfs release/restore/expire/recover e
  disco restore/purge usam o mesmo plano durável confirmado e ID no pai, com
  evidência dos alvos/conteúdo e validação no coordenador existente. A aba
  opções consulta IDs, reapresenta revisões após reabrir e cancela somente as
  não iniciadas. Timeout não permite retry cego; o recibo encerra só o ID correto.
- **Monitor:** índice incremental limitado das pendências, sem apagar o diário;
  corrupção/parcialidade bloqueia. Alertas locais para serviço ausente,
  disjuntor e espera prolongada; anel de 32 transições. Frescor usa CLOCK_BOOTTIME
  para incluir suspensão. Esses registros não certificam movimento/toque físico.

### Validação desta rodada

Python 3.14.7 e Qt 6.12.0 gerenciados por `./dev`, HOME/XDG privados, suítes
sequenciais. Gate `./dev check`: **1014 passed, 2 skipped em 27,07 s** sem Qt;
**1263 passed, 2 skipped em 44,15 s** Qt offscreen. Foco final de 34 casos
passou em 6,07 s. Dois skips por perfil exigem Edge real, ausente nas fixtures.
Após corrigir o corte do rótulo em foco, repetição Qt: **1263 passed, 2 skipped
em 42,34 s**. Logs e resumo portátil em
`handoff/validation/session-resilience-2026-10-30/`.

Após o soak, incluída regressão do ciclo real do QProcess com boot observado:
somente o teste e a documentação mudaram; produto/harness permaneceram no SHA
congelado. Suíte Qt final **1264 passed, 2 skipped em 42,15 s**
(`run-nv7a7fry`), incluindo registro, sessão e certificação do término do filho
próprio com `/proc` real. O log GUI publicado corresponde a essa última suíte.
Consulta de retenção na raiz desse filho descartável, com inventário real de
consumidores/referências: **zero movidos**, pois a propriedade de consumidores
não pôde ser comprovada neste host. Preservação correta, sem ampliar permissões
ou ignorar processos; recibo em `retention-real-proc.json`. Isso não homologa
arquivamento efetivo com todos os consumidores reais presentes.

QA KDE/Wayland própria: 800×600 e 1280×800, navegação por Tab, início ligado,
desligamento persistido após reabrir, aplicação/restauração real de arquivo
descartável pelo protocolo de revisão, ID apresentado e revisão reapresentada/
cancelada sem efeito. Launcher oficial vivo por 5 s em HOME privado; encerrado
somente o processo próprio. `systemctl` da QA foi simulado para não tocar units
do host. Evidência local final em `run-review-20261029/session-resilience-native-6/`.

Falhas corrigidas e preservadas: primeira rodada focada 176 pass/6 fail;
confirmação Qt com botão padrão incorreto no gate intermediário
(`run-oix0iopc`, 1261 pass/1 fail/2 skip); QA nativa 1 com alvo de harness
incorreto e 3 com callback Qt após destruição do widget. Repetições finais
passaram após correções, sem relaxar orçamentos nem somar tentativas.
Logs/run.json das suítes passadas regeneráveis foram preservados antes de
retirar apenas seus diretórios temporários; teto de 20 sessões inalterado.

### Ativação e próximos aceites

Executado `./dev run startup enable --confirmar --json` neste host: preferência
true, desktop entry gerenciada `Hidden=false`, serviço `enabled`/`active`,
FragmentPath próprio. Reiniciada somente a unit do Fôlego para carregar a versão
validada. Política de entrada preexistente preservada, baseline vazio, ciclo
waiting pelo PhaseZero ativo; nenhum reparo físico provocado. O executor de
recursos continua desligado. O comando `startup status --json` confere a escolha.

**Soak aprovado:** 7200,057 s contínuos, fonte congelada, mesmo orçamento
preexistente, 120/120 workers, 20/20 cancelamentos, 80 intenções/resultados
válidos, arquivo restaurado e nenhum filho restante. CPU UI+filhos 1,65% de
um núcleo, pico de RSS +0,49 MiB, FD +5, widgets +8, heartbeat p99 ≤5 ms e
máximo 197 ms, leitura 138,20 MiB/h e escrita 33,83 MiB/h, dentro dos limites.
Não se somaram tentativas. [Relatório, amostras e alcance](handoff/validation/session-resilience-2026-10-30/soak/README.md).

A matriz física (boot/SDDM, logout/login, suspend/resume, dock,
Steam, leitor de tela e toque) permanece pendente: não suspender/desconectar
o host de trabalho para produzir prova. Integração de writers interessados
usa o protocolo opcional; não se altera aplicações de terceiros automaticamente.

Limite do harness de soak: o `/proc` sintético contém montagens mas não boot ID.
Os manifests de jobs ficam conservadoramente não certificados nesse ambiente;
o ensaio mede GUI/workers/cancelamentos e não homologa retenção contínua.
Um teste separado de identidade/término usa filho próprio e `/proc` real.
Na metade do ensaio havia 24.316 KiB de VmSwap: queda de RSS pode envolver
paginação e não comprova liberação de heap nem ausência de vazamento.

Demais pendências de produto: concluir “Dar fôlego”, política integral de
retenção/expiração revisada, limites restantes de coleta/cancelamento e
compactação autoritativa do diário. A leitura incremental do monitor não é
compactação nem substitui revalidação na execução. Sem merge/release neste lote.

Checkpoint publicado: `a65b5f7f822ea55c520ad8e6b8598a00df741c5e`, SHA remoto
conferido na branch padrão `codex/portable-handoff-20261024`. PR #1 atualizado,
repositório público e MIT confirmados. CI desse SHA: seis jobs de código success
(push + PR); CodeRabbit/Sourcery skipped. O soak está identificado por
`run-review-20261029/soak-resilience-7200/launch.json`, com boot/starttime e hashes
de fonte/política. `tools/watch_soak.py` observou apenas esse processo, sem sinais
ou retry, e encerrou com análise aprovada. Fonte do produto congelada nesse
SHA durante todo o ensaio; alterações documentais/testes posteriores não a modificam.

## Ponto de retomada

Projeto Linux/KDE, Python 3.14.7 + PySide6. CLI independente de Qt. O objetivo é
manter uma máquina com agentes e aplicações responsiva sem perder trabalho,
inventando o mínimo possível sobre recursos ausentes e preservando recuperação.

Base histórica: `61179f55123b44a996aa6087d124474eb5e84b1e`. A entrega posterior
estava quase toda no working tree; esta migração preserva esse material em Git,
sem reset, limpeza ou redução de escopo para fazer os testes passarem.

Leia `AGENTS.md`, `docs/DIAGNOSTICO-2026-10-24.md` e `docs/NOVO-HOST.md`.
Depois execute `./dev check`. Não depender do antigo `/home/misael`, venv,
serviços, arquivos de anexos ou da disponibilidade deste host.

## O que está integrado

- Coordenação de mutações de disco/tmpfs/ajustes/processos, intenção antes do
  efeito, IDs, planos v2 imutáveis com prazo e consulta por operação.
- Proteção fresca de sessões/exclusões/ancestrais, boot/PID/starttime e
  acompanhamento de SIGTERM. A GUI de produção pede sinais por QProcess.
- Frescor/qualidade de saúde, histórico em worker com leitura limitada e
  feedback de parcial/desconhecido sem converter isso em recusa sem efeito.
- Inventário protegido de fixtures pytest, runtime por UID e temporários
  privados de filhos em destino verificado. Não há arquivamento automático.
- Central e compacto parciais: fallback decorado Wayland, botões acessíveis,
  ciclo de vida sem bandeja corrigido, pausa antes da primeira leitura e
  bandeja mostrada na abertura. Launcher absoluto testado via GIO.
- Bootstrap portátil com versões fixadas, ambientes GUI/headless próprios e
  testes com HOME/TMPDIR isolados. É suporte de desenvolvimento, não autostart.

F0/F1 preservados; F2/F3 avançados, F4/F5 parciais, F6 desligado, F7 protegido/
somente leitura, F8 parcial. Não promover essa classificação a “produto concluído”.

## Próximos incrementos, em ordem

| Prioridade | Trabalho | Aceite concreto |
|---|---|---|
| 1 | Validar bootstrap no novo Linux e registrar versões/recursos | Ambientes sem system-site-packages, CLI sem Qt, duas suítes sequenciais; distinguir skip por Edge ausente |
| 2 | Política de temporários administrados e retenção | Hoje 256 diretórios acumulados recusam novos filhos. Definir lease/identidade, orçamento e revisão/expiração segura; não remover diretórios ambíguos nem adotar fixtures legadas |
| 3 | Repetir soak controlado com raiz exclusiva | 7200 segundos reais, perfil fixo, todos os resultados e filhos contabilizados, fixture restaurada e orçamento aprovado; nunca somar tentativas |
| 4 | Vincular revisão/ID no pai para todas as mutações | Ajustes/tmpfs/restore/purge devem preservar o plano confirmado e ID mesmo em timeout; reconciliação de domínio pelo mesmo ID, sem reaplicar desconhecidos |
| 5 | Prazo total/cancelamento e histórico durável | Limitar coleta e operações, acompanhar filhos, reduzir I/O restante na apresentação; indexação/compactação preservando intenções pendentes e corrupção |
| 6 | Concluir fluxo Dar fôlego | Analisar → revisar o mesmo plano → confirmar → executar → verificar → recuperar; um clique repetido gera no máximo uma operação e arraste gera zero |
| 7 | Fechar matriz real de desktop | Leitor de tela, arraste físico Wayland, retorno do launcher para instância já aberta, outra distribuição limpa e login físico X11 |
| 8 | Assistido antes de Automático | Controlador sem Qt com evidência real, cooldown/orçamentos/disjuntor persistidos e grants de frequência; simulação verificável antes de qualquer executor opt-in |

As tarefas 2/4/5 precisam de desenho e testes de falhas; não são autorização para
limpar o host. O limite de 256 protegeu corretamente antes do efeito. A correção
de isolamento do harness não resolveu a gestão de retenção do produto.

## Provas e limites

Matriz de desktop: `docs/reviews/2026-10-18/desktop-validation/README.md`.
O topo atualizado explica que os ensaios foram arquivados sem aceite de duas horas.
Há capturas reais de cliente e compositor, logs de suíte e falhas preservadas.

Contratos de produção e lacunas: `docs/reviews/2026-10-18/continuacao/`.
Referências detalhadas: `avaliacao-entrega.md`, avaliação de runtime e planos de
17/10 em `docs/reviews`. As instruções originais recebidas estão preservadas em
`docs/handoff/inputs`; não são uma segunda implementação nem aceites já cumpridos.

O novo host deve iniciar com configuração própria e automação desligada.
Planos, grants, PIDs, boot IDs e caminhos antigos não devem ser reativados ou
reescritos para parecerem locais. Backups/diário exportados servem à inspeção e
recuperação explícita; não restaurar sobre dados existentes automaticamente.

## Rotina de qualidade

Um incremento por contrato, teste focado que reproduza a falha, mudança ligada
ao produto, suíte pertinente e registro de evidência. Usar `uv.lock`; atualizar
dependências deliberadamente. Registrar limitações ao lado do resultado.
Evitar novos frameworks, executores paralelos e módulos sem integração.

Antes de encerrar cada rodada: `git diff --check`, revisar o diff, atualizar
esta passagem e apontar a próxima ação objetiva. Commits/PRs devem explicar
problema, comportamento final e validação; não fazer merge sem pedido.

## Recuperação organizada — 2026-10-26

Raiz única neste host: `/home/misael/Projects/Folego`. Checkout existente realocado sem duplicação, base `815cf002248e80e51010191ace556dbaaa2319ce`. Ambientes recriados por `./dev`; núcleo: 916 pass/2 skip; Qt offscreen: 1133 pass/2 skip. Isso não aprova compositor físico nem soak de duas horas. Próxima tarefa continua sendo retenção segura dos temporários administrados; automação permanece desligada.

## Runtime /run/user cheio — 2026-10-28

Caso real: `/run/user/1000` a 100% por `forge-sessions/1bf5a050/audio.raw` (1,5 GB) de uma
sessão BlastEm do SGDKForge cuja árvore foi adotada pelo `systemd --user`. O plano tmpfs
protegia tudo corretamente, mas não dizia por quê nem qual o caminho seguro.

- `folego tmpfs diagnose [--json]` (somente leitura): maiores itens do volume mais cheio,
  maiores arquivos, holders com raiz da árvore e marca de árvore órfã, dono conhecido e
  comando oficial de encerramento (`actions/tmpfs/diagnosis.py`, `OWNER_HINTS`). Não sinaliza.
- `folego tmpfs runtime-size [--vezes N --confirmar]` e controle na aba tmpfs: 1×–4× do tamanho
  atual com teto de 65% da RAM (`core/runtime_size.py`). Aplicar é um único `pkexec` com
  argumentos posicionais: drop-in `/etc/systemd/logind.conf.d/60-folego-runtime-size.conf`
  (`RuntimeDirectorySize`) + remount imediato preservando conteúdo. Fila própria de 180 s para
  a senha; bloqueado enquanto houver resultado desconhecido.
- Validação: `./dev check` 928 + 1149 pass (2 skips cada); CLI real no host mostrou o
  `audio.raw`, o PID 1915399 como árvore órfã e opções 1482/2964/4446/5928 MiB; aba renderizada
  offscreen com dados reais. Não validado: compositor KDE real. O encerramento da sessão SGDKForge pelo `session_coordinator.py stop` não foi
  executado pelo agente (permissão negada); continua pendente com o usuário.
- Aplicação real em 28/10 pelo usuário: `./dev run tmpfs runtime-size --vezes 2 --confirmar`
  levou `/run/user/1000` de 1.554.046.976 para 3.107.979.264 bytes (`df`: 2,9 GB, 1% usado), drop-in
  `/etc/systemd/logind.conf.d/60-folego-runtime-size.conf` com `RuntimeDirectorySize=2964M`;
  os 36 itens do runtime permaneceram. A sessão SGDKForge que enchia o volume foi encerrada pelo
  `stop` oficial; o `audio.raw` dela não existia mais no momento da cópia (corrigido no SGDKForge,
  commit local `e80538de`, push bloqueado pelo registro de recuperação daquele projeto).

## Atalhos de inicialização — 2026-10-28

`src/folego/shortcuts.py`: a cada abertura da GUI (e por `folego shortcuts`) cria o atalho no menu e na
Área de trabalho se faltar, apontando para `run.sh` do checkout (ou o entrypoint instalado); atualiza
somente arquivos com `X-Folego-Managed=true`; preserva atalhos do usuário e symlinks; nunca autostart.
Validação: 8 testes; `./dev check` 936 + 1157 pass (2 skips cada); no host criou
`~/.local/share/applications/folego.desktop` e `~/Área de trabalho/folego.desktop` (válidos no
`desktop-file-validate`), segunda execução `present`, e `gio launch` do atalho da Área de trabalho abriu a
janela real no KDE (instância própria encerrada com SIGTERM).

## Visão padrão redesenhada — 2026-10-28

Padrão comum de painéis de manutenção (o artigo de referência do Medium não pôde ser lido; o usuário
aprovou seguir o padrão): navegação lateral (`SidebarTabBar`, abas West com rótulos horizontais), topo
com medidor de folga (`HealthGauge`: menor fração livre entre memória, swap e tmpfs; veredito e cor do
mesmo relatório de saúde do título) e uma ação principal que só leva à recomendação mais urgente,
cartões por recurso (memória, CPU, swap/zram, temporários; nível em palavra e cor, limiares oficiais),
recomendações com estado vazio e atividade recente com os detalhes da amostra. Nenhum comportamento
de ação mudou; nada novo executa efeito.
Validação: 4 testes novos; `./dev check` 936 + 1161 pass (2 skips cada); janela real no KDE capturada
quatro vezes durante os ajustes (rótulos rotacionados, abas altas e detalhes cortados corrigidos).
Para rodar o gate foi preciso remover 17 workspaces de QA desta sessão (o wrapper recusa com 20
retidos); os 3 anteriores a 28/10 foram preservados.

## Modo widget — 2026-10-28

Botão "⧉ Modo widget" na visão central: abre o controle compacto como widget flutuante (cartão sem
borda, mini medidor, RAM/CPU/Swap/Temp, botão "⤢ Abrir Fôlego" que volta à UI padrão e recolhe o
widget) e recolhe a janela para a bandeja (`hide_window` mantém a garantia de caminho de volta).
O widget nunca recebe foco, fica fora da barra de tarefas e no Wayland usa `startSystemMove`.
Keep-above no Plasma/Wayland não é possível pelo app: `ui/kwin_rule.py` cria, com confirmação, uma
regra do KWin só para o widget (app id `folego`, título exato; acima, sem borda, fora de barra/Alt+Tab,
sem foco, posição inicial no canto inferior direito) via kwriteconfig6 + reconfigure; preserva outras
regras; `folego widget-rule [--remover]`. Recusa fica gravada para não perguntar de novo.
Validação: 10 testes novos/ajustados; `./dev check` 940 + 1170 pass (2 skips cada); execução real no
KDE/Wayland: janela recolhida, bandeja presente, widget visível com dados reais (sem criar a regra).
Pendente: aplicar a regra do KWin no host real (decisão do usuário) e validar keep-above/posição.

## Avaliação do projeto — 2026-10-29

Revisão da base `5575ea06f15103dd28e071b04b6df3ef37c0db81`, igual ao SHA remoto
da branch de continuidade e do PR #1. Pedido de avaliação: nenhum código de
produção corrigido nesta rodada. Arquitetura CLI/core sem Qt, coordenador e
proteções têm cobertura ampla; isso não fecha os contratos dos caminhos novos.

Achados reproduzidos, em ordem de prioridade:

1. **P1 — configuração persistente alterada apresentada como recusa.**
   `core/runtime_size.py:apply_command` substitui o drop-in antes de chamar
   `mount`; uma falha de remount deixa o arquivo novo. Já
   `cli.py:_cmd_tmpfs_runtime_size` converte qualquer retorno não zero em
   `recusa`, sem ID/intenção no coordenador. Prova: corpo do shell executado
   sem pkexec, com todos os destinos em árvore descartável e `mount` simulado
   retornando 32; o drop-in novo permaneceu. CLI simulada retornou `recusa`.
   Correção: integrar no coordenador, preservar estado anterior, registrar as
   etapas e reconciliar configuração persistente e montagem; falha após efeito
   precisa de resultado parcial/desconhecido e recuperação explícita.
2. **P1 — resultado desconhecido permite repetir o resize na GUI.**
   `ui/tmpfs_tab.py:show_runtime_result` ignora `outcome=desconhecido`, mostra
   “runtime não alterado” e solicita opções; a resposta reabilita o botão sem
   preencher `_uncertain_text`. Prova com payload de timeout e atualização
   simulada. Correção: usar o bloqueio de incerteza também neste fluxo, com ID
   estável e reconciliação antes de permitir outra mutação.
3. **P1 — falha ao ler regras do KWin pode desativar regras alheias.**
   `ui/kwin_rule.py:_rules` ignora o código de saída de `kreadconfig6` e usa
   stdout vazio como lista vazia. `install` então grava somente a regra própria
   em `General/rules`; `remove` pode gravar lista vazia. Prova com ferramentas
   simuladas: lista inicial `existing-user-rule` substituída por `folego-widget`
   após erro de leitura. Correção: recusar antes de qualquer escrita quando a
   leitura não for comprovada e preservar a configuração anterior.
4. **P2 — corrida no registro de filhos curtos.** `cli.py:_session_run` inicia
   o comando antes de registrar a sessão; se ele já saiu, `register` recusa o
   zumbi e um comando `exit 0` vira erro 1. A CI do PR #1 já falhou assim
   ([run 40795479345](https://github.com/Misael-art/Folego/actions/runs/40795479345),
   939 pass / 1 fail / 2 skip). Reproduzido localmente atrasando apenas o registro
   de um filho descartável. Correção: coordenar lançamento/registro e término,
   preservando o código real e a proteção dos filhos ainda vivos.
5. **P2 — painel confunde ausência de recomendações com saúde.**
   `core/suggestions.py:suggest` não cobre tmpfs; `DashboardTab._sync_rows`
   apresenta “Tudo dentro do orçamento” sempre que não há sugestões. Provas:
   runtime 100% cheio com medidor “Crítico”, e meminfo ausente com medidor
   “Desconhecido”, ambos com texto de recursos dentro do orçamento. Correção:
   cobrir tmpfs/inodes e derivar o estado vazio do relatório de saúde/frescor,
   com navegação para a aba de temporários.

Verificação no host atual, Python 3.14.7, ambientes existentes do `./dev`,
HOME/XDG privados, temporários em disco e suítes sequenciais:

- `./dev check`: **939 passed, 1 failed, 2 skipped** no perfil headless;
  parou antes de Qt. `test_backup.py::test_roundtrip_property` gerou
  `FlakyFailure`: uma execução levou 328,57 ms (deadline 200 ms) e a repetição
  interna 11,44 ms. Não se alterou deadline/limite nem se aprovou o gate.
- `./dev test`: **1170 passed, 2 skipped**, 30,27 s, Qt offscreen.
- Seis provas isoladas + repetição focada do teste de backup: **7 passed**;
  prova adicional do KWin: **1 passed**. As provas afirmam os comportamentos
  defeituosos observados; não são testes de aceite de uma correção. Backup
  passou na repetição focada; a falha anterior continua registrada.
- Evidência local, descartável e fora do Git: `.scratch/dev-tests/run-_rab54lb`,
  `run-29la1x1v`, `run-4poe65yr`, `run-t9dqu524` (logs/run.json), e
  `run-review-20261029/test_assessment_probes.py` (sete provas). O relato acima
  preserva os resultados no Git. Dois skips de Edge ausente permanecem.
- Revisão documental e `git diff --check`; não se aplicou regra do KWin,
  redimensionamento privilegiado, limpeza ou efeito em processo alheio.
  Compositor físico e soak não foram exercitados nesta avaliação.

Lacunas conhecidas permanecem: retenção dos 256 temporários sem lease/término
comprovado (`safely/jobtemp.py`), plano/ID confirmado no pai para todas as
mutações, prazo total e cancelamento, histórico sem compactação, soak real de
7200 segundos e matriz física de desktop. Próximo incremento recomendado:
fechar os três P1 acima com regressões nos fluxos oficiais, depois a corrida
de sessão/CI e a retenção segura; automação continua desligada.


## Correções da avaliação e apresentação pública — 2026-10-29

Implementação em `fac2d2b377fa6395885b059cdb50f74d60d68bf7`, sobre a avaliação `2fff195`.
Os cinco achados receberam correção integrada e testes de regressão:

- Resize usa `actions/tmpfs/runtime_size.py`, o coordenador comum e intenção
  durável. A consulta entrega o plano v2 com tamanho exato/ID; a GUI preserva
  esse plano. O filho revalida volume, UID, identidade e capacidade antes do
  efeito, preserva a configuração anterior quando existe e deixa recibo de
  término. Falha após gravar configuração é parcial; falta de prova é desconhecida.
- Timeout conserva o ID no pai, bloqueia repetição e reapresenta operações
  pendentes após reabrir a aba. O botão “Verificar operação pendente” e
  `tmpfs runtime-size --reconciliar ID --json` verificam recibo e estado atual
  sob trava; não executam o resize novamente. Sem recibo comprovado, permanece
  desconhecido. Backups/recibos ficam ao lado do drop-in com sufixos por ID e
  não são removidos automaticamente.
- KWin recusa erro de leitura antes de qualquer escrita e preserva regras
  alheias. A GUI apresenta indisponibilidade em vez de propagar a exceção.
- Sessões registram filhos próprios ainda não coletados mesmo se já encerrados;
  registro avulso de zumbi continua recusado e o código real do comando é preservado.
- Painel recomenda a aba de temporários por ocupação/inodes e diferencia
  ausência de recomendação de ausência de evidência. Pausa/frescor invalidam
  também medidor, cartões e mensagem vazia.

Validação final com Python 3.14.7 e Qt 6.12.0:

- Focados: **135 passed**. Após a revisão final, `./dev check`: **952 passed,
  2 skipped** headless (18,34 s) e **1187 passed, 2 skipped** Qt offscreen
  (29,03 s), sequencialmente. Os skips continuam sendo Edge ausente.
- O teste de backup antes instável passou sem mudança de prazo ou remoção de
  verificação; isso não é uma afirmação de que toda variabilidade de I/O foi eliminada.
- Janela própria no KDE/Wayland real, HOME/XDG privados e dados sintéticos:
  exposição da janela, navegação pelo alerta tmpfs, bloqueio de timeout e
  invalidação de frescor passaram. `./dev gui` abriu em HOME próprio e permaneceu
  por 5 s; somente essa instância foi encerrada com SIGTERM. Nenhum efeito
  privilegiado, regra do KWin ou sinal a processo de trabalho foi aplicado.
- Shell privilegiado testado sem pkexec em árvore descartável, com ferramentas
  simuladas; a aplicação real do novo resize via polkit/remount não foi repetida.
- Logs finais locais: `.scratch/dev-tests/run-g0z90paq` e `run-wd7tp0ii`.
  Evidências adicionais em `run-review-20261029/native-demo` e `official-smoke`.
  Logs/manifestos da primeira rodada e do foco inicial foram preservados nessa
  raiz de revisão antes de remover somente os próprios workspaces regeneráveis
  já concluídos. O limite de revisão de QA permanece 20; revisar retenção antes
  de abrir novas rodadas, sem elevar o teto ou limpar evidência alheia.

Apresentação preparada: README com banner SVG próprio, captura real com dados
sintéticos, instruções, recursos, CLI e limites; licença MIT, metadados SPDX,
avisos de terceiros, guia de contribuição e modelos de issue/PR. Links locais,
SVG e `License-Expression: MIT` do pacote instalado foram verificados. A captura
`docs/assets/dashboard.png` não expõe dados do host.

A publicação pública foi solicitada explicitamente pelo usuário. Revisão local
prévia: 785 blobs históricos (22.418.992 bytes) sem correspondência aos padrões
procurados de chaves privadas, tokens GitHub/OpenAI/AWS e credenciais em URL;
109 capturas rastreadas revisadas por folhas de contato, com inspeção adicional
individual. Isso não é garantia universal de ausência de informação sensível.
A publicação usa a branch de continuidade como padrão para apresentar esta
versão, preservando `main` e o PR #1. Não há merge ou release de produto neste lote.

Continuam pendentes retenção segura dos temporários, demais planos/IDs no pai,
prazo total/histórico e matriz física/soak de duas horas. Automação permanece
desligada. Próximo incremento técnico: retenção com identidade/lease e orçamento,
sem adotar ou apagar diretórios ambíguos.

### Publicação confirmada

Repositório **público** em https://github.com/Misael-art/Folego, licença **MIT**
reconhecida pelo GitHub e branch padrão `codex/portable-handoff-20261024`.
Apresentação e código publicados em `3f770b19dbff7e1b12a1620b4684a4673b3508b8`;
README e as duas imagens conferidos por leitura anônima e igualdade com os
arquivos locais. Descrição e dez tópicos aplicados; PR #1 atualizado e aberto.
CI desse SHA: núcleo sem Qt, Qt offscreen e contratos CLI **success**, tanto
no push quanto no PR; CodeRabbit skipped. Nenhum merge ou release foi criado.
Recibo local: `run-review-20261029/anonymous-publication-verification.json`.

## Avaliação: supervisão da acessibilidade do desktop — 2026-10-29

Pedido novo: Fôlego acompanhar entrada/acessibilidade, espelhar estado por
dispositivo e solicitar reparo manual ou automático, aguardando intervenções
dos outros projetos. Esta rodada avalia viabilidade, dependências e aceite;
não implementa nem ativa um executor novo. A solicitação de automação para
acessibilidade não amplia autorização para limpar dados, sinalizar trabalhos,
parar containers ou habilitar o executor genérico de recursos do Fôlego.

### Estado verificado e fontes oficiais existentes

- Fôlego em `e86d7d2`: há coleta de recursos, adapters somente leitura,
  coordenador, diário e workers; não há monitor ou executor de acessibilidade.
- PhaseZero, código verificado em `83c50a60`: o backend oficial é
  `linux/steamdeck/desktop_session.py`, registrado por
  `~/.config/phasezero/desktop-session.json`; CLI `pz steamdeck input status`.
  Guardião de entrada e watcher do teclado estavam ativos/habilitados na
  consulta. Supervisor `phasezero-controller-desktop.service` não instalado.
- RetroFE mantém propriedade do perfil Steam e atalhos em
  `Tools/launchers/retrofe/steam_desktop_session.py`; seu
  `desktop_environment.py` já delega a política local ao backend registrado
  do PhaseZero. Guardião de recuperação também estava ativo/habilitado.
- Consulta oficial de status retornou processo com exit 0, mas `ok=false`,
  `desktopReady=false`, `ownershipRecovered=true` e `touchscreen=missing`.
  USB observado, dispositivos enumerados pelo KWin habilitados, teclado virtual
  disponível em modo 1 e áudio enumerado sem mute. Enumeração não comprova
  movimento, clique, caractere digitado, toque físico, audição ou fala.

### Lacunas que precedem a automação coordenada

1. **Não existe exclusão mútua comum de reparos.** `guardian.lock` do PhaseZero
   protege instâncias de `watch`; `reconcile`/`capture` não adquirem essa mesma
   trava de operação. RetroFE tem locks próprios de perfil/atalhos, e o
   coordenador do Fôlego protege somente seus participantes. Ler “active” no
   systemd ou conferir lease antes do efeito não elimina a corrida posterior.
2. **Contrato de saúde/propriedade ainda precisa de qualidade explícita.** O
   status do PhaseZero não pode ser interpretado só pelo exit code; leituras
   vazias/indisponíveis e erros ao verificar identidade precisam continuar
   desconhecidos. A leitura booleana `process_alive` existente exige revisão
   de falhas de observação antes de servir como autorização ao Fôlego.
3. **Containers não estão cobertos como donos de dispositivos.** O adapter
   atual do Fôlego lista containers/imagens/volumes, não acesso a `/dev/input`.
   Dispositivo passado ao container continua sendo recurso do host. Identificar
   descritor aberto não prova captura exclusiva; processos/projetos precisam
   cooperar com o mesmo contrato de propriedade.
4. **FTS e login são outro nível.** Touchscreen continua ausente. O reparo FTS
   restrito está no PhaseZero; fallback físico e persistência não homologados.
   Units de usuário em `graphical-session.target` não certificam entrada no
   greeter SDDM. Fôlego aberto depois do login não resolve sozinho bloqueio
   ocorrido antes dele. Usar [systemd.special](https://freedesktop.org/software/systemd/man/latest/systemd.special.html#graphical-session.target)
   e [documentação Docker](https://docs.docker.com/engine/containers/run/#runtime-privilege-and-linux-capabilities)
   como referência desses limites.

### Incrementos e aceite propostos

| Ordem | Integração | Dependência e aceite |
| --- | --- | --- |
| 1 | Monitor somente leitura, CLI e painel Entrada/Acessibilidade | Usar registro do backend, validar schema/owner e orçamento total; representar saudável/degradado/desconhecido/ausente conforme capacidades do host. Pode avançar sem esperar reparo FTS. |
| 2 | Protocolo comum e reparo manual | Estender o backend oficial, sem copiar sua política para Fôlego. Todos os caminhos envolvidos publicam/adquirem lease/trava por domínio/dispositivo. Testar concorrência, falha, filhos vivos, reboot/PID reutilizado e falta de evidência em fixtures. |
| 3 | Supervisão automática limitada, independente da janela | Após o contrato comum: aguardar dono, reler estado, solicitar operação com ID, verificar resultado; cooldown, orçamento, disjuntor e intenção durável. Reconciliar timeout sem retry cego. Serviços existentes não significam que suas GUIs precisem ficar abertas. |
| 4 | Garantia operacional antes do login e transições físicas | PhaseZero é owner do reparo FTS/boot. Validar driver e toque real, SDDM, cold boot, logout/login, suspend/resume, dock/USB, Steam/Big Picture e frontend com emulador filho vivo. Falha física não pode ser aprovada por fixture. |

Fluxo requerido: observar → outro dono reparando/usando → aguardar sem efeito →
adquirir exclusividade e revalidar → intenção → pedir reparo ao owner → testar →
confirmar resultado ou manter parcial/desconhecido. Heartbeat vencido sozinho
não prova abandono. Trava ausente só é autoridade quando todos os writers usam
o protocolo. Nenhum restart global de KWin/Steam/USB nem reset de barramento
compartilhado deve ser usado como fallback automático.

Na interface: cards com ícone **e texto** para Deck/trackpads, toque, teclado
físico/virtual, mouse/controles externos, áudio/microfone; mostrar dono, última
verificação, motivo e estado “aguardando PhaseZero/RetroFE”. Botões “Verificar”
e “Solicitar reparo” usam o mesmo controlador e as mesmas portas de automação,
sem caminho manual que ignore propriedade. Tab/Enter, nomes acessíveis e
feedback sem depender só de cor fazem parte do aceite. Não gravar teclas ou
áudio para manter o monitoramento.

A política observada é teclado automático somente por toque na tela (modo 1),
com atalhos explícitos preservados. O termo “touchpad” no pedido pode significar
trackpad ou touchscreen; esclarecer antes de alterar esse comportamento. O
pedido termina por solicitar avaliação; implementação e ativação não foram
inferidas desta avaliação enquanto essa escolha de escopo estiver pendente.

Verificação desta rodada: leitura do anexo e dos fontes responsáveis,
`systemctl --user show` das quatro units, enumeração do kernel/KWin e CLI
oficial de status, sem gravação de configurações, coleta de teclas, restart,
sinal ou reparo no host. Alteração apenas documental: revisar diff/referências;
não há nova contagem de testes de produto. Próximo passo concreto: incremento
1 e contrato comum do incremento 2, preservando os executores oficiais.

## Implementação: supervisão de entrada independente — 2026-10-29

O usuário aprovou avançar e corrigiu a premissa conjuntural: **PhaseZero pode
não existir no host**. A avaliação acima é histórica; esperar esse projeto
não é pré-requisito de implementação ou operação. Owner: Fôlego para observação,
política e reabilitação restrita de entrada no KWin; os responsáveis externos
continuam donos de seus perfis, drivers e recuperações específicas.

### Incremento integrado

- Nova CLI `accessibility` e sexta aba, cartões com ícone/texto para oito
  capacidades e estado espelhado na central. Coleta por worker, comandos por
  QProcess e dados antigos/incompletos sem aprovação implícita. A central ganhou
  rolagem após a QA Wayland reproduzir altura excessiva com fontes/mensagens
  reais; navegação e controles continuam acessíveis em 800×600.
- Backend nativo Linux/KWin, sem Qt em core/actions/CLI e sem executar caminhos
  do registro de terceiros. Outros desktops e dependências ausentes preservam
  observações possíveis e informam o reparo não suportado. Identidade inclui
  boot, dono único D-Bus/UID, event e chave física; duplicidade protege.
- Único efeito: `enabled=true` de entrada identificada, seguido de leitura.
  Política própria captura somente estados habilitados, preserva desconectados
  e incorpora hotplug saudável. Não altera drivers, Steam, atalhos, perfis,
  áudio, USB, login do sistema, containers ou processos de trabalho.
- Coordenador/diário existentes, intenção durável, ID estável, reconciliação
  sem reaplicar, cooldown 60 s, até três tentativas/h e disjuntor persistente.
  Resultado incerto continua pendente; rearmar exige revisão explícita e
  configuração habilitada comprovada, sem operações pendentes.
- Leases genéricos para aplicações cooperantes, com boot/PID/starttime, filhos,
  slots estáveis e trava comum. Filho vivo/desconhecido e reparador morto
  preservam propriedade/incerteza. Schemas desconhecidos não liberam recursos.
  Docker/Podman presentes são consultados com campos restritos de dispositivos;
  exposição/consulta desconhecida bloqueia. Integrações legadas ativas ou
  desconhecidas aguardam sem serem interrompidas.
- Unit de usuário `folego-accessibility.service`, independente da janela,
  vinculada à sessão gráfica e opcional em instalações novas. A autorização
  específica de monitoramento/ativação foi registrada no AGENTS; não habilita
  o executor genérico de recursos nem arquivamento de fixtures.

Operação, matriz por host, pausa, desinstalação e protocolo estão em
[ACESSIBILIDADE.md](ACESSIBILIDADE.md). O README público distingue claramente
a política de entrada do executor automático de recursos ainda desligado.

### Evidências e limites

- Gate final `./dev check`, Python 3.14.7 gerenciado, HOME/XDG privados,
  suítes sequenciais: **994 passed, 2 skipped em 17,69 s** sem Qt e
  **1236 passed, 2 skipped em 28,37 s** com Qt 6.12.0 offscreen; diff check aprovado.
  Logs/run.json: `run-a1i86z0r` e `run-pooobcvm`. Os dois skips em cada perfil
  exigem Edge real ausente. Regressão final de consultas: 42 testes headless
  focados aprovados em 1,30 s antes desse gate completo.
- Primeira ampliação focada: 79 passed/3 failed. Corrigidos o seam do teste
  da consulta do diário e o piso da janela, sem afrouxar o aceite. A repetição
  passou com 82 testes. A QA nativa posterior encontrou 800×652 com mensagens
  reais: as duas tentativas falhas foram preservadas; rolagem corrigiu a causa.
- QA KDE/Wayland real em HOME próprio: janela exposta em 800×600 e 1280×800,
  navegação da central à aba, foco por Tab, cancelamento sem despacho e
  operação desconhecida impedindo retry. Consulta nativa do host somente
  leitura: KWin, entradas habilitadas e PhaseZero ativo. Launcher oficial
  `./dev gui` sobreviveu cinco segundos em HOME próprio; só seu processo
  foi encerrado. Capturas são do cliente em compositor real, não certificam
  arraste, toque físico ou leitor de tela.
- A regressão de prazo/saída usa exclusivamente consultas e descendentes
  descartáveis. Inclui líder encerrado com filho mantendo pipes: o grupo
  próprio é encerrado antes de reaproveitar/recolher sua identidade.
- Fontes, unidades, diário, orçamento, perda de resposta, PID reutilizado,
  boot anterior, filhos vivos/desconhecidos, containers, host sem PhaseZero,
  backend ausente e hotplug têm testes. Nenhuma entrada física foi desabilitada
  como fixture; nenhuma unit de terceiro foi reiniciada.

Evidência local privada em `.scratch/dev-tests/run-review-20261029/`:
`accessibility-native-3/{report.json,launcher-report.json,activation.json}` e
capturas; tentativas 1/2 e logs/run.json anteriores permanecem identificados.
Só gerados próprios concluídos e revisados foram removidos após preservar logs,
para respeitar o teto de vinte workspaces; guardas não foram ampliadas.

### Ativação autorizada neste host

Executados `./dev run accessibility enable --confirmar --json` e
`./dev run accessibility install --confirmar --json`. A unit do Fôlego foi
verificada `enabled`, `active/running`, status 0, com heartbeat recente e zero
reinícios observados. Política habilitada, baseline vazio e nenhuma operação
pendente: ciclo **waiting**, aguardando o PhaseZero ativo. Isso confirma a espera,
não comprova reparo físico ou transição após reboot. Não foram parados os
guardiões existentes, e o executor automático de recursos continua desligado.

A exclusividade só existe entre participantes do protocolo. Aplicações
não cooperantes podem intervir após a leitura; inventário não cobre todos os
descritores, capturas exclusivas ou daemons remotos. Não declarar garantia
universal de acessibilidade. FTS ausente, boot/SDDM, login/logout, suspensão,
dock, atalhos Steam, leitor de tela e soak contínuo de duas horas continuam
pendentes. Próximo passo: integrar writers interessados ao protocolo e validar
essas transições no alvo físico, sem desligar entradas de trabalho para testes.

### Fechamento e publicação

Implementação, testes e documentação publicados no commit
`02db56c8d7399ddb3e8ba546f66358ec01f9f73f`, na branch padrão de continuidade
`codex/portable-handoff-20261024`; SHA remoto conferido. Repositório público e
licença MIT novamente confirmados. [PR #1](https://github.com/Misael-art/Folego/pull/1)
reutilizado, aberto e atualizado com o comportamento final e seus limites.
CI desse SHA: núcleo sem Qt, Qt offscreen e contratos CLI **success** no push
e no PR; CodeRabbit/Sourcery **skipped**. Nenhum merge ou release.

Após atualizar o código de consultas, somente a unit do Fôlego foi reiniciada
para carregar a versão validada. Consulta final: `enabled`, `active/running`,
`ExecMainStatus=0`, `NRestarts=0` (reinícios por falha), heartbeat recente,
política habilitada, ciclo `waiting` pelo PhaseZero e nenhuma operação pendente.
Diário do host: **zero intenções de reparo de acessibilidade**. O fechamento
subsequente altera apenas este registro, sem mudar o código testado.

### Correção de teste temporal descoberta na CI de fechamento

A CI de `a65a0027c5f76b30f80c50509c84663c5f8fa3e9` aprovou todos os jobs do PR,
mas o Qt do push falhou no teste **preexistente**
`test_file_changed_mid_read_is_not_certified`: 1235 passed, 2 skipped e uma
falha. [Job preservado](https://github.com/Misael-art/Folego/actions/runs/40978896214/job/123813676422).
O leitor retornou corretamente “em andamento” quando seu passo excedeu 10 ms;
o teste assumia que o diagnóstico final ocorreria na primeira chamada. Isso
não demonstra uma falha do novo reparador nem autoriza aumentar o orçamento.

A fixture agora injeta o relógio já suportado pelo leitor, isolando a mudança
de arquivo da latência do runner. Outra regressão expira explicitamente o
mesmo orçamento de 10 ms durante a mudança e exige estado não certificado,
seguido de revalidação que lê o conteúdo novo. Nenhum limite ou código de
produção foi alterado. Focados: `./dev test-headless tests/test_history_reader.py`,
**12 passed em 0,44 s**. Resposta/log da CI preservados em
`accessibility-native-3/failed-ci-job.json`; não se apagou a falha nem se
reexecutou o job para obter verde sem uma correção.

Gate após corrigir a fixture: `./dev check`, mesmas ferramentas, perfis privados
e execução sequencial, **995 passed, 2 skipped em 19,66 s** sem Qt e
**1237 passed, 2 skipped em 32,50 s** com Qt. Diff check aprovado; logs/run.json
em `run-2usf6g4u` e `run-3ay4598a`. O código de produto segue o SHA `02db56c`;
este incremento altera apenas o teste e o presente registro de continuidade.
