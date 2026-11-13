# Supervisão de entrada e acessibilidade

O Fôlego observa capacidades do host, apresenta evidências e pode reabilitar
entradas no KWin. No Steam Deck, a mesma política opcional pode restaurar dois
perfis de desktop conhecidos: trackpad da Steam e microfone interno. Ele
funciona sem PhaseZero, RetroFE, Docker ou Podman.
Integrações presentes acrescentam evidência ou impedem uma intervenção
concorrente. O reparo de perfil usa a API local da Steam ou `pactl`. A recuperação
específica da enumeração incompleta de áudio pode solicitar nova enumeração
pelo WirePlumber da sessão, com autorização própria e revalidação do responsável.
O diagnóstico preserva a privacidade da captura de áudio.
Uma solicitação **manual** pode chamar o backend registrado do responsável,
validando schema, propriedade, permissões e hashes antes do efeito. Não há
promessa de disponibilidade física universal.

## Capacidades por ambiente

| Ambiente/capacidade | Observação | Efeito suportado |
| --- | --- | --- |
| Linux com `/proc/bus/input/devices` legível | Inventário de entradas, identificação de dispositivos e ambiguidade | Nenhum diretamente no kernel |
| KDE/Wayland com API KWin disponível para o mesmo UID | Estado habilitado e capacidades do compositor | Somente `enabled=true` de uma entrada física identificada e com suporte à propriedade |
| Outro desktop, X11 ou sessão sem compositor acessível | Inventário disponível; fonte indisponível fica desconhecida | Sem reparo nativo; não há fallback que reinicie o desktop |
| Steam Deck Jupiter/Galileo observado por DMI | Toque ausente é indisponível; perfil de desktop da Steam e saídas mouse/teclado são consultados separadamente | Manual: reparador FTS registrado; automático: KWin e, quando conhecido, perfil `RetroFE Steam Deck Desktop` da Steam, sem trocar perfil durante jogo |
| Teclado virtual KWin | Disponibilidade, modo e visibilidade | Manual: abre explicitamente e verifica visibilidade, restaurando modo por toque; não digita nem registra texto |
| PulseAudio/PipeWire via `pactl` | Endpoint padrão, mute, ganho, perfil acp5x e ligações da cadeia física/AEC/BigLinux | Endpoint revisado e recuperação do perfil interno conhecido. Com opt-in separado, reenumeração WirePlumber no defeito identificado descrito abaixo |
| Controles | Enumeração no kernel e perfil da Steam quando API local está disponível | Manual: pede modo controle pela URI pública da Steam; o reparo automático de desktop não fecha a Steam |
| Dispositivo removido ou identidade duplicada | Ausente/ambíguo; baseline anterior preservado | Sem inventar dispositivo ou resetar barramento |

“Configuração observada” significa evidência de enumeração/configuração.
Não comprova que uma pessoa consegue mover, clicar, digitar, tocar, ouvir ou
falar. Leitor de tela, greeter SDDM, recuperação FTS, atalhos Steam e perfis de
jogo precisam de seus próprios responsáveis e validação física.

O incidente de 06/11 mostrou por que enumeração não basta: o KWin via o
controle e o PipeWire via a placa, mas a Steam havia selecionado o perfil
`RetroFE Steam Deck Gamepad` no desktop, sem saídas de mouse/teclado, e a placa
interna estava em `Pro Audio`. Os cartões agora mostram o perfil real e o
estado da guarda. `HiFi (Headset, Speaker)` salvo pelo PhaseZero apontava para
um fone ausente; quando a preferência de um responsável ativo diverge do perfil
interno, o Fôlego mostra o conflito e não inicia uma disputa de perfis.

## Usar e pausar

Na aba **acessibilidade**, cada cartão é um botão, acionável por clique, Tab e
Espaço. **Habilitar tudo** fica no topo; verificação, registro e opções ficam
fora da área de rolagem. **Verificar agora** mostra progresso, horário e resumo.
Verde significa configuração habilitada e verificada nesta sessão, com teste
físico pendente; amarelo significa conflito/falha ou evidência insuficiente.
O resultado explica cada capacidade. Um clique sozinho nunca produz verde.
O campo opcional de digitação não grava seu conteúdo. **Solicitar reparo** aparece
somente quando há um plano nativo específico. O resumo da central leva à aba.
I/O de coleta e comandos ficam fora do loop gráfico.

**Registrar configuração para preservar** guarda somente entradas identificadas
e habilitadas. Um PhaseZero registrado recebe `capture` para preservar suas
próprias preferências; FTS presente e habilitado pode usar seu `--persist`.
Essa rotina pode solicitar autenticação, preserva arquivos pessoais e não
certifica a tela de login. Não amplia grants nem habilita novos executores.

