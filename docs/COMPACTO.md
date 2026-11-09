# Widget, sessões de IA e atalhos

## Mini horizontal

A faixa mínima flutuante parte de **384 × 46 px lógicos** em uma linha: alça de
arraste, estado com palavra e cor, CPU agregada, temperatura com origem e uso de
RAM, bateria quando presente e franquias de IA confirmadas. A largura acompanha
o conteúdo dentro da área útil da tela, sem preencher todo o monitor. A altura
continua em 46 px. Uma leitura ausente ou antiga mostra `—`; `ACPI` não é chamada de
temperatura direta da CPU. O botão **Expandir** abre o compacto de 268 px, a
grade abre a Central e a seta abre diretamente os cinco formatos, com marca no
atual. O mesmo menu oferece **Tema de cores**, com amostras das oito paletas e
marca no tema em uso. Todas as barras e o compacto oferecem o seletor de formatos, e a Central
oferece **Mini horizontal** em **Posição do widget**. A área de arraste não
executa ações. O hover não abre atalhos nessa faixa; avisos completos
continuam no compacto e na Central. Calor no limite do sensor e bateria crítica
em descarga aparecem também no estado breve, com detalhes ao passar o ponteiro.
O [mockup e critérios](handoff/validation/mini-widget-2026-11-07/README.md)
registram a hierarquia e as transições.

Cada métrica tem uma célula arredondada com rótulo discreto acima do valor.
O valor usa verde, âmbar ou vermelho conforme sua própria criticidade, com
descrição acessível e dica de estado. CPU segue os limiares de 75% e 95%
da Central. RAM segue a folga configurada no monitor. Temperatura usa os
limites informados pelo sensor e fica neutra quando esses limites faltam.
Pausa, coleta parcial e leitura antiga retiram os valores e suas cores.
A diretriz é [qualidade visual nos mínimos detalhes](DESIGN.md).

Bateria e franquias seguem o mesmo modelo de célula. Bateria usa o percentual
com verde acima de 50%, amarelo até 50%, laranja até 25% e vermelho até 10%;
a estimativa de autonomia, quando medida, aparece na dica. Os alertas sonoros
existentes são compartilhados, sem duplicar monitoramento ou sons.

As IAs com cota positiva aparecem da maior para a menor, usando a mesma conta
selecionada pelo compacto. Com cota zerada ou desconhecida, a célula mostra
**Entrega**, **Entregas** ou **Resgate** conforme o lembrete disponível. O
marcador informa a quantidade de entregas para revisitar ou de resets
resgatáveis confirmados. Quando o último lembrete sai, a célula se recolhe.
Clique na célula para consultar a conta, inclusive seu estado de cota.
Quando a cota chega a zero e somente janelas confirmadas de **cinco horas**
impedem seu uso, a célula mostra o tempo até a reposição. Não há contagem
semanal. Ao vencer o prazo, a franquia permanece desconhecida até nova leitura;
o relógio não cria crédito. A interface usa o monitor já existente, inclusive
quando o compacto está oculto.

[Capturas e limites de validação](handoff/validation/mini-battery-quotas-2026-11-07/README.md)
registram os estados, o encolhimento e a adaptação às larguras previstas.

O compacto tem 268 px de largura em pixels lógicos do desktop. O estado e a
memória livre dividem a linha de resumo. Alertas completos e mensagens podem
aumentar a altura. O ícone de grade abre a **Central** e recolhe o widget.
A seta abre os controles, incluindo **Monitoramento → Pausar monitoramento**
ou **Retomar monitoramento**.
o ícone de teclado e sua seta são um grupo separado para abrir o teclado embaixo
ou no topo. **Modo widget**, na Central, retorna ao controle flutuante sem
parar o monitoramento. Em outras abas, use **Posição do widget → Widget
flutuante** ou **Mini horizontal** no menu do cabeçalho; a aba e os campos em edição são preservados.
As duas interfaces dispensam minimizar, maximizar e fechar.
Para encerrar, use a seta da Central → **Sair do Fôlego** ou a bandeja. **Ocultar widget**,
no mesmo menu, mantém um caminho de retorno: sem bandeja e com a central
oculta, ela é reaberta antes de ocultar o widget. O cabeçalho da central permite
arrastar a janela. Pausar controla a telemetria de recursos. A consulta de IAs é separada
e continua enquanto o Fôlego está aberto, inclusive com o widget oculto ou a
central em primeiro plano. Fechar o aplicativo encerra seus workers e seu próprio
auxiliar de entrada; um som em andamento conclui a restauração do volume.

## Encaixe nas bordas

Ao passar o mouse pela borda esquerda do widget, uma faixa em dois tons mais
escuros revela a seta para a barra direita. A borda direita abre a barra
esquerda; a borda superior abre a barra horizontal no topo. A seta da borda
externa de cada lateral, ou do centro da borda superior, retorna aos 268 px do
compacto. O seletor de visualizações em cada formato também leva diretamente
às outras quatro superfícies. Os controles, leitura de
recursos e cotas são os mesmos componentes nas quatro formas completas. As laterais têm
112–128 unidades lógicas de largura: o indicador principal fica centralizado,
seguido do estado, métricas, espaço livre, pausa e cotas confirmadas em coluna.
As métricas se alinham à borda correspondente; os cantos da janela são
recortados de forma arredondada.
As seis ações coloridas aparecem ao entrar com o ponteiro e se recolhem após
sair, nas três barras como no compacto. Nas laterais, formam uma coluna na base;
a área de leitura rola entre o cabeçalho fixo e os atalhos quando as cotas e
avisos excedem a altura útil. A barra superior tem 120 unidades lógicas de altura a partir de
900 unidades de largura: Fôlego e o indicador de folga começam à esquerda,
seguidos pelas cotas confirmadas, métricas e o grupo de teclado/menu na ponta
direita, com Pausar abaixo desses dois controles. Ações expandidas formam uma
linha na base; quatro cotas com badges cabem simultaneamente na área útil de
948 × 593 do Steam Deck. Em larguras menores, o topo preserva uma composição
em duas linhas e 190 unidades de altura.

