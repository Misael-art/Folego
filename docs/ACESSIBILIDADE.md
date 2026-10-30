# Supervisão de entrada e acessibilidade

O Fôlego observa capacidades do host, apresenta evidências e pode reabilitar
entradas no KWin. Ele funciona sem PhaseZero, RetroFE, Docker ou Podman.
Integrações presentes acrescentam evidência ou impedem uma intervenção
concorrente; não substituem o backend nativo nem executam caminhos registrados
por terceiros. Não há promessa de disponibilidade física universal.

## Capacidades por ambiente

| Ambiente/capacidade | Observação | Efeito suportado |
| --- | --- | --- |
| Linux com `/proc/bus/input/devices` legível | Inventário de entradas, identificação de dispositivos e ambiguidade | Nenhum diretamente no kernel |
| KDE/Wayland com API KWin disponível para o mesmo UID | Estado habilitado e capacidades do compositor | Somente `enabled=true` de uma entrada física identificada e com suporte à propriedade |
| Outro desktop, X11 ou sessão sem compositor acessível | Inventário disponível; fonte indisponível fica desconhecida | Sem reparo nativo; não há fallback que reinicie o desktop |
| Steam Deck Jupiter/Galileo observado por DMI | Toque ausente é indisponível; saída de ponteiro do controle é distinguida de gesto físico | Mesma operação restrita do KWin |
| Teclado virtual KWin | Disponibilidade e modo informado | Sem alterar modo, atalhos ou abrir/digitar automaticamente |
| PulseAudio/PipeWire via `pactl` | Enumeração de endpoints; fontes monitor excluídas do cartão de microfone | Sem capturar, reproduzir, mudar rota ou mute |
| Dispositivo removido ou identidade duplicada | Ausente/ambíguo; baseline anterior preservado | Sem inventar dispositivo ou resetar barramento |

“Configuração observada” significa evidência de enumeração/configuração.
Não comprova que uma pessoa consegue mover, clicar, digitar, tocar, ouvir ou
falar. Leitor de tela, greeter SDDM, recuperação FTS, atalhos Steam e perfis de
jogo precisam de seus próprios responsáveis e validação física.

## Usar e pausar

Na aba **acessibilidade**, os cartões combinam ícones e texto, com fontes e
motivos de espera. **Verificar agora**, **Solicitar reparo** e **Verificar
operação pendente** usam o mesmo supervisor da CLI. O resumo da central leva
à aba. I/O de coleta e comandos ficam fora do loop gráfico.

```bash
./dev run accessibility status --json
./dev run accessibility plan --json
./dev run accessibility enable --confirmar
./dev run accessibility install --confirmar
```

Não há reparo automático habilitado por padrão numa instalação nova. O **início
do aplicativo e da observação com a sessão** fica ligado por padrão; a aba
**opções** e `startup enable/disable --confirmar` controlam essa preferência.
Desligar afeta o próximo login e não sinaliza um monitor já aberto. `enable` ativa
somente a política de entrada; `install` cria/inicia a unit **do usuário**
`folego-accessibility.service`, vinculada a `graphical-session.target`.
O processo é independente da janela Qt e não requer Qt. Uma unit pessoal
preexistente ou caminho simbólico é preservado. O executável é o ambiente que
executou a instalação: após mover/remover esse ambiente, revise a unit.

