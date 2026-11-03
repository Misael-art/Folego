# Modo Desempenho — arquitetura e plano

Pedido de 03/11/2026: um **Modo Desempenho** em que o Fôlego monitora processos
que não servem ao desenvolvimento com agentes (Claude Code, Codex Desktop/CLI,
Codex Web, Claude Desktop/Cloud CLI) e os fecha **automaticamente e com segurança**,
sem afetar o que está sendo desenvolvido. Este documento é o contrato do recurso;
a implementação segue os incrementos do §8.

## 1. Origem: levantamento no host (03/11, 45 min após o boot)

| Candidato | Custo observado | Classe proposta |
|---|---|---|
| Edge aberto só para login do Claude | ~3,2 GB, 24 processos | Fechável |
| Steam silencioso (`steamwebhelper`, pressure-vessel) | ~0,6–0,8 GB | Fechável sem jogo |
| `biglinux-welcome`, demo do `geoclue`, `pamac-tray`, `appimagelauncherd` | pequeno | Autostart dispensável |
| Duas cadeias `npm exec mcp-remote@latest` para o mesmo endpoint | ~220 MB cada | Duplicata (sugestão) |
| Renderer do Claude Desktop acima de 1 GB | ~2 GB no total | Somente observar |
| Units `phasezero-ai-memory-sync`, `sddm-wallpaper` falhando | reinícios | Somente observar |

A própria GUI do Fôlego gastava ~35% de CPU; isso já foi corrigido em `671c2d4`.

## 2. Princípios (herdados de AGENTS.md, não renegociados)

1. **Fechar ≠ matar.** O efeito padrão é o encerramento pedido ao próprio app,
   pelo canal dele: menu da bandeja via DBus, `systemctl --user stop` da unit dele
   ou o fechamento de janela pelo KWin. SIGTERM só no grupo do app, com pidfd e
   acompanhamento. **SIGKILL nunca é automático.**
2. **Lista de permissão, nunca de bloqueio.** Só fecha um processo que casa com
   uma **regra de alvo** explícita, versionada e ativada pelo usuário. Ser
   desconhecido protege o processo; não o torna candidato.
3. **Proteção vence sempre.** Em qualquer momento, um alvo é recusado se:
   - estiver em sessão `keep_active`, exclusão ou `ProcessProtection`;
   - for ancestral, descendente ou estiver no mesmo cgroup/escopo de um agente
     ativo (§4);
   - tiver janela com foco ou estiver tocando áudio;
   - tiver arquivo de projeto aberto para escrita, ou o owner estiver indeterminado.
4. **Intenção durável antes do efeito.** Cada fechamento é um registro no
   `orchestration.Journal` (ID estável, boot_id, pid+starttime, regra, motivo)
   passando pelo `Coordinator`. Resultado incerto bloqueia a repetição até
   reconciliar.
5. **Orçamento e disjuntor.** A cada hora há um teto de fechamentos por regra e no
   total. Duas falhas ou dois resultados incertos seguidos abrem o disjuntor e
   pausam o modo, com aviso na GUI.
6. **Desligado por padrão.** Ligar o modo é uma escolha persistente do usuário na
   GUI/CLI. Cada regra tem modo próprio: Desligada, **Sugerir** (padrão),
   **Assistido** (um clique) ou **Automático**. Preset não amplia grant.

## 3. Arquitetura

```
core/ (sem Qt)                       actions/performance/                 ui/
──────────────                       ────────────────────                 ───
collector.Snapshot ──► perf_model    policy.py  regras+modos+orçamento    performance_tab.py
  (procs, PSI, units)   .AppGroup ──► planner.py  candidatos→Plano    ◄── cards, modo, histórico
agents.py (novo)        (árvore por   executor.py intents→efeito      ──► compact: chip "Desempenho"
  AgentActivity ───────► app/cgroup)  closers.py  bandeja/unit/kwin/term   ai_strip: sem mudanças
process_protection ───────────────►  journal + coordinator (existentes)
exclusions / sessions ────────────►  service.py  unit folego-performance.service (opt-in)
```

