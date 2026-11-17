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
| Barra de tarefas (padrão) | Indicadores vivos na área de notificação: um ponto de estado e ícones com o número de CPU, temperatura, RAM e bateria, na cor de saúde e com uma faixa na cor do tema. A dica de cada ícone traz a leitura completa. |
| Mini horizontal | Faixa de 384 × 46 px (escala com o DPI): estado, CPU, temperatura, RAM e bateria, expandir e menu. |
| Widget compacto | Cartão de 268 px com anel de folga, estado, RAM livre, CPU, zona térmica, bateria e perfil térmico. |
| Lateral esquerda / direita | Barra na borda da área de trabalho, 112–128 px de largura e altura total, como no Linux. |
| Barra superior | Faixa no topo da área de trabalho: 120 px em telas a partir de 900 px de largura, 190 px nas menores. |

Na **Barra de tarefas**, um clique (esquerdo ou direito) em qualquer indicador abre o
menu de funções: resumo atual, abrir a central, aplicar Fresco/Contenção ou
restaurar os originais (com a mesma confirmação da central), analisar consumidores,
inicialização, pausar, visualizações, tema, transparência, Gerenciador de Tarefas
e sair. O resultado de uma ação iniciada ali aparece como notificação, sem abrir a
central. Os indicadores aparecem neutros ("–") até a primeira leitura. O Windows 11
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
os padrões valem só na sessão, sem sobrescrevê-lo. Os atalhos de área de trabalho,
cotas de IA e regras do KWin do widget Linux não têm equivalente validado no Windows.

## Recursos e limites do port

| Função | Backend e comportamento Windows |
| --- | --- |
| RAM e CPU | GlobalMemoryStatusEx e diferença entre GetSystemTimes; CPU exige duas amostras. |
| Memória comprometida | GetPerformanceInfo: uso e limite de commit; não é tamanho nem uso isolado de pagefile. |
| Disco do aplicativo | Espaço livre pela API Win32, fila e saúde por consultas Windows. Sem varredura recursiva automática. |
| Bateria/carregador | GetSystemPowerStatus; ausência/255 permanece desconhecido. Sem inferir tensão ou saúde do carregador. |
| Temperatura | Zonas ACPI de root/wmi; sem elas (usuário comum), a mesma zona pela classe CIM `Win32_PerfFormattedData_Counters_ThermalZoneInformation`, que independe do idioma dos contadores. Limites passivo/crítico só quando o sensor os informa. Não equivale automaticamente à APU/GPU. |
| Perfis térmicos | `PROCTHROTTLEMAX` e `PERFBOOSTMODE` do plano ativo existente (tomada e bateria) por PowerRead/PowerWrite + PowerSetActiveScheme. Recibo antes, leitura depois, até quatro trocas por hora. Guarda automática opcional, desligada por padrão. |
| Consumidores e órfãos | Toolhelp + GetProcessTimes/GetProcessIoCounters em duas amostras de 2 s; dono pelo token; linha de comando resumida sem segredos. Encerramento só manual, confirmado e revalidado. |
| Inicialização | HKCU/HKLM Run, Run32, pastas Startup e tarefas de pacote; desativação pelo mesmo `StartupApproved` das Configurações, com recibo e restauração. |
| Identidade física | UUID SMBIOS; se o firmware informa um UUID de preenchimento (o Deck LCD informa `FFFFFFFF-…`), número de série da BIOS e depois da placa. Hosts com UUID válido mantêm o identificador anterior. |
| Alertas | Pressão observada, bateria baixa e desconexão, com intervalo mínimo de cinco minutos por tipo. |
| Diagnósticos manuais | Até 25 processos por RAM, amostra superficial limitada de temporários e até 12 eventos de corte/reinício. A triagem de consumidores mostra linhas de comando truncadas, com tokens/chaves/senhas ocultos, e não as grava. |
| Energia | Planos oficiais existentes, intenção durável antes da troca, confirmação por leitura, recuperação e até quatro trocas por hora. |
| Componentes do sistema | Windows Update, Otimização de Entrega, Defender, UAC e serviços: só detecção e a página oficial correspondente. Nada é alterado pelo app. |
| Manutenção de armazenamento | Reutiliza o painel do cartão quando presente; fora dele abre as Configurações do Windows. |
| Linux PSI, zram e tmpfs | Não são métricas equivalentes no Windows; não há leitura sintética ou verde presumido. |
| KWin, systemd, áudio/entrada e IA | Reparos e integrações com owners/contas Linux não têm adaptador Windows validado e não são executados. |
| TDP, ventoinha, drivers, EFI e discos Linux | Permanecem com os responsáveis próprios; nenhum acesso EC/SMU ou troca de driver é feito pelo port. |

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

## Como reverter cada ação

| Ação | Reverter no Fôlego | Sem o Fôlego |
| --- | --- | --- |
| Perfil Fresco/Contenção | **Restaurar os valores originais** (mesmo boot) ou **Adotar recibo** e depois Restaurar | `powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR PROCTHROTTLEMAX <valor>` e `/setdcvalueindex …`, idem `PERFBOOSTMODE`, depois `powercfg /setactive SCHEME_CURRENT`; os originais estão no recibo `thermal-<host>.json` |
| Guarda automática | **Desabilitar guarda** (não troca os valores) | apagar não é necessário; desligada ela não age |
| Economia de energia | **Restaurar o plano registrado** | Opções de energia do Windows |
| Desabilitar inicialização | **Restaurar a última alteração** ou **Habilitar início** | Configurações → Aplicativos → Inicialização |
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
última revisão de inicialização; `appearance.json` guarda visualização, tema,
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
reprova sem defeito do app; a CI usa 25 s. Windows PowerShell 5.1 e hardware físico têm aceites
separados das simulações no Linux e do runner Windows da CI.

## Fontes dos adaptadores

- [CPU](https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-getsystemtimes)
- [Memória física](https://learn.microsoft.com/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex)
- [Commit](https://learn.microsoft.com/windows/win32/api/psapi/nf-psapi-getperformanceinfo)
- [Energia e bateria](https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-getsystempowerstatus)
- [Plano ativo](https://learn.microsoft.com/windows/win32/api/powersetting/nf-powersetting-powergetactivescheme)
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
