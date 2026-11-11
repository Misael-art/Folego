# Base funcional do host Jupiter e diagnóstico recorrente

Atualizado em 11/11/2026 por solicitação do operador. Este guia descreve o
Steam Deck LCD Jupiter com BigLinux/Manjaro, KDE Plasma e Wayland. A base
preserva login, entrada, rede, áudio, energia, armazenamento e diagnóstico
durante o desenvolvimento com agentes. Os nomes das units precisam ser
reconsultados após atualização da distribuição ou mudança de host.

## Estado observado e requisitos físicos

- Kernel `6.18.49-1-MANJARO`, plataforma Jupiter e aproximadamente 14,5 GiB de
  RAM utilizável pelo Linux. A GPU usa memória compartilhada.
- Raiz e HOME em Btrfs no NVMe de 932 GiB. A consulta de 11/11 mostrou 118 GiB
  livres e 88% ocupado. Capacidade livre e integridade exigem consultas distintas.
- `/tmp` e `/run/user/1000` são tmpfs. `/var/tmp` fica no Btrfs. Builds, ambientes
  e temporários grandes precisam de destino persistente comprovado.
- Swap observada em zram de cerca de 6,9 GiB e arquivo de 512 MiB, administrada
  por `systemd-swap.service`. Seu tamanho precisa ser reavaliado conforme a carga.
- Energia, bateria, carregador, refrigeração, firmware e drivers fazem parte da
  base física. Perfil de economia depende do serviço que aplica o perfil.
- Kernel/initramfs/firmware compatíveis, drivers NVMe/Btrfs, AMDGPU/Mesa,
  ALSA/acp5x/UCM, Wi-Fi e entrada precisam permanecer instalados e carregáveis.
  GPU, ventilador e controles ALSA possuem componentes fora do systemd.
- PAM, contas/grupos, permissões de dispositivos, certificados TLS, resolução
  DNS, horário e bibliotecas da distribuição precisam permanecer coerentes.
  Atualizações da base rolling seguem o fluxo da distribuição.
- A margem de RAM, swap, CPU, temperatura e I/O depende da carga concorrente.
  O inventário atual com agentes abertos representa uma sessão de trabalho.
  Uma medição de repouso requer uma janela de observação própria.

## Serviços de sistema que compõem a base deste uso

As units de inicialização abaixo incluem serviços transitórios, mounts e
sockets. A disponibilidade de uma capacidade pode vir de ativação por D-Bus
ou socket. A política de habilitação deve preservar esse caminho.

| Capacidade | Units ou componentes a preservar | Verificação funcional |
| --- | --- | --- |
| Inicialização e arquivos | PID 1/systemd, `sysinit.target`, `basic.target`, `local-fs.target`, mounts usados, `systemd-remount-fs.service` | Raiz/HOME acessíveis, escrita persistente e espaço disponível |
| Preparação do sistema | `systemd-modules-load.service`, `systemd-sysctl.service`, `systemd-tmpfiles-setup*.service`, serviços de contas/random seed pertinentes | Dispositivos, diretórios de runtime e permissões preparados |
| Hardware e hotplug | `systemd-udevd.service`, seus sockets e `systemd-udev-trigger.service` | Entrada, armazenamento, rede e áudio enumerados |
| Comunicação entre serviços | `dbus-broker.service` e `dbus.socket`, com alias `dbus.service` conforme a distribuição | Barramento do sistema acessível |
| Login, sessão e acesso a dispositivos | `systemd-logind.service`, `systemd-user-sessions.service`, PAM e `user@UID.service` | Login/saída, seat, runtime privado e acesso do usuário aos dispositivos |
| Autorização administrativa | `polkit.service` e seu mecanismo de autenticação | Solicitação legítima de privilégio chega ao agente da sessão |
| Registros e recuperação | `systemd-journald.service`, sockets e `systemd-journal-flush.service` quando configurado | Journal legível e persistente dentro do orçamento |
| Rede de trabalho | `NetworkManager.service` e `wpa_supplicant.service` neste host, além de DNS funcional | Wi-Fi/rede, resolução e HTTPS respondem |
| Horário | `systemd-timesyncd.service`, ou o provedor NTP deliberadamente escolhido | Horário correto e sincronização confirmada |
| Bateria e fontes de alimentação | `upower.service` | Carga, descarga e fonte externa consultáveis |
| Perfis de energia BigLinux | `power-profiles-daemon-biglinux.service` e `power-profiles-daemon-biglinux-start.service` | API `powerprofilesctl` disponível e perfil confirmado |
| Margem de memória | `systemd-swap.service` e as units de swap/zram configuradas | Swap presente e pressão acompanhada |
| Entrada gráfica | `sddm.service`/`display-manager.service` e sessão Plasma Wayland | Login pelo fluxo disponível e retorno após logout |
| Segurança configurada | Firewall e políticas de confinamento adotadas na instalação | Regras efetivas e consumidores conhecidos |

