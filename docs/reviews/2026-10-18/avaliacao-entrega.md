# Avaliação da entrega do agente — 18/10/2026

O caminho recomendado é **consolidar os contratos de execução antes de ampliar automação e ações de virtualização**, e então concluir a experiência visual originalmente solicitada. Há implementação relevante para aproveitar; recomeçar ou seguir literalmente a lista de pendências do anexo repetiria trabalho e deixaria problemas importantes sem tratamento.

## Base e verificações

Revisado o working tree de `/home/misael/Projects/Folego`, com HEAD `61179f55123b44a996aa6087d124474eb5e84b1e` e numerosas alterações não commitadas. O HEAD sozinho não identifica esta entrega: [checkout.json](evidencias/checkout.json) registra hashes de 182 arquivos de código, testes, ferramentas e documentação de desenvolvimento. Ambiente observado: Python 3.14.7 e PySide6 6.11.2.

Foram comparados o relato anexado pelo usuário, o [plano F0–F8](../2026-10-17/04-plano-de-acao.md), o [progresso anterior](../2026-10-17/progresso.md), a implementação e os testes. Foram executados:

| Verificação | Resultado observado |
|---|---|
| Suíte completa existente, basetemp exclusivo em `.scratch` | **1 failed, 1019 passed in 31.40s** |
| Reexecução isolada da falha do painel | **1 failed in 0.66s** |
| Seleção literal do job `pure`, bloqueando importação de Qt | **819 tests collected, 2 errors**; não foi uma execução do GitHub Actions |
| Sondas com executores falsos, relógio controlado e persistência descartável | Confirmaram os casos descritos abaixo; nenhum processo de trabalho foi sinalizado |

Logs e script estão em [evidencias](evidencias/README.md). Não foram feitos instalação limpa, teste com daemons reais, ensaio prolongado com workers reais nem validação visual em KDE/Wayland. Os achados identificados como inspeção são conclusões sobre os caminhos de código, não medições no compositor.

## O que já existe e deve ser preservado

O anexo diz que seria necessário criar a CI, o registro de simulações e o consumo do estado de automação na GUI. **Esses componentes já existem**: `.github/workflows/ci.yml`, `orchestration/decisions.py`, `MainWindow._show_automation_state()` e os respectivos testes. Há também rotação de logs, `tests/test_ui_long_run.py` e `tools/soak.py`.

São avanços concretos: contratos independentes de Qt; diário de intenção e `flock` usados por disco/tmpfs; staging e recuperação; qualidade e idade de telemetria; pidfd/starttime e acompanhamento de SIGTERM; registro opt-in de sessões; exclusões; execução de diversos jobs em filhos; central, controle compacto, inventários, `doctor`, migração e entrypoint. A revisão não propõe retirar essas proteções.

Existir um módulo ou passar testes unitários não fecha seu aceite ponta a ponta. A política de automação e o log de decisões, por exemplo, ainda não formam um controlador em funcionamento.

## Achados que orientam a continuidade

P0 significa bloqueador para confiar no contrato comum ou habilitar execução automática. P1 afeta correção, confiabilidade, responsividade ou a entrega solicitada. P2 amplia cobertura depois de consolidar a base.

### C01 · P0 · Efeito executado pode ser apresentado como “nada foi feito”

**Reproduzido.** Em `orchestration/bridge.py:34`, o `except OSError` envolve toda a chamada ao coordenador. Se `append_intent` funciona, o executor produz efeito e `append_result` falha, a ponte devolve `recusa`, descarta o resultado do domínio e afirma que nada ocorreu. A sonda mostra exatamente essa sequência.

É necessário distinguir falha anterior ao início, resultado observado mas não persistido e efeito desconhecido. Depois de um efeito, a resposta não pode autorizar uma repetição ingênua. Preservar `operation_id`, evidências e necessidade de reconciliação. A captura genérica de exceções em `Coordinator._execute()` também precisa respeitar o ponto atingido pela operação; uma exceção após efeito não prova ausência de mudança.

### C02 · P0 · Validade e revogação não são verificadas após a espera

