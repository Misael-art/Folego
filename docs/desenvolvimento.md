# Desenvolvimento do Fôlego

Guia curto para quem mexe no código: como montar o ambiente, rodar a suíte, onde
cada coisa mora e o que está fora de escopo por decisão. O registro de evolução
(etapas F0–F8) fica em `docs/reviews/2026-10-17/progresso.md`.

## O produto hoje

Fôlego é um assistente residente de bancada para Linux/KDE: mede RAM/CPU e
volumes, aponta processos órfãos de agentes, libera temporários com quarentena
reversível e aplica ajustes reversíveis do navegador Edge. A GUI Qt e a CLI
headless executam os mesmos atos; **nenhum ato mutante acontece por conta própria
— todo ato exige confirmação explícita (`--confirmar`) e é revalidado no ato de
executar.**

Decisões de plataforma (F0 da evolução, commit `61179f5`):

- Manter Python 3.14 + PySide6/Qt 6; alvo primário Linux/KDE (X11 e Wayland).
- A CLI (`python -m folego ...`) não importa Qt e é o caminho dos atos matáveis:
  a UI dispara atos como processos-filho (`ui/tune_jobs.py`), nunca no processo
  da janela.
- Automação por presets **desligada** até cumprir as pré-condições de F6 do
  plano de ação; o modo é manual.

## Ambiente

O ambiente atual é gerenciado pelo wrapper portátil, sem system-site-packages:

```bash
./dev setup --system-deps
./dev test-headless
./dev test
```

- Python 3.14.7, uv 0.12.10 e dependências de `uv.lock` em `.dev/`.
- `.venv` com Qt do sistema é ambiente histórico, não requisito de desenvolvimento.
- Primeira leitura e pendências: `docs/HANDOFF.md` e `docs/NOVO-HOST.md`.

Rodar:

```bash
./dev gui
./dev run tmpfs plan --json
```

## Testes

Comando de referência — `basetemp` exclusivo dentro de `.scratch`, nunca o
temporário da sessão (que pode estar sob `/run/user`, em RAM):

```bash
./dev check
```

Regras da casa:

- Nenhum teste toca dados reais do host. Fixtures são discos de descarte
  (`tmp_path`, `fake_home`, `fixtures_proc.py`); o walk de disco usa raiz falsa.
- Testes de mutação afirmam bytes e efeitos observados (sha antes/depois, arquivo
  intacto na recusa), não apenas "não explodiu".
- A suíte offscreen **não substitui** validação no KDE/Wayland: bandeja, escalas
  100/150/200% e leitor de tela são evidência de host (`tools/verify_*.py`).
- A suíte verde atual vale como piso, não como prova de ausência de defeitos.

Validação de desktop em 18/10/2026: wheel GUI não editable em venv sem pacotes
do sistema, Qt 6.12.0, launcher por GIO e remoção preservando todo o HOME
descartável. KDE Wayland físico a 135%, escalas 100/150/200% e hotplug em KWin
privado; X11 em Xvfb/KWin isolado. Suítes completas: 1134 testes em cada versão
Qt (6.11.2 e 6.12.0), 917 sem Qt. O soak de duas horas foi interrompido e não
recebeu aceite; a migração de 24/10 conserva as falhas e a última amostra.
Escopos, relatórios e reprodução em
[validação de compositor e instalação](reviews/2026-10-18/desktop-validation/README.md).

## Arquitetura

