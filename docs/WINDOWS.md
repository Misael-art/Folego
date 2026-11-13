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

## Recursos e limites do port

| Função | Backend e comportamento Windows |
| --- | --- |
| RAM e CPU | GlobalMemoryStatusEx e diferença entre GetSystemTimes; CPU exige duas amostras. |
| Memória comprometida | GetPerformanceInfo: uso e limite de commit; não é tamanho nem uso isolado de pagefile. |
| Disco do aplicativo | Espaço livre pela API Win32, fila e saúde por consultas Windows. Sem varredura recursiva automática. |
| Bateria/carregador | GetSystemPowerStatus; ausência/255 permanece desconhecido. Sem inferir tensão ou saúde do carregador. |
| Temperatura | Zonas ACPI oferecidas por root/wmi; nome e limites passivo/crítico fornecidos pelo sensor. Não equivale automaticamente à APU/GPU. |
| Alertas | Pressão observada, bateria baixa e desconexão, com intervalo mínimo de cinco minutos por tipo. |
| Diagnósticos manuais | Até 25 processos por RAM, amostra superficial limitada de temporários e até 12 eventos de corte/reinício. Não coleta comandos/credenciais. |
| Energia | Planos oficiais existentes, intenção durável antes da troca, confirmação por leitura, recuperação e até quatro trocas por hora. |
| Inicialização básica | O desktop Trabalho do cartão é preservado; abre a tela oficial Aplicativos de inicialização. Não desabilita serviços ou itens desconhecidos por analogia com Plasma. |
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

O monitor não fecha agentes ou aplicações, não pausa processos, não esvazia
working sets, não remove dados e não executa limpeza no login. O diagnóstico
de temporários não certifica abandono: só mostra até 1000 arquivos diretamente
em cada pasta conhecida, sem recursão. Para reduzir carga, o usuário decide
o que encerrar pelo canal oficial da aplicação.

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
`latest-sample.json` conserva somente
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
APIs de efeito simuladas e dados descartáveis. `Folego.ps1 -Probe -NoStartup`
consulta APIs reais sem registrar início nem mudar energia. Um smoke próprio
pode usar `-NoStartup -DataRoot <pasta-descartável> -SmokeSeconds 5`; fecha só
essa janela/instância. Windows PowerShell 5.1 e hardware físico têm aceites
separados das simulações no Linux e do runner Windows da CI.

## Fontes dos adaptadores

- [CPU](https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-getsystemtimes)
- [Memória física](https://learn.microsoft.com/windows/win32/api/sysinfoapi/nf-sysinfoapi-globalmemorystatusex)
- [Commit](https://learn.microsoft.com/windows/win32/api/psapi/nf-psapi-getperformanceinfo)
- [Energia e bateria](https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-getsystempowerstatus)
- [Plano ativo](https://learn.microsoft.com/windows/win32/api/powersetting/nf-powersetting-powergetactivescheme)
- [Troca de plano](https://learn.microsoft.com/windows/win32/api/powersetting/nf-powersetting-powersetactivescheme)
- [HKCU Run](https://learn.microsoft.com/windows/win32/setupapi/run-and-runonce-registry-keys)

O port está preparado para teste nativo; a implementação não comprova redução
de consumo, prevenção de reset, funcionamento da APU ou equivalência integral
com os adaptadores Linux.
