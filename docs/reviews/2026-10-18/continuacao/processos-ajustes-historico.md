# Processos, ajustes e histórico fora do loop gráfico

## Implementado e integrado

**C05: rotas de produção migradas.** `tune apply/revert` e a entrada direta do
worker passam por `actions/tunings/coordinated.py`. Backups e protocolo existente
foram preservados. Identidade do arquivo é relida sob a coordenação e o guard é
reaplicado antes da escrita. Falha conhecida depois de começar a restauração
produz desconhecido; uma mudança do usuário detectada antes de restaurar continua
sendo recusa sem efeito. Falha de registro final conserva o backup e o resultado
observado com o ID da intenção.

`orphans`, `groups` e a nova entrada `process --plan JSON --confirmar --json`
usam `actions/orphans/coordinated.py`: mesmo coordenador/trava/diário de disco e
tmpfs. O plano v2 conserva boot, PID/starttime, aplicação e evidência de CPU.
Reboot, PID reutilizado, aplicação/CPU alteradas, descendentes novos ou leitura
incompleta recusam sinal de órfão. Grupos manuais revalidam os membros selecionados
e os filtros de navegador. Limite de 64 membros por plano. SIGKILL requer uma
confirmação própria; os lotes TERM e KILL compartilham um único prazo de
acompanhamento. Sinal enviado sem término observado é parcial (3), inclusive na
CLI antiga de grupos. `/proc/PID` ainda existente mas ilegível não vira término.

`core/process_protection.py` relê sessões/exclusões no ato e percorre até 64
ancestrais com identidade verificada. `keep_active` de um ancestral protege os
descendentes. Registro ilegível, ciclo, ancestral reaproveitado ou ausente impede
o sinal. O cache da janela serve apenas à apresentação/seleção.

Na GUI instalada, `_terminate/_force/_group` enviam o plano para `QProcess` e
recebem resultado pelo loop Qt; não chamam o reaper na thread gráfica. O teste
que injeta explicitamente `reaper_factory` mantém uma porta síncrona de fixture;
essa porta não é usada pelo app padrão. A análise precisa de boot conhecido e
amostra recente, sem pausa/falha. Cliques durante o job são ignorados. ID
divergente, timeout ou resultado ilegível produz desconhecido, conservando o ID
do plano de processos.

**C01, feedback na GUI:** abas de processos, ajustes, disco e tmpfs distinguem
desconhecido de recusa. Exibem o ID quando disponível e bloqueiam novas mutações
nesse painel enquanto a operação permanece sem reconciliação. Nova coleta ou
consulta não limpa esse bloqueio. Isso é proteção da sessão da interface, não um
registro persistente de reconciliação entre reinícios. A CLI continua exigindo
consulta e avaliação do efeito; não existe botão que certifique o resultado por
mera releitura de configuração.

**C13, custo do histórico na interface:** `_last_operation_text` só lê texto em
memória. `HistoryReader` é executado por worker com uma consulta em voo e fila
limitada; central e compacto recebem a mesma resposta. Arquivo inalterado custa
abertura/stat/fechamento, sem reler conteúdo. Alteração de inode/tamanho/mtime/ctime
inicia revalidação completa em passos, inclusive do interior do diário.

Orçamento por passo: até **256 KiB**, blocos de 16 KiB, verificação de prazo de
**10 ms entre blocos**, linha de até **64 KiB**. A leitura conserva apenas buffer,
contador de sequência/problemas e último registro; não acumula o histórico.
Linha maior exige revisão e não aparece como vazia. O prazo é cooperativo: uma
chamada do kernel ou decodificação em andamento pode ultrapassá-lo. I/O travado
não bloqueia a GUI, mas não se promete interromper uma thread em estado D.
Durante a varredura, o resultado aparece como ainda não comprovado. Arquivo que
muda durante a leitura não é certificado. Esse resumo nunca autoriza uma ação:
o coordenador continua consultando o diário autoritativo.

## Testes e evidências

- `test_process_coordinated.py`: intenção antes do sinal; replay pelo mesmo
  plano/ID sem novo efeito; exclusão e `keep_active` tardios; ancestral protegido;
  reboot, PID/CPU/descendentes alterados; falha de registro final conserva efeito
  e impede retry pelo mesmo plano.
- `test_orphans_sigterm_e2e.py`: subprocesso criado pelo teste é o único alvo do
  endpoint CLI coordenado; saída por SIGTERM observada e intenção/resultado
  persistidos em HOME isolado. Não se sinalizam processos de trabalho do host.