O encaixe usa a área disponível da tela informada pelo Qt para excluir os
painéis conhecidos. Em X11, a geometria muda em 260 ms. Em KDE/Wayland, o
Fôlego pede ao KWin para posicionar **somente sua própria janela** e verifica
a posição antes de concluir; o conteúdo reaparece suavemente após a confirmação.
Ao reabrir uma barra depois de visitar a Central, o Fôlego confirma novamente
o encaixe: a regra inicial do KWin para o widget flutuante pode ter reposicionado
a mesma janela. **Modo widget** na Central abre o widget flutuante. O menu **Posição
do widget** na Central e o seletor direto no widget oferecem mini, compacto,
as duas laterais e o topo, sem depender da alça de borda estar visível.
O flutuante preserva a posição quando ela cabe na área útil; se a altura mudou,
ajusta apenas o necessário para manter a janela inteira acessível. Uma mudança
tardia do KWin na barra é conferida por leitura da geometria, com número limitado
de correções.
Se o compositor não confirmar, a interface informa a incerteza e não repete o
pedido por conta própria. O modo de encaixe vale para a janela atual; uma nova
abertura inicia no compacto.

## Sessões de IA

No compacto e nas barras, as cotas positivas confirmadas aparecem do maior
para o menor **percentual disponível**. Um empate mantém a ordem Codex, Codex Web,
Claude e Grok. A conta padrão representa o provedor quando tem cota; se estiver
zerada ou sem confirmação, a conta elegível com maior percentual aparece em seu
lugar. Nome acessível, clique e painel se referem à mesma conta. Passe o mouse
num indicador visível para abrir o painel. Todos os provedores, inclusive os
ocultos, ficam em **Contas e cotas de IA** na seta da Central. O menu informa
zero, ausência de confirmação, entregas e tickets separadamente. Se nenhuma
cota positiva estiver confirmada, a faixa mostra uma mensagem curta. A conta
padrão aparece primeiro na lista lateral do painel; escolha outra quando quiser.
O percentual gasto, tickets e referência da assinatura ficam em destaque; cada janela mostra
seu próprio reset e tempo restante. Detalhes adicionais têm rolagem. Clique fora
ou use Escape para fechar. O clique direto no indicador abre o cliente da conta
exibida; **Abrir cliente** no painel usa a conta selecionada.

Os indicadores usam o mesmo desenho circular do medidor do PhaseZero:
disco colorido de identificação, percentual **disponível** no centro e anel
externo proporcional à cota da conta exibida. O anel é verde acima de 60%, amarelo
de 21% a 60% e vermelho até 20%. Zero confirmado e dado desconhecido ou vencido
saem da faixa, mas preservam estados distintos no menu e no painel. Uma outra
conta não altera o percentual da padrão enquanto ela tiver cota positiva.

Uma atualização entre percentuais conhecidos move o anel suavemente em 450 ms;
o número e a descrição acessível mostram o valor atual desde o início.
Expiração ou falha retiram o percentual imediatamente e cancelam a transição.
Uma conta que ganha cota durante a observação entra na faixa com transição curta,
respeitando a preferência de animação do estilo Qt. A reposição confirmada usa
o aviso sonoro já configurável em Opções; a primeira leitura e a simples passagem
da data de reset não tocam som.
Entregas confirmadas para revisitar fazem a borda interna pulsar em ciclos de
1,8 s, mantendo a contagem separada abaixo. Isso não representa cota ou tickets.
Sem entregas confirmadas, o pulso para. Todas as animações param com o widget
oculto; a consulta continua sob o monitor existente. Cores de identificação e
do anel seguem a referência nos oito temas e não perdem opacidade com o fundo.

Ao lado da contagem azul de entregas aparece um **presente verde piscando**
quando há tickets de redefinição disponíveis. A quantidade soma somente os
tickets confirmados das contas daquele provedor, sem alterar o medidor da conta
padrão ou a contagem de entregas. Acima de nove mostra **9+**; o mouse revela o
número exato e a divisão por conta. Clique no presente para abrir o painel numa
conta com tickets, preferindo a padrão quando ela tem ofertas. Não resgata.

O presente pulsa a cada 800 ms entre duas intensidades e mantém o número
legível. Zero, ausência de confirmação, consulta com mais de 15 minutos ou a
primeira validade conhecida vencida retiram o aviso até nova observação válida.
Uma reposição automática da janela de uso não é um ticket. A animação para com
o widget oculto. O suporte visual é comum aos quatro indicadores; só aparece
quando a fonte daquele provedor informa tickets (atualmente confirmado no Codex).

