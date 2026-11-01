# Widget, sessões de IA e atalhos

O widget tem 280 px de largura em pixels lógicos do desktop. Recursos ficam em
duas linhas; alertas completos e mensagens podem aumentar a altura. Minimizar
oculta o widget com um caminho de retorno; ampliar abre a central; fechar sai
do Fôlego. Pausar controla a telemetria de recursos. A consulta de IAs é separada
e funciona enquanto o widget está visível. Fechar o aplicativo encerra seus
workers e seu próprio auxiliar de entrada.

## Sessões de IA

Passe o mouse sobre Codex, Web, Claude ou Grok para abrir o painel de contas.
A conta padrão aparece primeiro; escolha outra na lista à esquerda. O percentual
gasto, tickets e referência da assinatura ficam em destaque; cada janela mostra
seu próprio reset e tempo restante. Detalhes adicionais têm rolagem. Clique fora
ou use Escape para fechar. O clique direto no indicador abre o cliente da conta
padrão; **Abrir cliente** no painel usa a conta selecionada.

A bolinha representa a conta padrão: verde significa mais de 60% disponível;
amarelo, de 21% a 60%; vermelho, até 20%. Cinza é desconhecido, vencido ou parcial.
Uma outra conta não altera a cor da padrão; seu estado aparece ao selecioná-la.

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
- Codex Web e Grok: esta fonte não oferece uma franquia percentual confirmada.
  Permanecem cinza. Metadados de assinatura, quando disponíveis, aparecem como
  tal, separados da reposição de cota. A data de Grok pode ser informada pelo
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

## Abas de ações rápidas

**Selecionar tudo**, **Apagar tudo** e **Prompts** ficam em uma linha fina acima das abas.
Atuam somente no campo editável em foco, identificado pelo AT-SPI e pelo
proprietário da janela ativa. Apagar remove o texto do campo inteiro, não só a
seleção. Não leem seu conteúdo, não usam a área de transferência, não enviam
Enter nem apagam arquivos. Foco/campo alterado recusa a operação; não há repetição
automática. Campos sem acessibilidade e terminais sem interface editável informam
indisponibilidade, sem substituir a operação por atalhos globais de terminal.
Dependências opcionais: `libatspi`/AT-SPI 2 e `kdotool` no KDE/Wayland ou
`xdotool` em X11 com gerenciador de janelas. Não há instalação automática.

**Copiar** solicita a cópia da seleção do aplicativo em foco. **Colar** solicita
a colagem nele. Usam os atalhos alternativos de edição Ctrl+Insert e Shift+Insert;
assim, copiar nunca envia Ctrl+C para interromper um trabalho no terminal. O
aplicativo de destino precisa aceitar esses atalhos. O Fôlego não lê nem grava
o conteúdo da área de transferência ou as teclas em logs.

**Prompts** abre uma lista de 11 títulos: diagnóstico real, continuidade,
implementação, investigação de erro, revisão, testes, desempenho, segurança,
usabilidade, passagem de contexto e prontidão para PR/distribuição. Escolher um
copia seu texto para a área de transferência; depois cole no agente desejado.
Não cola, executa ou envia pedidos automaticamente. Os textos são genéricos,
respeitam as instruções e autorizações do projeto e pedem evidências verificáveis.

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