Esta base mantém a inicialização normal da distribuição e suas dependências.
`graphical.target` traz a base multiusuário e o gerenciador de login. Um target
personalizado precisa preservar também as dependências funcionais instaladas
pela distribuição nesse alvo. `After=` estabelece ordem de inicialização.
`Wants=` e `Requires=` estabelecem o vínculo que traz a outra unit.

`power-profiles-daemon-biglinux.service` fica `active/exited` após preparar a
configuração. O processo residente está na unit `-start.service`. UPower e a
unit de início do daemon podem aparecer `disabled` e estar ativos por outro
caminho de ativação. O mask do `power-profiles-daemon.service` genérico existe
na imagem BigLinux observada. A revisão usa o provedor instalado e sua API.

O inventário de 11/11 encontrou `libvirtd.service` e seus três sockets em falha.
Essa capacidade possui diagnóstico próprio no fluxo de virtualização. UFW
estava `active/exited`, e as units AppArmor e systemd-oomd estavam inativas.
O estado efetivo do firewall, dos perfis de confinamento e da política de
memória precisa ser consultado pelos mecanismos correspondentes.

## Serviços e componentes da sessão gráfica

| Capacidade | Units ou componentes do usuário | Condição de permanência |
| --- | --- | --- |
| Barramento da sessão | `dbus-broker.service` no gerenciador do usuário e runtime XDG | Disponível durante a sessão |
| Imagem, janelas e entrada | `plasma-kwin_wayland.service`, drivers gráficos e libinput | KWin presente durante a sessão Wayland |
| Área de trabalho e gerenciamento da sessão | `plasma-plasmashell.service`, `plasma-ksmserver.service`, `plasma-kded6.service` | Integração Plasma usada neste host |
| Autenticação gráfica | `plasma-polkit-agent.service` | Agente disponível para as solicitações autorizadas |
| Energia do desktop | `plasma-powerdevil.service` | Brilho, bateria, botões e políticas da sessão disponíveis |
| Áudio e microfone | `pipewire.service`, `pipewire-pulse.service`, `wireplumber.service` e sockets respectivos | Servidor, compatibilidade das aplicações, dispositivos, perfis e rotas funcionais |
| Microfone BigLinux atual | `filter-chain.service`, configuração UCM e controles ALSA | Cadeia física → echo-cancel → `mic-biglinux` comprovada |
| Escalonamento multimídia | `rtkit-daemon.service` no sistema, pelo canal de ativação instalado | Disponível ao backend de tempo real usado pelo áudio |
| Portais de aplicações | `xdg-desktop-portal.service` e backend apropriado, incluindo `plasma-xdg-desktop-portal-kde.service` | D-Bus e ambiente da sessão permitem ativação quando solicitado |
| Documentos e permissões de apps isolados | `xdg-document-portal.service`, `xdg-permission-store.service` quando utilizados | Permissões e acesso aos documentos preservados |
| Entrada acessível | Método de entrada KWin, executável `plasma-keyboard`, `plasma-kaccess.service` e AT-SPI quando usados | Teclado, toque e acessibilidade requeridos pelo operador disponíveis |
| Aplicações X11 | Xwayland e integração com KWin | Ativação conforme as aplicações instaladas |
| Discos removíveis e gerenciador de arquivos | `udisks2.service`, GVfs e componentes usados pelo Dolphin | Montagem e acesso pelos consumidores em uso |

