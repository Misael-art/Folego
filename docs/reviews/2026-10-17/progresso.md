# Registro de progresso da evolução

Plano: [04-plano-de-acao.md](04-plano-de-acao.md). Revisão base:
`61179f55123b44a996aa6087d124474eb5e84b1e`. Este arquivo é o ponto de retomada:
se o contexto terminar, continue a partir daqui.

## Etapa atual

**Migração de 24/10/2026:** entrega preservada em Git e preparada para novo host.
Leia primeiro [HANDOFF](../../HANDOFF.md),
[diagnóstico atual](../../DIAGNOSTICO-2026-10-24.md) e
[recuperação/bootstrap](../../NOVO-HOST.md). O wrapper `./dev` reconstrói
Python/dependências isoladamente, com lockfile e testes em HOME privado.
**Nenhum soak de duas horas foi concluído/aceito**; última amostra: 2470 segundos.
Os avisos “em andamento” abaixo são histórico, não processos atuais. Automação
permanece desligada. O próximo agente não precisa deste disco nem do venv antigo.

**Retomada compositor/instalação/soak:** corrigidos largura da central,
fallback decorado do compacto no Wayland, ciclo de vida sem bandeja, pausa
antes da primeira amostra e bandeja disponível desde a abertura. Instalação
por wheel GUI em venv limpo no mesmo BigLinux, launcher GIO sem ativação de
venv e remoção preservando estado passaram. KDE Wayland físico a 135%; escalas
100/150/200% e hotplug em KWin privado; X11 em Xvfb/KWin isolado passaram.
Suítes: **1134/1134** com Qt 6.11.2/6.12.0; **917** sem Qt.
**Soak de duas horas ainda em andamento**: tentativa anterior interrompida
antes do reboot do host; tempo não somado. Leitor de tela, arraste físico
Wayland e outra distribuição limpa continuam sem aceite.
[Matriz, correções, evidências e limites](../2026-10-18/desktop-validation/README.md).

**Retomada processos/ajustes/histórico:** rotas mutantes de produção usam o
coordenador; GUI padrão sinaliza por QProcess, com plano/boot/ID e proteção
fresca de sessões/exclusões/ancestrais. Sinal sem término comprovado é parcial;
resultado desconhecido permanece visível e bloqueia repetição nos painéis.
Histórico da central/compacto sai da thread gráfica, com leitura por passos e
revalidação de arquivo alterado. Suíte completa: **1127 passed in 24.92s**;
venv sem PySide6/shiboken6: **917 passed in 14.82s**. `git diff --check` passou.
C05 original tratado nas rotas de produção; C01/C04/C13 e I2 ainda parciais.
Automação desligada; sem aceite de compositor, instalação limpa ou soak de horas.
[Código, evidências, comandos e próximos aceites](../2026-10-18/continuacao/processos-ajustes-historico.md).

**Retomada revisão de disco/runtime:** o plano JSON exibido na GUI é confirmado
e executado com o mesmo ID; árvore/ancestrais/montagem revalidados e proteção
também aplicada à entrada direta. Inventário de fixtures pytest integrado em
`ecosystem`, somente leitura e todos os itens protegidos. Resultado incerto do
motor prevalece sobre sucesso do domínio na CLI. Suíte completa: **1092 passed
in 23.82s**; sem Qt: **890 passed in 14.99s**. I1/I2/R3 continuam parciais; automação desligada.
[Registro, capturas e limites](../2026-10-18/continuacao/revisao-disco-runtime.md).

**Retomada autorização/frescor:** planos v2 profundamente imutáveis e com prazo;
grants por identidade explícita, limitados e revogação/pausa relidas sob travas;
consulta `folego operation ID --json`; saúde expira sem amostras novas.
Suíte final: **1074 passed in 19.42s**; sem Qt: **873 passed in 13.45s**.
I1/I2 continuam parciais; automação desligada. [Registro e pendências](../2026-10-18/continuacao/autorizacao-implementacao.md).

**Retomada runtime (18/10/2026): I2R/R1/R2/R5 parciais integrados.** Descoberta
do runtime por UID, qualidade por volume, alertas por bytes/inodes e temporários
privados em disco nos filhos Qt/CLI. Suíte final: **1049 passed in 28.50s**;
venv sem Qt: **850 passed in 17.85s**. R3/R4 e automação não habilitados.
[Código, comandos, evidências e limites](../2026-10-18/continuacao/runtime-implementacao.md).

**Atualização de 18/10/2026 — continuidade I0/I1 parcial.** A classificação
histórica abaixo não é o aceite atual: F2 continua bloqueado por autorização,
snapshot do plano e integração de todas as mutações. Foram corrigidos C06
(reuso visível/callback/foco), C07 (seleção anterior à importação Qt) e C09
(transação leitura–alteração–escrita); C01/C02/C04/C12 receberam correções
parciais. A automação permanece desligada. A suíte offscreen mais recente
executou **1033 passed in 19.60s**; venv isolado sem Qt executou **835 passed
in 15.48s**. Houve segfault intermitente em `QApplication.allWidgets` antes
de adicionar descarte explícito das árvores Qt entre testes; os logs de falha
foram preservados. Comandos, limites e pendências em
[registro da continuidade](../2026-10-18/continuacao/README.md).

