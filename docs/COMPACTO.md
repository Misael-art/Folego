# Widget, sessões de IA e atalhos

O widget tem 280 px de largura em pixels lógicos do desktop. Recursos ficam em
duas linhas; alertas completos e mensagens podem aumentar a altura. Minimizar
oculta o widget com um caminho de retorno; ampliar abre a central; fechar sai
do Fôlego. Pausar controla a telemetria de recursos. A consulta de IAs é separada
e funciona enquanto o widget está visível. Fechar o aplicativo encerra seus
workers e seu próprio auxiliar de entrada.

## Sessões de IA

Passe o mouse sobre Codex, Web, Claude ou Grok para consultar cada conta. Clique
no indicador para abrir a aplicação ou seu terminal existente. Verde significa mais de 60% da cota disponível;
amarelo, de 21% a 60%; vermelho, até 20%. Cinza é desconhecido, vencido ou parcial,
inclusive se uma das contas agrupadas não tem uma observação válida.

- Codex: leitura limitada dos registros `rate_limits` que o cliente grava em
  seu diretório de sessões. A menor disponibilidade das janelas conhecidas
  determina a cor. Observação de mais de 15 minutos, futura ou com reposição já
  vencida deixa de fornecer um percentual atual. Não se inventa 100% no reset.
- Claude: consulta de uso ao endpoint OAuth da Anthropic com a credencial local
  já existente. Credencial expirada ou alterada durante a consulta invalida a
  resposta. Não se renova, copia ou grava a credencial; redirecionamentos HTTP
  são recusados. Não há rede no loop gráfico.
- Codex Web e Grok: esta fonte não oferece uma franquia percentual confirmada.
  Permanecem cinza. Metadados de assinatura, quando disponíveis, aparecem como
  tal, separados da reposição de cota. A data de Grok pode ser informada pelo
  usuário; isso não confirma pagamento ou cota.
- Token presente não prova renovação futura válida. O painel distingue a
  observação aceita pelo provedor de metadados locais e validade não verificada.
  Cupons/créditos não fornecidos pela fonte continuam não informados.

Fôlego usa configuração própria e não importa, inicia ou administra PhaseZero.
Os diretórios nativos padrão são `$CODEX_HOME` ou `~/.codex`,
`~/.local/share/codex-web-gpt/codex-home` e `$CLAUDE_CONFIG_DIR` ou `~/.claude`.
Para outras contas, crie `$XDG_CONFIG_HOME/folego/ai-sessions.json` (por padrão,
`~/.config/folego/ai-sessions.json`). Caminhos devem ser absolutos. Exemplo:

```json
{
  "schema": 1,
  "accounts": [
    {"provider": "codex", "label": "Codex trabalho", "path": "/caminho/conta/codex-home"},
    {"provider": "web", "label": "Web pessoal", "path": "/caminho/conta-web/codex-home"}
  ],
  "grok_paid_until": "2026-11-30T23:59:59-03:00"
}
```

Pode apontar para um diretório já criado por outro launcher; os arquivos
permanecem no lugar. Nenhum token deve ser colocado nessa configuração. Schema
desconhecido, conta ilegível ou orçamento excedido aparecem como desconhecidos.
O limite é 16 contas adicionais e 40 rollouts com caudas de até 64 KiB por conta.
Para consultar sem Qt: `./dev run ai status --json`.

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
com classe e identidade verificadas. Em KDE/Wayland usa `kdotool`; em X11,
`xdotool`. Se não houver janela, pode solicitar uma única abertura pelo atalho
nativo instalado (`gtk-launch`). Sem janela/atalho identificado, informa a
indisponibilidade. Nenhum comando é enviado aos agentes e nenhuma sessão é
encerrada. A abertura mostra a aplicação para o usuário escolher a sessão;
não seleciona automaticamente uma conversa ou aba interna do terminal.

Os avisos exibidos só são marcados como vistos após confirmação de foco da
janela. Falha preserva a contagem; uma conclusão posterior ao clique não é
apagada por ele. O estado pertence ao Fôlego em
`$XDG_STATE_HOME/folego/ai-deliveries.json` (padrão
`~/.local/state/folego/ai-deliveries.json`), privado, com marco inicial e recibos
em hash, sem texto de conversas ou credenciais. Reiniciar preserva os avisos.
Estado ilegível ou schema desconhecido não é sobrescrito.

Orçamentos do monitor de entregas: 64 raízes, 128 sessões por raiz, caudas de
64 KiB e até 2048 recibos. Inventário excedido, registro incompleto ou conclusão
fora da cauda legível deixam a observação parcial, sem amostragem silenciosa.

## Abas de ações rápidas

**Copiar** solicita a cópia da seleção do aplicativo em foco. **Colar** solicita
a colagem nele. Usam os atalhos alternativos de edição Ctrl+Insert e Shift+Insert;
assim, copiar nunca envia Ctrl+C para interromper um trabalho no terminal. O
aplicativo de destino precisa aceitar esses atalhos. O Fôlego não lê nem grava
o conteúdo da área de transferência ou as teclas em logs.

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

Em KDE/Wayland, o posicionamento exige KWin e `qdbus6`; a confirmação compara os
mesmos pixels físicos, inclusive com escala fracionária. A entrada exige
`ydotool`, `ydotoold` e permissão **já existente** para `/dev/uinput`. O Fôlego
cria um auxiliar transitório próprio e seu socket privado de IPC, encerrando-o
ao sair; não instala serviço, amplia permissões ou reutiliza um daemon alheio.
Somente o socket de comunicação fica no runtime; TMPDIR/payloads ficam em disco
persistente. Em X11, usa `xdotool`. Ausência ou falha é apresentada, sem retry
automático. Nenhum desses controles habilita o executor de recursos.

## Distribuição e evidência

Esta entrega é **0.2.0b1**, uma prévia para Linux, Python 3.14 e Qt/PySide6.
Baixe a versão marcada na página Releases do GitHub, confira `SHA256SUMS` e use
o código-fonte para `./dev setup` e `./dev gui`, ou instale o wheel em um ambiente
Python 3.14 próprio com a dependência GUI. Não há AppImage/Flatpak nesta prévia.
As dependências opcionais acima não são instaladas silenciosamente.

[Validação deste incremento](handoff/validation/compact-ui-2026-11-01/README.md).
O histórico e as pendências gerais continuam em [HANDOFF](HANDOFF.md); a prévia
não certifica a matriz física de entrada, login, hardware ou todas as aplicações
de destino, nem resolve as pendências do motor de recursos registradas ali.
