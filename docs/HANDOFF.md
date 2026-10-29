# Passagem para o próximo agente — 24/10/2026

## Ponto de retomada

Projeto Linux/KDE, Python 3.14.7 + PySide6. CLI independente de Qt. O objetivo é
manter uma máquina com agentes e aplicações responsiva sem perder trabalho,
inventando o mínimo possível sobre recursos ausentes e preservando recuperação.

Base histórica: `61179f55123b44a996aa6087d124474eb5e84b1e`. A entrega posterior
estava quase toda no working tree; esta migração preserva esse material em Git,
sem reset, limpeza ou redução de escopo para fazer os testes passarem.

Leia `AGENTS.md`, `docs/DIAGNOSTICO-2026-10-24.md` e `docs/NOVO-HOST.md`.
Depois execute `./dev check`. Não depender do antigo `/home/misael`, venv,
serviços, arquivos de anexos ou da disponibilidade deste host.

## O que está integrado

- Coordenação de mutações de disco/tmpfs/ajustes/processos, intenção antes do
  efeito, IDs, planos v2 imutáveis com prazo e consulta por operação.
- Proteção fresca de sessões/exclusões/ancestrais, boot/PID/starttime e
  acompanhamento de SIGTERM. A GUI de produção pede sinais por QProcess.
- Frescor/qualidade de saúde, histórico em worker com leitura limitada e
  feedback de parcial/desconhecido sem converter isso em recusa sem efeito.
- Inventário protegido de fixtures pytest, runtime por UID e temporários
  privados de filhos em destino verificado. Não há arquivamento automático.
- Central e compacto parciais: fallback decorado Wayland, botões acessíveis,
  ciclo de vida sem bandeja corrigido, pausa antes da primeira leitura e
  bandeja mostrada na abertura. Launcher absoluto testado via GIO.
- Bootstrap portátil com versões fixadas, ambientes GUI/headless próprios e
  testes com HOME/TMPDIR isolados. É suporte de desenvolvimento, não autostart.

F0/F1 preservados; F2/F3 avançados, F4/F5 parciais, F6 desligado, F7 protegido/
somente leitura, F8 parcial. Não promover essa classificação a “produto concluído”.

## Próximos incrementos, em ordem

| Prioridade | Trabalho | Aceite concreto |
|---|---|---|
| 1 | Validar bootstrap no novo Linux e registrar versões/recursos | Ambientes sem system-site-packages, CLI sem Qt, duas suítes sequenciais; distinguir skip por Edge ausente |
| 2 | Política de temporários administrados e retenção | Hoje 256 diretórios acumulados recusam novos filhos. Definir lease/identidade, orçamento e revisão/expiração segura; não remover diretórios ambíguos nem adotar fixtures legadas |
| 3 | Repetir soak controlado com raiz exclusiva | 7200 segundos reais, perfil fixo, todos os resultados e filhos contabilizados, fixture restaurada e orçamento aprovado; nunca somar tentativas |
| 4 | Vincular revisão/ID no pai para todas as mutações | Ajustes/tmpfs/restore/purge devem preservar o plano confirmado e ID mesmo em timeout; reconciliação de domínio pelo mesmo ID, sem reaplicar desconhecidos |
| 5 | Prazo total/cancelamento e histórico durável | Limitar coleta e operações, acompanhar filhos, reduzir I/O restante na apresentação; indexação/compactação preservando intenções pendentes e corrupção |
| 6 | Concluir fluxo Dar fôlego | Analisar → revisar o mesmo plano → confirmar → executar → verificar → recuperar; um clique repetido gera no máximo uma operação e arraste gera zero |
| 7 | Fechar matriz real de desktop | Leitor de tela, arraste físico Wayland, retorno do launcher para instância já aberta, outra distribuição limpa e login físico X11 |
| 8 | Assistido antes de Automático | Controlador sem Qt com evidência real, cooldown/orçamentos/disjuntor persistidos e grants de frequência; simulação verificável antes de qualquer executor opt-in |

As tarefas 2/4/5 precisam de desenho e testes de falhas; não são autorização para
limpar o host. O limite de 256 protegeu corretamente antes do efeito. A correção
de isolamento do harness não resolveu a gestão de retenção do produto.

## Provas e limites