### Registro histórico anterior (17/10; não representa o aceite atual)

**F0 e F1 concluídos; F2 com as entregas 1–8 completas e uma extensão registrada;
F3 (telemetria e sessões) completo nos cinco incrementos.** A suíte completa fechou
em **859 passed** com `basetemp` exclusivo dentro de `.scratch` (17/10/2026).
F0 e F1 entregam as regressões R01–R07, as correções de risco e de interface e a
documentação de base (`docs/desenvolvimento.md`). Em F2,
`orchestration/{models,journal,coordinator}.py` têm testes próprios e
`release_item`, `restore_item`, `expire_over_budget`, `recover_staging`,
`disk quarantine/restore/purge` e o reparo de queda (`reconcile`) executam
**sempre** sob o coordenador quando confirmados (intenção antes do efeito; trava
`flock` entre processos). A liberação grava `staging` antes do primeiro byte;
interrupção no meio da cópia é recuperável, com a origem viva ou preservando o
único clone. O ledger de tmpfs e o manifesto da quarentena são versionados e
falham fechados; destino não-RAM, folga e cota conjunta são verificados no ato; o
release separa lógico/alocado/observado. Todo desfecho da CLI segue o protocolo
0–6, com um objeto JSON único no stdout inclusive na recusa. O encerramento de
processos usa `pidfd` aberto **antes** da releitura (fallback de starttime
nomeado), SIGTERM acompanhado e sobrevivente nomeado; `SIGKILL` só por pedido
explícito, nunca escalada automática. Ainda fora do coordenador: as mutações de
ajustes e de órfãos/grupos; a automação segue **desligada**.

F3 entregou a base honesta de telemetria (`Snapshot.mono`/idade/fontes com
`ok|partial|missing|error` e bloqueios de ação), CPU/I/O somente por delta (a
primeira leitura é `None`, nunca zero), `HealthEngine` puro com histerese,
coleta em thread sem Qt e UI por diferença, e o registro opt-in de sessões com
UUID/reboot/PID reciclado/estados distintos, `keep_active` revalidado no ato,
exclusões versionadas, artefatos só como metadados com validade, cgroup de usuário
somente leitura e a investigação de processos com CPU ativa (pista, não
autorização).

## Linha de base (F0)

- Commit de partida: `61179f55123b44a996aa6087d124474eb5e84b1e`; HEAD conferido em
  17/10/2026 antes das alterações (mesmo commit, com `docs/reviews` não rastreado).
- Python 3.14.7; PySide6 6.11.2; Linux/KDE.
- Suíte antes das alterações: 553 testes.
  - Com basetemp exclusivo dentro de `.scratch`:
    `553 passed in 7.95s`.
  - No temporário padrão da sessão (sob `/run/user/...`), o teste
    `test_the_mutation_seams_default_to_the_ssd_not_ram` falhava porque deduzia
    "não é RAM" do prefixo do caminho do pytest. Era premissa de ambiente, não
    defeito de produção; a regra real agora vive em `safely/mounts.py` e o teste
    afirma a regra, não o prefixo.
- Comando de referência da suíte:
  `rtk proxy bash -c 'qa_tmp=$(mktemp -d "$PWD/.scratch/base-pytest-XXXXXX"); .venv/bin/python -m pytest -o addopts= --basetemp="$qa_tmp" -q'`
- Decisão registrada: manter Python/Qt, CLI headless sem Qt e alvo Linux/KDE
  (X11 e Wayland). Nada migra de framework nesta evolução.
- Inventário de funcionalidades e guia de desenvolvimento:
  `docs/desenvolvimento.md` (novo). O T14 do plano M7 (evidência no host via
  `tools/verify_tmpfs.py`) segue **pendente no checkout** — o script não existe
  aqui; não foi anunciado como concluído.

## F0 — concluído

- Regressões R01–R07 escritas antes das correções; falhavam contra o código
  antigo e passam com F1 (ver "Comandos e resultados").
- Premissa "SSD" corrigida: `safely/mounts.py` decide a partir de mountinfo
  (tipo do monte e identidade de origem/destino), com testes de fixture em
  `tests/test_mounts.py`; o teste de costura da CLI deixou de julgar prefixo.
- Decisões documentadas em `docs/desenvolvimento.md`.

## F1 — concluído

