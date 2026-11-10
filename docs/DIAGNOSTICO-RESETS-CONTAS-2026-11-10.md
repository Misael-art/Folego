# Resets e contas: lacunas e correções — 10/11/2026

## O que aconteceu

O Claude Desktop mostrou em **Configurações › Uso** uma "Redefinição do Fable"
gratuita, válida até 17/11 04:59 BRT. O Fôlego não mostrou marcador, pop-up
nem som. A mesma tela mostrava um aviso de ritmo ("vai esgotar seu limite
amanhã") que o Fôlego também não exibiu.

## Evidência colhida no host

- Leitura única, pelo coletor do próprio Fôlego, de
  `api.anthropic.com/api/oauth/usage` em 10/11 08:07 UTC, com o reset visível
  no Desktop. A resposta **não traz a oferta**: `promo_credits`, `pace`,
  `indicator` e todos os campos promocionais vieram `null`.
- O Claude Code instalado (2.1.316) e os recursos locais do Desktop
  (4.23118.0) não contêm endpoint de leitura dessa oferta. A tela de Uso é
  conteúdo remoto servido pela sessão web do claude.ai.
- A mesma resposta traz `limits[]` com um limite `weekly_scoped` do modelo
  **Fable em 54%**, enquanto a semana geral estava em 45%. O Fôlego só lia
  `seven_day_opus` e `seven_day_sonnet`, ambos `null`.

## Lacunas

| # | Lacuna | Causa | Situação |
|---|--------|-------|----------|
| 1 | Reset gratuito do Claude não é percebido | A fonte autorizada (OAuth) não expõe a oferta. Ler a sessão web do Desktop exigiria copiar cookies, o que o projeto proíbe | Contornada com lembrete pessoal; detecção automática segue impossível |
| 2 | Nenhum aviso quando surge um reset, em qualquer provedor | O rastreador de alertas só observava percentuais. Um ticket novo do Codex também passava em silêncio | Corrigida |
| 3 | Reset perto de vencer não é lembrado | Não existia noção de validade nos alertas | Corrigida |
| 4 | Limite semanal por modelo (Fable) invisível | O coletor lia só os campos antigos por modelo | Corrigida |
| 5 | Texto "não informados nesta fonte" não orienta | A mensagem não dizia onde conferir | Corrigida para o Claude |
| 6 | Aviso de ritmo do provedor não aparece | `pace` veio `null` na leitura; o formato real é desconhecido | Aberta |
| 7 | Resgate de reset no meio da janela não toca "disponível novamente" | O som exige cota zerada, faixa crítica ou prazo de reposição maior | Aberta |
| 8 | Estrutura nova `spend` (créditos de uso) ignorada | O coletor lê só `extra_usage` | Aberta |
| 9 | Reset e limite do Codex Web continuam desconhecidos | O launcher só conta envios próprios | Aberta, sem fonte do provedor |

## Correções aplicadas

- **Janela por modelo.** `core/ai_sessions.claude` lê os limites
  `weekly_scoped` e cria janelas como `Semana Fable`. O percentual da conta
  passa a refletir a janela mais restrita. Entrada inválida mantém o
  comportamento de resposta parcial, sem percentual.
- **Lembrete pessoal de reset.** Como a fonte não expõe a oferta, a conta
  aceita um lembrete com validade: botão **Lembrete de reset…** no painel de
  contas e `folego ai reset-note --account ID --expires "DD/MM/AAAA HH:MM"`
  (`--clear` remove). Fica em `reset_notes` de `ai-sessions.json`. Aparece
  como ticket "informado por você" nos mesmos marcadores da mini, do compacto
  e do painel. Nunca substitui a contagem do provedor e deixa de contar após a
  validade. O Fôlego não consulta nem resgata o reset.
- **Aviso de reset.** `AlertTracker.reset_changes` relata reset novo (após a
  primeira leitura, que é silenciosa) e um único lembrete nas últimas 24 h de
  validade. Leitura desconhecida não vira zero nem repete aviso. A bandeja
  publica "Contas · provedor" e há um som próprio, testável em Opções.

## Como superar o que ficou aberto

- **1:** acompanhar novas versões do Claude Code. Se `oauth/usage` passar a
  preencher um campo de oferta, ler esse campo e aposentar o lembrete manual.
- **6:** capturar uma resposta com `pace` preenchido antes de exibir. Uma
  projeção própria pela inclinação do uso é alternativa, com rótulo de
  estimativa.
- **7:** tratar queda brusca de uso dentro da mesma janela como reposição
  confirmada, com teste que separe resgate de troca de conta.
- **8:** ler `spend` quando houver conta com créditos ativos para validar.

## Validação

Python 3.14.7, HOME/XDG privados, Qt offscreen. Headless focado: 86 aprovados
(`run-c7qf0ch2`). Qt focado: 198 aprovados (`run-ox_y14ut`) e 8 do painel
(`run-72t15vp5`). No host real, `ai status` mostrou `Semana Fable` e o
lembrete registrado para a conta Claude principal. Suítes completas ficam
para o CI. Pop-up, som e diálogo não foram exercitados no KDE/Wayland real: a
GUI residente carrega a mudança só na próxima abertura.