Matriz de desktop: `docs/reviews/2026-10-18/desktop-validation/README.md`.
O topo atualizado explica que os ensaios foram arquivados sem aceite de duas horas.
Há capturas reais de cliente e compositor, logs de suíte e falhas preservadas.

Contratos de produção e lacunas: `docs/reviews/2026-10-18/continuacao/`.
Referências detalhadas: `avaliacao-entrega.md`, avaliação de runtime e planos de
17/10 em `docs/reviews`. As instruções originais recebidas estão preservadas em
`docs/handoff/inputs`; não são uma segunda implementação nem aceites já cumpridos.

O novo host deve iniciar com configuração própria e automação desligada.
Planos, grants, PIDs, boot IDs e caminhos antigos não devem ser reativados ou
reescritos para parecerem locais. Backups/diário exportados servem à inspeção e
recuperação explícita; não restaurar sobre dados existentes automaticamente.

## Rotina de qualidade

Um incremento por contrato, teste focado que reproduza a falha, mudança ligada
ao produto, suíte pertinente e registro de evidência. Usar `uv.lock`; atualizar
dependências deliberadamente. Registrar limitações ao lado do resultado.
Evitar novos frameworks, executores paralelos e módulos sem integração.

Antes de encerrar cada rodada: `git diff --check`, revisar o diff, atualizar
esta passagem e apontar a próxima ação objetiva. Commits/PRs devem explicar
problema, comportamento final e validação; não fazer merge sem pedido.

## Recuperação organizada — 2026-10-26

Raiz única neste host: `/home/misael/Projects/Folego`. Checkout existente realocado sem duplicação, base `815cf002248e80e51010191ace556dbaaa2319ce`. Ambientes recriados por `./dev`; núcleo: 916 pass/2 skip; Qt offscreen: 1133 pass/2 skip. Isso não aprova compositor físico nem soak de duas horas. Próxima tarefa continua sendo retenção segura dos temporários administrados; automação permanece desligada.

## Runtime /run/user cheio — 2026-10-28

Caso real: `/run/user/1000` a 100% por `forge-sessions/1bf5a050/audio.raw` (1,5 GB) de uma
sessão BlastEm do SGDKForge cuja árvore foi adotada pelo `systemd --user`. O plano tmpfs
protegia tudo corretamente, mas não dizia por quê nem qual o caminho seguro.

- `folego tmpfs diagnose [--json]` (somente leitura): maiores itens do volume mais cheio,
  maiores arquivos, holders com raiz da árvore e marca de árvore órfã, dono conhecido e
  comando oficial de encerramento (`actions/tmpfs/diagnosis.py`, `OWNER_HINTS`). Não sinaliza.
- `folego tmpfs runtime-size [--vezes N --confirmar]` e controle na aba tmpfs: 1×–4× do tamanho
  atual com teto de 65% da RAM (`core/runtime_size.py`). Aplicar é um único `pkexec` com
  argumentos posicionais: drop-in `/etc/systemd/logind.conf.d/60-folego-runtime-size.conf`
  (`RuntimeDirectorySize`) + remount imediato preservando conteúdo. Fila própria de 180 s para
  a senha; bloqueado enquanto houver resultado desconhecido.
- Validação: `./dev check` 928 + 1149 pass (2 skips cada); CLI real no host mostrou o
  `audio.raw`, o PID 1915399 como árvore órfã e opções 1482/2964/4446/5928 MiB; aba renderizada
  offscreen com dados reais. Não validado: compositor KDE real. O encerramento da sessão SGDKForge pelo `session_coordinator.py stop` não foi
  executado pelo agente (permissão negada); continua pendente com o usuário.
- Aplicação real em 28/10 pelo usuário: `./dev run tmpfs runtime-size --vezes 2 --confirmar`
  levou `/run/user/1000` de 1.554.046.976 para 3.107.979.264 bytes (`df`: 2,9 GB, 1% usado), drop-in
  `/etc/systemd/logind.conf.d/60-folego-runtime-size.conf` com `RuntimeDirectorySize=2964M`;
  os 36 itens do runtime permaneceram. A sessão SGDKForge que enchia o volume foi encerrada pelo
  `stop` oficial; o `audio.raw` dela não existia mais no momento da cópia (corrigido no SGDKForge,
  commit local `e80538de`, push bloqueado pelo registro de recuperação daquele projeto).