| Tarefa | O que mudou |
|---|---|
| F1.1 Limpeza legada | `tmpclean.plan_tmp` usa a data mais recente da árvore inteira (descendente novo mantém o item); `disk tmp --confirmar` não muta mais: lista e aponta `tmpfs plan/release`; `--raiz` só aceita raízes suportadas e monte interno recusa |
| F1.2 Inventário honesto | `HolderIndex` ganha estado `complete/partial/unavailable`; leitura desconhecida/parcial bloqueia elegibilidade (`policy.classify`); `_fresh_entry` propaga o estado; `disk/planner` não marca `reclaimable` com erro/truncamento e não soma esses bytes no total |
| F1.3 Ledger | `find` prefere registro **ativo** (partial/released) e o mais recente para o mesmo caminho; três ciclos no mesmo caminho ficam cobertos por teste |
| F1.4 Jobs | `TuneJobs` finaliza exatamente uma vez em `FailedToStart`, timeout, cancelamento e erro; remove referências e chama `deleteLater`; `procs` não cresce mais em sessão longa |
| F1.5 Listas e ações | `OrphansPanel.show_groups` guarda a seleção por identidade antes de trocar a coleção (sem `IndexError`); estado textual passa a refletir candidatos; item protegido no tmpfs não tem "Liberar" habilitado e o motivo fica no tooltip; plano inconsistente desabilita a execução inteira; a confirmação de expiração lista as **vítimas efetivas** (`tmpfs ledger --json` expõe `victims`), não o total retido |
| F1.6 Mensagens | "Possivelmente abandonado" no lugar de órfão comprovado; remoção de "sem risco"; CLI de órfãos diz "sinalizado" e separa sobreviventes; release fala de bytes **transferidos** e o ledger histórico não se apresenta como RAM liberada; ausência de dados nunca vira sucesso |
| F1.7 Ajustes e backup | `worker revert` exige `--confirmar` também na entrada direta (exit 2); `engine.revert` revalida caminho (guard) e navegador fechado; backup com permissões privadas (0700/0600) e escrita durável (fsync de payload, manifesto e diretórios) |
| F1.8 Parsers | `read_proc` tolera processo sumindo e campos malformados por linha; zram lê `mem_used_total` no terceiro campo (ABI do kernel) |

Limites que permanecem bloqueados para automação (herdados da revisão): R08
(exclusão mútua ampla), R09 (procedência de processos), R11/R12/R13/R14
(transações, destino comprovado, quarentena, guard por identidade), R15
(contabilidade fina), R16/R17 (coleta e prazos). Isso é matéria de F2/F3.
Nenhuma automação foi ligada.

## F2 — em andamento (entregas 1–8: coordenação, persistência transacional, destino, cota, contabilidade, protocolo de saída e identidade de processo)

Feito nesta etapa, com testes próprios (`tests/test_orchestration_models.py`,
`tests/test_orchestration_journal.py`, `tests/test_orchestration_coordinator.py`,
`tests/test_tmpfs_coordinated.py`, `tests/test_disk_coordinated.py`):

- `orchestration/models.py`: `ResourceIdentity` (path com dev/ino, processo com
  `pid`+`start_ticks`, entrada, tuning), `ActionPlan` (digest que denuncia plano
  alterado, prazo de validade), `Grant` (fechado por construção: teto numérico,
  igualdade, lista; revogável/inativo), `ActionResult` (vocabulário
  sucesso/parcial/recusa/falha/cancelamento/desconhecido) e `OperationState`,
  todos com serialização versionada (`schema`) e validação de entrada.
- `orchestration/journal.py`: diário append-only com intenção **antes** do
  efeito, fsync por linha, sequência verificada; linha final truncada é denúncia
  (nunca silêncio); `state_of` responde "intenção", "concluída" ou nada.
- `orchestration/coordinator.py`: `flock` por usuário/estado entre processos
  (espera sem prazo ou fila limitada com `wait`), uma mutação por vez; operação
  repetida é **consultada, não reaplicada**; intenção sem resultado vira
  resultado desconhecido; porta fechada (plano expirado, grant inativo/fora do
  escopo, diário corrompido, trava ocupada) recusa sem registrar operação.
- Prova entre processos reais: duas execuções simultâneas do mesmo
  `operation_id` executam o ato **uma** vez; trava ocupada recusa com `wait=0` e
  prossegue quando libera.
- **Integração (entrega 2/3)**: `actions/tmpfs/coordinated.py` é a única ponte —
  monta `ActionPlan`/`ResourceIdentity` reais (path+volume no release, id de
  entrada no restore, grupo do excedente no expire), roda o ato sob o
  coordenador e traduz o resultado do domínio para `ActionResult` (clone retido
  na SSD com origem intacta = **parcial**; erro relatado no expire = parcial,
  nunca sucesso limpo; recusa do domínio é registrada como recusa). Os handlers
  `tmpfs release/restore/expire` da CLI só orquestram **depois** da confirmação:
  dry-run e recusa de flag respondem direto pelo domínio, sem diário. Diário
  corrompido/ilegível fecha a porta antes do ato (nada é copiado) e nada é
  anexado por cima do problema. A CLI espera a trava (`wait=None`): duas mutações
  concorrentes serializam; o filho da GUI passa pelo mesmo caminho.
- Testes de integração que caem sobre o arquivo: intenção antes do resultado no
  diário real do chão falso, recusa de domínio registrada, porta fechada sem
  cópia, dry-run sem diário, restore/expire também journalados, payload sumido
  virando parcial.