- Codex: consulta somente leitura aos endpoints de uso e tickets do próprio
  provedor, com a credencial local já existente e ainda válida. Exibe consumo,
  reposição com data/hora e contagem regressiva, tickets disponíveis com validade
  quando informada e saldo extra. Não resgata tickets. Se a consulta não estiver
  disponível, tenta os registros `rate_limits` locais e identifica a fonte.
  A menor disponibilidade das janelas conhecidas determina a cor. Observação de mais de 15 minutos, futura ou com reposição já
  vencida deixa de fornecer um percentual atual. Não se inventa 100% no reset.
- Claude: consulta de uso ao endpoint OAuth da Anthropic com a credencial local
  já existente. Credencial expirada ou alterada durante a consulta invalida a
  resposta. Não se renova, copia ou grava a credencial; redirecionamentos HTTP
  são recusados. Inclui uso extra e teto mensal quando retornados. A referência
  mensal derivada do início da assinatura ativa é **estimativa**, não recibo de
  cobrança. Leituras de uso são reaproveitadas por 5 minutos; perfil por 6 horas.
  HTTP 429 suspende novas consultas pelo prazo informado, com observação recente
  da mesma conta quando ainda válida. Estado vencido não vira percentual atual.
  A identidade do cache inclui também a conta/organização em `~/.claude.json`:
  mudar a organização invalida uso e perfil anteriores mesmo sem trocar o token.
  A espera por HTTP 429 continua valendo para a mesma credencial durante essa troca.
  Não há rede no loop gráfico.
- Codex Web: o launcher registra somente seus próprios envios Pro, quando o
  rastreamento está ativo. Esse histórico parcial não é saldo da conta nem
  informa o reset do provedor. O Fôlego nunca converte essas contagens em
  percentual de franquia ou horário de reposição. No menu e no painel mostra
  separadamente o serviço local (`/healthz`), o runtime local do túnel
  (inspeção somente leitura, no máximo a cada cinco minutos), o histórico
  parcial e a resposta Web não comprovada sem envio. Serviço e túnel prontos
  não provam inferência nem conexão remota do broker. Plano não suportado no
  rastreador não significa uso ilimitado nem instalação quebrada. Não há smoke
  automático, pois ele gastaria mensagens. Na faixa de IAs, um cliente Codex
  realmente aberto com perfil `chatgpt-web/*` mostra círculo verde pulsante
  com “OK”; na mini horizontal aparece “OK”. A contagem de entregas concluídas
  permanece distinta da contagem de instâncias abertas, disponível na descrição
  acessível e no painel. O launcher sozinho não acende o indicador. Sem
  instância confirmada, a mini ainda pode mostrar uma entrega Web pendente.
  Sem inventário confiável, a contagem de instâncias fica desconhecida.
  A observação usa a varredura existente de contas a cada 60 segundos e
  vence em 120 segundos. Instância aberta não comprova turno em execução,
  resposta remota ou cota disponível. A conta permanece no menu de contas.
- Grok: se sua fonte não oferecer uma franquia percentual confirmada, o menu
  de contas mantém o diagnóstico e a mini pode mostrar entregas pendentes.
  Metadados de assinatura aparecem separados da reposição de
  cota. A data de Grok pode ser informada pelo
  usuário; isso não confirma pagamento ou cota. Esses campos continuam
  indisponíveis nas fontes consultadas; não se usam tokens gastos na conversa
  como percentual da franquia do plano.
- Token presente não prova renovação futura válida. O painel distingue a
  observação aceita pelo provedor de metadados locais e validade não verificada.
  Cupons/créditos não fornecidos pela fonte continuam não informados.

Fôlego usa configuração própria. A observação de contas não depende do PhaseZero;
a recuperação Web opcional descrita abaixo apenas solicita um ciclo ao responsável
já instalado e habilitado, sem administrar sua instalação ou suas políticas.

### Recuperação do Codex Web

O monitor reconhece a mensagem exata `Selected model is at capacity. Please try
a different model.` no campo `error.message` de uma conclusão nativa do Codex
Web. A mesma frase em conversa, resposta bem-sucedida ou outro provedor não
aciona reparo. A leitura aproveita a cauda de 64 KiB já coletada a cada 5 s;
o recibo guarda identidade e booleano, sem texto da conversa. Há badge vermelho
`!`, aviso na Central/bandeja e nenhum som de conclusão bem-sucedida.

Durante o monitoramento, erros novos e recentes solicitam o ciclo do responsável
da mesma conta. O adaptador atual reconhece o protocolo de recuperação PhaseZero
já habilitado: confere manifesto/hashes, propriedade e a unit efetiva do systemd,
incluindo a ausência de overrides. Outros launchers continuam observáveis, com
recuperação indisponível. Desabilitar a recuperação no responsável bloqueia novos
pedidos do Fôlego. Não há novo daemon, grant de recursos ou instalação automática.

Cada pedido passa pelo coordenador, com intenção durável e ID por conta/turno.
O erro é revalidado antes do pedido. No máximo três intenções por dez minutos,
com intervalo de um minuto; solicitações incertas bloqueiam novos pedidos até
revisão. O responsável conserva sua própria trava, verificação de ociosidade,
orçamento e disjuntor. O Fôlego não troca conta/modelo, renova credenciais,
reenvia tarefa nem reinicia diretamente agentes ou navegador.

O painel da conta e `./dev run ai status --json` mostram a atividade observada
no launcher, o estado do conector e a idade do último diagnóstico do
responsável. Uma previsão de nova tentativa vem do próprio recibo. Após 150 s,
o estado atual fica desconhecido e a previsão, se ainda futura, aparece como
histórica. `login-required` pede login no ChatGPT **dentro do launcher desta
conta**. Serviço, túnel, conector e resposta Web são sinais independentes.

