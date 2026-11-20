# Fôlego no Windows

Port nativo em prévia, mantido no mesmo projeto. O ponto de entrada é
`Folego.ps1`; os arquivos executáveis ficam em `Program Files\Folego`, e o
estado privado do usuário em `%LOCALAPPDATA%\Folego`. O pacote usa Windows
PowerShell 5.1, .NET Framework e Windows Forms presentes no Windows 11.
Não exige Python, Qt, WSL, serviço privilegiado ou download no primeiro início.

## Usar e iniciar com a sessão

No cartão preparado, use **Steam Deck → Fôlego**. No próximo login, o dispatcher
existente do cartão solicita o primeiro início com 30 segundos de atraso.
O Fôlego registra uma única entrada própria `Folego` em HKCU Run e começa na
bandeja. Depois dessa configuração inicial, o dispatcher deixa de solicitá-lo;
a entrada do próprio Fôlego assume o início. O atraso dá espaço à abertura do
desktop; não impõe uma quota às outras aplicações.

Para abrir diretamente, execute no Windows:

```powershell
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "$env:ProgramFiles\Folego\Folego.ps1"
```

**Opções e recuperação** permite ligar/desligar o início com a sessão, abrir
o estado e encerrar somente o Fôlego. Fechar a janela mantém a bandeja;
**Sair** encerra esta instância. Uma nova abertura pede à instância existente
que mostre a central. Uma entrada de inicialização divergente é preservada.
O comando usa a instalação real e as pastas conhecidas, sem caminhos Linux,
letras de disco ou nomes de usuário gravados. Mudar a instalação exige revisar
a entrada anterior; não são criadas variantes concorrentes.

## Visualizações e cores

As visualizações do Fôlego Linux e uma própria do Windows, a **Barra de tarefas**, que
é a de abertura padrão. Ficam no menu **Visualizações** (barra do topo da central,
menu dos ícones da bandeja e menu ☰ do widget); **Ctrl+Shift+F** alterna entre a
central e o último widget usado:

| Visualização | Forma no Windows |
| --- | --- |
| Central do Fôlego | Janela com abas; um widget aberto recolhe a central para a bandeja. |
| Barra de tarefas (padrão) | Indicadores vivos na área de notificação. Cada ícone traz a sigla **CPU**, **TEMP**, **RAM** ou **BAT** acima do valor. A faixa da sigla segue o tema. A cor do valor indica a faixa de saúde. |
| Mini horizontal | Faixa de 384 × 46 px (escala com o DPI): estado, CPU, temperatura, RAM e bateria, expandir e menu. |
| Widget compacto | Cartão de 268 px com anel de folga, estado, RAM livre, CPU, zona térmica, bateria e perfil térmico. |
| Lateral esquerda / direita | Barra na borda da área de trabalho, 112–128 px de largura e altura total, como no Linux. |
| Barra superior | Faixa no topo da área de trabalho: 120 px em telas a partir de 900 px de largura, 190 px nas menores. |

Na **Barra de tarefas**, um clique (esquerdo ou direito) em qualquer indicador abre o
menu de funções: resumo atual, abrir a central, aplicar Fresco/Contenção ou
restaurar os originais (com a mesma confirmação da central), analisar consumidores,
inicialização, pausar, visualizações, tema, transparência, Gerenciador de Tarefas
e sair. No cabeçalho do menu, as leituras ficam agrupadas e mostram `%` ou `°C`.
A dica de cada ícone informa a unidade, o uso de RAM e a origem ACPI da temperatura.
Se uma consulta atrasar ou vier parcial, o último valor confirmado fica por até
30 s além do seu prazo normal, com fundo neutro, marca pontilhada e dica
**leitura anterior**. O menu indica esse valor com **~**. CPU, RAM e bateria
têm prazo de 15 s e a zona ACPI tem prazo de 90 s. Cada fonte vence separadamente.
Depois da janela adicional, ou durante a pausa, aparece um traço. A guarda e os
alertas usam os prazos originais e as próprias leituras atuais.
O Windows 11
não oferece mais deskbands, e encaixar uma janela dentro do `explorer.exe` seria
frágil; por isso são ícones nativos da área de notificação, que o próprio Windows
recoloca se o explorer reiniciar. Ícones novos podem ir para o menu ^: **Deixar os
indicadores sempre visíveis…** abre Configurações → Barra de tarefas, onde o
usuário liga os ícones do Fôlego (Windows PowerShell) em Outros ícones da bandeja.
O Fôlego não altera essa configuração sozinho.

O widget não rouba o foco, não aparece na barra de tarefas nem no Alt+Tab, fica
acima das outras janelas e se move arrastando qualquer área fora dos botões; o
mini e o compacto lembram a posição, recolocada dentro da tela atual. As
laterais e a barra superior usam só a área de trabalho, sem cobrir a barra de
tarefas, e não reservam espaço como uma appbar: janelas maximizadas passam por
baixo. **Modo de abertura**, em Opções, escolhe a visualização da próxima abertura; sem
escolha salva, o Fôlego abre na Barra de tarefas, inclusive no início da sessão.

**Tema de cores** oferece os oito temas de console do Linux (SNES americano,
Super Famicom, Mega Drive, Master System III, PC Engine, NES, TurboGrafx-16 e
PlayStation 2). `tools/build_windows.py` copia de `palettes.py` os tokens já
ajustados para contraste mínimo de 4,5:1; as cores de saúde (ok, atenção,
crítico) mantêm o sentido em todos os temas. O tema vale na hora para a central,
as abas, os menus e o widget. **Transparência do widget** vai de 0 a 60%: no
Windows a opacidade atinge a janela inteira, texto incluído, por isso o limite é
menor que o do Linux, que torna transparente só o fundo.