- **Staging e recuperação (entrega 4)**: `release_item` grava a linha `staging`
  no ledger **antes** do primeiro byte (bytes 0: ainda não certificados); queda no
  meio da cópia vira estado recuperável, não clone órfão — a janela da R11 entre a
  cópia e o registro `partial` fecha. Os desfechos pegos pelo `except` (cópia
  falhou, digest ilegível/divergente) fecham a própria linha como `dropped` com
  evento de auditoria, sem staging pendurado. O novo `recover_staging` +
  `folego tmpfs recover [--confirmar] [--json]` resolve o que sobrou: **origem
  viva** → clone inacabado é descartado e a linha fecha `dropped` (o caminho volta
  a ser liberável); **origem sumida** → o clone não certificado pode ser a única
  cópia, então nada é apagado, a entrada fica `staging` e o resultado nomeia a
  decisão manual (`RecoverResult.kept`/`notes`; veredito **parcial**, nunca
  sucesso limpo). O `restore` de uma entrada `staging` é recusado apontando o
  `recover`; `staging` fica fora do orçamento e do `expire` (bytes desconhecidos,
  origem possivelmente viva — `expire` jamais apaga a única cópia). O `recover`
  confirmado passa pelo coordenador (grupo `tmpfs.staging`), com guard também
  sobre o clone: raiz não permitida vira erro relatado e a entrada segue
  `staging`. Na verificação adversarial desta entrega apareceu um hazard
  pré-existente: linha degradada do ledger (versão futura, edição à mão) hidrata
  com `stored=""`, e `Path("")` é `.` — com `.` sob uma raiz permitida,
  `expire`/`recover`/`restore` mutariam o diretório de trabalho. Os três atos agora
  exigem caminho registrado absoluto (`_registered_path`): desconhecido/ilegível
  nunca autoriza mutação — a entrada é preservada e o problema é relatado. A aba
  da GUI ainda não tem botão de recover (F4); a linha `staging`
  aparece no ledger dela e o Restaurar recusa com a mensagem do domínio.
- **Quarentena de disco sob o coordenador**: `actions/disk/coordinated.py` é a
  ponte — `quarantine` (identidade `path`, com `~` expandido), `restore` e `purge`
  (identidade `entry`) montam `ActionPlan` real, rodam sob a trava e traduzem o
  resultado do domínio (`MutationResult`) para `ActionResult` com efeitos
  observados (entrada relida depois do ato, nunca o que se supôs). A recusa de
  `--confirmar`/`--irreversivel` mora na ponte, uma porta só para CLI e GUI: sem
  confirmação, nada entra no diário e o alvo não é tocado. Recusa do domínio
  (guard, alvo sumido, outro dispositivo) vira `recusa` registrada — e o
  `PermissionError` do `_check` no `purge`, que antes escapava cru da CLI, agora
  é recusa relatada. O esqueleto `Coordinated`/`perform` saiu de
  `tmpfs/coordinated.py` para `orchestration/bridge.py`: mesma porta, dois
  domínios, uma trava e um diário por usuário.
- **Persistência do manifesto (entrega 5, primeira metade)**: novo kernel
  compartilhado `safely/persist.py` — anexo JSONL durável (`O_APPEND`+fsync,
  0600), leitura que **relata** cada problema com a linha (`read_jsonl`/`read_json`)
  e escrita de arquivo inteiro atômica com a geração anterior em `<nome>.bak`
  (`write_json_atomic`; se o atual não puder ser lido para o backup, nada é
  escrito). O manifesto da quarentena virou envelope versionado
  (`{"schema": 1, "entries": [...]}`), escrito com backup; listas cruas do
  formato antigo continuam legíveis e migram na primeira escrita, com o original
  preservado no `.bak`. Entrada inválida (campo ausente, `bytes` inválido,
  estado desconhecido, `entry_id` repetido, caminho **relativo** — `Path("")` é
  `.`) é problema nomeado, não alvo: com manifesto inconsistente,
  `quarantine`/`restore`/`purge` **recusam** e nada é reescrito por cima —
  corrupção não vira "quarentena vazia". O `reconcile` classifica cada linha
  `planned` sem adivinhar: origem sumida + payload presente → `stored`; origem
  intacta + sem payload → `dropped` (o rename nunca aconteceu; nenhum dado
  tocado); ambíguo (ambos ou nenhum) → decisão manual, nada escrito. O reparo
  entrou na porta: `disk list` varre só para decidir se há reparo a registrar —
  havendo, roda sob o coordenador com veredito (parcial quando resta decisão
  manual); sem reparo, listar continua sendo leitura. Manifesto inconsistente →
  `disk list` recusa (exit 1) com o relatório; porta fechada (diário corrompido)
  → aviso e a leitura segue.
- **Registro de tmpfs (entrega 5, segunda metade)**: o ledger JSONL de tmpfs usa o
  mesmo kernel `safely/persist.py` — linha nova carrega `schema` (linha sem o
  campo é formato legado aceito; schema de versão mais nova é problema, não dado).
  A leitura relata cada problema com a linha (`load`/`problems`) em vez de pular
  em silêncio, e os **quatro** atos (`release`/`restore`/`expire`/`recover`)
  recusam antes de tocar em qualquer coisa enquanto houver problema — nem o
  dry-run decide com mapa incompleto. Linha legível com campo de tipo errado não
  derruba a leitura (`bytes` coagido, `holder_pids` normalizado, `ts` inválido não
  vira idade absurda); a linha degradada continua virando decisão manual nos atos,
  nunca autorização. A visão `tmpfs ledger` mostra o que pôde ser lido, nomeia o
  resto (`problems` no `--json`, aviso no stderr) e não mente sobre a saúde do
  registro; a CLI do `recover`/`expire` separa recusa pura (código de recusa,
  stderr) de parcial confirmado com erros (relatório com avisos), que antes sairia
  sempre como sucesso.
