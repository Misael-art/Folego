# Avaliação técnica do Fôlego

O Fôlego tem uma boa separação inicial entre coleta, decisões, ações e apresentação. O maior risco para a evolução solicitada é reutilizar rotas manuais, hoje com garantias diferentes, dentro de um botão de execução automática. Os achados abaixo priorizam perda de dados, interrupção de trabalho legítimo, responsividade e honestidade dos resultados.

P0 significa bloqueador de automação ou de uma operação segura; P1 significa correção necessária para operação cotidiana confiável; P2 significa evolução de abrangência e manutenção. Estas prioridades são de produto e engenharia, não uma classificação de vulnerabilidades exploráveis.

## Cobertura atual

| Área | O que existe | Limite atual |
|---|---|---|
| Plataforma | Python 3.14+, PySide6 do sistema, Linux, launcher local | Produto descrito como Steam Deck/BigLinux/KDE; sem matriz declarada de compatibilidade |
| Memória | `MemAvailable`, swap, PSI, RSS agregado e do próprio app | RSS compartilhado pode ser contado várias vezes; não mede ganho causal |
| CPU e I/O | PSI e load coletados; ticks de CPU por processo | Sem taxa de CPU apresentada, inventário de I/O por sessão ou motor de intervenção |
| Órfãos | Observação temporal, identidade PID/starttime, lista protegida, SIGTERM/SIGKILL | Heurística não prova abandono; não gerencia ciclo de vida de agentes |
| Navegadores | Grupos Edge/Chrome e dois ajustes do Edge | Agrupamento por executável aparente; ajustes limitados ao perfil Default e chaves observadas no host original |
| Disco | Inventário de caches, quarentena por rename, restore e purge | GUI apenas consulta; CLI permite alvos além do plano; quarentena não libera espaço no mesmo volume |
| Temporários | Inventário, holders por fd, allow-list, cópia verificada, ledger e retenção | Prova de ausência de uso incompleta, concorrência e recuperação ainda insuficientes |
| Interface | Cinco abas, sinal no título, bandeja opcional | Sem controle flutuante, presets, histórico integrado ou execução unificada |
| Testes | 553 testes, fixtures, Hypothesis, testes Qt e subprocessos | Lacunas de integração entre camadas, concorrência, falhas de início e ambiente real |
| VMs e containers | Não há adaptadores no código revisado | Nem inventário de dependências nem encerramento orientado ao gerenciador |
| Projetos de agentes | Não há registro de sessão/artefato | Não diferencia fonte, trabalho não salvo, worktree, cache e descarte autorizado |

## O que preservar

- `core` e `actions` independentes de Qt e CLI utilizável sem ambiente gráfico.
- Snapshots e decisões representados por dados simples, com dependências injetáveis.
- Confirmação nas principais interfaces de mutação, proteção contra PID reutilizado e recusa de vários processos essenciais.
- Edição pontual de JSON, hash antes/depois e backup para ajustes.
- Recusa de movimentos entre dispositivos na quarentena baseada em rename.
- Copy → verify → registro parcial → remoção na transferência de temporários, incluindo retenção e restore.
- Testes contra configurações de navegador falsas e verificação de que o perfil real não mudou.

## Falhas reproduzidas em ambiente isolado

As sete verificações estão em [reproduzir.py](evidencias/reproduzir.py), com resultados em [resultados.json](evidencias/resultados.json). São diagnósticos que registram o comportamento atual; não foram incorporados à suíte de regressão do produto e não executam exclusões ou sinais contra recursos reais do usuário.

### R01 Limpeza antiga aceita árvore com conteúdo recente

**P0 — reproduzido.** Em [tmpclean.py](../../../src/folego/actions/disk/tmpclean.py), `plan_tmp`, linha 57, considera a data do filho direto, não a data mais recente de toda a árvore. Uma pasta com cinco dias e um arquivo recém-escrito foi selecionada para exclusão. `expire_tmp` aplica `rmtree` sem consultar holders, mounts ou a política de `tmpfs`.

Além disso, `_cmd_tmp` em [cli.py](../../../src/folego/cli.py) aceita `--raiz` arbitrária e recusa apenas caminhos cujo resultado começa por `/mnt`. As duas flags são uma confirmação de exclusão, mas não tornam a seleção segura. **Correção:** desativar a mutação legada ou redirecioná-la para um único planejador conservador; aceitar apenas raízes e itens explicitamente suportados. Testar descendente recente, arquivo aberto, montagem interna, raiz arbitrária e troca de caminho.