```
src/folego/
  core/        telemetria e regras sem Qt: procfs, sysfs, collector, snapshot,
               health (histerese), sessions (registro opt-in), exclusions,
               tmpfs (capacidade/plan), orphans, suggestions, browser
  actions/     atos: disk (planner/tmpclean/quarantine/measure/coordinated), tmpfs
               (inventory/holders/policy/ledger/release/coordinated), tunings
               (specs/engine/worker/coordinated), orphans (scan/reaper/coordinated)
  safely/      kernel de segurança: guard, mounts, atomicfile, backup, hashing,
               audit, jsonedit, persist (JSON/JSONL durável com problemas
               relatados e backup), selftest
  process/     runner de filho isolado (timeout, kill, JSON de saída)
  orchestration/  contratos comuns (F2): ResourceIdentity/ActionPlan/ActionResult/
               Grant/OperationState, diário de intenção, coordenador com flock e
               ponte (Coordinated/perform), histórico visual com leitura limitada
  cli.py       CLI headless: disk, orphans, groups, process, tune, tmpfs, session,
               exclusions
  ui/          Qt: main_window, dashboard, ajustes, órfãos, disco, temporários,
               bandeja, tune_jobs, workers
  paths.py     XDG; tudo lê o ambiente na chamada (testável com HOME falso)
```

Invariantes que o código precisa preservar:

- `core/` e `actions/` não importam Qt; a UI só pede atos por argv de filho.
- Leitura desconhecida/parcial **não** vira "vazio/livre/abandonado": resultados
  carregam estado/erro e a política recusa o que não foi lido por inteiro.
- Idade, nome, PPID=1 ou CPU baixa geram *candidato*, nunca autorização
  automática. No ato do sinal, o pidfd é aberto **antes** da releitura do
  `/proc` (o fd pina o processo; starttime, proteção, órfão e automação são
  revalidados) — kernel sem pidfd cai no fallback de starttime + `kill`, nomeado
  no resultado. `SIGTERM` não é prova de encerramento: a saída é acompanhada até
  um prazo, o sobrevivente é nomeado e não há escalada automática para `SIGKILL`
  (só por pedido explícito, com confirmação própria).
- Telemetria declara sua própria qualidade: cada fonte carrega
  `ok|partial|missing|error` e um detalhe, e a idade usa o relógio monotônico
  (`Snapshot.mono`), nunca a parede. Amostra sem relógio, antiga ou com fonte
  obrigatória inutilizável **bloqueia ação** (`action_blockers`); não vira
  "vazio/seguro". CPU e I/O são diferenças entre amostras — a primeira leitura é
  `None`, nunca zero — e RSS é estimativa; PSS é lido sob demanda. O
  `HealthEngine` é puro, piora escala na hora e melhora um degrau por
  `recovery_samples`; a coleta roda em thread sem Qt, com no máximo uma em voo.
- Sessões são opt-in: arquivo ausente = vazio, nunca inferido; JSON versionado,
  UUID, `boot_id` e `starttime` distinguem reboot e PID reciclado. `active`,
  `disconnected`, `heartbeat_lost` e `ended` são estados diferentes. `keep_active`
  é revalidado no ato por órfãos/grupos/reaper e sobrevive à perda de heartbeat
  enquanto a identidade viver; registro ilegível protege (falha fechada). O
  launcher `folego session run -- ...` inicia o filho em sessão própria e não o
  sinaliza se o launcher cair. Exclusões por app/projeto/sessão/cmdline/path
  seguem a mesma regra; `keep_active` protege além de filtrar.
- Artefatos guardam apenas metadados (caminho absoluto, tipo, tamanho observado,
  validade) e **nunca** são apagados por expiração: `session expired` só lista.
  Cgroup é leitura experimental de `/user.slice`/`user@...`; nenhuma unidade
  systemd é criada ou sinalizada. Processo adotado com CPU ativa aparece como
  **investigação possível**, não como órfão provado, e não habilita encerrar.
- Destino de retenção de tmpfs tem de estar comprovadamente fora da RAM, em monte
  diferente da origem e com folga — decidido por `safely/mounts.py` (mountinfo
  lido **no ato da liberação**), nunca por prefixo de caminho ou pela convenção do
  XDG. A cota de retenção é **conjunta** com o staging: o teto soma o que está
  certificado e os clones `staging` medidos no disco na hora (clone que não mede
  por inteiro é problema: a cota recusa, não estima); o `expire` segue intocável
  para staging — apagar a única cópia seria adivinhação.