- **Destino e cota (entrega 6, primeira metade)**: a prova de destino deixou de ser
  presumida. No ato, `release_item` lê a tabela de montes e recusa destino em RAM,
  no mesmo monte da origem (copiar para dentro do tmpfs não devolve capacidade) ou
  fora de monte conhecido — fail-closed para host ilegível, com a tabela injetável
  nos testes. A folga nomeia os números ("X livres, menos que Y para copiar Z com
  folga"). A cota virou **conjunta**: o teto soma a retenção certificada e os
  clones `staging` medidos no disco agora (clone que não mede por inteiro é recusa
  nomeada, nunca zero); `expire` continua intocável para staging. A verificação
  expôs um defeito real no `_hydrate`: linha editada à mão sem `audit_event_id`
  (o reparo documentado) caía no fallback de "versão futura" e hidratava com
  `stored=""` — campos legíveis descartados em silêncio. A hidratação agora é
  campo a campo (o que está legível continua legível; a validade é revalidada no
  ato) e o fallback foi eliminado. A quarentena de disco fica sem a prova de RAM
  de propósito: é renomeação no mesmo dispositivo, com recusa cross-device própria.
- **Contabilidade fina (entrega 6, segunda metade)**: o `release` parou de devolver
  um número só. Saem separados o tamanho aparente (lógico = transferido), os
  **bytes alocados** medidos no clone que ficou (`st_blocks*512`; em arquivo
  esparso o aparente mente) e a **variação observada** do volume medida por
  `statvfs` antes/depois do ato — volume que não responde vira `None` ("não
  medido"), nunca zero. O parcial que não removeu a origem reporta alocado (>0)
  sem observação: o clone ocupa SSD mesmo sem nada ter saído da RAM. Os rótulos
  atravessam CLI (linhas "no SSD" e "variação observada"), JSON (incl. `effects`
  do veredito) e a aba de tmpfs — payload antigo, sem os campos, não inventa
  número.
- **Protocolo de desfecho (entrega 7)**: a CLI deixou de ter duas verdades. Todo
  caminho termina em um dos seis desfechos com código de saída documentado (0
  sucesso, 1 recusa, 2 falta confirmar — o mesmo 2 do argparse —, 3 parcial, 4
  falha, 5 desconhecido; 6 cancelamento fica **reservado**: nenhuma rota da CLI o
  produz hoje). Com `--json`, o desfecho sai como **objeto único no stdout** —
  inclusive a recusa, que antes deixava o stdout vazio e fazia a aba dizer "o
  filho não respondeu"; o stderr continua sendo a voz humana. O envelope carrega
  `ok`/`exit`/`outcome` e, quando a operação foi coordenada,
  `operation_id`/`effects`; `--json` agora vale também para
  `disk quarantine/restore/purge`. Exceção inesperada vira `falha` (4) com o
  traceback atrás de `FOLEGO_TRACEBACK`; Ctrl-C vira `desconhecido` (5), porque
  interromper não prova ausência de efeitos — é o mesmo motivo pelo qual o
  timeout do runner da GUI deixou de afirmar recusa: mutação que estourou o prazo
  ou abandonou a janela sai como `desconhecido`, leitura como recusa e
  `FailedToStart` (o filho não existiu) como recusa. A entrega também **expôs e
  corrigiu um defeito real**: o veredito do `recover` confirmado não olhava
  `result.ok` e gravava `sucesso` no diário por cima da recusa do ledger — agora
  diz `recusa`, como a CLI sempre disse.
- **Identidade de processo e SIGTERM (entrega 8)**: o encerramento de órfãos e de
  grupos de navegador parou de confiar no número do PID. `safely/procs.py` abre o
  **pidfd antes** da releitura de `/proc/<pid>`; como o fd pina o processo, um PID
  reciclado entre a checagem e o sinal não recebe nada — e a releitura confere
  starttime, proteção, órfão e automação como antes. Kernel/python sem pidfd cai no
  fallback de starttime + `os.kill`, e o resultado nomeia o método
  (`identity: pidfd|starttime`), em vez de fingir a mesma garantia. O SIGTERM (e o
  SIGKILL pedido) passou a ser **acompanhado** até um prazo: `exited=True` só
  quando a ausência (ou o zumbi) foi observada; sobrevivente sai como
  `exited=False`, a CLI devolve **3 (parcial)** e nomeia a escalada manual
  (`--confirmar --forcar`), e a UI o coloca no conjunto do Forçar — inclusive
  depois de um poll, enquanto a identidade for a mesma; PID reciclado cai. A
  escalada continua sem automaticidade: `terminate` nunca envia SIGKILL, e a
  leva de grupo acompanha todos os membros com um prazo só. No caminho, a CLI de
  `groups` ganhou o `--forcar` que já existia para órfãos. Testes de fixture
  provam o ciclo real (SIGTERM observado, filho que ignora SIGTERM nomeado,
  SIGKILL separado e confirmado) sem tocar em processo do host.

Pendente de F2 (fora das entregas 1–8, registrado como extensão):

1. Migrar as mutações de ajustes (`tune apply/revert`) e de órfãos/grupos para o
   coordenador único (item 2 do plano F2) — a entrega 8 endureceu o sinal, mas
   essas rotas ainda não passam pela trava/diário; a automação segue desligada.

## F3 — concluído (telemetria, saúde e sessões)

### F3.1 Relógio e qualidade por fonte

- `Snapshot` ganhou `mono` (relógio monotônico do fim da coleta), `duration_s`,
  `ts_iso`, `age_s()` e `is_stale()`; idade/frescor usam `mono`, não o relógio de
  parede. `Snapshot.sources` carrega `SourceQuality` com `ok`, `partial`,
  `missing` ou `error` e um detalhe nomeado; `usable()` e `source()` nunca
  confundem "não coletado" com "vazio".
- `action_blockers()` recusa agir sem relógio monotônico, com amostra antiga ou
  com fonte obrigatória inutilizável. `ProcScan` distingue entrada ilegível de
  processo que sumiu, marca truncamento como `partial` e limita a varredura a
  8192 PIDs por padrão.
- O `Poller`/snapshot dos testes sintéticos preserva o comportamento legado
  quando não há fontes declaradas; snapshot real sem `mono` é `unknown`, não
  "fresco por omissão".
- **Achado real no parser de `/proc/<pid>/stat`:** `utime`, `stime` e
  `starttime` são os índices `11`, `12` e `19` depois do `comm`, não `10`, `11` e
  `16`. O parser antigo lia campos deslocados; a fixture antiga escondia o
  defeito. Corrigido com regressão em `tests/test_procfs.py` e fixture no layout
  real.

### F3.2 Métricas por diferença

- CPU global e por processo só existem como delta entre amostras; a primeira
  leitura é `None`, nunca `0`. `CpuTimes` e `cpu_busy_frac` têm o mesmo contrato.
- I/O é cumulativo no `/proc` e vira bps apenas entre leituras; a UI não inventa
  taxa com uma amostra só. PSS é lido sob demanda (`read_pss_kb`); RSS é
  apresentado como estimativa.
- PSI `some`/`full`, zram, inodes por volume e CPU no dashboard/bandeja foram
  ligados ao snapshot. `OrphanCandidate.cpu_frac` existe, mas é pista — não
  autorização.

### F3.3 `HealthEngine` puro

- `core/health.py` não importa Qt e recebe apenas o snapshot/limiares. Piora
  escala imediatamente; melhora desce **um degrau por `recovery_samples`**, sem
  oscilar a cada poll. Limiares são versionados (`THRESHOLDS_VERSION = 1`).
- Fonte ausente, ilegível ou antiga leva o veredito a `unknown`; o título da
  janela usa o veredito estável do único engine da `MainWindow`, em vez de
  recalcular por conta própria.

### F3.4 Coleta desacoplada

- `Poller` ganhou execução em thread Python com filas, sem Qt no worker: no
  máximo uma coleta em voo, fila de um e erro entregue como dado. O timer usa
  `request()` quando `offload=True`; o drain acontece na thread principal e só
  ele emite sinais. `poll_once()` continua síncrono para testes e chamadores
  diretos.
- O `_drain_timer` começa preguiçoso; fechar a janela para a thread sem deixar
  coleta órfã. A UI reutiliza as linhas do dashboard/órfãos por identidade
  (`pid`+`starttime`), não por posição.

### F3.5 Sessões, artefatos, exclusões e investigação

- `core/sessions.py` é um registro **opt-in**: arquivo ausente = vazio, nada é
  inferido. JSON versionado (`SCHEMA_VERSION = 1`), UUID, parede para exibição e
  `boot_id` para distinguir reboots; leitura normal não cria arquivo nem lock.
  Corrupção/versão desconhecida levanta `SessionError` e o chamador falha fechado.
- Estados distintos: `active`, `disconnected` (o cliente saiu, o processo pode
  continuar), `heartbeat_lost` (TTL vencido) e `ended` (fim explícito, reboot, PID
  morto/reutilizado ou zumbi). Reboot encerra a sessão antiga com motivo; reuso de
  PID por starttime diferente encerra a antiga e um novo registro recebe UUID
  novo. Dois reboots/PIDs reciclados não herdam a proteção anterior.
- `keep_active` é uma promessa persistida: continua protegendo em
  `disconnected`/`heartbeat_lost` enquanto PID+starttime vivos; só o fim explícito
  (ou reboot/morte/reuso) a desfaz. O `Reaper`, a listagem de órfãos e os grupos
  de navegador recebem `protected_fn` e revalidam no ato; um erro de leitura
  protege (falha fechada). Grupo com qualquer membro protegido não é oferecido
  parcialmente.
- `core/exclusions.py` guarda exclusões versionadas por app, projeto, sessão,
  cmdline e path, com `keep_active` mais forte que o filtro de listagem. Arquivo
  ausente = nenhuma exclusão; ilegível = proteção não comprovada. O `--manter-ativo`
  vale no ato, não só na tela.
- Artefatos são **metadados**: caminho absoluto, tipo, tamanho observado e
  `expires_at`; a expiração lista vencidos e **nunca apaga** nada. O launcher
  local `folego session run -- ...` registra o filho com `start_new_session` e
  heartbeat enquanto vive; se o launcher cai, o filho continua e a promessa
  `keep_active` permanece até o fim/TTL. `start/heartbeat/disconnect/end/list/
  artifact/expired` e `exclusions add/list/remove` também são API local com
  UUID e `--json`.
- Cgroup é somente leitura experimental: registra o caminho quando legível
  dentro de `/user.slice`/`user@...`; nenhuma unidade systemd é criada ou
  sinalizada, e `cgroup_verified` só é verdadeiro quando a leitura comprovou.
- A investigação por **CPU ativa** (`active_investigation`) lista processos
  adotados, sem filhos vivos, com CPU acima do limiar e sem proteção. É rotulada
  na UI como "Investigação possível (CPU ativa; abandono não provado)" e não
  habilita Encerrar/Forçar, porque um build útil também consume CPU.
- A UI compõe sessões+exclusões uma vez por amostra, aplica a proteção aos
  candidatos/grupos e mostra a pista de CPU ativa; registry ou exclusões
  ilegíveis escondem todos os candidatos (desconhecido não autoriza).

**Aceite F3 coberto:** fonte ausente/antiga bloqueia ação; CPU não vira zero por
uma leitura; processo abandonado consumindo CPU aparece como investigação
possível sem ser confundido com órfão provado; dois reboots e PID reciclado não
confundem sessões; agente desconectado com build útil e `keep_active` não é
encerrado por heurística; exclusões e `keep_active` são revalidados no ato; nada
é apagado por expiração de artefato.

## Comandos e resultados

Regressões novas de F1 (falhavam contra o código antigo, passam agora):

```bash
.venv/bin/python -m pytest -o addopts= tests/test_disk_tmpclean.py \
  tests/test_disk_planner.py tests/test_tmpfs_holders.py \
  tests/test_tmpfs_policy.py tests/test_tmpfs_ledger.py \
  tests/test_ui_orphans.py tests/test_ui_tune_jobs.py \
  tests/test_ui_tmpfs_tab.py tests/test_procfs.py tests/test_mounts.py -q
```

- Suíte completa depois de F3.1–F3.5, com basetemp em `.scratch`:
  **859 passed in 19.11s** (17/10/2026). Novos testes: `test_snapshot_quality.py`,
  `test_metrics_deltas.py`, `test_health_engine.py`, `test_workers_offload.py`,
  `test_sessions.py`, `test_exclusions.py`, `test_cli_sessions.py` e os casos de
  proteção/investigação em `test_core_orphans.py`, `test_orphans_reaper.py`,
  `test_ui_orphans.py` e `test_ui_main_window_tabs.py`. O total cresceu de 765
  para 859; a suíte continua sem tocar dados reais (fixtures de `/proc`, HOME e
  `tmp_path`).
- Suíte completa depois de F1 + F2.1–F2.5, das entregas 6a/6b (destino não-RAM,
  folga por volume, cota conjunta retenção+staging, contabilidade
  lógico/alocado/observado), da entrega 7 (protocolo de desfecho na CLI) e da
  entrega 8 (identidade pidfd/starttime e SIGTERM acompanhado):
  **765 passed in 13.06s** (comando de referência da seção "Linha de base",
  basetemp em `.scratch`; 74 testes novos no total — 7 em `test_persist.py`,
  8 em `test_disk_quarantine.py`, 6 em `test_disk_coordinated.py`, 6 em
  `test_cli_disk.py`, 6 em `test_tmpfs_ledger.py`, 9 em `test_tmpfs_release.py`,
  8 em `test_cli_tmpfs.py`, 1 em `test_ui_tmpfs_tab.py`, 5 em
  `test_safely_procs.py`, 7 em `test_orphans_reaper.py`, 2 em
  `test_orphans_sigterm_e2e.py`, 5 em `test_cli_orphans.py` e 4 em
  `test_ui_orphans.py`).
- Nenhum teste toca recursos reais do host; a validação KDE/Wayland continua
  sendo evidência manual (`tools/verify_*.py`) e não foi refeita nesta sessão.

## Riscos remanescentes

- R08 **parcialmente corrigido**: `tmpfs release/restore/expire/recover` e
  `disk quarantine/restore/purge/reconcile` confirmados passam pelo coordenador
  (trava `flock` entre processos, intenção antes do efeito, recusa fail-closed com
  diário corrompido). A entrega 8 endureceu o sinal de órfãos/grupos (pidfd,
  starttime e SIGTERM acompanhado), mas essas mutações ainda não passam pela trava
  e pelo diário; a automação segue desligada.
- R11 **corrigida para o ciclo de cópia**: a linha `staging` entra no ledger
  antes do primeiro byte e a interrupção em qualquer transição (durante a cópia,
  entre a cópia e a certificação, antes do `partial`) é resolvida por
  `folego tmpfs recover` — origem viva descarta o clone inacabado; origem sumida
  preserva o único clone e nomeia decisão manual. O que resta de R11 é a *reserva*
  física de espaço durante a cópia: a 6a verifica folga de 2× e recusa sem ela;
  reservar de verdade (alocação) segue pendente.
- R12 **corrigida no essencial (6a)**: o destino é verificado no ato contra a
  tabela de montes (fora da RAM, monte diferente da origem, monte conhecido) e a
  folga é conferida com os números no motivo; falta a reserva física de espaço
  durante a cópia (alocação), que segue pendente junto de R11.
- R13 **corrigida para o manifesto**: corrupção não vira mais "quarentena vazia" —
  manifesto versionado com backup, entradas inválidas viram problema nomeado e
  `quarantine`/`restore`/`purge` recusam com estado inconsistente; o payload tem
  de estar confinado à raiz privada (o guard aceita qualquer caminho sob as raízes
  permitidas); `reconcile` cobre as três transições de `planned` (concluído,
  nunca-aconteceu, manual) e audita cada fechamento. O que resta de R13 é matéria
  de catálogo: associar a quarentena a um plano/plano de caches e bloquear raízes
  de projeto — trabalho de política, não de persistência.
- R15 **corrigida no release (6b)**: o ato separa lógico/transferido, alocado
  (`st_blocks`, medido no clone) e a variação observada do volume (`None` = não
  medido), e os rótulos da CLI/JSON/aba não chamam conteúdo de "RAM liberada". O
  que resta é a mesma observação em `restore`/`expire` (direção SSD→RAM e SSD
  liberada) — extensão da entrega 6.
- R16/R17 **corrigidos no essencial (F3.1/F3.4)**: idade vem do relógio
  monotônico, cada fonte declara `ok|partial|missing|error`, amostra antiga ou
  fonte obrigatória inutilizável bloqueia ação e a coleta roda em thread própria
  com no máximo uma em voo. O que resta é prazo global entre todos os coletores e
  validação visual/real do comportamento sob carga; a entrega 7 fechou o buraco de
  honestidade do timeout no runner da GUI (mutação sem resposta = `desconhecido`,
  nunca recusa).
- Sessões/exclusões são novas desde F3.5: persistência privada, versionada e
  fail-closed, mas a integração com unidades systemd/cgroups é **somente leitura
  experimental**; nenhuma unidade é criada ou sinalizada. A validação em KDE/
  Wayland real das novas telas e da pista de CPU ativa segue pendente.
- A aba de tmpfs da GUI ainda não oferece o `recover` (só a CLI); a linha
  `staging` já é exibida e o Restaurar dela recusa apontando a CLI. Um botão de
  recover entra junto do trabalho de UI de F4.
- Nada foi validado em compositor real, bandeja, leitor de tela ou escalas
  (100/150/200%) nesta sessão; as entregas de UI novas estão offscreen.

## Próxima ação concreta

1. F4: central manual única, com plano/confirmar/resultado para os atos, sem
   automação e sem progresso inventado; incluir o botão de `recover` de tmpfs na
   GUI. O launcher de sessões já existe na CLI e pode alimentar a central.
2. F5: controle compacto com alternativa de bandeja e acessibilidade 100/150/200%
   (a validação visual real continua sendo evidência de host).
3. Extensões registradas: a mesma contabilidade observada em `restore`/`expire`;
   reserva física de espaço na cópia (R11/R12); mutações de ajustes/órfãos fora da
   porta (item 2 do F2 do plano); prazo global de coleta; cgroups/unidades de
   usuário além do registro somente leitura.

## Última execução

17/10/2026 — suíte completa verde com basetemp em `.scratch`: **859 passed in
19.11s**. F0, F1.1–F1.8, F2.1–F2.5 com as entregas 6a/6b/7/8 e F3.1–F3.5.
F2: integração ao coordenador dos atos de tmpfs (incl. staging/recover) e da
quarentena de disco; manifesto e ledger versionados com fail-closed; destino
não-RAM/não-mesmo-monte, folga e cota conjunta; contabilidade fina do release;
protocolo de desfecho 0–6; identidade por pidfd/starttime e SIGTERM acompanhado,
com SIGKILL só por pedido explícito. F3: `Snapshot.mono`/qualidade de fonte e
bloqueios de ação, CPU/I/O por delta (primeira leitura `None`), `HealthEngine`
puro com histerese versionada, coleta em thread e UI por identidade, e o registro
opt-in de sessões com UUID/reboot/PID reciclado/estados distintos, `keep_active`
revalidado no ato, exclusões versionadas, artefatos com validade e sem exclusão
automática, cgroup de usuário somente leitura, launcher `session run`,
investigação de CPU ativa como pista e UI/CLI com falha fechada. No caminho foi
corrigido o parser de `/proc/<pid>/stat` (índices 11/12/19 após o `comm`; a
fixture antiga mascarava o deslocamento). Tudo coberto por testes de núcleo,
CLI, UI e processos; nenhum teste sinaliza processo real do host.
Nada foi commitado; `docs/`, `docs/reviews/`, `src/folego/safely/mounts.py`,
`src/folego/safely/persist.py`, `src/folego/orchestration/`,
`src/folego/actions/tmpfs/coordinated.py`, `src/folego/actions/disk/coordinated.py`,
`src/folego/core/{health,sessions,exclusions}.py` e os testes novos seguem não
rastreados.