Recibos PhaseZero sem versão ainda informam espera, tarefa longa e configuração
incompleta quando esses dados estão presentes. Para exibir o resultado de uma
tentativa, o adaptador reconhece `schemaVersion: 1` e `connectorVerification`
com `state` (`verified`, `deferred`, `failed` ou `unknown`) e `at` do mesmo ciclo.
A confirmação exige recibo recente e nenhuma ação pendente ou indicação de
configuração incompleta. A lista de ações do recibo pode incluir uma tentativa
adiada. A leitura exporta estados e horários, sem IDs de abas nem conteúdo da
sessão. A verificação e o alerta de tarefa longa pertencem ao PhaseZero.

Para solicitar manualmente o mesmo ciclo para um erro ainda não visto, de até
15 minutos, use `./dev run ai recover-web --account ID --confirmar --json`.
O ID da conta vem de `ai status`; `operation ID --json` consulta a intenção.
Resultado parcial significa que o pedido foi aceito para processamento, sem
certificar recuperação. Timeout permanece desconhecido e não autoriza repetição.
Os diretórios nativos principais são `~/.codex`,
`~/.codex-chatgpt-web` (WebGPT standalone),
`~/.local/share/codex-web-gpt/codex-home` (compatibilidade), `~/.claude` e `~/.grok`.
Quando o launcher WebGPT empacotado está em execução, sua instalação e seu
diretório de dados são descobertos pelos caminhos do próprio processo e
arquivos do WebGPT, inclusive em instalação personalizada. Nenhum processo do
PhaseZero é necessário. Fôlego só consulta loopback e não copia token ou login.
Raízes de `$CODEX_HOME`, `$CLAUDE_CONFIG_DIR` e `$GROK_HOME` acrescentam contas;
não substituem a principal. Processos locais podem fornecer suas raízes nativas.
Quando existe, o registro opcional `phasezero/ai-accounts/codex-profiles/profiles.json`
em XDG_DATA_HOME fornece nomes e caminhos dos perfis Codex/Web, inclusive inativos.
Perfis arquivados não são adotados automaticamente. A descoberta não executa
código, inicia serviço ou copia login do PhaseZero. Sem esse registro, os diretórios nativos e
a configuração própria continuam funcionando. Registro complementar inválido
é ignorado com aviso visível, sem adotar seus perfis.
Para outras contas, crie `$XDG_CONFIG_HOME/folego/ai-sessions.json` (por padrão,
`~/.config/folego/ai-sessions.json`). Caminhos devem ser absolutos. Exemplo:

```json
{
  "schema": 1,
  "accounts": [
    {"provider": "codex", "label": "Codex trabalho", "path": "/caminho/conta/codex-home"},
    {"provider": "web", "label": "Web pessoal", "path": "/caminho/conta-web/codex-home",
     "web_core_home": "/caminho/conta-web/core-home",
     "web_launcher_data": "/caminho/conta-web/launcher-data"},
    {"provider": "claude", "label": "Claude trabalho", "path": "/caminho/claude-work", "default": true}
  ],
  "grok_paid_until": "2026-11-30T23:59:59-03:00"
}
```

Pode apontar para um diretório já criado por outro launcher; os arquivos
permanecem no lugar. Nenhum token deve ser colocado nessa configuração. Schema
desconhecido, conta ilegível ou orçamento excedido aparecem como desconhecidos.
O limite é 16 contas configuradas adicionais, 32 raízes totais e 40 rollouts com
caudas de até 64 KiB por conta no fallback. Há deduplicação por provedor/caminho.
`default: true` escolhe explicitamente uma padrão por provedor; duas padrões
são configuração inválida. Sem override, prefere a principal existente e depois
a primeira raiz existente. A descoberta de processos fica no HOME selecionado;
HOME privado não adota contas nativas do HOME físico.
Para consultar sem Qt: `./dev run ai status --json`.

O painel aparece mesmo com outro aplicativo em foco. O botão direito no
indicador abre **Atualizar dados**, **Contas, uso e renovação**,
**Definir dia da renovação mensal** e **Consultar no site do provedor**.
A referência mensal
pessoal aceita dias 1–31, ajusta meses curtos e persiste na configuração própria;
0 remove somente essa referência. Ela é identificada como informada pelo usuário,
sem confirmar cobrança. A GUI grava a referência por `account_id` em
`billing_accounts`, sem compartilhar a data com outras contas. O ID opaco aparece
na consulta JSON. Remover uma referência por conta também suprime a referência
legada daquele provedor para essa conta. A configuração anterior continua aceita
para a padrão quando não há override:

```json
"billing": {"codex": {"monthly_day": 15}, "grok": {"monthly_day": 31}}
```

**Reposição da franquia**, **ticket de reposição**, **saldo/uso extra** e
**renovação mensal da assinatura** são informações distintas. A presença de um
token de login não preenche a data de cobrança. A indisponibilidade de uma fonte
é explicitada, sem fabricar percentual ou cupom.

## Entregas para revisitar

Um pequeno número acima de cada indicador mostra quantas sessões principais
concluíram uma entrega desde a primeira ativação deste monitor. Duas sessões
concluídas mostram **2**; eventos repetidos, ferramentas e subagentes internos
não aumentam a contagem. O próximo pedido na mesma sessão retira o aviso antigo;
uma nova conclusão pode gerar outro aviso. Não se importa todo o histórico.