- `test_tunings_worker.py` e `test_tunings_engine.py`: worker real, backup e
  retorno byte a byte; EACCES depois do efeito; restauração interrompida; mudança
  do usuário preservada. Tudo em arquivos descartáveis.
- `test_ui_process_jobs.py`: filho sintético demora, heartbeat Qt continua,
  clique repetido cria um job; respostas ilegíveis/desconhecidas conservam aviso,
  ID e bloqueio. `test_ui_*_tab.py` cobre o mesmo feedback nas outras abas.
- `test_history_reader.py`: diário de 3.000 registros, I/O por rodada limitado,
  zero releitura de payload inalterado, limite de linha/memória, alteração
  interna/substituição/truncamento, escrita incompleta, FIFO/symlink recusados.
- `test_ui_history.py`: leitor lento executa em outra thread, sem multiplicar
  pedidos durante snapshots repetidos; heartbeat Qt continua e corrupção chega
  à central.

Execuções intermediárias: 27, 48, 53, 75 e 62 testes focados passaram.
Suítes intermediárias: **1109 passed in 27.58s** (`process-suite.log`) e
**1124 passed in 27.94s** (`process-history-suite.log`). O progresso registra a
execução final depois da correção dos demais painéis.

**Resultado final:** **1127 passed in 24.92s**, em `process-ui-suite.log`;
**917 passed in 14.82s** no venv limpo sem Qt, em `process-headless.log`.
`find_spec` confirmou `PySide6: None` e `shiboken6: None` nesse venv.
`git diff --check` passou. CI remota não executada; estes são resultados locais.

`.scratch` verificado em btrfs de `/home`, com 53,1 GiB disponíveis antes da suíte.
Cada execução usa base exclusiva e variáveis de temporários fora de `base`:

```bash
rtk proxy bash -c 'qa_tmp=$(mktemp -d "$PWD/.scratch/process-qa-XXXXXX"); mkdir -p "$qa_tmp/general" "$qa_tmp/pytest-root"; env TMPDIR="$qa_tmp/general" PYTEST_DEBUG_TEMPROOT="$qa_tmp/pytest-root" .venv/bin/python -m pytest -o addopts= --basetemp="$qa_tmp/base" -q'
```

Sem Qt: mesmo preparo, substituindo o Python por
`.scratch/i0-headless/bin/python` e acrescentando `--without-qt`. Rodar as suítes
sequencialmente evita a disputa de disco já registrada com Hypothesis.

## Aceites e limites

- C05 original recebeu migração das rotas e proteção fresca com testes de CLI,
  Qt e efeito real em filho próprio. **I2 ainda parcial**: prazo total de coleta/
  operação, encerramento sob estado D e política integral de cancelamento/filhos
  não receberam aceite. Sessões/exclusões ainda têm leitura na apresentação.
- C13 parcial: custo do histórico saiu da GUI com orçamento explícito; append e
  consulta autoritativa ainda percorrem o diário. Compactação/indexação durável,
  retenção total de audit/decisions/backups e ensaio prolongado permanecem abertos.
- C01/C04 parciais: processos conservam o plano até o filho e consulta pelo ID;
  ajustes ainda planejam dentro do worker depois da confirmação. Timeout antes
  da resposta de ajustes/tmpfs/restore/purge pode não trazer ID ao pai; consultar
  histórico antes de repetir. Falta contrato de plano revisado em todas as ações
  e reconciliação de domínio pelo mesmo ID após cada fronteira de queda.
- Não foi implementado controlador automático (C08), nem orçamento de frequência
  dos grants (C03), nem o restante do fluxo Dar fôlego/compositor (C10/C11).
- F0/F1 preservados; F2 e F3 avançaram sem aceite integral; F4/F5 parciais; F6
  desligado; F7 somente leitura/protegido; F8 parcial. I2R/R1/R2/R5 mantêm a entrega
  anterior; R3 continua inventário protegido e R4/arquivamento não estão ligados.
- Nenhum commit, push, autostart, limpeza do host ou automação foi realizado.
  Instalação limpa, soak de horas e certificação KDE/X11/Wayland seguem pendentes.

Próximas ações concretas: vincular revisão e IDs no pai para todas as mutações,
com consulta/reconciliação de domínio; definir prazo total e cancelamento dos
filhos; completar indexação/retenção do diário preservando operações pendentes.
Depois, integrar simulação assistida e fluxo Dar fôlego sem habilitar o executor
automático a partir de evidência incompleta.
