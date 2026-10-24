# Proteção do runtime da sessão KDE — avaliação e continuidade

**Conclusão: existe uma base aproveitável, mas ainda não uma solução automática robusta para este incidente.** O Fôlego mede o volume e alerta por ocupação; não identifica nem trata com segurança as fixtures pytest aninhadas no runtime. O reparo PhaseZero tem proteções úteis, porém precisa de integração e endurecimento antes de virar uma rotina autônoma. Este caso passa a ser requisito prioritário da continuidade.

## Evidência do incidente e situação observada

O usuário relatou que fixtures herdaram `TMPDIR=$XDG_RUNTIME_DIR/codex-desktop/tmp`, saturaram o tmpfs e impediram a criação de unidades transitórias, afetando abertura de aplicações pelo KDE. Relatou também prova com `/usr/bin/true`, recuperação do Ashy, quatro conjuntos arquivados e 15 testes aprovados. Essa sequência histórica não foi repetida nesta avaliação; não enchemos o runtime para reproduzi-la.

A hipótese é coerente com a infraestrutura: o systemd usa `$XDG_RUNTIME_DIR/systemd/transient` para configuração transitória do usuário. O erro “Unit … not found” sozinho não identifica sua causa, nem justifica recriar uma unidade com UUID. [Documentação de systemd.unit](https://www.freedesktop.org/software/systemd/man/257/systemd.unit.html).

Confirmamos por leitura:

- `/opt/codex-desktop/start.sh:86` define o temporário dentro de `$XDG_RUNTIME_DIR/$CODEX_LINUX_APP_ID/tmp` quando `TMPDIR` está ausente. Um valor herdado já existente é preservado.
- O script de reparo no projeto externo e a cópia instalada tinham o mesmo SHA-256: `ca70da4c7166b2f0223dac2a04c9db6ce8093e1ea0bd4bbec6bd47d4822146aa`.
- O arquivo `~/.config/environment.d/70-phasezero-agent-tmp.conf` existe. O ambiente exportado pelo systemd já contém `TMPDIR=/home/misael/.cache/phasezero/agent-tmp` e `PYTEST_DEBUG_TEMPROOT` no subdiretório `pytest`.
- **O processo desta avaliação ainda herdava `TMPDIR=/run/user/1000/codex-desktop/tmp`, sem `PYTEST_DEBUG_TEMPROOT`.** Configuração persistida e ambiente efetivo de aplicações antigas são estados diferentes. A documentação de `environment.d` delimita a herança aos serviços iniciados pelo gerenciador; outros processos dependem de quem os inicia. [environment.d](https://www.freedesktop.org/software/systemd/man/latest/environment.d.html).
- Em **18/10/2026, 06:10:07 -03**, o runtime tinha **97,04% de ocupação**, aproximadamente **43,85 MiB disponíveis**, capacidade de 1.554.046.976 bytes e 356.750 inodes disponíveis. Portanto a pressão observada era de bytes, não de inodes. A leitura anterior, alguns minutos antes, também estava em torno de 97%.
- O destino de temporários/backup fica em `/home`, btrfs, com aproximadamente 59 GB disponíveis na leitura. Estar fora da RAM não dispensa orçamento e monitoramento do disco de destino.

Os valores são uma fotografia, não monitoramento contínuo. [Registro da leitura e recibo anterior](evidencias/runtime/host-leitura.json). Não foram alterados ambiente do usuário, perfis, serviços, launchers ou arquivos do runtime.

## Cobertura atual do Fôlego

| Capacidade | Estado conferido | Consequência |
|---|---|---|
| Ocupação em bytes e inodes | `core/tmpfs.py` mede ambos | Boa base de coleta barata com `statvfs` |
| Runtime correto por usuário | `WATCHED` fixa `/run/user/1000` | UID 1001 ou runtime diferente não entra automaticamente |
| Alerta de volume cheio | `HealthEngine` alerta em 75%/90% de bytes | Detecta a pressão deste host quando a coleta funciona |
| Alerta de inodes esgotados | Métrica existe, mas não participa do julgamento | Sonda com inodes zerados e bytes livres ficou **green** |
| Falha de leitura de volume | `watched_volumes()` omite `statvfs` que falha; coletor marca fonte tmpfs OK antes disso | Falta qualidade por volume, independente do sucesso de ler mounts |
| Candidatos no runtime | Política padrão libera apenas padrões de `/tmp`; inventário trabalha com filhos imediatos | Não alcança a unidade segura `…/pytest-of-usuario/pytest-N` |
| `pytest-current`, locks e sessões pytest | Não há adaptador dedicado | Não basta adicionar `/run/user/*` à allow-list |
| Referências de processos | `holders.py` lê descritores, não cwd/maps | Uso sem fd aberto pode escapar; EACCES de um readlink individual é ignorado |
| Arquivamento recuperável | Cópia, digest, fsync, staging e ledger existem para tmpfs | Reutilizáveis após corrigir contratos; não provam inatividade futura |
| Tratamento automático | Política/grants parciais, sem controlador integrado | Não há ciclo autônomo de prevenção e recuperação validado |

Fontes locais: `core/tmpfs.py`, `core/health.py`, `core/collector.py`, `actions/tmpfs/{inventory,policy,holders,release}.py` e `orchestration/automation.py`. Além destas lacunas, exigir aceite dos contratos C01–C05/C08/C09 da [avaliação anterior](avaliacao-entrega.md): autorizações, idempotência, revalidação e honestidade dos resultados precisam estar comprovados antes da automação. Ao terminar esta avaliação, o checkout já continha mudanças adicionais no coordenador, CI e outras áreas em relação ao manifesto anterior; elas foram preservadas e não foram reauditadas integralmente neste complemento. Os arquivos específicos de runtime/health/holders analisados permaneceram iguais ao manifesto anterior.

## O que aproveitar e o que falta no reparo PhaseZero

Arquivo examinado: `/mnt/sdcard/Projects/pz-ashyterm-repair/linux/repairs/terminal.py`. O wrapper instalado chama uma cópia em `~/.local/share/phasezero/repairs/terminal.py`; a integração não deve depender da disponibilidade de um checkout em `/mnt/sdcard`.

Proteções relevantes presentes:

- Seleção por diretório numerado `pytest-N`, idade mínima de uma hora e propriedade do usuário.
- Preservação inicial de `pytest-current`, locks vivos ou ilegíveis e referências detectadas.
- Leitura de cwd, descritores e mapas; tentativa de leitura administrativa quando parte da varredura não é acessível.
- Cópia com symlinks preservados, comparação do conteúdo de arquivos regulares, rechecagem da árvore, fsync de arquivos/diretórios e remoção posterior.
- Exclusão mútua entre instâncias do próprio reparo, backup e prevenção em ambiente de novas aplicações. Ausência de reinício de serviços/agentes.

Essas medidas são superiores a uma limpeza genérica. Porém, não fecham o contrato de um executor automático:

1. **Revalidação de fixture atual incompleta — reproduzido.** `candidates()` verifica `pytest-current`; `archive()` não o verifica novamente. Na sonda, selecionamos uma fixture antiga, mudamos o link para ela e chamamos o arquivador com referências simuladas vazias. A origem foi removida, o link ficou pendente e o backup foi mantido. Não houve perda de conteúdo na sonda, mas o diretório que deveria ser protegido deixou de existir. O lock do reparo não impede pytest ou outro escritor de usar a árvore.
2. **Ausência de referências é evidência momentânea.** Mesmo reler cwd/fd/maps antes de remover não impede uso ou escrita começando logo depois. Idade de uma hora não resolve essa corrida. Para automação, exigir ciclo de vida administrado, término comprovado e exclusão de novos escritores por protocolo cooperativo/lease; se a aplicação externa não oferece essa garantia, manter o candidato bloqueado ou sob revisão manual.
3. **Completude da varredura precisa ser explícita.** Há exceções de readlink descartadas individualmente; `os.walk` no snapshot não recebe tratamento explícito de erros de enumeração. UID, namespaces, PID reciclado, processo que desaparece e permissão negada exigem estados distintos. Não elevar permissões automaticamente nem executar Python arbitrário como root para contornar isso; eventual helper precisa de interface fixa, validada e somente leitura.
4. **Destino diferente não prova destino persistente.** O reparo compara `st_dev` com o runtime, mas outro tmpfs também pode ter device diferente. A implementação integrada precisa usar mountinfo, espaço/inodes, orçamento e política de destino do Fôlego. Não seguir mounts/bind mounts inseridos durante a operação.
5. **Crash e retenção precisam de protocolo comum.** O reparo grava seu resultado ao final; não fornece o diário de cada transição e a reconciliação por operação que o Fôlego exige. É necessário preservar clones incompletos identificados, certificar também symlinks/metadados relevantes, sincronizar entradas de diretório necessárias e tratar ENOSPC/EIO/queda entre etapas. Arquivos arquivados precisam de cota e recuperação, não retenção ilimitada.
6. **“Terminou” não significa “sessão saudável”.** O reparo considera menos de 1 MiB livre como cheio e aceita o resultado quando supera esse piso. O host pode voltar a abrir um terminal e continuar em 97–98%, com pouca margem para outra execução. A UI deve separar recuperação funcional, pressão remanescente e prevenção aplicada aos novos processos.

Não é recomendável agendar repetidamente `reparo-terminal.sh --yes` como implementação de automação. O wrapper inclui confirmação gráfica, o reparo mistura arquivamento e alteração de perfis e não está coordenado com o motor do Fôlego. Separar diagnóstico, autorização/prevenção e execução é necessário.

## Solução proposta: proteção da sessão como recurso de primeira classe

### R1 — Diagnóstico contínuo, leve e independente de reparo

Descobrir o runtime pelo `XDG_RUNTIME_DIR` validado contra UID, proprietário, permissões, mount e boot; usar `/run/user/<uid>` apenas como fallback verificado. Não fixar 1000. Não mudar o próprio `XDG_RUNTIME_DIR`: sockets, barramento e demais recursos de sessão continuam nele.

Coletar bytes totais/livres, inodes quando suportados, identidade do monte, idade/qualidade por volume e tendência de crescimento. Se `f_files=0`, distinguir métrica não suportada de zero inodes livres. Falha de `statvfs` preserva o volume como desconhecido, em vez de removê-lo da tela.

Valores iniciais propostos, a calibrar em testes: atenção em 75%, crítico em 90%, emergência em 97%, acrescidos de pisos absolutos proporcionais à capacidade. Zero bytes ou zero inodes conhecidos exigem alerta imediato; ações continuam sujeitas às mesmas proteções. Histórico de crescimento pode antecipar alerta, mas não prometer um tempo exato até falha. Saída do alerta exige folga e amostras estáveis, não apenas cruzar 1 MiB.

Fazer `statvfs` em frequência curta, sem varrer todo `/proc` ou todo o runtime em cada poll. Inventário detalhado é limitado por tempo/itens, acionado sob pressão ou solicitação, e executado fora da UI. Mostrar separadamente espaço total ocupado, bytes de candidatos conhecidos, protegidos e uso não atribuído. Arquivos apagados ainda abertos ou uso não explicado não autorizam matar processos.

### R2 — Prevenir a próxima saturação

O launcher de sessões e os workers do Fôlego devem receber explicitamente temporários privados em volume persistente, mesmo quando o próprio Fôlego herdar ambiente antigo. Verificar mount/folga antes de criar arquivos grandes. Para pytest, diretório exclusivo por execução e `--basetemp` próprio; nunca apontar essa opção a um diretório compartilhado ou com dados úteis, pois pytest limpa a base fornecida. A raiz padrão pode ser configurada por `PYTEST_DEBUG_TEMPROOT`; retenção tem configurações próprias. [Documentação de temporários do pytest](https://docs.pytest.org/en/stable/how-to/tmp_path.html).

Registrar run ID, sessão, UID, boot/starttime, raiz, limites e ciclo de vida. Prever quota/limite de concorrência para novos jobs administrados e retenção em disco, sem suspender ou encerrar trabalhos externos automaticamente.

Detectar a prevenção PhaseZero já existente e reutilizá-la quando válida; não criar blocos concorrentes nos mesmos perfis. A GUI deve indicar **“novas execuções protegidas; processos antigos ainda usam o runtime”** quando for o caso. Mudanças globais de perfil/ambiente exigem adesão inicial explícita e backup; operações de pressão recorrentes não reescrevem perfis a cada disparo. Não reiniciar agentes para impor o novo ambiente.

### R3 — Adaptador de fixtures e política de ação específica

Criar catálogo de raízes registradas/confiáveis. Para o incidente: `$XDG_RUNTIME_DIR/codex-desktop/tmp/pytest-of-<usuario>/pytest-<numero>`, com validação de todos os ancestrais. Não liberar a raiz `codex-desktop`, o runtime inteiro ou qualquer pasta que apenas contenha “pytest” no nome.

Classificar explicitamente: atual, ativa, recente, lock inválido, referência desconhecida, administrada concluída, candidata legada à revisão, protegida por exclusão. Revalidar `pytest-current`, locks, identidade da raiz e descendentes, permissões, cwd/fd/maps e ciclo de vida no ato, inclusive após cópia. PID existente é proteção conservadora; identidade administrada usa boot/starttime, não apenas número de PID.

O conjunto automático inicial deve ser **menor** que o conjunto revisável manualmente: somente execuções administradas concluídas, grant por raiz/ação e garantia suficiente de ausência de escritores. Fixtures legadas podem ser inventariadas e arquivadas por plano manual; só entram na automação depois de adoção explícita e comprovação dos requisitos. Preservar toda ambiguidade, inclusive se nada puder ser liberado.

Proteger permanentemente sockets, D-Bus, Wayland, PipeWire, portais, `systemd`, credenciais, agentes e outros objetos especiais. Nome de serviço ausente não muda essa política.

### R4 — Execução limitada e recuperável mesmo sob runtime cheio

Integrar com o coordenador corrigido, grants fechados, ID estável e diário no disco. Processo residente e worker precisam funcionar sem criar unidade transitória para iniciar o próprio reparo; não depender exclusivamente do menu KDE, de `kdialog` ou de novas alocações no runtime que está cheio. Usar worker próprio com temporários em disco e garantir que lock, journal e staging de controle não voltem ao runtime saturado.

Sequência: evidência atual → plano e autorização → intenção durável → staging/cópia em disco → verificação completa → proteção/identidade/ciclo de vida revalidados → remoção estritamente confinada → fsync/resultado → nova leitura de capacidade → reconciliação quando necessária. Sem garantia de escritor ausente, copiar pode ser permitido, mas remover automaticamente continua bloqueado.

Executar um candidato por vez, com limites de bytes/tempo/I/O, intervalo e teto por hora. Reavaliar folga depois de cada um e parar ao atingir margem ou perder evidência. Emergência antecipa alerta, não remove os filtros. Não reiniciar serviços, aumentar tmpfs, recriar UUIDs, executar prune ou limpar runtime genérico como escalada.

### R5 — Verificação e apresentação honesta

Exibir na central e no compacto: **“Runtime da sessão crítico — aplicativos podem não abrir”**, bytes/inodes, causa identificada ou desconhecida, estimativa elegível, bloqueados e motivo. Separar saúde, ação e prevenção.

Depois da execução: bytes copiados/alocados, variação observada no volume, itens preservados, caminho de recuperação e margem remanescente. Uma ação que recupera 44 MiB e deixa 97% não recebe “problema resolvido” genérico. Se só houver material ativo/ambíguo, apresentar “tratamento automático bloqueado com segurança”, com prevenção e revisão possíveis.

Uma prova funcional opcional pode usar uma unidade transitória própria com `/usr/bin/true`, prazo e resultado observado, sem abrir aplicações do usuário. É operação diagnóstica distinta de leitura; não executá-la a cada poll. O teste deve medir a execução, não a presença posterior da unidade, que pode ser coletada. [systemd-run](https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html). Nenhuma prova funcional real foi disparada nesta avaliação.

## Testes e critério de aceite

Nesta revisão, **136 testes existentes passaram em 1,26 s** nas áreas health, holders, política/inventário/plano/release tmpfs e coletor. Isso não cobre os novos cenários: as [sondas isoladas](evidencias/runtime/sondas.json) demonstraram as lacunas fora desses testes. [Script reproduzível](evidencias/runtime/reproduzir-runtime.py) e [log](evidencias/runtime/testes-focados.log).

O próximo agente deve transformar as sondas em regressões das invariantes desejadas e acrescentar:

| Cenário | Aceite |
|---|---|
| UID diferente de 1000, runtime personalizado/ausente/inválido | Descoberta correta ou desconhecido explicado; nunca tocar runtime de outro usuário |
| Bytes esgotados; inodes esgotados; statvfs negado; f_files não suportado | Alerta/qualidade corretos, sem verde falso |
| `pytest-current` muda depois do plano ou durante cópia | Preservar origem; não apagar fixture que passou a ser atual |
| Lock vivo/inválido/reciclado, cwd sem fd, mmap após fechar fd, proc opaco | Preservar ou bloquear; referências incompletas nunca são “complete” |
| Escrita começa depois da última varredura | Lease/protocolo impede corrida; sem garantia, recusa automática |
| Symlink/mount/bind mount/inode trocado e ancestral substituído | Recusa confinada, sem seguir destino nem remover dados externos |
| Destino outro tmpfs, disco/inodes insuficientes, quota, ENOSPC/EIO | Não remover origem; staging/resultado recuperáveis |
| Queda antes/depois de copiar, certificar, apagar e registrar | Pelo menos cópia certificada preservada; mesma operação não reaplicada cegamente |
| Duas instâncias, grant revogado, pausa durante fila, duplo clique | Coordenação e autorização atuais; no máximo uma execução |
| Runtime sem capacidade para nova unidade transitória | Residente/worker continua diagnosticando e tratando apenas candidatos autorizados |
| Ambiente antigo herdado versus ambiente novo configurado | Filho administrado recebe temporários de disco explícitos; não afirmar que processos antigos mudaram |
| Nenhum candidato elegível; runtime continua crítico após ganho pequeno | Resultado parcial/bloqueado honesto, sem escalar limpeza |
| Uso prolongado e disco de backup sob pressão | Budgets e retenção conservadora; não transferir o problema ilimitadamente para `/home` |

Usar árvores descartáveis em disco, proc/mounts sintéticos e, para integração, namespace/VM de teste com tmpfs pequeno. **Nunca saturar `/run/user` real para provar o teste.** Não instalar helper privilegiado, modificar o pacote PhaseZero ou ativar limpeza no host como parte deste aceite.

## Ordem de entrega

1. **Agora, na continuidade:** R1 e R2 — diagnóstico por runtime real, prevenção dos próprios jobs e ambiente efetivo. Podem avançar sem liberar nenhuma limpeza.
2. **Depois dos bloqueadores I1/I2 do prompt principal:** R3 e R4 em modo de simulação, testes de corrida/queda e integração de arquivamento manual.
3. **Após aceite isolado:** ativação opt-in do escopo administrado, R5 e integração com o botão “Dar fôlego”. Não tratar a configuração automática de testes como permissão para ligá-la no host atual.

O [prompt principal](prompt-continuidade.md) incorpora este requisito. Esta entrega é avaliação e especificação; não implementa nem habilita o novo controlador.