O ciclo padrão é de dez segundos. Fontes externas têm limite individual de
um segundo, total de coleta de oito segundos e saída limitada. A identidade do
monitor residente inclui boot/PID/starttime; um arquivo antigo sozinho não
significa monitor ativo. As amostras expiram em vinte segundos, inclusive após
suspensão: usa-se o [CLOCK_BOOTTIME do Linux](https://docs.python.org/3.14/library/time.html#time.CLOCK_BOOTTIME).
O autostart gráfico segue a [especificação XDG](https://specifications.freedesktop.org/autostart/latest/),
com `Hidden=true` para desligar e sem sobrescrever uma entrada pessoal.

A política aprende entradas reparáveis **já habilitadas**, somente numa leitura
completa e sem responsáveis bloqueando. Dispositivos saudáveis conectados depois
são incorporados; os desconectados continuam registrados. Uma entrada que já
aparece desabilitada na primeira observação precisa de revisão/reparo manual
antes de se tornar baseline. O limite de 128 identidades exige revisão ao
atingir o teto; nada é descartado automaticamente.

Antes de desabilitar entradas intencionalmente:

```bash
./dev run accessibility disable --confirmar
```

Esse comando mantém a observação e suspende reparos automáticos. A pausa do
coletor de recursos, os presets e os grants de limpeza não controlam esta
política. Para remover a persistência, pause-a e execute:

```bash
systemctl --user disable --now folego-accessibility.service
```

Após conferir que é a unit gerenciada pelo Fôlego, ela pode ser removida de
`$XDG_CONFIG_HOME/systemd/user/` (padrão `~/.config/systemd/user/`), seguida de
`systemctl --user daemon-reload`. Não remova units de outros projetos.

## Reparo e resultado incerto

O reparo manual precisa de plano atual e confirmação. O JSON de `plan` contém
`plans`; passe **um objeto dessa lista** ao comando:

```bash
./dev run accessibility repair --plan '{...plano completo...}' --confirmar --json
./dev run operation ID --json
./dev run accessibility reconcile ID --json
```

O coordenador existente serializa intervenções e registra intenção antes do
efeito. O ato confere novamente boot, dono único do barramento e UID, identidade
do dispositivo, responsáveis, política e orçamento. O único efeito é reabilitar
a propriedade de uma entrada no compositor; segue-se uma nova leitura. Repetir
o mesmo ID consulta o resultado registrado.

Timeout, perda de resposta ou efeito não verificado ficam **desconhecidos**,
com disjuntor persistente. Reconciliação lê a configuração atual sem reaplicar
o efeito. Ela não certifica funcionalidade física nem rearma silenciosamente.
Há intervalo mínimo de sessenta segundos e até três tentativas por hora,
persistidas antes do efeito. Nova demanda após três reparos abre o disjuntor:
investigue a aplicação que está desfazendo a configuração.

Depois de resolver a causa, reconciliar operações pendentes e verificar as
entradas habilitadas, use **Rearmar após revisão** ou:

```bash
./dev run accessibility rearm --confirmar
```

Estado privado, schema desconhecido, corrupção, relógio regressando ou falta
de evidência protegem o recurso. Não apague diário, baseline ou leases para
forçar uma aprovação. Estado do módulo fica em
`$XDG_STATE_HOME/folego/accessibility/` (padrão `~/.local/state/folego/accessibility/`),
com arquivos privados e gravação atômica. O diário e a trava são os comuns do
Fôlego. Não se coletam teclas, áudio ou variáveis de ambiente de containers.

## Coordenação com aplicações

O protocolo cooperativo serve a qualquer aplicação do mesmo usuário, inclusive
launchers e ferramentas de mercado. Antes de usar/reparar entradas, publique a
propriedade e espere o comando confirmar aquisição. Faça a operação e então
libere. O PID deve ser o processo duradouro responsável, **não** a CLI transitória:

```bash
./dev run accessibility lease --provider meu-launcher --pid "$$" --state using --confirmar --json
# Execute a atividade somente após a aquisição bem-sucedida.
./dev run accessibility lease --provider meu-launcher --pid "$$" --state released --confirmar --json
```

Use `repairing` antes de uma alteração de recuperação. Declare filhos via
`--child-pid PID`, repetível; o launcher é responsável por registrar todos os
consumidores relevantes. O mesmo slot estável por provider evita criar um
arquivo a cada execução. Há até 32 providers ativos e 64 filhos por lease. Propriedade
inclui boot/PID/starttime, sem expiração por idade. Filhos vivos ou desconhecidos
são preservados, inclusive se omitidos numa atualização, e impedem liberação.

Para comandos próprios, há um launcher que publica a identidade do filho antes
de permitir sua execução e acompanha os consumidores conhecidos:

```bash
./dev run accessibility lease-run --provider meu-launcher -- comando argumento
```

Nesse fluxo, o lease exige conclusão explícita: a morte do launcher não libera
automaticamente descendentes cuja situação ficou incerta. Uma execução iniciada
sem prova de conclusão retorna desconhecido; consulte/reconcilie o mesmo lease
em vez de repetir o comando. Aplicações que não usam esse launcher/protocolo
continuam sujeitas aos limites de observação descritos abaixo.

Leases explicitamente liberados e validados saem dos slots ativos, sob a trava
comum, para `leases-closed/`. Preserva-se o recibo mais recente por provider;
documentos inválidos, filhos vivos/desconhecidos e reparos incertos não expiram.

As publicações e o reparo usam a mesma trava do coordenador. Outro dono ativo
ou desconhecido impede aquisição/reparo. Se dono e filhos de um lease `using`
estão comprovadamente encerrados, o uso terminou; `repairing` sem dono vivo
continua incerto porque pode ter deixado efeitos. Após conferir os responsáveis
encerrados e a configuração atual habilitada, a reconciliação explícita é:

```bash
./dev run accessibility lease-reconcile LEASE_ID --confirmar --json
```

Integrações legadas são conservadoras: registro PhaseZero inválido/desconhecido
ou guardião registrado ativo bloqueia o reparo; registro válido e inativo permite
o backend nativo. Recuperações RetroFE pendentes bloqueiam. Essas aplicações
não são alteradas nem seus serviços interrompidos. No host em que os guardiões
permanecem ativos, o Fôlego observa e aguarda.

Quando Docker/Podman estão disponíveis, inventário inacessível, schema inesperado,
container privilegiado ou exposição de `/dev/input`, `/dev/hidraw`, `/dev` ou `/`
bloqueiam intervenções. Não se para container nem se revoga acesso ao dispositivo.

Processos que não participam do protocolo podem mudar de estado após uma
observação. Inventário de containers não cobre todos os daemons remotos,
descritores ou capturas exclusivas de outras aplicações. Portanto, ausência de
bloqueador observado **não certifica exclusividade global**. A atuação limitada,
o orçamento e o disjuntor reduzem conflitos; cobertura coordenada exige que os
outros writers adotem o protocolo. Não há descoberta universal de donos nem
reinício global de KWin, Steam, USB ou drivers como contingência.

## Validação e limites

O monitor mantém uma leitura incremental limitada do diário comum (256 KiB e
10 ms por etapa, linhas de até 64 KiB). Arquivo alterado/incompleto, corrupção
ou índice ainda não validado bloqueiam efeitos; a execução continua revalidando
no coordenador. Não se apagam intenções ou se compacta silenciosamente o diário.

O painel e a bandeja avisam sobre monitor ausente, disjuntor aberto e espera
prolongada (cinco minutos). Notificações locais têm intervalo limitado. O anel
diagnóstico conserva até 32 transições de boot, compositor, dispositivos, estado
e lacunas de observação. Ele não certifica testes físicos e não registra teclas
ou áudio:

```bash
./dev run accessibility transitions --json
```

Os testes usam árvores e filhos próprios e cobrem hosts sem integrações, fontes
ausentes, desktops sem backend, propriedade, containers, hotplug, identidade,
timeout, orçamento, diário e estados da GUI. Não desligam entradas reais para
produzir uma falha. Qt offscreen não certifica compositor; uma consulta KWin não
certifica toque físico. Cold boot, login, suspend/resume, dock/USB, uso Steam e
ensaio prolongado continuam sendo aceites específicos do alvo real.