As escolhas ficam em `appearance.json`, gravado só quando o usuário muda visualização,
tema, transparência, modo de abertura ou posição. Um arquivo inválido é preservado e
os padrões valem só na sessão, sem sobrescrevê-lo. Os menus dos indicadores e dos
widgets oferecem **Abrir teclado virtual do Windows** e **Mostrar ou restaurar a
área de trabalho**. O teclado também está na **Visão geral**.

## Prompts, atalhos e textos pessoais

O clique esquerdo ou direito em um indicador da bandeja abre **Prompts e
atalhos**. O mesmo submenu fica no widget. A biblioteca reúne os 16 prompts
do Linux em seis categorias e inclui diagnóstico, implantação a partir de
achados, desempenho, design e continuidade. Escolher um prompt nesses menus
copia o texto integral. Cole no agente quando quiser enviá-lo.

Na Central, **Prompts e atalhos** permite criar, editar e remover textos e
macros. O clique direito nos campos do editor oferece os comandos habituais de
edição e o submenu do Fôlego. Um prompt escolhido no campo de várias linhas
substitui apenas a seleção ou é inserido no cursor. O campo de título oferece
copiar os prompts longos. Os textos pessoais também aparecem no menu.

Para usar em um aplicativo externo, ligue **Abrir painel ao clicar com o botão
direito em campos editáveis de outros aplicativos** na mesma aba. Com o
aplicativo em primeiro plano, clique com o botão direito em um campo. Ao
identificar um campo editável por UI Automation, o Fôlego mostra um botão
flutuante **Prompts e atalhos** perto do clique. Clique nele para selecionar
um item. Cada aplicativo continua responsável pelo seu menu de contexto e
pela ação Colar. Use o menu da bandeja como alternativa em campos de senha,
áreas somente leitura, controles sem acessibilidade compatível e telas
protegidas.

Com um campo externo identificado, o submenu de atalhos traz opções de
**Janelas**, **Edição** e **Terminal**, além do **Teclado virtual do Windows** e
**Mostrar ou restaurar a área de trabalho**. Uma macro personalizada pode
invocar a área de trabalho ou uma combinação, como **Ctrl+Shift+F5**.
O Fôlego revalida o foco e o campo antes de enviar uma combinação uma vez.
Um aplicativo pode usar outras associações, manter seu menu aberto ou ter
privilégios que impeçam o envio. Nesses casos use o teclado virtual ou o
próprio menu do aplicativo. Selecionar um texto externo copia para a área de
transferência, sem enviá-lo ao agente.

A preferência do painel externo começa desligada e fica em **appearance.json**.
O observador de clique preserva o evento original e usa o provedor de
acessibilidade fora da interface. Consulta a editabilidade do controle, sem
ler seu texto. A biblioteca privada fica em **custom-prompts.json** no estado
do Fôlego. Suporta até 32 itens e 512 KiB, com títulos de até 80 caracteres e
textos de até 16.000. Exemplos aparecem na primeira leitura. Uma biblioteca
salva vazia permanece vazia. Se o arquivo mudou desde a edição, recarregue
antes de salvar. Formatos incompatíveis ficam disponíveis para revisão e
bloqueiam gravações.

## Recursos e limites do port

| Função | Backend e comportamento Windows |
| --- | --- |
| RAM e CPU | GlobalMemoryStatusEx e diferença entre GetSystemTimes; CPU exige duas amostras. |
| Memória comprometida | GetPerformanceInfo: uso e limite de commit; não é tamanho nem uso isolado de pagefile. |
| Disco | Espaço, fila e saúde do volume do aplicativo. Em **Trabalho e disco → Ver espaço nos volumes locais**, inventário sob demanda dos volumes locais fixos com letra, com sistema de arquivos, capacidade, espaço livre e ocupação. Leituras incompletas ficam indisponíveis. |
| Bateria/carregador | GetSystemPowerStatus. A Visão geral e a dica do ícone **BAT** exibem uma estimativa de tempo em descarga quando o Windows a fornece. Tensão, corrente e saúde do carregador seguem sem leitura própria. |
| Temperatura | Zonas ACPI de root/wmi; sem elas (usuário comum), a mesma zona pela classe CIM `Win32_PerfFormattedData_Counters_ThermalZoneInformation`, que independe do idioma dos contadores. Limites passivo/crítico só quando o sensor os informa. Não equivale automaticamente à APU/GPU. |
| Perfis térmicos | `PROCTHROTTLEMAX` e `PERFBOOSTMODE` do plano ativo existente (tomada e bateria) por PowerRead/PowerWrite + PowerSetActiveScheme. Recibo antes, leitura depois, até quatro trocas por hora. Guarda automática opcional, desligada por padrão. |
| Consumidores e órfãos | Toolhelp + GetProcessTimes/GetProcessIoCounters em duas amostras de 2 s; dono pelo token; linha de comando resumida sem segredos. Encerramento só manual, confirmado e revalidado. |
| Inicialização | HKCU/HKLM Run, Run32, pastas Startup e tarefas de pacote; desativação pelo mesmo `StartupApproved` das Configurações, com recibo e restauração. |
| Identidade física | UUID SMBIOS; se o firmware informa um UUID de preenchimento (o Deck LCD informa `FFFFFFFF-…`), número de série da BIOS e depois da placa. Hosts com UUID válido mantêm o identificador anterior. |
| Alertas | Pressão observada, bateria baixa e desconexão, com intervalo mínimo de cinco minutos por tipo. |
| Diagnósticos manuais | Até 25 processos por RAM, amostra superficial limitada de temporários, eventos de boot e até 24 eventos de disco, NTFS e WHEA dos últimos sete dias. A triagem mostra condições do encerramento, classificação e motivos de proteção. As linhas de comando são truncadas e ocultam tokens/chaves/senhas na apresentação. |
| Cota local do Codex | A aba **Cotas de IA** mostra a janela e a reposição quando há um registro recente de uso no perfil local. Só durante a consulta manual ou enquanto a aba está visível, com atualização automática no máximo uma vez por minuto. A fonte local não confirma a conta nem atribui a observação a CLI ou Desktop. |
| Energia | Planos oficiais existentes, intenção durável antes da troca, confirmação por leitura, recuperação e até quatro trocas por hora. |
| Componentes do sistema | Windows Update, Otimização de Entrega, Defender, UAC e serviços: só detecção e a página oficial correspondente. Nada é alterado pelo app. |
| Manutenção de armazenamento | Reutiliza o painel do cartão quando presente; fora dele abre as Configurações do Windows. |
| Linux PSI, zram e tmpfs | Não são métricas equivalentes no Windows; não há leitura sintética ou verde presumido. |
| KWin, systemd, áudio/entrada e IA | Reparos e integrações com owners/contas Linux não têm adaptador Windows validado e não são executados. |
| TDP, ventoinha, drivers, EFI e discos Linux | Permanecem com os responsáveis próprios; nenhum acesso EC/SMU ou troca de driver é feito pelo port. |