**Reproduzido.** `Coordinator.run()` (`coordinator.py:70`) verifica prazo e grant antes de adquirir a trava. Um plano e grant válidos em t=100, expirando em t=102, executam em t=105 após a espera. Outra sonda revoga o grant persistido durante a espera e a execução ainda ocorre usando o objeto antigo.

Revalidar sob a coordenação da execução, carregar a versão atual da autorização e definir a ordem de locks com revogação/pausa. A espera padrão ilimitada também contraria a fila limitada prevista em F2. Testar a fronteira de autorização com duas instâncias, além do relógio controlado.

### C03 · P0 · Grant não é fechado por escopo

**Reproduzido e confirmado por inspeção.** `Grant.covers()` (`models.py:238`) percorre apenas as chaves do grant, aceitando parâmetros adicionais do plano. `GrantStore.add()` aceita limites vazios; um grant vazio cobre qualquer plano da mesma ação. O contrato não vincula explicitamente o alvo a um conjunto autorizado de caminhos, sessões ou identidades.

Definir schemas por ação, limites obrigatórios, valores válidos e escopo de recursos. Parâmetros desconhecidos devem recusar; nenhum grant genérico deve liberar automaticamente qualquer temporário. Grants antigos insuficientes precisam ser migrados de forma conservadora ou exigir nova revisão, nunca receber escopo ampliado por inferência.

### C04 · P0 · Idempotência e plano aprovado não estão ligados de ponta a ponta

**Reproduzido.** Reutilizar um `operation_id` de `tmpfs.release` para `disk.purge` em outro alvo devolve o sucesso antigo de `tmpfs.release`. O coordenador não compara o conteúdo da intenção existente com o novo pedido. A sonda também mostra que `ActionPlan.params` é mutável apesar de a dataclass ser frozen: o digest muda após a criação.

**Inspeção adicional:** `perform()` cria plano/ID novos a cada chamada; não recebe o plano apresentado ao usuário. Identidades de caminho aceitam ausência de device/inode e são usadas assim nas pontes. A validade não faz parte do digest atual. Não há um contrato completo de plano revisado → confirmação desse plano → revalidação → execução → consulta pelo mesmo ID.

Corrigir conflito de ID, imutabilidade profunda e validação de campos relevantes, com versionamento. Um digest recalculável não é autenticação: a execução precisa comparar com o plano efetivamente autorizado. Troca de inode, montagem ou parâmetros após a revisão deve recusar/replanejar.

### C05 · P0/P1 · Rotas de mutação ainda contornam o motor e a proteção pode ficar antiga

**Inspeção.** O próprio progresso reconhece ajustes e órfãos/grupos fora do coordenador. `MainWindow._terminate/_force/_group` (`main_window.py:368`) chama o reaper diretamente na thread da GUI. O acompanhamento de até 0,5 s por processo pode bloquear a interface por múltiplos desse prazo.

O reaper da GUI recebe `_protection_reason`, que consulta os mapas preenchidos no último snapshot. Uma exclusão ou `keep_active` adicionado após a amostra não é relido por esse callback no momento da ação. A revalidação do processo não substitui a atualização da política de proteção.

Migrar as rotas para executores fora da thread gráfica, compartilhando coordenação, identidade e resultado. Revalidar sessões/exclusões no ato; verificar também descendentes e pertencimento à sessão sem inferir propriedade por nome ou PPID. Preservar SIGKILL como ação manual separada.

### C06 · P1 · Sugestão reutilizada continua oculta

**Reproduzido na suíte e isoladamente.** `tests/test_ui_dashboard.py:151` falha. `_sync_rows()` (`dashboard_tab.py:251`) devolve ao layout uma linha previamente ocultada, sem torná-la visível. Um alerta que desaparece e volta pode continuar escondido.

Corrigir mantendo os limites de vida útil/pool que motivaram o código; não remover o teste nem voltar a destruições que reintroduzam o problema anterior de Qt/Shiboken. Verificar foco, reutilização e crescimento do pool.

### C07 · P1 · CI sem Qt seleciona testes com dependência transitiva de Qt