Na consulta de 11/11, o frontend de portais e o backend GTK estavam ativos.
O backend KDE estava instalado como unit estática e inativo. O aceite de
screen sharing e dos portais específicos requer uma solicitação real do app.
Serviços ativáveis podem estar inativos entre solicitações.

O processo `plasma-keyboard` pode ser iniciado pelo método de entrada do KWin.
Este host apresentou `plasma-keyboard.service` ausente. A disponibilidade do
teclado deve ser consultada pelo componente real da sessão e sua API.

## Dependência de energia omitida no Vibe Code

O alvo `phasezero-vibe-code.target` instalado pedia `multi-user.target` e
`sddm.service`. As units de energia BigLinux estavam vinculadas a
`graphical.target`, que permanecia inativo nesse modo. Em 11/11 foi instalado
o vínculo direto do target Vibe Code para `power-profiles-daemon-biglinux.service`.
O inicializador oficial configurou AMD P-State `active` e o perfil-base
`balanced`. O boot posterior no Desktop padrão confirmou daemon e API ativos.
Um boot natural no Vibe Code ainda precisa confirmar o caminho específico.

A consulta de 11/11 ao gerador PhaseZero `linux/boot/vibe-code.sh` mostrou
que ele ainda produz o target apenas com a base multiusuário e SDDM. A receita
de instalação precisa incorporar a dependência de energia da distribuição
para novas instalações. Essa pendência pertence ao responsável pelo boot.

O target também herda os serviços habilitados em `multi-user.target`, incluindo
vários opcionais neste host. Seu nome representa o modo de entrada. O custo
real precisa ser medido pelo conjunto efetivamente iniciado e seus consumidores.

## Serviços cuja necessidade depende do uso

| Grupo observado | Critério para operação sob demanda |
| --- | --- |
| Docker e `containerd` | Projetos/containers e volumes identificados antes de mudar a disponibilidade |
| libvirt e SWTPM | VMs, sockets e consumidores conhecidos. Falhas dessas units são investigadas no fluxo de virtualização |
| CUPS e `cups-browsed` | Impressão exigida pelo operador e clientes configurados |
| Samba e Avahi | Compartilhamento e descoberta de rede utilizados |
| Bluetooth | Teclado, mouse, controle, áudio ou outros periféricos em uso |
| ModemManager | Modem ou acesso móvel necessário |
| Geolocalização, sensores, KDE Connect e efeitos de cor | Recursos de desktop exigidos pelo usuário |
| Snap e portais de pacotes | Aplicações instaladas e seus formatos de distribuição |
| Notificadores e agendadores | Atualização, logs, manutenção, snapshots e backups com periodicidade conhecida |
| Agentes, launchers, Steam e aplicações | Trabalho e sessão do proprietário, com canal de fechamento autorizado |

O modo econômico pode abrir ferramentas de desenvolvimento conforme a ação
do usuário e reduzir polling com orçamento. Antes de mudar um serviço, conferir
owner, dependências, sockets/ativação D-Bus, consumidores, recuperação e teste
funcional. A contagem de processos isolada é insuficiente para avaliar o custo.

## Aprendizados de estabilidade e gargalos