A consulta ocorre a cada cinco segundos enquanto o widget está visível, em
worker independente da franquia. São aceitos eventos nativos explícitos:
`task_complete` do Codex/Web, resposta final `end_turn` com texto do Claude e
`turn_completed/end_turn` do Grok. Falhas, cancelamentos ou silêncio não provam
entrega. **?** indica ausência de evidência; **2+** indica pelo menos duas
conclusões verificadas, com outras sessões ainda não verificadas. Não se exibe
zero quando a leitura está parcial. O Codex usa seu índice SQLite em modo de
leitura; diretórios adicionais de clientes ativos podem ser identificados pelas
variáveis nativas de caminho dos próprios processos, sem importar PhaseZero.

O clique procura a janela desktop ou o terminal ancestral do processo local,
com conta, classe e identidade verificadas. Em KDE/Wayland usa `kdotool`; em X11,
`xdotool`. Se não houver janela, pode solicitar uma única abertura pelo atalho
nativo instalado (`gtk-launch`) para uma conta principal com raiz padrão.
Perfis adicionais não fazem fallback para o launcher de outra conta.
Sem janela/atalho identificado, informa a
indisponibilidade. Nenhum comando é enviado aos agentes e nenhuma sessão é
encerrada. A abertura mostra a aplicação para o usuário escolher a sessão;
não seleciona automaticamente uma conversa ou aba interna do terminal.

Os avisos da conta aberta só são marcados como vistos após confirmação de foco da
janela. Avisos de outras contas permanecem. Falha preserva a contagem; uma conclusão posterior ao clique não é
apagada por ele. O estado pertence ao Fôlego em
`$XDG_STATE_HOME/folego/ai-deliveries.json` (padrão
`~/.local/state/folego/ai-deliveries.json`), privado, com marco inicial e recibos
em hash, sem texto de conversas ou credenciais. Reiniciar preserva os avisos.
Estado ilegível ou schema desconhecido não é sobrescrito.

Orçamentos do monitor de entregas: inventário compartilhado de 32 raízes, 128 sessões por raiz, caudas de
64 KiB e até 2048 recibos. Inventário excedido, registro incompleto ou conclusão
fora da cauda legível deixam a observação parcial, sem amostragem silenciosa.

## Sons dos agentes e da franquia

O Plasma recebe pop-ups identificados por categoria, com selo próprio e
título curto. Uma entrega nova confirmada produz um aviso por provedor no
ciclo, mesmo com os sons desativados. Entregas anteriores à abertura,
recibos repetidos e erros estruturados não geram aviso de conclusão. Os
avisos de Codex Web, pressão, temperatura, entrada e Desempenho têm seus
próprios selos. O Plasma aplica as preferências de exibição da sessão.

Na janela principal, abra **opções → Captura e avisos sonoros**. **Sons de
conclusão dos agentes e de franquia** vem ligado. Codex, Codex Web, Claude e
Grok têm quatro melodias curtas distintas. Escolha o aviso na lista e use
**Testar som** para ouvir, inclusive quando os avisos automáticos estão desligados.

Há três outros toques: atenção ao cruzar **20% restantes**, notas descendentes
quando a franquia chega a **zero** e uma melodia ascendente quando a fonte confirma
a disponibilidade novamente. Todas as contas são acompanhadas; considera-se a
menor disponibilidade das janelas válidas de cada conta. Se a leitura salta de
mais de 20% direto para zero, toca o aviso de esgotamento. Uma data de reset
vencida, dado desconhecido ou uma estimativa de assinatura não significa reposição.
Web/Grok continuam sem alertas percentuais quando a fonte não informa a franquia.

Os avisos ocorrem na próxima observação válida. A primeira leitura estabelece
uma referência silenciosa, sem tocar todas as entregas antigas ao abrir. Uma
conclusão nativa com horário posterior à abertura ainda toca, mesmo quando é a
primeira sessão legível daquele provedor. Eventos
repetidos, abrir uma conta e falhas de leitura não repetem os sons. Desligar os
avisos continua atualizando a referência; religar não reproduz o histórico mudo.
Conclusões simultâneas do mesmo provedor são agrupadas enquanto aguardam som.
A fila mantém no máximo uma instância pendente por identidade sonora, incluindo
os quatro sons de bateria, e reproduz os avisos em sequência.

## Bateria

O widget e a Central mostram o percentual quando a leitura da bateria é válida.
No widget, ele fica verde acima de 50%, amarelo de 26% a 50%, laranja de 11% a
25% e vermelho em 10% ou menos. Em 75%, ainda verde, toca o primeiro aviso de
queda. Ao cruzar 50% e 25% durante a descarga, os toques ficam mais acentuados.
Em 10% ou menos, o toque crítico começa na primeira leitura e se repete a cada
60 segundos de monitoramento válido. Um salto que atravessa várias faixas toca
apenas o aviso mais urgente. Carregar, pausar ou perder a leitura interrompe a
repetição. O primeiro valor conhecido acima de 10% estabelece referência sem
reproduzir avisos antigos.

O tempo restante vem de `time_to_empty_avg`/`time_to_empty_now` do Linux ou é
estimado com energia e potência (ou carga e corrente) da mesma bateria. Não é
mostrado quando esses dados faltam, a leitura é antiga ou o estado não é de
descarga. Equipamentos sem bateria não recebem um percentual fictício; leituras
inválidas ficam sem valor. Os quatro sons estão na lista **Testar som**, e a
preferência de sons existente governa também os avisos automáticos de bateria.