**Reproduzido por bloqueio de imports.** O job `pure` escolhe arquivos usando `grep -L "PySide6"`. `test_ui_orphans.py` e `test_ui_smoke.py` não contêm essa string, mas importam módulos que dependem de Qt. A coleta falha antes de executar testes.

Separar testes por organização explícita e mecanismo de seleção que opere antes da importação de módulos dependentes de Qt. Um marcador usado apenas na seleção posterior à coleta não resolve importações no topo. Validar de fato num ambiente sem PySide6 e manter outro job com toda a GUI; não mascarar a falha instalando Qt no job headless.

### C08 · P1 · F6 tem peças, mas falta o fluxo real de simulação/execução

**Inspeção.** `automation.evaluate()` é uma função pura alimentada por `Candidate`; contagem sustentada, propriedade, cooldown e histórico chegam prontos do chamador. Não foi encontrado chamador de produção conectando telemetria → construção dessas evidências → avaliação → `DecisionLog.record()`. A CLI lê decisões existentes. A GUI carrega configuração/grants apenas na construção da janela (`main_window.py:89/129`), ficando desatualizada quando a CLI altera modo/pausa ou um grant expira/revoga.

Implementar um controlador testável que produza evidência real e mantenha limites entre reinícios, sem registrar a cada poll a mesma decisão. Expor modo configurado, modo efetivo, executor habilitado, pausa e razão de bloqueio separadamente. A CLI dizer “automático/ativo” não comprova executor funcionando. Manter execução real desligada por padrão; liberar apenas o primeiro escopo administrado depois de simulação e ensaio descartável.

### C09 · P1 · Alterar preset pode perder uma pausa concorrente

**Reproduzido.** `ConfigStore.set_*()` lê antes da trava; só `_write()` é serializado (`config.py:69–114`). Na sonda, uma instância lê para mudar preset, outra salva `paused=True`, e a primeira sobrescreve com o snapshot antigo, voltando a `False`.

O ciclo leitura–alteração–escrita precisa ser transacional, com versão ou lock adequado. Testar principalmente pausa concorrente com mudança de preset/modo; autorização não pode depender de configuração perdida.

### C10 · P1 · Visibilidade, pausa e saúde precisam de estado consistente

**Inspeção.** `hide_window()` verifica se `_compact` existe, não se está visível. O próprio compacto permite ocultar-se sem assegurar outra janela ou bandeja. A combinação pode deixar o aplicativo sem acesso visível. Sem bandeja, `closeEvent()` da central para os workers mesmo se o compacto ainda existir. Não foi validado esse ciclo em desktop real.

`show_error()` só muda uma linha do dashboard; título, bandeja e compacto podem continuar mostrando a saúde anterior quando deixam de chegar amostras. A idade deve avançar e invalidar o estado mesmo sem um novo snapshot. Distinguir pausa de monitoramento e pausa de automação, sem manter indicador de saúde confiável com dados vencidos.

### C11 · P1 · O controle flutuante solicitado ainda não foi entregue integralmente

**Inspeção de implementação, sem nova certificação visual.** Existe uma janela compacta com informações e quatro botões de navegação/pausa/saída. Ainda faltam o controle principal “Dar fôlego”, revisão rápida de plano, estados/animações associados à operação e o fluxo de autorização da ação rápida. Portanto F5 não está concluído pelo aceite original.

O fallback mantém `FramelessWindowHint` em todos os backends e tenta `move()` durante arraste mesmo quando a matriz declara posicionamento absoluto não comprovado. O clamp ocorre ao mostrar e permite só 32×32 px visíveis, o que não garante acesso aos controles. Exigir fallback utilizável e testes de hotplug enquanto a janela está aberta; não afirmar suporte real a Wayland só porque `desktop_caps.py` existe.

### C12 · P1/P2 · F7 ainda é inventário parcial, e o JSON coleta duas vezes

**Reproduzido:** `_cmd_ecosystem()` (`cli.py:1131`) chama `collect()` e depois `to_dict()`, que coleta de novo. Um adaptador falso recebe duas chamadas. Isso duplica custo e pode montar resposta de um instante diferente do primeiro inventário.