- Contabilidade separa estimativa, transferência, retenção e **variação
  observada**: o `release` reporta o tamanho aparente (`st_size`, lógico e
  transferido), os **bytes alocados** medidos no clone que ficou (`st_blocks*512`
  — num arquivo esparso o aparente mente) e a variação de RAM medida por
  `statvfs` no volume antes/depois do ato. Volume que não responde vira `None`
  ("não medido"), nunca zero; "liberado" rotula o conteúdo que saiu da RAM, não a
  variação medida.
- Toda mutação confirmada de tmpfs (`release`/`restore`/`expire`/`recover`) e da
  quarentena de disco (`quarantine`/`restore`/`purge`/`reconcile`) passa pelo
  coordenador único (`actions/*/coordinated.py`, com o esqueleto comum em
  `orchestration/bridge.py`): intenção no diário antes do efeito e resultado
  estruturado depois. Dry-run e recusa de flag respondem direto, sem diário; o
  reparo do `disk list` só é operação quando há transição pendente — sem reparo
  (ou com decisão manual), listar continua sendo ler.
- Ajustes (`apply/revert`) e sinais (`orphans/groups/process`) também passam
  pelo coordenador comum. A GUI padrão usa QProcess para sinais, com plano v2 e
  ID estável; proteção de sessões/exclusões e ancestralidade é relida no executor.
  Sinal sem término comprovado é parcial. Acompanhamento ilegível não vira saída.
- O histórico da central/compacto é texto em memória, atualizado por worker com
  leitura limitada por rodada; mudanças no arquivo exigem revalidação. Resumo
  ainda em leitura não autoriza mutação. Resultados desconhecidos não aparecem
  como recusa e bloqueiam repetição pelo painel até reconciliação.
- Estado persistido desconhecido/ilegível **nunca** vira vazio: o manifesto da
  quarentena é versionado (envelope `schema` + `entries`, listas cruas antigas
  migram na primeira escrita com a geração anterior em `manifest.json.bak`) e um
  manifesto inconsistente bloqueia toda mutação, com o relatório nomeando cada
  problema (linha, motivo). Caminho registrado relativo é problema, não alvo; o
  payload tem de estar confinado à raiz privada da quarentena (o guard sozinho
  aceita qualquer caminho sob as raízes permitidas).
- O ledger JSONL de tmpfs segue a mesma regra: cada linha nova carrega `schema`
  (linha sem o campo é formato legado aceito), e JSONL ilegível ou schema de
  versão mais nova é problema **relatado**, nunca pulado em silêncio —
  `release`/`restore`/`expire`/`recover` recusam enquanto houver qualquer
  problema, nem o dry-run decide com mapa incompleto. A visão `tmpfs ledger`
  mostra o que pôde ser lido e nomeia o resto (campo `problems` no `--json`).
  A hidratação é campo a campo: linha editada à mão perde só o campo removido —
  `stored` legível continua legível, estado ausente assume `partial` — e nunca
  blanka o registro inteiro (o fallback que fazia isso foi eliminado; achado da
  entrega 6, onde um clone vivo deixava de contar na cota conjunta).
- A liberação de tmpfs registra `staging` **antes** do primeiro byte copiado:
  interrupção no meio da cópia é recuperável (`folego tmpfs recover`), nunca clone
  órfão. Com a origem viva o clone inacabado é descartado; com a origem sumida o
  clone não certificado é preservado e vira decisão manual — apagar seria
  adivinhação destrutiva.
- Backup reversível é privado (0600/0700) e durável (fsync do payload, do
  manifesto e dos diretórios) antes da escrita que ele protege.
- Todo caminho da CLI termina em um desfecho nomeado do vocabulário do diário,
  com código de saída estável (0 sucesso, 1 recusa, 2 falta confirmar, 3 parcial,
  4 falha, 5 desconhecido; 6 cancelamento reservado). Com `--json`, **todo**
  desfecho — inclusive recusa — é um objeto único no stdout com
  `ok`/`exit`/`outcome`; o stderr é a voz humana. Interromper ou estourar o prazo
  não prova ausência de efeitos: `desconhecido`, nunca `cancelamento`. Detalhes
  na seção "Protocolo de saída da CLI".