- **`core/perf_model.py`**: agrupa processos em `AppGroup` (raiz do app, cgroup
  `app-*.service` da sessão systemd, RSS/PSS e CPU somados, janelas, áudio). A
  identidade usa cgroup + exe + starttime, nunca só o nome.
- **`core/agents.py`**: detecta a atividade de agentes, item que vale como **proteção**:
  - processos `claude`, `codex`, `codex app-server`, launchers do Codex Web e do
    Claude Desktop;
  - filhos deles com cwd dentro de um projeto (`git rev-parse` em cache por cwd);
  - sessões registradas em `core/sessions.py`;
  - CPU e escrita de I/O recentes da árvore.

  O resultado é um `AgentActivity` com o conjunto de PIDs, cgroups e diretórios
  protegidos e um nível de carga (ocioso, interativo ou build/teste).
- **`actions/performance/policy.py`**: o arquivo de regras é JSON versionado e com
  schema. Schema desconhecido ou corrompido **desliga o modo**, sem cair em vazio.
  Cada regra traz `match` (exe/cgroup/unit/desktop-id), `when` (condições
  objetivas, como "Steam sem jogo filho há 10 min" ou "Edge sem janela focada há
  15 min, sem download ativo"), `closer` (canal), `mode` e `budget`.
- **`planner.py`**: é puro. Recebe Snapshot, AgentActivity, regras e o estado da
  pressão de memória e devolve `Plan[Candidate]`, com motivo legível e evidências.
  É testável sem /proc.
- **`executor.py`**: cumpre o ciclo intenção → revalidação **no ato** (pidfd,
  starttime, boot_id e proteção de novo) → closer → acompanhamento (o processo
  saiu em N s?) → resultado `closed | still_running | uncertain | refused`.
- **`closers.py`**:
  - `TrayQuit`: item "Sair/Quit" do dbusmenu, identificado por rótulo e pelo pid
    dono do nome no barramento;
  - `UnitStop`: `systemctl --user stop`, só para `app-*@autostart.service` ou
    unit listada na regra;
  - `WindowClose`: KWin, pelo fechamento normal da janela;
  - `GroupTerm`: SIGTERM ao grupo via `Reaper` existente, permitido somente se a
    regra declarar e o app não tiver bandeja.
- **`service.py`**: a unit `folego-performance.service` (usuário, opcional) segue o
  padrão de `accessibility_service.py`. A GUI também pode hospedar o laço quando
  aberta; um lock garante um único executor.

### Gatilho por pressão, não por relógio
O laço observa a cada 10 s e só **age** quando há motivo: PSI de memória acima do
limiar, RAM disponível abaixo do piso, um agente em fase build/teste
(`AgentActivity.load`) ou a regra marcada como "sempre que ocioso". Sem pressão,
o modo apenas sugere.

## 4. Proteção do trabalho de agentes

Um alvo é recusado se qualquer item abaixo for verdadeiro no ato:
- seu PID ou cgroup está em `AgentActivity.protected`;
- é um navegador usado por um agente: perfil com depuração remota (CDP/Marionette)
  aberto, ou janela do Browser pane / Claude in Chrome;
- serve um endpoint consumido por agente (porta local escutada com cliente de um
  PID protegido; caso do `mcp-remote`, que por isso é só sugestão);
- tem arquivo aberto em diretório Git, banco, modelo, volume ou disco virtual
  (contratos do produto);
- é Docker, VM/`swtpm`, áudio, compositor, portal, teclado, `hermes`,
  `ai-memory`, `phasezero-*` ou o próprio Fôlego, protegidos por classe fixa no
  código e não por regra.

## 5. Regras iniciais

| Regra | Condição | Canal | Modo inicial |
|---|---|---|---|
| `steam-idle` | Steam sem jogo/Proton filho há 10 min, sem download | TrayQuit | Sugerir |
| `edge-after-login` | Edge sem janela focada há 15 min, sem download, sem CDP | WindowClose | Sugerir |
| `autostart-extras` | welcome / geoclue-demo / pamac-tray / appimagelauncherd | UnitStop | Assistido |
| `mcp-duplicate` | Duas cadeias com mesmo comando e endpoint | — | Somente sugestão |
| `electron-bloat` | Renderer acima de 1,5 GB por mais de 30 min | — | Somente sugestão |
| `failed-units` | Unit em falha/reinício | — | Somente sugestão |

Promover uma regra para Automático é decisão do usuário, regra a regra.

## 6. Interface (mantém tema, tokens e componentes atuais)

- **Aba Desempenho**:
  - interruptor do modo;
  - medidor de RAM e PSI no estilo dos anéis;
  - cards por `AppGroup` com custo, motivo e ação, nos estados Proteção / Sugestão
    / Agendado / Fechado / Incerto;
  - lista de regras com seletor de modo;
  - histórico do journal;
  - estado do disjuntor com botão "Retomar".
- **Compacto**: um chip "Desempenho" com o total liberado hoje; clique abre a aba.
- **Notificação**: aviso antes de um fechamento automático, com "Adiar 30 min" e
  "Proteger sempre", que cria a exclusão. Sem confirmação, o efeito só ocorre após
  a carência.
- Todo efeito vai para um worker; a GUI apenas apresenta o estado.

## 7. CLI

`folego performance status|plan|rules|enable|disable|run --once|history|resume`.
`plan` mostra o que seria feito e por quê, sem efeito.

## 8. Incrementos

1. **Observação**: `perf_model` + `agents` + PSI no collector; aba somente
   leitura e CLI `status`/`plan`. Aceite: grupos e proteções corretos no host real.
2. **Políticas e Sugerir**: schema, regras da §5 e cards de sugestão.
3. **Assistido**: closers `TrayQuit` e `UnitStop`, executor com journal,
   revalidação e acompanhamento. Testes de efeito apenas com processos e units
   descartáveis criados pelo teste.
4. **Automático**: laço com gatilho de pressão, orçamento, disjuntor, carência e
   notificação; unit opcional.
5. **Endurecimento**: `WindowClose`, `GroupTerm`, detecção de CDP e portas, e uma
   sessão de soak real com agentes rodando.

Cada incremento roda `./dev test-headless` e `./dev test`, faz QA no KDE/Wayland
real e registra o resultado no HANDOFF.

### Estado em 03/11/2026

Os incrementos 1–4 estão integrados. O 5 entregou os sinais de uso em
`core/usage.py`, que protegem o grupo no plano e na revalidação:
- janela em foco, lida por `kdotool`;
- áudio tocando, lido por `pactl`;
- download em andamento;
- arquivo de projeto aberto para escrita.

Foco ou áudio desconhecido também protegem. Navegadores com CDP ou Marionette
contam como agente. O 5 incluiu ainda um soak a seco com agentes rodando.

Decisões do 5:
- **`WindowClose` e `GroupTerm` ficaram de fora.** `unit_stop` já encerra o Edge
  de forma limpa pelo systemd do usuário, e nenhuma regra precisa enviar sinal
  direto. Reabrir essa questão exige uma regra concreta que não tenha bandeja nem
  unit.
- **A detecção de portas ficou de fora.** A ponte MCP é só conselho, então não
  precisa dessa prova.

## 9. Riscos e mitigação

- **Fechar algo em uso**: mitigado por lista de permissão, proteção no ato, foco,
  áudio e arquivos abertos, carência com notificação e Sugerir como padrão.
- **PID reciclado**: mitigado por pidfd, starttime e boot_id antes do efeito.
- **Laço de fecha/reabre**: autostarts são parados por unit; a regra registra
  "reaberto pelo usuário" e se suspende até o próximo boot.
- **Estado corrompido**: o modo desliga e mostra a causa, sem fallback silencioso.