Antes da autenticação de FTS, o campo de teste recebe foco e o owner precisa
confirmar seu teclado nativo visível. Ele mantém o modo temporário de abertura
durante a janela de senha, acompanha a troca de foco e restaura o modo anterior
ao terminar. O watcher do owner cede pela mesma trava, sem disputar o modo.
Sem painel utilizável, a autenticação não é solicitada. Senha permanece no
diálogo do sistema e nunca passa pelo Fôlego. Exige as APIs `recover-touch` e
`persist-touch` do owner atualizado e seu watcher carregado.

O card **Teclado virtual** permanece disponível quando uma operação anterior
está pendente: abrir o painel explicitamente é uma saída de emergência
independente do reparo de hardware. Isso não encerra nem repete o ID incerto.
Cada operação pendente protege as capacidades que pode afetar. Uma solicitação
ao owner de entrada abrange todas as entradas do protocolo, preservando o reparo
independente de áudio e microfone. Planos legados com escopo incompleto mantêm
proteção de todas as capacidades. **Habilitar tudo** apresenta o resultado por
capacidade e preserva cada operação pendente.
Enquanto uma rotina está em voo, o próprio owner mantém o teclado durante a
autenticação. O reparo FTS compartilha o orçamento durável de entrada: 60 s de
intervalo e no máximo três intervenções por hora; disjuntor bloqueia repetição.

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

No Deck, a guarda aprende cada perfil somente depois de duas observações
saudáveis, com a política habilitada. A referência da Steam inclui o hash do
template Desktop instalado; a do microfone registra a placa, o perfil interno
e se a entrada padrão é a física ou `mic-biglinux`. Duas observações da falha
específica são necessárias antes de agir. Antes do efeito, o monitor revalida
boot, identidade, perfil e responsável pertinente. Trackpads dependem de
KWin, jogo e leases de entrada. Microfone depende da cadeia e da preferência
de áudio, podendo ser diagnosticado e recuperado com KWin indisponível.
Operações antigas de outra capacidade não escondem esses dois diagnósticos.
O reparo tem limite de três tentativas por hora e intervalo de 120 s por perfil.
Resultado incerto abre um disjuntor e nunca é repetido automaticamente.
Mute, fonte externa, outro perfil da Steam, template alterado ou API ausente
ficam para revisão; o Fôlego não interpreta isso como defeito recuperável.

### Enumeração incompleta do microfone interno

Em 11/11, o ALSA/UCM reconhecia a captura interna, enquanto o WirePlumber
enumerava somente `off`, `pro-audio` e um perfil de fone indisponível. A
preferência persistida continuava `HiFi (Mic, Speaker)`. O microfone virtual
existia e estava sem mute, mas faltava a fonte física. Esse conjunto agora
recebe o diagnóstico `audio-enumeration-incomplete` e um caminho de reparo.

Em 13/11, o perfil `HiFi (Mic, Speaker)` estava ativo e os PCMs ALSA livres,
com as rotas físicas ausentes após falha de abertura por dispositivo ocupado
no login. O diagnóstico `audio-nodes-missing-after-busy` usa a mesma opção de
recuperação. Confere os erros de captura e reprodução acp5x no journal do boot,
com PID/UID/unit do PipeWire atual e timestamps posteriores ao início dos dois
responsáveis atuais. Leitura limitada a 64 registros e 64 KiB, com prazo de 2 s.
Também exige a preferência salva, todos os PCMs internos livres e ausência de
outra rota física. Revalida a falha e o uso do áudio imediatamente antes do
efeito. Históricos antigos, incompletos ou indisponíveis deixam o caso em revisão.

A opção **Reenumerar áudio automaticamente após falha conhecida** fica na aba
acessibilidade. Novas instalações e configurações migradas começam com essa
opção desligada. Para habilitar pelo terminal, com a supervisão já habilitada,

```bash
./dev run accessibility audio-reprobe-enable --confirmar --json
./dev run accessibility audio-reprobe-disable --confirmar --json
```

O monitor exige duas amostras distintas e recentes do mesmo boot e referência
saudável previamente aprendida. Lacunas de mais de 30 s reiniciam a confirmação.
O reparo manual pelo cartão pode usar a preferência persistida comprovada.
Reenumeração e troca de perfil compartilham três tentativas por hora e intervalo
de 120 s. Relógio regressivo preserva o orçamento. Resultado incerto pausa
novas solicitações até consulta e revisão.

Quando houver mais de uma operação pendente, o seletor da aba permite consultar
cada ID. A consulta confirma o estado atual e preserva o efeito já solicitado.
Uma recuperação manual de microfone com resposta perdida pode ser conciliada
depois de comprovado o encerramento do solicitante e a cadeia saudável estável.
**Rearmar guarda de microfone/trackpads** aparece para o disjuntor correspondente
e confere referência saudável e ausência de pendência nessa capacidade.