## Protocolo de saída da CLI (F2/entrega 7)

Consulta de recuperação: `folego operation ID --json` lê o diário sem reaplicar.
ID ausente/intenção pendente/histórico ilegível devolvem desconhecido (5), não
prova de ausência de efeito. Não repetir mutações desconhecidas às cegas.

O endpoint `folego process --plan JSON --confirmar --json` executa o plano de
processos exibido pela GUI; SIGKILL exige também `--forcar`. Boot desconhecido,
identidade/CPU/proteção alterada recusam; mesmo plano/ID não repete o sinal.
Detalhes, testes e limites de recuperação em
[processos, ajustes e histórico](reviews/2026-10-18/continuacao/processos-ajustes-historico.md).

Quarentena manual: `disk plan --json` entrega `action_plan` por item cuja revisão
completa foi possível. A GUI confirma e envia o mesmo snapshot por
`disk quarantine CAMINHO --reviewed-plan JSON --confirmar --json`; mesmo ID já
concluído consulta o resultado. Mudança de identidade/árvore/montagem ou validade
exige nova análise. A entrada direta usa o mesmo filtro de revisão. Ausência de
lease contra novos escritores ainda impede automação desse caminho.

Runtime: `ecosystem --adapter pytest-fixtures --json` inventaria fixtures legadas
apenas na raiz específica do Codex, preservando atual/locks/referências e
desconhecidos. Todos os itens ficam protegidos; não há arquivamento integrado.

Grants novos exigem `--resource JSON` (ResourceIdentity serializada), limites
reconhecidos e TTL limitado; registros antigos insuficientes ficam inativos.
Planos v2 usam snapshot imutável e prazo padrão de 300 segundos. Detalhes e
pendências em [contratos atuais](reviews/2026-10-18/continuacao/autorizacao-implementacao.md).

Todo comando termina em **um** desfecho, com o mesmo vocabulário do diário
(`Outcome`) e um código de saída estável:

| Código | Desfecho (`outcome`) | Quando |
|---|---|---|
| 0 | `sucesso` | o ato pedido aconteceu por inteiro |
| 1 | `recusa` | nada foi tocado (trava/porta, guard, alvo fora do plano, flag) |
| 2 | `falta confirmar` | mutação sem `--confirmar` (o mesmo 2 que o argparse usa para invocação inválida) |
| 3 | `parcial` | parte do efeito existe e o resto ficou nomeado (clone retido, vítima com suspeita) |
| 4 | `falha` | erro inesperado (exceção); traceback só com `FOLEGO_TRACEBACK=1` |
| 5 | `desconhecido` | não dá para saber se houve efeito (Ctrl-C no ato, timeout/abandono do filho) |
| 6 | `cancelamento` | **reservado** — nenhuma rota da CLI o produz hoje |

Com `--json`, **todo** desfecho — inclusive recusa — sai como um objeto único no
stdout; o consumidor de máquina não depende do stderr nem de inferir pelo
código, e o stderr continua sendo a voz humana:

```json
{"acao": "release", "ok": false, "exit": 1, "outcome": "recusa",
 "entry_id": "1700-abcd", "reason": "refused: ...", "operation_id": "…",
 "effects": {"entry_id": "1700-abcd", "freed_bytes": 0}}
```

Resultados de domínio (com `to_dict`) e `operation_id`/`effects`/`errors` do
veredito viajam no objeto quando existem; `disk quarantine/restore/purge` também
aceitam `--json`. Semântica que não se negocia:

- **Ctrl-C** no meio de uma operação devolve `desconhecido` (5): interromper não
  prova ausência de efeitos — o diário mostra o que começou, consulte antes de
  repetir. `cancelamento` (6) fica reservado para quem cancela **antes** de
  qualquer efeito.