### R02 Falta de visibilidade de processos vira ausência de uso

**P0 — reproduzido.** [holders.py](../../../src/folego/actions/tmpfs/holders.py) registra `proc_count`, mas [inventory.py](../../../src/folego/actions/tmpfs/inventory.py) leva à política apenas `holder_pids`. Com `/proc` inexistente, `proc_count=0` e o item ainda pode ser elegível. A prova usa idade mínima zero para isolar exclusivamente esse defeito de completude. O caminho de mutação `_fresh_entry` também perde essa informação.

Mesmo um índice legível de fd não cobre sozinho `cwd`, `root`, arquivos mapeados após fechar o fd, namespaces e futuras aberturas. **Correção:** estado `complete/partial/unavailable`, erros e abrangência no inventário; desconhecido bloqueia automação. Recursos externos sem contrato de propriedade continuam sujeitos a revisão manual. Um `flock` não impede um escritor que não participa do protocolo.

### R03 Inventário de disco incompleto aparece como recuperável

**P0 para execução futura; hoje principalmente erro de diagnóstico — reproduzido.** Em [planner.py](../../../src/folego/actions/disk/planner.py), `build_plan` calcula `reclaimable` por bytes e idade, mesmo com `errors` e `truncated`. O caso sintético retornou `reclaimable=true` com erro de permissão e leitura truncada. A aba de disco dá prioridade ao rótulo recuperável e não preserva todos esses avisos.

**Correção:** separar “tamanho parcialmente conhecido”, “candidato” e “autorizado”; inventário incompleto nunca entra automaticamente no total elegível. O digest precisa representar identidade, política e pré-condições, não apenas pares caminho/tamanho.

### R04 Consulta do ledger por caminho retorna ciclo antigo

**P0 para automação — reproduzido.** [ledger.py](../../../src/folego/actions/tmpfs/ledger.py), `find`, linha 134, retorna a primeira entrada com aquele `src`. Após um ciclo restaurado e uma nova liberação, a busca devolveu `old/restored` em vez de `new/released`. `release_item` usa essa busca para impedir uma duplicação ativa; portanto a proteção pode consultar o ciclo errado.

**Correção:** operações por ID estável; índice com unicidade de retenção ativa por identidade de origem; busca de caminho deve priorizar entradas ativas e tratar ambiguidade. Testar três ciclos no mesmo caminho e reconstrução do diretório entre eles.

### R05 Mudança na lista de navegadores lança exceção

**P1 — reproduzido.** [orphans_panel.py](../../../src/folego/ui/orphans_panel.py), `show_groups`, linha 88, substitui `_groups` e depois usa o índice da lista anterior. Selecionar o segundo de dois grupos e receber uma lista com um único grupo causa `IndexError`. Isso pode interromper a aplicação daquele snapshot, inclusive as atualizações posteriores do painel e da bandeja.

**Correção:** guardar a chave da seleção anterior antes de substituir a coleção; restaurar por identidade; nunca por posição. Corrigir também o texto “Sem órfãos”, que permanece após candidatos surgirem, visível na captura 04.

### R06 Falha de início deixa executor ocupado

**P1 — reproduzido.** [tune_jobs.py](../../../src/folego/ui/tune_jobs.py), `_error`, linha 105, apenas guarda uma mensagem. Quando o executável não existe, o fluxo pode não emitir `finished`; depois do timeout, a prova encontrou zero callbacks e `in_flight=1`.

**Correção:** uma finalização idempotente comum para sucesso, `FailedToStart`, erro, timeout e cancelamento. Remover referências de `procs`, parar timers e liberar objetos Qt. Hoje os objetos concluídos continuam em `procs`, e não há `deleteLater` no término: risco de crescimento em sessões longas.

### R07 A interface oferece liberação de item protegido

**P1 — reproduzido.** [tmpfs_tab.py](../../../src/folego/ui/tmpfs_tab.py), `show_plan`, cria botão “Liberar” habilitado para candidatos e protegidos. A captura 05 mostra “arquivo em uso” e o botão ativo na mesma linha. O executor pode recusar novamente, mas a interface oferece uma ação que já sabe estar bloqueada.

**Correção:** ação desabilitada com motivo; leitura inconsistente bloqueia execução do plano inteiro. Restauração deve respeitar o estado do registro. A confirmação de expiração deve listar apenas as vítimas efetivas, não o total retido.