**Elevar o volume a pelo menos 85% durante o som e restaurar depois** também vem
ligado. Se a saída já estiver acima disso, não a reduz. O Fôlego guarda os valores
de cada canal e o estado mudo, identifica a saída padrão, eleva/desmuta só durante
o aviso e restaura ao terminar, inclusive se a reprodução falhar. Um ajuste de
volume ou mudo feito pelo usuário durante o aviso é preservado. Desmarcar mantém
o volume e mudo atuais. Não muda o dispositivo padrão, perfis ou serviços de áudio.

Requer `pactl` e `paplay` no PulseAudio/PipeWire local. A intenção fica em
`$XDG_STATE_HOME/folego/audio-volume.json`, privada, antes de alterar volume.
Ao iniciar, um registro pendente é reconciliado somente com servidor, saída,
boot e valores ainda comprovados. Estado desconhecido, saída substituída ou
registro de outro boot preservam o volume atual e informam a pendência em opções;
não se restaura às cegas nem se repete o som incerto.

## Abas de ações rápidas

No compacto, a gaveta que abre com o ponteiro tem dois grupos. **Selecionar**,
**Apagar tudo**, **Prompts**, **Copiar**, **Colar** e **Print** ocupam duas linhas
de 22 px, com os nomes completos nas dicas e na acessibilidade. O botão
**D** tem ícone de desktop e ocupa a altura das duas linhas. Ele solicita
**Mostrar área de trabalho** ao KDE/KWin pelo mesmo fluxo do menu Custom.
O compositor recolhe as janelas e mantém as aplicações abertas. Se o desktop
já estiver visível, o comando mantém esse estado.

**Selecionar tudo**, **Apagar tudo** e **Prompts** ficam em uma linha fina acima das abas.
Atuam somente no campo editável em foco, identificado pelo AT-SPI e pelo
proprietário da janela ativa. Apagar remove o texto do campo inteiro, não só a
seleção. Não copiam nem registram seu conteúdo, não usam a área de transferência, não enviam
Enter nem apagam arquivos. Foco/campo alterado recusa a operação; não há repetição
automática. Campos sem acessibilidade e terminais sem interface editável informam
indisponibilidade. Em Chromium, que expõe texto sem a interface EditableText,
selecionam o campo exato por AT-SPI, verificam a seleção inteira e o foco e
enviam um único Backspace. Não usam Ctrl+A como fallback global. A confirmação
consulta o tamanho e, quando há um único caractere, aceita o terminador de linha
do campo vazio. Uma falha informa resultado não confirmado, sem repetição automática.
Dependências opcionais: `libatspi`/AT-SPI 2 e `kdotool` no KDE/Wayland ou
`xdotool` em X11 com gerenciador de janelas. Não há instalação automática.

### Temas em toda a interface

Na central, **opções → Aparência · consoles clássicos** oferece oito paletas:
SNES americano (cinza/lavanda), Super Famicom (quatro cores), Mega Drive / Genesis
(preto/vermelho/azul), Master System III (preto/vermelho), PC Engine
(branco/laranja), NES (cinza/preto/vermelho), TurboGrafx-16 (grafite/laranja) e
PlayStation 2 (preto/azul). São inspirações aproximadas nas cores fornecidas
pelo usuário; os tons de texto são ajustados para contraste nas superfícies.
Na mini horizontal, **Controles → Tema de cores** usa as mesmas paletas e
mostra qual delas está em uso.

A seleção aplica imediatamente em todas as superfícies Qt, abertas ou ocultas:
central, widget, prompts/submenus/Custom, contas, avisos, controles e teclado.
Novas janelas usam a mesma paleta. A preferência `appearance/theme` usa a
autoridade QSettings existente `folego/folego`; o próximo início restaura a
escolha. O padrão sem preferência é SNES americano. Tema salvo desconhecido
é informado nas opções, usando o padrão visual sem sobrescrever a preferência.
Falha ao salvar mantém o tema em uso e mostra a falha; não anuncia sucesso.

Verde/âmbar/vermelho mantêm o significado de saúde e franquia, sempre com texto.
Texto normal e semântico tem contraste mínimo 4,5:1 nas três superfícies opacas;
botões usam tinta clara ou escura conforme seu fundo, com foco visível.
A escolha não muda cotas, automação, sons, atalhos ou grants.

**Transparência do fundo**, no mesmo grupo, ajusta todas as superfícies de
**0% opaco** a **100% sem fundo**. O padrão sem preferência é 0%. Arrastar
mostra uma prévia sem gravar a configuração a cada movimento; soltar salva uma
vez. Teclas/setas e acessibilidade também salvam a escolha. Trocar de tema
preserva a transparência. A autoridade QSettings existente guarda
`appearance/background_transparency`; o próximo início restaura a escolha.
Valor desconhecido é informado, usando 0% sem sobrescrever o dado. Falha de
gravação retorna à aparência anterior e informa o problema.

O ajuste muda somente as pinturas de fundo. Textos, ícones, contornos de teclas,
faixas, medidores e sinalizadores continuam opacos; a opacidade da janela inteira
permanece 1. Rótulos e espaços de layout são transparentes para evitar caixas
fragmentadas. O painel de contas tem uma superfície contínua, sem a moldura
preta do popup. Na composição transparente, a leitura também depende do fundo
da tela; escolha o nível que combina com o seu tema e conteúdo.