- Em 07/11, um build chegou a aproximadamente 3,4 GiB de RSS e coincidiu com
  QA do Fôlego, ACPI a 100 °C e pressão de memória/I/O. Depois a pressão caiu,
  e o boot terminou abruptamente. A causalidade física permanece aberta.
- Em 09/11 houve descarga com tensão a 6,57 V mesmo com indicador a 54%.
  O histórico registra degradação da bateria e episódios também na tomada.
  Tensão, corrente, estado AC e horário precisam acompanhar o percentual.
- Em 11/11 às 05:41, logind registrou solicitação de reboot por
  `plasma-shutdown`, seguida de encerramento organizado. A origem da ação
  dentro da sessão permanece indeterminada.
- No microfone, placa acp5x em `off`, perfil interno ausente da enumeração,
  ALSA presente e preferência interna salva formaram o defeito recuperado.
  Fonte virtual sem mute coexistiu com captura física ausente. Nova enumeração
  do WirePlumber restaurou perfil e cadeia, e o usuário confirmou voz.
  A causa exata da enumeração incompleta permanece aberta.
- Fôlego 0.2.0b11 acrescentou diagnóstico específico, recuperação autorizada,
  escopos de bloqueio por capacidade, verificação da captura, rearme por perfil,
  amostras frescas distintas e orçamento durável de energia. A guarda de áudio
  está habilitada neste host. O teste após uma nova falha natural está pendente.
- PhaseZero, RetroFE e Fôlego podem observar entrada/áudio na mesma sessão.
  A preferência do responsável e as referências saudáveis precisam concordar.
  O incidente histórico de captura de um perfil defeituoso pelo watcher já
  motivou proteção no PhaseZero. Intenções de resultado incerto preservam o ID.
- Os renderizadores Electron e o Plasma aparecem entre os consumidores
  relevantes. Uma amostra de 11/11 mostrou cerca de 1,05 GiB de RSS em um
  renderizador Codex Desktop. RSS é uma amostra por processo. `%CPU` de `ps`
  representa a média calculada pela ferramenta e exige janela para tendência.
- O histórico Btrfs contém corrupção acumulada, anteriormente 6741, sem delta
  novo nas investigações citadas. O NVMe registrou desligamentos inseguros
  acumulados. Esses contadores precisam ser correlacionados com tempo e delta.
- Journal, amostras de 15 s e coleta iniciada pela GUI podem perder o final
  de um corte ou um boot curto. A revisão após os cortes de 11/11 passou a
  solicitar fsync em cada amostra gravada; antes, amostras normais sincronizavam
  a cada quatro gravações. Isso reduz a janela de perda no cache, sem certificar
  que o dispositivo preservará a escrita durante uma falha física.
  Pstore estava sem backend. Flags observadas
  incluem `nowatchdog`, `nosoftlockup`, `nomce` e `audit=0`, que reduzem parte
  da observabilidade. Sua origem e uma eventual revisão pertencem ao owner do boot.
- Os cortes de 11/11 às 07:52, 08:03 e 08:11 não preservaram encerramento
  organizado. Nos dois últimos, a abertura do Codex Desktop precedeu o corte,
  com RAM disponível e temperatura moderada nas últimas amostras. O launcher
  comunitário instalado aceita `~/.config/codex-desktop/electron-flags.conf`;
  `--disable-gpu` foi aplicado como mitigação reversível para a próxima abertura.
  O diagnóstico de flags confirmou também Vulkan desativado. A causa e o aceite
  físico da mitigação continuam pendentes; a proximidade temporal não comprova
  falha da GPU. Um reset de GPU às 08:26:55 foi provocado acidentalmente pelo
  agente ao ler debugfs e deve ser excluído da atribuição dos incidentes.
- Há limites persistentes do Fôlego e dos ambientes de QA. Estado cheio ou
  desconhecido exige diagnóstico e retenção comprovada. O material útil possui
  caminho de recuperação próprio, com fonte/receita preservadas no GitHub.

## Roteiro de uma nova investigação