### Funções que ainda precisam de equivalente Windows

Inventário comparado com a [visão geral do produto Linux](../README.md#o-que-você-pode-fazer)
e o [guia do widget](COMPACTO.md).

| Área | Implementado no Windows | Pendências e critérios de aceite |
| --- | --- | --- |
| Identidade de contas de IA | Leitura local do perfil Codex. | Inventário de perfis do Codex CLI, Desktop e Web, Claude CLI/Desktop e Grok nas fontes nativas e no inventário opcional do responsável. Vincular conta, organização, instalação e cliente por evidência. Trocar de conta ou organização invalida a observação anterior mesmo no mesmo diretório. Mostrar distintamente fonte ausente, parcial, sem vínculo, vencida e indisponível. |
| Cotas, resets e ofertas | Observação recente de janelas do Codex, disponibilidade e reposição quando registradas localmente. | Adaptadores de leitura por conta, orçamento e cache por provedor, tratamento de HTTP 429 e sessão expirada, reposição confirmada antes de alertar, saldo/extra quando disponível, tickets e ofertas com seu prazo real, lembretes declarados e referência mensal separada da data de cobrança confirmada. Preservar zero confirmado e esconder números expirados. Validar sem resgatar tickets ou gastar uma mensagem. |
| Trabalho dos agentes | Triagem Win32 com dono, criação, janelas, CPU e E/S. | Relacionar sessão, projeto, responsável, execução ativa, fila, entregas e histórico. Portar alertas de MCP e capacidade do Codex Web e o pedido de recuperação pelo responsável da mesma conta, com orçamento, recibo e deduplicação. O aviso de um processo e a confirmação de uma entrega são evidências diferentes. |
| Sessões e encerramento | Classes, motivos, reapuração da identidade, pedido gentil e força após nova confirmação. | Proteção explícita de trabalho por sessão e heartbeat, exclusões, vínculo com Job Objects/ancestrais, agrupamento por aplicação e perfil, opções cooperativas e recibo recuperável. Testar PID reaproveitado, pai/janela ausentes, dono desconhecido e agente ocupado. Preservar processos compartilhados, sessões, instaladores, segurança e projetos. A automação de encerramento tem contrato separado. |
| Navegadores | Sugestões para Chrome, Edge e entradas do Internet Explorer identificadas na triagem. | Distinguir navegador, renderizadores, extensões, apps instalados, WebView2 e automações ativas. Recomendar ajustes pela evidência de uso. Para ajustes persistentes, detectar política gerenciada e exigir confirmação, recibo, leitura posterior e restauração quando o valor ainda pertencer ao Fôlego. Manter modo IE do Edge para compatibilidade com sites legados. |
| Inicialização | Inventário, recibos, início em série sob condições de calma e retorno ao Windows. Reabertura com **NoStartup** desvia do logon. | Qualificar em outro equipamento e no Deck real: login, reinício no mesmo boot, cancelamento, duas sessões, UAC negado, mudanças externas, comando inválido, ausência de sensores, timeout e retorno ao Windows. Medir tempo até desktop responsivo, duração total, CPU, fila e temperatura. Guardar as ações por host e deixar operações inconclusivas para revisão. |
| Disco e temporários | Capacidade e ocupação dos volumes locais, fila do volume do aplicativo, saúde via consulta CIM, leitura superficial dos temporários e eventos conhecidos do Windows. | Histórico limitado de espaço e tendência, bytes/segundo, latência, fila e pressão sustentada por volume e dispositivo físico. Mapear cartão SD, NVMe, NTFS, pontos de montagem, WSL e Btrfs pelo identificador e responsável. Portar inventário por escopo, arquivos com handles abertos, cópia verificada, quarentena e restauração. Medir custo em repouso e qualidade com volume bloqueado, desconectado ou somente leitura. |
| Incidentes e retomada depois de crash | Eventos de boot, desligamento, WER, disco, NTFS e WHEA sob demanda. | Dossiê por host e boot com últimos recursos observados, atividade de disco, evidências de temperatura/energia, eventos de falha e lacunas. Distinguir erro de parada, desligamento por aplicativo e reinício sem causa comprovada. Contexto de dumps, SMART, APU/GPU e drivers vem dos responsáveis documentados. Testar corrupção de estado, escrita interrompida, recuperação e tolerância a fontes lentas sem provocar falhas físicas. |
| Sensores, energia e tela | CPU, RAM/commit, ACPI, estado da tomada e da carga, autonomia estimada, perfis térmicos e guarda por carga. | Temperatura de APU/GPU, RPM, tensão/corrente, descarga com tomada detectada, bateria crítica e guarda por queda de tensão quando houver um adaptador confiável. Adicionar alertas sustentados e temporizador reversível da tela interna respeitando dock, jogos e acessibilidade. Verificar ausência de sensor e perda de telemetria sem acionar mudança. |
| Entrada e acessibilidade | Atalho para teclado virtual nativo. | Inventariar teclado, controle, trackpads, toque, entrada e saída de áudio e responsável de cada perfil. Confirmar estado saudável no mesmo host antes de qualquer reparo sob supervisão. Validar navegação por teclado e toque, leitores de tela e erro recuperável. |
| Portabilidade do SDK | Identidade física derivada do SMBIOS, recibos de ações vinculados ao host, manifesto e **Inspect Overview**. | Inventário global por dispositivo, usuário/perfil, versão do esquema, boot e responsável. Conciliar versão/commit e SHA-256 do pacote com o SDK e exportar status sanitizado com idade da leitura. Migrar preferências compatíveis e manter históricos consultáveis, com poderes e recibos vinculados à máquina original. Testar mudança de letra de disco, novo hardware, mesmos dados de usuário, acesso parcial, versões desconhecidas e retorno ao equipamento anterior. |
| Interface e CLI | Temas, bandeja legendada, visualizações, Central, consultas **Inspect**, catálogo compartilhado de prompts, textos pessoais, macros e painel de contexto opcional. | Navegação por tarefas, origem e idade junto de cada valor, tela de revisão com motivo e retorno, agrupamento das contas e entregas, filtros e busca em listas, preferências de movimento, contraste e DPI, encaixe e transparência do fundo. Ampliar compatibilidade dos campos externos, ações de captura e CLI estruturada para diagnóstico, revisão e recuperação. Validar a 100/125/150% de escala e no tamanho real da bandeja. |
| Integração com responsáveis | Painel de manutenção do cartão quando instalado e atalhos do Windows. | Contratos versionados e opcionais para PhaseZero, componentes do SDK, recuperação de conectores e instruções de recursos aos IDEs/CLIs. Mostrar ausente, desligado, protegido, erro e recuperação disponível. Conferir escopo, assinatura/integridade e proprietário antes de solicitar qualquer ação. |

PSI, zram, tmpfs, unidades systemd, layout do Plasma, regras do KWin, PipeWire e
contadores Btrfs pertencem ao ambiente Linux. A paridade no Windows passa por
diagnósticos e ações equivalentes para o usuário, usando as fontes e os
responsáveis do Windows.

Para transportar um diagnóstico entre máquinas, execute no PowerShell 5.1
o ponto de entrada do pacote com uma destas opções. **Overview** inclui o
identificador de dispositivo, boot, versão do Windows, versão e SHA-256 do
manifesto. O resultado ajuda a comparar instalações da mesma versão; contém um
identificador estável de dispositivo, então revise antes de compartilhar.

~~~powershell
.\Folego.ps1 -Inspect Overview
.\Folego.ps1 -Inspect CodexQuota
.\Folego.ps1 -Inspect Volumes
.\Folego.ps1 -Inspect Incidents
.\Folego.ps1 -Inspect Boot
~~~

A consulta Codex lê no máximo seis finais de arquivos, limitados a 256 KiB
cada, nas pastas do dia atual e do anterior em UTC e horário local. Ignora
linhas incompletas, aceita observações de até 15 minutos e retira uma janela
assim que chega sua reposição registrada. O diagnóstico mantém a fonte local
explícita. O scanner não consulta credenciais nem endpoints.

Uma coleta por vez, fora da thread da interface. Amostras nativas a cada
10 segundos; sensores/fila/saúde a cada 60 segundos. CPU/RAM/commit/espaço
antigos depois de 15 segundos ficam desconhecidos; detalhes depois de 90 s
não sustentam alerta atual. Falhas não viram zero. A melhora de estado exige
três amostras consecutivas, como no núcleo Linux.

`tools/build_windows.py` gera `policy.json` a partir de `HealthThresholds` e
`battery_band` do núcleo existente. Esses limites compartilhados não são uma
segunda configuração manual. Limites adicionais de commit/CPU/disco são regras
de triagem Windows, não benchmarks nem limites térmicos universais.

Nada é encerrado, pausado ou limpo automaticamente: não há esvaziamento de
working sets, remoção de dados nem limpeza no login. O diagnóstico de
temporários não certifica abandono: só mostra até 1000 arquivos diretamente
em cada pasta conhecida, sem recursão. Encerrar um processo é sempre uma
escolha do usuário na aba **Consumidores**, descrita abaixo.

## Medição de disco do Windows

Em **Trabalho e disco**, use **Medir disco do Windows (36 s)** durante o fluxo
que você quer comparar. Na linha de comando, `Folego.ps1 -Inspect Storage`
usa o mesmo diagnóstico. A medição usa janelas de 3 s em um worker próprio e não
interrompe a atualização normal do Fôlego. Só uma medição pode estar ativa por
usuário e sessão. **Cancelar medição de disco** encerra a janela em andamento
sem publicar um resumo incompleto.

O painel identifica o disco físico do volume do Windows em vez de usar
a letra como nome de contador. Mostra a mediana das latências das janelas com
operações e a fila, as operações estimadas, RAM disponível, commit, indicadores
de paginação do sistema e os eventos `disk` 51/153 cujo caminho corresponde ao
dispositivo no boot atual, até 24 horas. Volume sem associação comprovada,
contador ausente e direção sem operações têm estados próprios. O disco físico
pode reunir I/O de outros volumes, e a paginação inclui arquivos mapeados.

Cada medição concluída salva um dos seis arquivos
`storage-diagnostic-0.json` a `storage-diagnostic-5.json` na pasta de dados.
O resumo inclui início e fim, tempo de preparo, duração e intervalos reais,
fontes, unidades, janelas válidas e CPU do processo durante a coleta. Ele não inclui linhas de
comando, números de série, IDs de volume nem mensagens completas de eventos.
Para comparar, use a mesma alimentação e o mesmo fluxo de trabalho, anote
quais aplicativos já estavam abertos e copie o resumo que quiser manter antes
que o Fôlego reutilize a vaga mais antiga.

## Guarda térmica e perfis do processador

A aba **Temperatura e CPU** mostra a zona atual e a máxima dos últimos 10
minutos, o limite do processador e o turbo do plano ativo, o perfil do Fôlego e
o último recibo.

| Perfil | Limite máximo do processador | Turbo (`PERFBOOSTMODE`) |
| --- | --- | --- |
| Normal | valores originais do usuário/fabricante | original |
| Fresco | 99% | desligado (0) |
| Contenção | 80% | desligado (0) |

Antes de escrever, o Fôlego grava em `thermal-<host>.json` um recibo `intended`
com os quatro valores originais (tomada/bateria × limite/turbo) e o plano;
depois relê os valores e só então marca `applied`. Trocar Fresco ↔ Contenção
conserva os originais do primeiro recibo. **Restaurar** devolve esses originais
somente no mesmo host e boot e se os valores atuais ainda forem os aplicados:
uma alteração de Handheld Companion, `powercfg` ou outro programa é preservada,
e o recibo fica para revisão. Resultado não confirmado vira `unknown`, pausa a
guarda e bloqueia repetição; **Conferir recibo** apenas compara por leitura.

Os limites sobrevivem a reinícios. Depois de um reset, o recibo é de outro boot:
nada é restaurado ou trocado automaticamente. **Adotar recibo de outro boot**,
com confirmação, aceita o recibo neste boot como escolha manual desde que os
valores atuais ainda sejam os aplicados; a seguir **Restaurar** funciona.

A **guarda automática** começa desligada e é habilitada por hardware com
confirmação. Enquanto ativa, lê a zona a cada 5 s. Sobe para Fresco quando a
média de 3 amostras chega a 80 °C ou uma amostra chega a 90 °C; em Fresco, a
média ≥ 80 °C leva a Contenção; volta aos originais após 60 amostras seguidas
(5 min) abaixo de 70 °C. Temperatura ilegível zera a evidência e nunca aciona
efeito. Perfis escolhidos à mão e recibos de outro boot nunca são alterados pela
guarda. Esgotado o orçamento de quatro trocas por hora, o perfil atual — o mais
fresco atingido — é mantido. Cada recibo automático guarda a temperatura e a
janela que o motivaram. Esses limites são regras de triagem para a zona ACPI
do Deck, não limites certificados do sensor, e **não comprovam que evitam
reinícios**: servem para registrar a evidência e reduzir os picos de turbo.

## Consumidores e processos órfãos

**Analisar consumidores** mede 2 s de CPU (em núcleos) e E/S por processo e
agrupa por executável. Agentes conhecidos (`claude`, `codex`, `node`,
`powershell`, `pwsh`, `cmd`, `conhost`, `python` e afins) cujo processo pai
terminou — ou cujo PID foi reutilizado por um processo mais novo —, sem janela,
aparecem como **agente-órfão**, com “em loop” quando usam ≥ 0,5 núcleo e
“ocioso há N min” quando o tempo de CPU não mudou desde uma análise anterior.

São sempre **protegidos**: sessão de serviços, outros usuários e dono não
comprovado, caminho ilegível, a lista de nomes protegidos (sistema, shell,
segurança, Steam, Handheld Companion, instaladores), o próprio Fôlego e a
cadeia que o iniciou, agentes com pai vivo ou janela, e árvores de instalador
(`msiexec`, TiWorker, setup). Com `Global\_MSIExecute` ativo, nenhum processo é
elegível. Outros processos do mesmo usuário aparecem como **consumidor** e
podem ser fechados só com confirmação.

Encerrar: a confirmação mostra caminho, linha de comando resumida, idade, CPU,
E/S e pai. O pedido gentil usa `taskkill` sem força (fecha as janelas do app);
processos só de console costumam recusar. **Forçar** exige uma tentativa
gentil registrada para o mesmo processo e uma nova confirmação; usa
TerminateProcess no mesmo handle em que o horário de início é conferido, contra
reutilização de PID. No ato, identidade, dono, caminho e proteções são
revalidados. Recibos (até 20) ficam em `processes-<host>.json`, junto do
rastreio limitado de ociosidade. `process-rules.json`, aberto por **Editar
listas**, acrescenta nomes de agentes e protegidos (protegido vence); não
existe encerramento automático.

## Inicialização e componentes da Microsoft

A aba **Inicialização** lista HKCU/HKLM Run, Run32, as pastas Startup do
usuário e comum e as tarefas de inicialização de pacotes, com origem, app
reconhecido (Copilot, Edge, OneDrive, Everything), estado e proteção, e destaca
o que mudou desde **Marcar revisão**. Desabilitar grava o mesmo valor
`StartupApproved` que Configurações → Aplicativos → Inicialização (ou o estado
“desabilitado pelo usuário” da tarefa de pacote): a entrada original continua
intacta. Instâncias abertas não são encerradas.

O Copilot desktop deste cartão inicia com `--win-session-start` sem aparecer em
`Win32_StartupCommand`. O relatório mostra instalação, entradas, instâncias e,
quando a instância veio da sessão sem entrada visível, avisa que o app pode
recriá-la. **Mostrar instâncias do Copilot na triagem** leva ao encerramento
confirmado; **Desinstalação oficial** abre Aplicativos instalados (o
desinstalador do Copilot é do sistema e pede administrador). Não há edição de
políticas de grupo nem remoção de pacotes.

As entradas `Steam Deck`, `Folego` e Segurança do Windows são preservadas; um
formato de aprovação desconhecido protege a entrada. Entradas da máquina (HKLM,
pasta comum) pedem a confirmação de administrador (UAC) desta mesma conta para
uma única alteração, com o mesmo recibo. Ao contrário dos perfis térmicos, a
restauração da inicialização vale **depois de reiniciar** — o efeito só aparece
no próximo login —, mas apenas se o valor atual ainda for o que o Fôlego gravou.

## Sequência de início (logon em série)

Todos os itens de logon disparando juntos estressam o SD e a APU logo no início da
sessão; os reinícios abruptos deste Deck coincidiram com disco 100% ocupado e zona
acima de 90 °C. Por pedido do usuário (17/11/2026), a **orquestração do início é
ligada por padrão e não pergunta antes**: a cada login, o Fôlego adota as entradas
de início do usuário (HKCU Run e pasta Startup do usuário) que o Windows iniciaria
em paralelo — pelo mesmo `StartupApproved` das Configurações, com recibo — e as
inicia depois do login, **uma por vez**. Entradas já desabilitadas, entradas da
máquina (exigem administrador) e as que o usuário devolveu ao Windows ficam como
estão; **Adicionar à sequência**, na aba **Inicialização**, adota manualmente
qualquer outra entrada elegível, inclusive da máquina (com UAC):

| Condição antes de cada item | Valor |
| --- | --- |
| Desktop assentado | 15 s depois de o Fôlego (já atrasado 30 s) obter a primeira leitura |
| CPU | ≤ 50% |
| Disco físico (`Win32_PerfFormattedData_PerfDisk_PhysicalDisk`, `_Total`) | ≤ 40% ocupado e fila ≤ 1 |
| Zona térmica | < 80 °C |
| Confirmação | duas leituras calmas seguidas, a cada 5 s |
| Intervalo | 20 s desde o item anterior |
| Tarefas de logon de terceiros | nenhuma em execução (como `\SteamDeck\Disco Linux - montar/unidades`) |

Enquanto organiza, uma janela pequena, que não rouba o foco, avisa “Fôlego está
organizando a inicialização — aguarde”, com o **tempo desde o boot** correndo, itens
feitos e restantes, o próximo item, a estimativa do restante e o que está sendo
aguardado. No fim mostra **“Sistema completamente inicializado em mm:ss”** (e uma
notificação). “Completamente” só vale depois do último item e de duas leituras calmas
sem tarefa de logon em execução; se o sistema não acalmar em 10 minutos, o aviso diz
“Inicialização concluída” com o motivo, para nunca prender o fim do início. A janela
some depois de 20 s ou em **Ocultar**; o resultado fica em Inicialização.

Leitura ausente nunca conta como calma. Sem janela de calma em 10 minutos, o item
**não é iniciado sob estresse**: fica registrado como adiado, com o motivo, e o
Fôlego avisa. No ato, o item precisa continuar adotado, desabilitado no Windows (se
alguém o reabilitou, não é iniciado em dobro) e com o mesmo comando da adoção (um
comando alterado não é executado às cegas). A sequência roda uma vez por boot no
início da sessão; se o Fôlego reiniciar no mesmo boot, só continua os itens ainda
não tratados. Pausar o monitoramento pausa a sequência.

`Steam Deck.lnk` (o dispatcher do cartão, dono da continuação do login), o próprio
Fôlego e a Segurança do Windows nunca entram; tarefas de pacote continuam com o
Windows. Uma entrada que já estava desabilitada fora do Fôlego pode ser adotada; ao
removê-la, continua como estava. **Remover da sequência** devolve a entrada ao
Windows pelo recibo e a adoção automática passa a respeitar essa escolha. Desabilitar
o início do próprio Fôlego com itens adotados pede confirmação, porque eles só
iniciam por ele.

**Serviços.** Com a orquestração ligada, depois do aviso de sistema inicializado o
Fôlego pede administrador (UAC) **uma vez** e muda os serviços automáticos de terceiros
(fora da pasta do Windows, como CodexSandbox, CoworkVM, Everything, usbipd, WSL e
edgeupdate) de Automático para **Automático (início atrasado)**: continuam iniciando,
mas fora do pico do login. Recibo antes de cada `sc.exe config`, leitura depois;
Defender, Segurança do Windows e serviços do próprio Windows nunca são alterados. Se o
UAC for recusado, a recusa fica registrada e não é repetida sozinha; **Aplicar agora o
início atrasado** em Opções tenta de novo.

**Opções** traz **Ligar/Desligar a orquestração automática** (desligar não desfaz o que
já foi organizado) e **Desfazer a orquestração**, que devolve ao Windows todas as
entradas adotadas e os serviços que ainda têm o valor gravado pelo Fôlego (com UAC) e
desliga o modo automático.

**Outros itens de logon** lista, sem alterar, as tarefas agendadas de logon de
terceiros (com atraso e nível), os serviços automáticos fora do Windows e as tarefas
de pacote, com o modo de início de cada serviço; os do Defender aparecem como
segurança. O Fôlego não altera tarefas agendadas: as do Disco Linux do cartão
continuam com o SDK, e a sequência espera por elas.

O Copilot desktop é baseado no Edge e usa o mecanismo de autolaunch do Edge
(`edge_autolaunch` no `Local State`): o próprio app grava ou remove o seu valor em
HKCU Run com `--win-session-start`. Por isso a entrada pode não estar lá quando se
procura e reaparecer depois; **mudanças desde a revisão** a destaca como nova, e ela
pode ser desabilitada ou adotada pela sequência.

O Fôlego inicia com a sessão por padrão (entrada própria `Folego` em HKCU Run) e
mantém o atalho **Fôlego** no menu Iniciar, recriado se tiver sido removido (um
atalho personalizado é preservado). Fixá-lo na lista principal do Iniciar é escolha
do usuário: o Windows não oferece API para isso.

## Como reverter cada ação

| Ação | Reverter no Fôlego | Sem o Fôlego |
| --- | --- | --- |
| Perfil Fresco/Contenção | **Restaurar os valores originais** (mesmo boot) ou **Adotar recibo** e depois Restaurar | `powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX <valor>` e `/setdcvalueindex …`, idem `PERFBOOSTMODE`, depois `powercfg /setactive SCHEME_CURRENT`; os originais estão no recibo `thermal-<host>.json` |
| Guarda automática | **Desabilitar guarda** (não troca os valores) | apagar não é necessário; desligada ela não age |
| Economia de energia | **Restaurar o plano registrado** | Opções de energia do Windows |
| Desabilitar inicialização | **Restaurar a última alteração** ou **Habilitar início** | Configurações → Aplicativos → Inicialização |
| Item na sequência de início | **Remover da sequência** (devolve ao Windows pelo recibo) | Configurações → Aplicativos → Inicialização |
| Orquestração inteira | **Desfazer a orquestração** em Opções | Inicialização nas Configurações; `sc.exe config <serviço> start= auto` (administrador) |
| Serviço em início atrasado | **Desfazer a orquestração** (UAC) | `services.msc` → Automático; o original está em `services-<host>.json` |
| Encerrar processo | não reversível: abra o app de novo | — |
| Listas de processos | editar/remover `process-rules.json` | — |

## Energia reversível

**Aplicar Economia** aceita somente os planos padrão conhecidos e um plano
Economia já existente. Não cria planos nem substitui configurações do fabricante.
**Restaurar** exige o mesmo host/boot e que o plano ativo ainda seja o aplicado
pelo recibo. Uma mudança de outro programa bloqueia a restauração. Isso evita
disputa com gerenciadores como Handheld Companion.

A proteção automática por carga começa **desligada**, com habilitação própria
por hardware: duas amostras na bateria com carga ≤10% permitem pedir Economia;
na tomada, a restauração segue o recibo. A condição é consultada novamente antes
do efeito. Essa regra Windows é distinta da proteção Linux por queda de tensão:
percentual de carga não comprova tensão segura nem evita um corte físico.
Não há alteração de voltagem, TDP, brilho, paginação, proteção ou suspensão.

Recibo `intended`/`unknown`, estado ilegível ou confirmação malsucedida bloqueiam
repetição. **Conferir recibo** apenas compara o plano atual, no mesmo host/boot,
com o original e o alvo; não repete a troca. Recibos de outro boot ou planos
divergentes requerem revisão manual preservando a evidência. Desligar o guarda
não restaura silenciosamente o plano nem apaga seu recibo.

## Estado, gravações e remoção

`settings.json` controla o início; `power-<host>.json` guarda preferência, orçamento
e recibo de energia por identidade física, com até 12 recibos anteriores;
`thermal-<host>.json` faz o mesmo para os perfis do processador (gravado só
quando um perfil muda ou a guarda é ligada/desligada); `processes-<host>.json`
guarda até 20 recibos de encerramento e o rastreio de ociosidade (gravado só
em análise ou ação manual); `startup-<host>.json` guarda até 30 recibos e a
última revisão de inicialização; `sequence-<host>.json` guarda os itens adotados (com o
comando completo, para iniciá-los), as entradas devolvidas pelo usuário e o resultado e o
tempo da última inicialização por boot; `services-<host>.json` guarda os recibos de início
atrasado; `appearance.json` guarda visualização, tema,
transparência e posições do widget; `latest-sample.json` conserva somente
a última amostra, substituída atomicamente no máximo uma vez por minuto.
Configurações acima de 1 MiB, schema desconhecido e campos essenciais inválidos
bloqueiam operações. Não há logs de sensores sem limite nem histórico de
comandos. Arquivos `.tmp` próprios somente existem durante a escrita atômica.

Para remover: desligue o início nas Opções, confira eventual recibo/plano,
saia pela bandeja e remova a instalação oficial. Preserve ou exporte o estado
até concluir a revisão. Não use limpeza ampla de AppData nem apague recibos
para contornar uma operação de energia incerta.

## Construir e verificar

No checkout canônico, com o ambiente headless já preparado:

```bash
.dev/venv-headless/bin/python tools/build_windows.py
./dev test-headless tests/test_windows_package.py
```

O destino oficial é `dist/folego-windows`; o construtor recusa sobrescrever um
destino existente. `manifest.json` registra versão, tamanhos e SHA-256 locais
para todos os arquivos, incluindo licença e política gerada. Isso não é uma
assinatura de editor. Não distribua configurações, credenciais ou recibos reais.

No Windows, `Test-Folego.ps1` exercita política, persistência e recuperação com
APIs de efeito simuladas e dados descartáveis, incluindo recibo/restauração do
perfil térmico com alteração por terceiro e outro boot, histerese e orçamento,
órfão × protegido, confirmação obrigatória e ida e volta do Copilot no
`StartupApproved`. `-ReplayCsv <arquivos>` reproduz CSVs do monitor leve do
cartão (`SteamDeck\logs-monitor\monitor-*.csv`) só pela lógica de decisão, sem
chamar APIs de energia; a CI usa as cópias de `tests/fixtures/windows`. `Folego.ps1 -Probe -NoStartup`
consulta APIs reais sem registrar início nem mudar energia. Um smoke próprio
pode usar `-NoStartup -DataRoot <pasta-descartável> -SmokeSeconds 5`; fecha só
essa janela/instância. No Deck com WMI frio, a primeira coleta pode passar de
20 s (o provedor de `Get-Volume` sozinho levou 12,7 s), e um smoke de 5 s
reprova sem defeito do app; a CI usa 25 s e o limite é 300 s. Windows PowerShell 5.1 e hardware físico têm aceites
separados das simulações no Linux e do runner Windows da CI.

## Fontes dos adaptadores

- [CPU](https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-getsystemtimes)
- [Memória física](https://learn.microsoft.com/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex)
- [Commit](https://learn.microsoft.com/windows/win32/api/psapi/nf-psapi-getperformanceinfo)
- [Energia e bateria](https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-getsystempowerstatus)
- [Plano ativo](https://learn.microsoft.com/windows/win32/api/powersetting/nf-powersetting-powergetactivescheme)
- [Capacidade de volumes locais](https://learn.microsoft.com/windows/win32/cimwin32prov/win32-logicaldisk)
- [Saúde de volumes](https://learn.microsoft.com/windows-hardware/drivers/storage/msft-volume) e [eventos de E/S](https://learn.microsoft.com/en-us/troubleshoot/windows-server/backup-and-storage/windows-server-mpio-troubleshooting)
- [Inicialização rápida do Edge](https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/startupboostenabled) e [modo IE](https://learn.microsoft.com/en-gb/lifecycle/faq/internet-explorer-microsoft-edge)
- [Eventos de inicialização e reinício](https://learn.microsoft.com/en-us/troubleshoot/windows-server/performance/troubleshoot-unexpected-reboots-system-event-logs)
- [Teclado virtual](https://support.microsoft.com/en-us/accessibility/windows/use-the-on-screen-keyboard-osk-to-type) e [alternância da área de trabalho](https://learn.microsoft.com/windows/win32/shell/shell-toggledesktop)
- [Observação nativa do mouse](https://learn.microsoft.com/windows/win32/winmsg/lowlevelmouseproc), [UI Automation fora da interface](https://learn.microsoft.com/dotnet/framework/ui-automation/ui-automation-threading-issues) e [envio de teclas](https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-sendinput)
- [Troca de plano](https://learn.microsoft.com/windows/win32/api/powersetting/nf-powersetting-powersetactivescheme)
- [HKCU Run](https://learn.microsoft.com/windows/win32/setupapi/run-and-runonce-registry-keys)
- [Leitura](https://learn.microsoft.com/windows/win32/api/powersetting/nf-powersetting-powerreadacvalueindex) e [escrita](https://learn.microsoft.com/windows/win32/api/powersetting/nf-powersetting-powerwriteacvalueindex) de configurações de energia
- [Limite máximo do processador](https://learn.microsoft.com/windows-hardware/customize/power-settings/processor-power-management-options) e [modo de turbo](https://learn.microsoft.com/windows-hardware/customize/power-settings/options-for-perf-state-engine-perfboostmode)
- [Tempos](https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes) e [E/S](https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-getprocessiocounters) por processo; [TerminateProcess](https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess)
- `StartupApproved` não tem documentação pública: o formato (primeiro byte ímpar = desabilitado, seguido do horário) é o que a tela de Configurações grava; formatos diferentes ficam protegidos.

O port está preparado para teste nativo; a implementação não comprova redução
de consumo, prevenção de reset, funcionamento da APU ou equivalência integral
com os adaptadores Linux. Perfis térmicos, encerramento de processos e
alterações de inicialização ainda não têm aceite físico no Deck.