## Riscos confirmados pela leitura do código

Estes achados descrevem contratos ausentes ou inconsistentes no código; cenários de corrida, queda de energia e filesystem defeituoso não foram provocados no host.

### R08 Exclusão mútua não abrange a aplicação

**P0.** [main_window.py](../../../src/folego/ui/main_window.py) cria três `TuneJobs`; cada um guarda seu próprio `in_flight`. [runner.py](../../../src/folego/process/runner.py) usa `threading.Lock`, que não coordena CLIs independentes. O reaper é chamado diretamente pela janela. Não há autoridade única entre GUI, CLI e futuras automações.

O plano histórico já reconhece o limite por camada; portanto isto é uma dívida conhecida que se torna bloqueadora com o novo escopo. Criar coordenador comum e trava entre processos por usuário/estado. Escrita atômica de um arquivo não substitui transação para leitura → alteração → escrita nem evita perda de atualizações do manifesto.

### R09 Heurística de órfãos não comprova abandono

**P0 para automação.** [core/orphans.py](../../../src/folego/core/orphans.py) procura processos adotados, sem filhos vivos e sem mudança de CPU. Um serviço legítimo esperando rede pode satisfazer isso. Um processo abandonado que continua consumindo CPU pode nunca satisfazer. A relação de sessões usada por `is_adopted` também não autentica a identidade do supervisor. CLI usa janela padrão de 10 s; GUI usa 300 s.

[reaper.py](../../../src/folego/actions/orphans/reaper.py), `_send`, linha 81, revalida starttime, nome protegido e adoção, mas não repete UID, cadeia ancestral, filhos, liderança e atividade recente. Proteção de automação é aplicada no modo de grupo, não de forma equivalente na rota de órfão. Há ainda uma janela entre a leitura e `kill(pid)`.

Introduzir procedência de sessão, proteção por identidade/cgroup e revalidação completa. Usar pidfd quando disponível e recusar automação quando a identidade não puder ser estabilizada. Renomear a experiência para “possivelmente abandonado”. Remover “sem risco” de [suggestions.py](../../../src/folego/core/suggestions.py).

### R10 Sinal enviado e processo encerrado são tratados de maneira desigual

**P1.** A CLI imprime “encerrado” após `os.kill` retornar. A UI é mais correta ao dizer “sinalizado”, mas `_after` chama de sobreviventes apenas os resultados recusados; um processo que recebeu SIGTERM e permaneceu ativo não entra nesse conjunto. O próximo snapshot limpa o conjunto novamente. Ordenar membros por PID decrescente também não equivale a ordenar filhos antes dos pais.

Criar ciclo solicitado → sinalizado → aguardando → encerrado/permanece ativo/recusado. Recusa de proteção nunca autoriza escalada. Escalada manual requer identidade atual e nova avaliação; grupo deve ser representado por árvore ou unidade administrada.

### R11 Cópias e restaurações têm janelas de recuperação incompletas

**P0.** Em [release.py](../../../src/folego/actions/tmpfs/release.py), o registro `partial` nasce depois da cópia e dos hashes. Interrupção durante a cópia deixa destino sem entrada no ledger. Uma escrita na origem depois do hash e antes de `rmtree` pode perder conteúdo novo. Um novo holder também pode aparecer nesse intervalo.

Na restauração, o clone retido é removido após comparação de hash, sem etapa equivalente de persistência durável de todo o destino. `_sync_tree` da liberação sincroniza arquivos, não todos os diretórios internos, e `is_file` pode seguir links. Hash de conteúdo não representa diretórios vazios, toda a metadata ou durabilidade após energia cair.

Registrar intenção antes de criar destino, usar staging exclusivo e máquina de estados recuperável. Validar identidade em cada transição; proibir execução automática de árvore com escritor externo não coordenado. Definir contrato de metadata, links e persistência; conservar a cópia quando o estado ficar incerto. Falha durante remoção pode deixar origem parcialmente apagada: a recuperação deve preservar ambos e oferecer destino alternativo, pois o restore atual recusa origem já existente.

### R12 O destino de retenção não é comprovadamente disco

**P0 para automação.** [paths.py](../../../src/folego/paths.py) deriva a retenção de `XDG_DATA_HOME` e a descreve como SSD. O executor verifica folga e permissões, mas não comprova filesystem de destino, dispositivo ou mount identity. XDG pode estar em tmpfs, disco remoto ou armazenamento diferente do esperado.

