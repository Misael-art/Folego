# Economia da tela e alívio cooperativo

## Controle da tela

Em **Opções → Economia da tela · Steam Deck**, a escolha começa desligada. Ao
ativá-la em KDE/Wayland, o Fôlego registra os valores anteriores do PowerDevil
antes de configurar o desligamento da tela por inatividade: 120 segundos na
bateria e 180 segundos na tomada. O próprio Plasma detecta ociosidade e reacende
a tela com mouse, toque, teclado ou controle reconhecido pelo compositor. O
Fôlego não suspende a sessão, não muda brilho/perfil de energia e não interrompe
os agentes.

O Fôlego consulta KWin antes de cada reconciliação. Uma janela ativa em tela
cheia pausa o temporizador; leitura de janela/monitor incerta também o pausa.
Com monitor externo já ativo, o temporizador é pausado. Se a tela interna ainda
estiver ativa, KScreen recebe uma operação para desativar **somente** `eDP-*`;
o compositor redistribui as janelas da saída removida. Quando o monitor externo
desaparece, o Fôlego reativa a tela interna que ele próprio desativou. Um
registro persistente identifica uma operação de dock incompleta para evitar
repetição cega. Uma mudança feita por outro aplicativo na configuração do
PowerDevil é preservada e apresentada como divergência.

Entregas confirmadas pelo monitor de agentes e subida para calor urgente/crítico
pedem ao KScreen que reacenda a tela. Eventos `PermissionRequest` e `Stop` do
Codex também pedem atenção se o hook opcional abaixo estiver habilitado. A
sondagem desses eventos é limitada a 5 segundos. A interface não lê conteúdo
de conversas para esse fim. O KDE Connect ou outro aplicativo pode inibir a
ociosidade no PowerDevil; a opção mostra o bloqueio e não força DPMS sobre ele.

Dependências nativas desta integração: PowerDevil/KDE Plasma, `kwriteconfig6`,
`qdbus6`, `kscreen-doctor`, `kdotool` e `busctl`. Se uma estiver ausente, a
ativação recusa o efeito. Esses utilitários são usados sem daemon adicional.

## Pedido aos agentes

Em calor urgente ou crítico, o Fôlego publica um pedido local em
`$XDG_RUNTIME_DIR/folego/agent-pressure.json`, com ID, boot, nível e validade de
90 segundos. A publicação se renova no máximo a cada 45 segundos enquanto o
calor permanecer na faixa. O retorno a uma faixa menor remove o pedido.
Somente o usuário da sessão pode ler esse canal. O pedido solicita reduzir
paralelismo ou aguardar no próximo checkpoint seguro; ele **não** pausa,
sinaliza, mata ou reconfigura processos. A publicação não comprova entrega,
aceite ou redução efetiva de carga.

O hook Codex `folego-agent-hook` lê esse pedido em `PreToolUse` e adiciona o
contexto ao agente. Em `PermissionRequest` e `Stop`, registra apenas um ID de
atenção de vida curta para o Fôlego reacender a tela. Não acessa o transcript
nem copia prompts, ferramentas ou credenciais. Como hooks locais exigem revisão
de confiança pelo Codex, a integração só opera depois que o usuário examina e
confia na definição pelo comando `/hooks`. A documentação oficial dos
[hooks do Codex](https://learn.chatgpt.com/docs/hooks) descreve esse fluxo e os
limites de cobertura. Outras IAs continuam com o aviso sonoro/visual de entrega
já suportado; nenhum canal de controle de carga dessas IAs foi presumido.

Exemplo para uma instalação em outro host, a ser mesclado ao `hooks.json`
existente sem substituí-lo; use o caminho absoluto do executável instalado:

```json
{
  "hooks": {
    "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/caminho/venv/bin/folego-agent-hook", "timeout": 3}]}],
    "PermissionRequest": [{"hooks": [{"type": "command", "command": "/caminho/venv/bin/folego-agent-hook", "timeout": 3}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "/caminho/venv/bin/folego-agent-hook", "timeout": 3}]}]
  }
}
```

## Limites de validação

Testes descartáveis cobrem configuração, reversão, divergência de outro owner,
janela desconhecida, dock e validade do pedido. O KDE/Wayland real deste host
está disponível para verificar opção, PowerDevil e tela interna. Sem monitor
externo conectado, o movimento real de janelas e o ciclo físico do dock não
podem ser certificados. Uma captura de tela não prova que o painel apagou nem
mede consumo de bateria; essas provas exigem observação física e medição em
descarga, sem gerar carga ou calor artificial.