- **Timeout/abandono do filho** na GUI segue a mesma regra: mutação que ficou sem
  resposta é `desconhecido` (pode ter começado o efeito); leitura é `recusa`;
  `FailedToStart` (o filho não existiu) é `recusa`.

## Inventário de funcionalidades

| Área | GUI (abas) | CLI | Estado |
|---|---|---|---|
| Memória/CPU ao vivo | memória, título da janela, bandeja | — | manual; fontes com qualidade, idade monotônica, CPU/I/O por delta e `HealthEngine` com histerese |
| Órfãos de agentes | órfãos: candidatos, grupos, seleção, pista de CPU ativa | `folego orphans [--confirmar] [--forcar]`, `folego groups [--confirmar] [--forcar]` | manual; identidade por pidfd/starttime no ato; SIGTERM acompanhado (sobrevivente = parcial); SIGKILL só por pedido explícito e confirmado; `keep_active`/exclusões revalidados no ato; CPU ativa é investigação, não autorização |
| Sessões e exclusões | proteção aplicada aos órfãos; pista de CPU ativa | `folego session start\|run\|heartbeat\|disconnect\|end\|list\|artifact\|expired`, `folego exclusions add\|list\|remove` | manual/opt-in; UUID, reboot e PID reciclado distintos; artefatos só metadados; expiração nunca apaga; cgroup somente leitura experimental |
| Disco/quarentena | disco: plano, quarentena, restauração | `folego disk plan\|quarantine\|restore\|purge\|list` | manual; mutações e reparo de queda sob o coordenador (F2); manifesto v1 com backup e recusa de estado inconsistente; mutações com `--json` no protocolo de desfecho |
| Temporários legados | — | `folego disk tmp` | **somente leitura**; aponta para `tmpfs` |
| Ajustes Edge | ajustes: aplicar/reverter com backup | `folego tune status\|apply\|revert` | manual; Edge fechado obrigatório; backup privado |
| Tmpfs/watch-list | temporários: volumes, plano, ledger | `folego tmpfs status\|plan\|release\|restore\|ledger\|expire\|recover` | manual; retenção com orçamento; estado `staging` recuperável; mutações confirmadas sob o coordenador (F2); ledger v1 por linha, com inconsistências relatadas que recusam mutação; destino não-RAM com folga e cota conjunta (retenção+staging) verificados no ato; contabilidade fina do release (lógico/alocado/observado); protocolo de desfecho (0–6) com `--json` em todo desfecho |
| Bandeja | menu com estado e atalhos | — | manual |
| Automação/presets | — | — | **desligada** (F6 do plano) |

Limitações conhecidas e pendências:

- A matriz atual de compositor usa `tools/desktop_probe.py` e
  `tools/verify_desktop_flow.py`, com controladores privados de X11/hotplug.
  Evidência de compositor permanece separada da suíte offscreen. Leitor de
  tela real e arraste físico Wayland continuam pendentes.
- **T14 do plano M7 segue pendente no checkout**: `tools/verify_tmpfs.py` e
  `tests/test_tools_verify_tmpfs.py` não existem neste commit. A evidência de
  host para o M7 não foi produzida; nada neste repositório afirma o contrário.
- Riscos ainda bloqueados para automação (R08, R09, R11–R17 da avaliação
  técnica) e as ações de F2–F8 estão descritos no plano e no registro de
  progresso; não repita neste arquivo o estado que muda por sessão.
- A central e o compacto existem parcialmente; o fluxo integral de revisão,
  execução e recuperação e o botão principal “Dar fôlego” seguem pendentes. A
  proteção de sessões/exclusões já vale na listagem e no reaper, mas não há uma
  tela dedicada para iniciar/encerrar sessões; o launcher é a CLI. A validação
  de todas as telas novas em KDE/Wayland já tem capturas e fluxos de ciclo de
  vida; escalas 100/150/200% foram exercitadas em compositor virtual. Leitor de
  tela e os demais limites estão registrados na matriz de validação.