Antes de solicitar `systemctl --user restart wireplumber.service`, o Fôlego
confere o fragmento de sistema, ausência de drop-ins, executável root-owned,
boot/PID/starttime e cgroup contendo apenas esse processo. Verifica a captura
ALSA, a preferência salva, outras placas e fontes físicas e o owner opcional
de áudio. Outro uso comprovado ou identidade insuficiente bloqueia o efeito.
A reenumeração pode causar interrupção breve do áudio da sessão. O resultado
exige retorno estável do perfil e da cadeia física → echo-cancel → mic-biglinux.
Uma fonte virtual isolada permanece insuficiente para concluir sucesso.

Se um reparo de perfil ficar incerto, consulte o ID e reconcilie **sem repetir**:

```bash
./dev run accessibility profile-reconcile ID --confirmar --json
./dev run accessibility profile-rearm touchpad --confirmar --json
./dev run accessibility profile-rearm microphone --confirmar --json
./dev run accessibility profile-capture touchpad --confirmar --json
```

Rearme apenas depois de confirmar o estado saudável e resolver o conflito.
Se uma atualização legítima alterar o template Desktop ou a preferência de
entrada padrão, revise o novo estado saudável e use `profile-capture` para
registrar uma nova referência; esse comando não troca perfis nem rearma um
disjuntor aberto. Há a mesma opção para `microphone`.
O API CEF da Steam usada para consultar/selecionar o perfil é privada ao cliente
instalado; se ela mudar, o estado fica desconhecido e não há troca por heurística.
Não há teste automático do gesto físico no trackpad nem de voz captada.

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

## Solicitação manual por capacidade

O fluxo da GUI prepara um plano fresco e executa exatamente seu ID. Pela CLI:

```bash
./dev run accessibility activation-plan keyboard --json
./dev run accessibility activation-plan all --json
./dev run accessibility activate --plan '{...objeto plan completo...}' --confirmar --json
./dev run accessibility activation-plan all --save-profile --json
./dev run accessibility save-profile --plan '{...objeto plan completo...}' --confirmar --json
./dev run accessibility activation-reconcile ID --json
```

As chaves são `keyboard`, `pointer`, `touchpad`, `touch`, `gamepad`,
`virtual-keyboard`, `audio`, `microphone` e `all`. Áudio tem resultado independente
de conflitos de entrada; resposta perdida interrompe efeitos posteriores e
bloqueia nova operação. O recibo privado registra etapas/ID, sem teclas ou áudio.
Reconciliação nunca reaplica rotina sem prova de término.

Quando presente, PhaseZero recebe apenas **`reconcile-input`**, que não restaura
áudio nem altera Steam ou modo do teclado. Registro antigo sem essa API falha
explicitamente: atualize o responsável, sem contornar o bloqueio. Lease/jogo
ativo ou pendente impede a chamada. A espera conservadora do monitor automático
permanece; a ação manual encaminha o pedido ao responsável conhecido, em vez
de esperar indefinidamente só porque o observador está aberto.

Se o FTS3528 não aparece no kernel, habilitar uma propriedade KWin não resolve.
O reparador opcional do owner verifica modelo Jupiter, adapter I²C dedicado,
outros clientes e processos antes de reanexar o barramento FTS. USB e Valve HID
ficam fora do alvo. Ausência, incompatibilidade, autenticação recusada ou falha
continuam amarelas; não existe garantia de recuperar hardware defeituoso.

## Reparo nativo e resultado incerto

O reparo manual precisa de plano atual e confirmação. O JSON de `plan` contém
`plans`; passe **um objeto dessa lista** ao comando:

```bash
./dev run accessibility repair --plan '{...plano completo...}' --confirmar --json
./dev run operation ID --json
./dev run accessibility reconcile ID --json
```

O coordenador existente serializa intervenções e registra intenção antes do
efeito. O ato confere novamente boot, dono único do barramento e UID, identidade
do dispositivo, responsáveis, política e orçamento. Nesse fluxo manual KWin,
o único efeito é reabilitar a propriedade de uma entrada no compositor; segue-se
uma nova leitura. Repetir
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

No **reparo automático KWin**, integrações legadas são conservadoras: registro PhaseZero inválido/desconhecido
ou guardião registrado ativo bloqueia o reparo; registro válido e inativo permite
o backend nativo. Recuperações RetroFE pendentes bloqueiam. Essas aplicações
não são alteradas nem seus serviços interrompidos. No host em que os guardiões
permanecem ativos, o Fôlego observa e aguarda. A guarda separada de perfis
Steam/microfone verifica o dono e a preferência de cada perfil; um bloqueio
antigo de outra capacidade não a desliga.

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
