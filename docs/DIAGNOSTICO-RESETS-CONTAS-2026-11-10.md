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
| 6 | Aviso de ritmo do provedor não aparece | `pace` veio `null` na leitura; o formato real é desconhecido | Corrigida com estimativa local |
| 7 | Resgate de reset no meio da janela não toca "disponível novamente" | O som exige cota zerada, faixa crítica ou prazo de reposição maior | Corrigida |
| 8 | Estrutura nova `spend` (créditos de uso) ignorada | O coletor lê só `extra_usage` | Corrigida para os campos observados |
| 9 | Reset e limite do Codex Web continuam desconhecidos | O launcher só conta envios próprios | Contornada com lembrete pessoal; sem fonte do provedor |

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

## Segundo lote (mesmo dia)

- **Ritmo (6).** O formato de `pace` não existe no cliente instalado, então o
  Fôlego calcula uma estimativa linear própria (`pace_forecast`): janela com
  duração confirmada, 10% decorridos, 20% usados e esgotamento previsto com
  folga de 10% antes da reposição. Aparece em `ai status` e no painel com o
  rótulo "estimativa local". A bandeja avisa uma vez por janela de um dia ou
  mais. Na leitura real de 10/11 a previsão da semana coincidiu com o aviso
  do provedor ("amanhã no começo da noite").
- **Resgate no meio da janela (7).** Subida de 20 pontos ou mais na cota da
  mesma conta toca "disponível novamente".
- **Créditos de uso (8).** `spend` é lido para habilitação, consumo, teto,
  saldo e percentual. `limit` e `balance` vieram `null`; só entram quando
  tiverem o mesmo formato monetário de `used`.
- **Codex Web (9).** Continua sem fonte do provedor. A conta Web aceita um
  lembrete de quando o ChatGPT disse que o limite volta (**Lembrete de
  limite…** ou `ai limit-note`). Não vira cota nem percentual; a bandeja
  avisa quando o prazo passa.

## O que continua aberto

- **1 e 9:** detecção automática depende de o provedor expor a informação.
  Se `oauth/usage` passar a preencher um campo de oferta, ler esse campo e
  aposentar o lembrete manual.
- **6:** substituir a estimativa pelo valor do provedor quando houver uma
  resposta com `pace` preenchido.
- **8:** validar `limit` e `balance` em conta com créditos ativos.

## Validação

Python 3.14.7, HOME/XDG privados, Qt offscreen. Headless focado: 86 aprovados
(`run-c7qf0ch2`). Qt focado: 198 aprovados (`run-ox_y14ut`) e 8 do painel
(`run-72t15vp5`). No host real, `ai status` mostrou `Semana Fable` e o
lembrete registrado para a conta Claude principal. Segundo lote: headless
focado 127 aprovados (`run-f_jga585`); Qt focado 219 de 220, com a única falha
sendo a contagem de modelos do painel de prompts, corrigida e repassada.
`ai status` real mostrou ritmo e créditos de uso. Suítes completas ficam
para o CI. Pop-up, som e diálogo não foram exercitados no KDE/Wayland real: a
GUI residente carrega a mudança só na próxima abertura.
