# Widget, sessões de IA e atalhos

O widget tem 280 px de largura em pixels lógicos do desktop. Recursos ficam em
duas linhas; alertas completos e mensagens podem aumentar a altura. O ícone de
grade abre a **Central** e recolhe o widget. A seta ao lado abre os controles;
o ícone de teclado e sua seta são um grupo separado para abrir o teclado embaixo
ou no topo. **Voltar**, no topo da central,
retorna ao controle flutuante sem perder a aba, os campos em edição ou parar o
monitoramento. As duas interfaces dispensam minimizar, maximizar e fechar.
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
interna da barra retorna aos 280 px do compacto. Os controles, leitura de
recursos e cotas são os mesmos componentes nas quatro formas. As laterais têm
112–128 unidades lógicas de largura: o indicador principal fica centralizado,
seguido do estado, métricas, espaço livre, pausa e cotas confirmadas em coluna.
As seis ações coloridas ficam sempre acessíveis na base, uma por linha. A
rolagem aparece quando as cotas e avisos excedem a altura disponível. No topo,
os indicadores e controles ocupam a largura útil e as ações formam uma linha.

O encaixe usa a área disponível da tela informada pelo Qt para excluir os
painéis conhecidos. Em X11, a geometria muda em 260 ms. Em KDE/Wayland, o
Fôlego pede ao KWin para posicionar **somente sua própria janela** e verifica
a posição antes de concluir; o conteúdo reaparece suavemente após a confirmação.
Se o compositor não confirmar, a interface informa a incerteza e não repete o
pedido por conta própria. O modo de encaixe vale para a janela atual; uma nova
abertura inicia no compacto.

## Sessões de IA

O widget mostra somente provedores com cota positiva confirmada, do maior para o
menor **percentual disponível**. Um empate mantém a ordem Codex, Codex Web,
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
- Codex Web e Grok: se suas fontes não oferecerem uma franquia percentual
  confirmada, ficam no menu de contas, fora da faixa principal. Quando houver
  observação válida e cota positiva, entram automaticamente. Metadados de
  assinatura, quando disponíveis, aparecem como tal, separados da reposição de
  cota. A data de Grok pode ser informada pelo
  usuário; isso não confirma pagamento ou cota. Esses campos continuam
  indisponíveis nas fontes consultadas; não se usam tokens gastos na conversa
  como percentual da franquia do plano.
- Token presente não prova renovação futura válida. O painel distingue a
  observação aceita pelo provedor de metadados locais e validade não verificada.
  Cupons/créditos não fornecidos pela fonte continuam não informados.

Fôlego usa configuração própria e não importa, inicia ou administra PhaseZero.
Os diretórios nativos principais são `~/.codex`,
`~/.local/share/codex-web-gpt/codex-home`, `~/.claude` e `~/.grok`.
Raízes de `$CODEX_HOME`, `$CLAUDE_CONFIG_DIR` e `$GROK_HOME` acrescentam contas;
não substituem a principal. Processos locais podem fornecer suas raízes nativas.
Quando existe, o registro opcional `phasezero/ai-accounts/codex-profiles/profiles.json`
em XDG_DATA_HOME fornece nomes e caminhos dos perfis Codex/Web, inclusive inativos.
Perfis arquivados não são adotados automaticamente. Não se executa código, inicia
serviço ou copia login do PhaseZero. Sem esse registro, os diretórios nativos e
a configuração própria continuam funcionando. Registro desconhecido protege as
fontes e aparece como inventário não confirmado.
Para outras contas, crie `$XDG_CONFIG_HOME/folego/ai-sessions.json` (por padrão,
`~/.config/folego/ai-sessions.json`). Caminhos devem ser absolutos. Exemplo:

```json
{
  "schema": 1,
  "accounts": [
    {"provider": "codex", "label": "Codex trabalho", "path": "/caminho/conta/codex-home"},
    {"provider": "web", "label": "Web pessoal", "path": "/caminho/conta-web/codex-home"},
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
A fila é limitada às sete identidades sonoras, reproduzidas em sequência.

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

As métricas mostram RAM e Swap à esquerda, CPU e Tmp alinhados à direita e a
temperatura em °C à direita da CPU. **Tmp** é a ocupação dos temporários em
memória, não a temperatura. A coleta lê sensores CPU/SoC em sysfs; se ausentes,
aceita o sensor de sistema ACPI, identificado no tooltip. Não usa temperatura
de GPU/disco como temperatura do host. Ausente/ilegível resulta em **— °C**.
A leitura acontece no coletor, fora do loop gráfico, sem alterar ventoinhas.

**Copiar** solicita a cópia da seleção do aplicativo em foco. **Colar** solicita
a colagem nele. Usam os atalhos alternativos de edição Ctrl+Insert e Shift+Insert;
assim, copiar nunca envia Ctrl+C para interromper um trabalho no terminal. O
aplicativo de destino precisa aceitar esses atalhos. O Fôlego não lê nem grava
o conteúdo da área de transferência ou as teclas em logs.

**Prompts** abre uma lista de 12 títulos: diagnóstico real, continuidade,
implementação, investigação de erro, revisão, testes, desempenho, segurança,
usabilidade, design com mockups, passagem de contexto e prontidão para PR/distribuição. Escolher um
copia seu texto para a área de transferência; depois cole no agente desejado.
Não cola, executa ou envia pedidos automaticamente. Os textos são genéricos,
respeitam as instruções e autorizações do projeto e pedem evidências verificáveis.

O seletor usa seis blocos: **Diagnóstico e continuidade**, **Desenvolvimento e
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