**Inspeção:** Docker/Podman compartilham uma superfície de comando sem fixar explicitamente o contexto em todas as chamadas; falha de `context show` não impede as próximas consultas. Referências de volumes/imagens são inferidas de strings de listagem, não de um grafo completo por identidade. libvirt usa nomes/URI padrão e marca `backing_verified=False`, sem completar snapshots/backing chains. Projetos aceitam caminhos relativos, verificam apenas `.git/index.lock` diretamente e ocultam falha de `worktree list` como contagem zero. Worktree limpo aparece `protected=False` mesmo sem autorização de descarte.

Os objetos virtuais permanecem protegidos e os adaptadores não implementam remoção: **não houve demonstração de exclusão indevida**. Essas limitações impedem promover o inventário atual a autoridade para mutar. Completar descoberta de identidade/referências e preservar desconhecidos antes da segunda entrega de cada adaptador.

### C13 · P1 · O custo do próprio Fôlego ainda não tem limite comprovado

**Inspeção.** `Journal.load()` lê o arquivo inteiro; `state_of` e cada append também percorrem o histórico. A GUI chama `_last_operation_text()` em cada snapshot e novamente quando o compacto existe, na thread gráfica. Assim, a coleta offload não remove esse trabalho crescente da interface.

Rotação existe para audit/decisions, mas os arquivos de arquivo compactado continuam se acumulando; isso não é orçamento total nem manutenção dos backups/quarentenas. O diário de operações precisa de estratégia própria que preserve idempotência e operações pendentes.

Os 1.500 snapshots do teste longo e os ciclos rápidos de `tools/soak.py` usam dependências falsas. São regressões úteis, mas não comprovam horas de consumo estável, fechamento de QProcesses, I/O e ausência de filhos esquecidos. Medir o sistema completo com carga sintética isolada e registrar budgets; não reduzir a persistência necessária para parecer leve.

### C14 · P1/P2 · Documentação e aceite não refletem o checkout

**Inspeção.** O progresso ainda termina em 859 testes e F3; `docs/desenvolvimento.md` diz que central/compacto não existem e faz afirmações de execução por filhos que não cobrem o reaper da GUI. O anexo aponta componentes agora presentes como inexistentes. Empacotamento fornece base, mas não evidência de instalação limpa ou launcher executável fora do venv ativado.

Atualizar a documentação como parte de cada incremento, incluindo versões, comando e resultado, ambiente, limitações e próximo passo. Não substituir números antigos por uma contagem maior sem data e execução. Não apagar o histórico de decisões nem anunciar compositor, desempenho ou ações de F7 que não foram validados.

## Situação F0–F8 após a conferência

| Etapa | Classificação nesta revisão | O que impede fechamento |
|---|---|---|
| F0 | Base registrada | Atualizar a fotografia da entrega não commitada |
| F1 | Correções anteriores presentes; regressão atual aberta | C06 e suíte novamente verde |
| F2 | **Parcial, bloqueador** | C01–C05; integração integral, autorização e recuperação ponta a ponta |
| F3 | Base implementada; integração a completar | Proteções atuais no ato, idade sem novas amostras, prazo/custo global |
| F4 | Fluxos manuais e tema parciais | Plano comum, central/histórico/recuperação integrados, critérios visuais e acessibilidade |
| F5 | Compacto de navegação implementado | C10/C11; ação principal, estado/animação reais e validação de desktop |
| F6 | Contratos/config/log parciais | C02/C03/C08/C09; controlador, simulação e execução limitada validada |
| F7 | Inventário inicial | C12; completar referências e depois ações específicas sem privilégios |
| F8 | Infraestrutura inicial | C07/C13/C14; CI funcional, instalação limpa, budgets e ensaio prolongado |

A sequência executável e o aceite de cada incremento estão no [prompt de continuidade](prompt-continuidade.md). O próximo agente deve começar corrigindo a regressão reproduzida e a seleção da CI, e seguir imediatamente para o contrato comum; não deve tratar F2 como uma etapa encerrada.