Determinar origem e destino por `mountinfo`, tipo e identidade da montagem; exigir destino suportado fora do tmpfs de origem. Não chamar qualquer armazenamento persistente de SSD sem evidência. Reservar orçamento durante a cópia e aplicar teto ao crescimento real, não apenas à estimativa inicial.

### R13 Quarentena permite escopo maior que o inventário

**P0 para automação.** [quarantine.py](../../../src/folego/actions/disk/quarantine.py), `move_in`, linha 121, recebe caminho e aplica o guard com raízes amplas, incluindo home. Não exige associação a um plano de caches. Conteúdo ativo ou uma árvore de projeto pode ser movido com confirmação. Manifesto corrupto vira lista vazia; ações de restore/purge dependem dos caminhos do manifesto, sem validação completa da relação entry ID → payload → raiz privada.

Separar ferramenta manual avançada do catálogo elegível; bloquear raízes de projetos, ancestrais da retenção, montagens e estado interno. Validar esquemas e confinamento de origem/destino. Corrupção deve bloquear mutação e oferecer recuperação, não permitir recomeçar um manifesto vazio. Auditar intenção e resultado de restore/purge e reconciliar todas as transições, não só `planned` → `stored`.

### R14 Guard de caminhos é necessário, mas insuficiente

**P0 para automação.** [guard.py](../../../src/folego/safely/guard.py), linha 32, verifica prefixo textual, symlink final, caminho resolvido e dono. Não representa mount ID, bind mounts, estabilidade dos ancestrais ou identidade inode/device do objeto validado. Medição e mutação usam caminhos novamente, sujeitos a mudanças entre as etapas.

Reaplicar regras sobre identidade resolvida; usar operações relativas a descritores e recusa de links onde suportado. Não ampliar a allow-list inteira para acomodar um novo adaptador. VMs, containers e montagens devem passar por seus próprios contratos e gerenciadores.

### R15 Resultados de economia podem induzir erro

**P1.** [measure.py](../../../src/folego/actions/disk/measure.py) soma `st_size`: isso representa tamanho lógico, não blocos efetivamente recuperáveis, principalmente com arquivos esparsos, hardlinks e reflinks. Quarentena por rename no mesmo filesystem não libera capacidade. `release_item` chama os bytes do clone de `freed_bytes`; [ledger.py](../../../src/folego/actions/tmpfs/ledger.py) agrega eventos históricos como “RAM liberada de fato”. `expire_over_budget` soma bytes até para payload que já não existia, comportamento hoje fixado em teste.

Separar tamanho lógico, blocos alocados estimados, bytes transferidos, retenção e variação observada de disponibilidade. Medir antes/depois por volume e janela temporal; não atribuir toda variação a uma ação quando outros processos trabalham. PSS é mais adequado que soma de RSS para atribuição de memória compartilhada, com custo e disponibilidade explícitos.

### R16 Coleta e renderização podem competir com a responsividade

**P1.** [workers.py](../../../src/folego/ui/workers.py) executa a coleta completa na thread principal a cada 2 s. A decisão foi motivada por falhas observadas com QThread/PySide; não se recomenda trocar por QThread sem investigação. Milhares de processos, races de `/proc` ou chamadas lentas podem atrasar o event loop. A UI recria linhas e barras a cada snapshot, mesmo oculta.

`read_proc` em [procfs.py](../../../src/folego/core/procfs.py), linha 86, protege as primeiras leituras, mas `comm.exists()` seguido de `read_text()` fica fora do bloco; desaparecimento do processo pode abortar a coleta. Conversões de inteiros de meminfo/status também não degradam como promete a docstring.

Usar coleta incremental ou processo persistente com canal limitado, amostras monotônicas e tolerância por campo/processo. Atualizar modelos por diferença, suspender pintura oculta e medir custo no hardware alvo. Exibir idade da amostra e estado desconhecido; não manter sinal verde indefinidamente após falhas.

### R17 Deadlines e término de filhos não são globais

**P1.** `inventory` recebe prazo por entrada, enquanto CLI e comentários o descrevem como prazo por volume. `holder_index` não tem prazo. `measure_tree` materializa um diretório inteiro em lista e checa o prazo no início de cada diretório. Muitos itens podem ultrapassar amplamente o orçamento esperado.