Os seis atalhos têm o mesmo tamanho, em duas linhas: **Selecionar tudo / Apagar
tudo / Prompts**, depois **Copiar / Colar / Print**. Passar o mouse revela a área
de cima para baixo em 140 ms; ao sair, aguarda 200 ms antes de recolher. Menus
abertos preservam a área durante a escolha. O teclado fica sempre no cabeçalho:
ícone para abrir embaixo e seta para abrir no topo.

As métricas mostram RAM e Swap à esquerda, CPU e Tmp alinhados à direita. No
widget flutuante, a terceira linha põe temperatura e RPM lado a lado; na barra
superior ficam juntos à direita da CPU.
**Tmp** é a ocupação dos temporários em
memória, não a temperatura. A coleta lê sensores CPU/SoC em sysfs; se ausentes,
aceita o sensor de sistema ACPI, identificado no tooltip. Não usa temperatura
de GPU/disco como temperatura do host. Ausente/ilegível resulta em **— °C**.
Quando a fonte é `acpitz`, a tela mostra **ACPI**: essa zona não comprova a
temperatura específica da CPU. O percentual **CPU** é uso agregado dos núcleos,
medido separadamente a partir de `/proc/stat`.
O RPM vem do tacômetro `fan*_input` em sysfs: o sensor rotulado CPU tem
preferência, seguido do primeiro ventilador do host. Sensores de GPU e disco
não entram nessa leitura. Zero é uma leitura válida de ventoinha parada;
ausência ou valor inválido aparece como **— RPM**. O tooltip identifica o sensor.
As leituras acontecem no coletor, fora do loop gráfico, sem alterar ventoinhas.

**Copiar** solicita a cópia da seleção do aplicativo em foco. **Colar** solicita
a colagem nele. Usam os atalhos alternativos de edição Ctrl+Insert e Shift+Insert;
assim, copiar nunca envia Ctrl+C para interromper um trabalho no terminal. O
aplicativo de destino precisa aceitar esses atalhos. O Fôlego não lê nem grava
o conteúdo da área de transferência ou as teclas em logs.

**Prompts** abre uma lista de 13 títulos: diagnóstico real, implantação do
diagnóstico item a item, continuidade, implementação de melhoria,
investigação de erro, revisão, testes, desempenho, segurança,
usabilidade, design com mockups, passagem de contexto e prontidão para PR/distribuição. Escolher um
copia seu texto para a área de transferência; depois cole no agente desejado.
Não cola, executa ou envia pedidos automaticamente. Os textos são genéricos,
respeitam as instruções e autorizações do projeto e pedem evidências verificáveis.

O seletor usa seis blocos: **Diagnóstico, implantação e continuidade**, **Desenvolvimento e
correção**, **Qualidade e segurança**, **Desempenho**, **Design e experiência**
e **Documentação e entrega**. Cada bloco tem faixa lateral colorida, título
horizontal e linhas clicáveis com ícone de copiar; clicar em qualquer ponto da
linha copia o texto integral e fecha o painel. A cor complementa o nome da
categoria. O painel tem até 480 × 540 px e se limita à área disponível da tela;
nomes longos quebram linha e a lista tem rolagem. O rodapé permanece visível.
Setas para cima/baixo ou Tab percorrem as escolhas, Enter copia ou abre o grupo
de atalhos e Escape fecha. Janelas, Edição, Terminal e Custom ficam no rodapé.
Os atalhos mantêm o comportamento do aplicativo de destino e a biblioteca
personalizada não é migrada nem regravada pela organização visual.

**Design e mockups para aprovação** copia integralmente o prompt fornecido pelo
usuário, incluindo as oito etapas, referências, restrições e passagem ao agente
implementador. Esse item preserva o texto original, sem adicionar o preâmbulo
dos demais prompts: propõe visuais para aprovação antes de implementar.

Antes de Custom, o menu **Prompts** oferece três grupos de atalhos padrão:

| Grupo | Ação | Combinação enviada |
|---|---|---|
| Janelas | Alternar aplicativo | `Alt+Tab` |
| Janelas | Visão geral das janelas | `Meta+W` |
| Janelas | Janela à esquerda / à direita | `Meta+Left` / `Meta+Right` |
| Edição | Desfazer / Refazer | `Ctrl+Z` / `Ctrl+Shift+Z` |
| Edição | Salvar / Buscar no aplicativo | `Ctrl+S` / `Ctrl+F` |
| Terminal | Copiar / Colar no terminal | `Ctrl+Shift+C` / `Ctrl+Shift+V` |

São dez ações disponíveis também em instalações existentes, sem alterar a
biblioteca pessoal. O menu mostra as combinações, mas não registra atalhos
globais: somente escolher um item envia a combinação uma vez pelo worker de
entrada existente. Edição atua no aplicativo em foco; Terminal usa as combinações
do Konsole. Janelas depende das associações do KDE (conferidas no host deste
incremento); atalhos remapeados e outros aplicativos podem responder de outra
forma. Meta corresponde à tecla Windows/Super. Não há shell nem envio de Enter
após colar. Nenhum arquivo personalizado é migrado ou recriado para incluir os
atalhos padrão, que continuam disponíveis se a biblioteca estiver vazia/ilegível.