1. Registrar horário, boot, modo de entrada, carregador, periféricos e sintoma.
2. Consultar journal do boot atual/anterior e a linha do tempo do Fôlego.
   Conferir solicitação organizada de desligamento, lacunas e qualidade das fontes.
3. Medir RAM disponível, swap ativa, PSI, CPU por janela, temperatura/limite
   do sensor e espaço persistente. Conferir RSS e comando completo dos concorrentes.
4. Consultar sistema e sessão separadamente. Conferir dependências do target
   selecionado, estado funcional, owner e caminho de ativação das units.
5. Para áudio, conferir ALSA/UCM, placa/perfil, fonte física, ligações dos
   filtros, fonte padrão e preferências persistidas do responsável.
6. Consultar IDs pendentes e o disjuntor da capacidade. Revalidar identidade
   antes do efeito. Uma solicitação incerta exige consulta/reconciliação.
7. Validar a capacidade real na sessão do operador e acompanhar o próximo
   evento natural pertinente. Preservar receitas, evidência e limites do diagnóstico.

Consultas de partida no ambiente do usuário, com RTK quando disponível,

```bash
rtk proxy systemctl get-default
rtk proxy systemctl list-dependencies phasezero-vibe-code.target --plain
rtk proxy systemctl --failed
rtk proxy systemctl --user --failed
rtk proxy journalctl -b -1 -e --no-pager
rtk proxy ./dev run disk health --json
rtk proxy ./dev run disk timeline --json
rtk proxy ./dev run accessibility status --json
rtk proxy ./dev run accessibility transitions --json
rtk proxy powerprofilesctl get
rtk proxy timedatectl show -p NTPSynchronized -p NTP
```

O shell de diagnóstico precisa do barramento da sessão correta. O runtime XDG
é usado para IPC. Temporários de teste e builds continuam no destino próprio
em disco. Logs com identidade de conta, credenciais ou dados pessoais ficam no
destino privado apropriado.

## Aceite de um modo econômico

A revisão deve demonstrar login/saída e recuperação por console, teclado e
ponteiro, método de entrada acessível, rede/DNS/HTTPS/horário, voz e reprodução,
controle de energia/bateria e portais requeridos pelas aplicações. Deve medir
carga e memória em janela definida, incluindo o uso dos agentes. Cold boot,
suspend/resume, dock/periféricos e estabilidade prolongada mantêm seus próprios
aceites físicos. A base documentada permite conduzir esses aceites.

## Fontes e continuidade

- Ocorrências, correções, SHAs e limites do alvo real estão em
  [HANDOFF.md](HANDOFF.md) e [ROADMAP-RESILIENCIA-HOST.md](ROADMAP-RESILIENCIA-HOST.md).
- Contratos de entrada/áudio e recuperação estão em [ACESSIBILIDADE.md](ACESSIBILIDADE.md).
- A definição dos alvos básicos e gráficos está na
  [documentação systemd](https://www.freedesktop.org/software/systemd/man/latest/systemd.special.html).
- Dispositivos, perfis e rotas pertencem ao gerenciador de sessão do áudio.
  [WirePlumber](https://pipewire.pages.freedesktop.org/wireplumber/design/understanding_session_management.html).
- Ativação e ambiente dos portais seguem a integração do desktop.
  [XDG Desktop Portal](https://flatpak.github.io/xdg-desktop-portal/docs/system-integration.html).
- Comunicação de rede, fontes de energia, política Plasma e sincronização
  estão descritas pelos respectivos projetos.
  [NetworkManager](https://networkmanager.dev/docs/api/latest/NetworkManager.html),
  [UPower](https://upower.freedesktop.org/docs/UPower.7.html),
  [PowerDevil](https://github.com/KDE/powerdevil),
  [systemd-timesyncd](https://www.freedesktop.org/software/systemd/man/262/systemd-timesyncd.html).