## Atalhos de inicialização — 2026-10-28

`src/folego/shortcuts.py`: a cada abertura da GUI (e por `folego shortcuts`) cria o atalho no menu e na
Área de trabalho se faltar, apontando para `run.sh` do checkout (ou o entrypoint instalado); atualiza
somente arquivos com `X-Folego-Managed=true`; preserva atalhos do usuário e symlinks; nunca autostart.
Validação: 8 testes; `./dev check` 936 + 1157 pass (2 skips cada); no host criou
`~/.local/share/applications/folego.desktop` e `~/Área de trabalho/folego.desktop` (válidos no
`desktop-file-validate`), segunda execução `present`, e `gio launch` do atalho da Área de trabalho abriu a
janela real no KDE (instância própria encerrada com SIGTERM).

## Visão padrão redesenhada — 2026-10-28

Padrão comum de painéis de manutenção (o artigo de referência do Medium não pôde ser lido; o usuário
aprovou seguir o padrão): navegação lateral (`SidebarTabBar`, abas West com rótulos horizontais), topo
com medidor de folga (`HealthGauge`: menor fração livre entre memória, swap e tmpfs; veredito e cor do
mesmo relatório de saúde do título) e uma ação principal que só leva à recomendação mais urgente,
cartões por recurso (memória, CPU, swap/zram, temporários; nível em palavra e cor, limiares oficiais),
recomendações com estado vazio e atividade recente com os detalhes da amostra. Nenhum comportamento
de ação mudou; nada novo executa efeito.
Validação: 4 testes novos; `./dev check` 936 + 1161 pass (2 skips cada); janela real no KDE capturada
quatro vezes durante os ajustes (rótulos rotacionados, abas altas e detalhes cortados corrigidos).
Para rodar o gate foi preciso remover 17 workspaces de QA desta sessão (o wrapper recusa com 20
retidos); os 3 anteriores a 28/10 foram preservados.

## Modo widget — 2026-10-28

Botão "⧉ Modo widget" na visão central: abre o controle compacto como widget flutuante (cartão sem
borda, mini medidor, RAM/CPU/Swap/Temp, botão "⤢ Abrir Fôlego" que volta à UI padrão e recolhe o
widget) e recolhe a janela para a bandeja (`hide_window` mantém a garantia de caminho de volta).
O widget nunca recebe foco, fica fora da barra de tarefas e no Wayland usa `startSystemMove`.
Keep-above no Plasma/Wayland não é possível pelo app: `ui/kwin_rule.py` cria, com confirmação, uma
regra do KWin só para o widget (app id `folego`, título exato; acima, sem borda, fora de barra/Alt+Tab,
sem foco, posição inicial no canto inferior direito) via kwriteconfig6 + reconfigure; preserva outras
regras; `folego widget-rule [--remover]`. Recusa fica gravada para não perguntar de novo.
Validação: 10 testes novos/ajustados; `./dev check` 940 + 1170 pass (2 skips cada); execução real no
KDE/Wayland: janela recolhida, bandeja presente, widget visível com dados reais (sem criar a regra).
Pendente: aplicar a regra do KWin no host real (decisão do usuário) e validar keep-above/posição.

## Avaliação do projeto — 2026-10-29

Revisão da base `5575ea06f15103dd28e071b04b6df3ef37c0db81`, igual ao SHA remoto
da branch de continuidade e do PR #1. Pedido de avaliação: nenhum código de
produção corrigido nesta rodada. Arquitetura CLI/core sem Qt, coordenador e
proteções têm cobertura ampla; isso não fecha os contratos dos caminhos novos.

Achados reproduzidos, em ordem de prioridade:

1. **P1 — configuração persistente alterada apresentada como recusa.**
   `core/runtime_size.py:apply_command` substitui o drop-in antes de chamar
   `mount`; uma falha de remount deixa o arquivo novo. Já
   `cli.py:_cmd_tmpfs_runtime_size` converte qualquer retorno não zero em
   `recusa`, sem ID/intenção no coordenador. Prova: corpo do shell executado
   sem pkexec, com todos os destinos em árvore descartável e `mount` simulado
   retornando 32; o drop-in novo permaneceu. CLI simulada retornou `recusa`.
   Correção: integrar no coordenador, preservar estado anterior, registrar as
   etapas e reconciliar configuração persistente e montagem; falha após efeito
   precisa de resultado parcial/desconhecido e recuperação explícita.