O último item, **Custom**, abre um submenu de textos e macros pessoais.
**123** copia exatamente `123`, sem espaços. **Mostrar área de trabalho**
mostra o desktop do KDE/KWin sem fechar aplicações; se ele já estiver visível,
permanece assim. A ação usa a conexão persistente do Fôlego com o compositor.
O encerramento dessa conexão permite ao KWin restaurar as janelas.

Use **Editar textos e macros…** ou a aba **prompts** da janela principal.
**+ Texto** cria um título e um texto para copiar; **+ Macro** permite escolher
Mostrar área de trabalho ou um atalho como `Ctrl+Alt+T`, `Meta+D` e `Ctrl+Shift+F5`.
Clique em **Salvar** para disponibilizar no menu. Salvar não executa a macro.
Atalhos são uma combinação de teclas enviada ao aplicativo em foco, com o layout
ativo do sistema; não são comandos de shell nem sequências de várias combinações.
**Remover item** retira o item selecionado e **Atualizar** relê a biblioteca.

O arquivo privado é `$XDG_CONFIG_HOME/folego/custom-prompts.json` (padrão
`~/.config/folego/custom-prompts.json`), com até 32 itens, títulos de 80 caracteres
e textos de 16.000 caracteres, limitado a 512 KiB. Os exemplos aparecem apenas
quando o arquivo ainda não existe; abrir o menu não cria arquivo. Uma biblioteca
salva vazia continua vazia. Erros ou schemas desconhecidos preservam o arquivo
e bloqueiam gravações; alterações concorrentes exigem atualizar. Um menu antigo
não executa um item modificado: reabra Custom. Este incremento é posterior à
tag publicada v0.2.0b2.

**Print** abre a seleção de região do Spectacle. Conclua, salve ou cancele na
ferramenta de captura; o Fôlego não escolhe um destino nem declara uma imagem
salva sem confirmação. Um clique repetido não abre outra captura em andamento.
Uma captura que está sendo editada permanece na ferramenta ao sair do Fôlego.

Em **opções → Captura e avisos sonoros**, **Incluir widget flutuante no print**
vem marcado, mantendo o comportamento anterior. Desmarque para ocultar o widget
e o teclado antes de abrir a captura pelo botão Print do Fôlego. Eles retornam
quando você fecha o Spectacle, inclusive ao cancelar; no KDE/Wayland a posição
anterior do widget é restabelecida e limitada à área útil da tela. Uma falha ao
abrir o Spectacle também restaura o widget. A opção não controla capturas iniciadas
por outros programas ou pelo atalho global do desktop.

**Teclado** abre o teclado próprio do Fôlego na parte inferior da tela atual;
a seta separada abre no topo. A posição não fica memorizada: o próximo clique
na aba continua abrindo embaixo. O teclado usa as teclas físicas QWERTY e o
layout ativo do sistema, com Shift, números, Tab, espaço, apagar e Enter.
Não muda a preferência do teclado virtual nativo nem a abertura automática
por toque do desktop. Botões e teclado preservam o foco do aplicativo de destino.

Em KDE/Wayland, o posicionamento exige KWin e `qdbus6`. Ao abrir o teclado, um
worker prepara a regra própria `folego-virtual-keyboard`, com app-id Fôlego e
título específico do teclado, usando `kwriteconfig6`/`kreadconfig6`. Ela impede
o teclado de tomar foco; as demais regras ficam preservadas. O hint Qt sozinho
não impedia o clique de ativar o teclado neste KWin. A confirmação do compositor
compara os mesmos pixels físicos, inclusive com escala fracionária, e verifica
que a superfície não aceita foco. Sem confirmação, as teclas não são enviadas.
A entrada exige
`ydotool`, `ydotoold` e permissão **já existente** para `/dev/uinput`. O Fôlego
cria um auxiliar transitório próprio e seu socket privado de IPC, encerrando-o
ao sair; não instala serviço, amplia permissões ou reutiliza um daemon alheio.
Somente o socket de comunicação fica no runtime; TMPDIR/payloads ficam em disco
persistente. Em X11, usa `xdotool`. Ausência ou falha é apresentada, sem retry
automático. Nenhum desses controles habilita o executor de recursos.

## Distribuição e evidência

A versão **0.2.0b2** é uma prévia para Linux, Python 3.14 e Qt/PySide6.
Baixe a versão marcada na página Releases do GitHub, confira `SHA256SUMS` e use
o código-fonte para `./dev setup` e `./dev gui`, ou instale o wheel em um ambiente
Python 3.14 próprio com a dependência GUI. Não há AppImage/Flatpak nesta prévia.
As dependências opcionais acima não são instaladas silenciosamente.

Ela inclui contadores, seleção de contas, painel de cotas, correção do teclado
por clique e biblioteca de prompts. A tag v0.2.0b1 preserva o código anterior.
Baixe a fonte completa e SHA256SUMS; com os arquivos desejados na mesma pasta,
`sha256sum --ignore-missing -c SHA256SUMS` verifica os que foram baixados.

[Interface inicial](handoff/validation/compact-ui-2026-11-01/README.md) ·
[Contadores](handoff/validation/agent-deliveries-2026-11-01/README.md) ·
[Hover e edição](handoff/validation/ai-details-editing-2026-11-01/README.md) ·
[Contas, teclado e prompts](handoff/validation/ai-accounts-keyboard-prompts-2026-11-01/README.md).
O histórico e as pendências gerais continuam em [HANDOFF](HANDOFF.md); a prévia
não certifica a matriz física de entrada, login, hardware ou todas as aplicações
de destino, nem resolve as pendências do motor de recursos registradas ali.