O runner síncrono inicia sessão própria, mas primeiro mata apenas o filho; sinaliza o grupo somente quando a drenagem excede o prazo. `TuneJobs` mata apenas o processo Qt associado e não gerencia toda a descendência. Um filho em estado D pode continuar após SIGKILL; timeout significa resultado desconhecido, não morte comprovada. `Popen` também é criado fora do bloco que trata falha de início.

Orçamento total de tempo/entradas/bytes, paginação, grupo de processos ou unidade gerenciada e protocolo de cancelamento recuperável são necessários. Consultas repetidas devem ser agregadas; hoje leituras concorrentes não sofrem o bloqueio de mutações.

### R18 Ajustes e backups precisam do mesmo contrato de mutação

**P1.** [worker.py](../../../src/folego/actions/tunings/worker.py) executa `revert` sem verificar `confirm`; CLI e GUI verificam antes, mas a entrada direta do worker não. [engine.py](../../../src/folego/actions/tunings/engine.py) exige navegador fechado em apply, não em revert. Revalidação de guard não acompanha todas as fases de escrita.

[backup.py](../../../src/folego/safely/backup.py) salva payload e manifesto com escritas simples, sem protocolo durável equivalente ao arquivo alterado e sem permissões privadas garantidas para todos os backups. Configurações de navegador podem conter dados pessoais. Falhas depois de escrever não têm sempre um resultado estruturado e recuperável.

Centralizar autorização no executor, validar estado do navegador nas duas direções, criar backups privados e duráveis e preservar erro parcial. Chaves inferidas de binário/config local não comprovam efeito em outras versões; documentar versões suportadas e validar comportamento, não só persistência dos bytes.

### R19 Saúde do host está incompleta

**P1/P2.** PSI CPU/I/O é coletado, mas o sinal principal considera memória/tmpfs e RSS próprio. Não há inodes livres, capacidade de todos os volumes relevantes por identidade, taxa de I/O, processos em D, eventos de OOM, GPU/VRAM ou inventário de containers/VMs. `sysfs.read_zram_mm_stat` interpreta o quarto campo como memória usada; a documentação do kernel define `mem_used_total` como terceiro e `mem_limit` como quarto. O teste repete o entendimento incorreto, e essa leitura ainda não entra no Snapshot. [Referência de zram](https://docs.kernel.org/admin-guide/blockdev/zram.html).

Adicionar observação em camadas, mantendo adaptadores opcionais. Primeira prioridade: PSI, CPU por deltas, I/O, bytes/inodes e saúde da própria coleta. GPU, térmica e bateria são extensões de diagnóstico; ações de configuração global não entram automaticamente no escopo.

### R20 Persistência, distribuição e documentação ainda são locais

**P1/P2.** Logs JSONL e ledger crescem sem rotação/compactação; leituras carregam arquivos inteiros. `AuditLog` tem janela de criação concorrente e a maioria dos atos audita depois de mutar. Não há instância única, formato versionado de settings/presets, migração de estado ou gerenciador residente independente da janela.

`pyproject.toml` declara dependências vazias apesar de PySide6 ser necessário à GUI. Não há entrypoint instalado `folego`, README de instalação, CI ou arquivo desktop versionados encontrados. O código usa `/run/user/1000`, `.cache` e caminhos específicos; a lixeira procura `trash` minúsculo. O plano M7 descreve `tools/verify_tmpfs.py` e seu teste, mas eles não estão no checkout. A renomeação de DeckWellness para Fôlego exige estratégia de migração do estado anterior, não apenas novos caminhos.

Documentar ambiente suportado; oferecer `doctor` sem mutações; instalar CLI e GUI de forma reproduzível; usar UID/XDG efetivos; versionar e migrar dados com backup. A leitura de logs deve ser limitada e a retenção auditável. Não remover backups antigos automaticamente durante a migração.

## Síntese de prioridade

| Antes de | Resolver |
|---|---|
| Próxima versão manual confiável | R01–R07, mensagens de R09/R10/R15, coleta tolerante e erros de worker |
| Qualquer preset automático | R02, R04, R08–R14, autorização de R18, recuperação e capacidade real |
| Uso residente prolongado | R06, R16, R17, rotação/compactação de R20 e budgets medidos |
| Gestão de agentes e VMs | Procedência, adaptadores e inventário de dependências previstos na arquitetura |

Os testes existentes são uma base de regressão útil. O próximo conjunto deve verificar invariantes entre componentes e contra exemplos adversos, principalmente desconhecido versus seguro, sinalizado versus encerrado, retido versus liberado e plano confirmado versus objeto atual.