2. **P1 — resultado desconhecido permite repetir o resize na GUI.**
   `ui/tmpfs_tab.py:show_runtime_result` ignora `outcome=desconhecido`, mostra
   “runtime não alterado” e solicita opções; a resposta reabilita o botão sem
   preencher `_uncertain_text`. Prova com payload de timeout e atualização
   simulada. Correção: usar o bloqueio de incerteza também neste fluxo, com ID
   estável e reconciliação antes de permitir outra mutação.
3. **P1 — falha ao ler regras do KWin pode desativar regras alheias.**
   `ui/kwin_rule.py:_rules` ignora o código de saída de `kreadconfig6` e usa
   stdout vazio como lista vazia. `install` então grava somente a regra própria
   em `General/rules`; `remove` pode gravar lista vazia. Prova com ferramentas
   simuladas: lista inicial `existing-user-rule` substituída por `folego-widget`
   após erro de leitura. Correção: recusar antes de qualquer escrita quando a
   leitura não for comprovada e preservar a configuração anterior.
4. **P2 — corrida no registro de filhos curtos.** `cli.py:_session_run` inicia
   o comando antes de registrar a sessão; se ele já saiu, `register` recusa o
   zumbi e um comando `exit 0` vira erro 1. A CI do PR #1 já falhou assim
   ([run 40795479345](https://github.com/Misael-art/Folego/actions/runs/40795479345),
   939 pass / 1 fail / 2 skip). Reproduzido localmente atrasando apenas o registro
   de um filho descartável. Correção: coordenar lançamento/registro e término,
   preservando o código real e a proteção dos filhos ainda vivos.
5. **P2 — painel confunde ausência de recomendações com saúde.**
   `core/suggestions.py:suggest` não cobre tmpfs; `DashboardTab._sync_rows`
   apresenta “Tudo dentro do orçamento” sempre que não há sugestões. Provas:
   runtime 100% cheio com medidor “Crítico”, e meminfo ausente com medidor
   “Desconhecido”, ambos com texto de recursos dentro do orçamento. Correção:
   cobrir tmpfs/inodes e derivar o estado vazio do relatório de saúde/frescor,
   com navegação para a aba de temporários.

Verificação no host atual, Python 3.14.7, ambientes existentes do `./dev`,
HOME/XDG privados, temporários em disco e suítes sequenciais:

- `./dev check`: **939 passed, 1 failed, 2 skipped** no perfil headless;
  parou antes de Qt. `test_backup.py::test_roundtrip_property` gerou
  `FlakyFailure`: uma execução levou 328,57 ms (deadline 200 ms) e a repetição
  interna 11,44 ms. Não se alterou deadline/limite nem se aprovou o gate.
- `./dev test`: **1170 passed, 2 skipped**, 30,27 s, Qt offscreen.
- Seis provas isoladas + repetição focada do teste de backup: **7 passed**;
  prova adicional do KWin: **1 passed**. As provas afirmam os comportamentos
  defeituosos observados; não são testes de aceite de uma correção. Backup
  passou na repetição focada; a falha anterior continua registrada.
- Evidência local, descartável e fora do Git: `.scratch/dev-tests/run-_rab54lb`,
  `run-29la1x1v`, `run-4poe65yr`, `run-t9dqu524` (logs/run.json), e
  `run-review-20261029/test_assessment_probes.py` (sete provas). O relato acima
  preserva os resultados no Git. Dois skips de Edge ausente permanecem.
- Revisão documental e `git diff --check`; não se aplicou regra do KWin,
  redimensionamento privilegiado, limpeza ou efeito em processo alheio.
  Compositor físico e soak não foram exercitados nesta avaliação.

Lacunas conhecidas permanecem: retenção dos 256 temporários sem lease/término
comprovado (`safely/jobtemp.py`), plano/ID confirmado no pai para todas as
mutações, prazo total e cancelamento, histórico sem compactação, soak real de
7200 segundos e matriz física de desktop. Próximo incremento recomendado:
fechar os três P1 acima com regressões nos fluxos oficiais, depois a corrida
de sessão/CI e a retenção segura; automação continua desligada.
