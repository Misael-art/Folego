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


## Correções da avaliação e apresentação pública — 2026-10-29

Implementação em `fac2d2b377fa6395885b059cdb50f74d60d68bf7`, sobre a avaliação `2fff195`.
Os cinco achados receberam correção integrada e testes de regressão:

- Resize usa `actions/tmpfs/runtime_size.py`, o coordenador comum e intenção
  durável. A consulta entrega o plano v2 com tamanho exato/ID; a GUI preserva
  esse plano. O filho revalida volume, UID, identidade e capacidade antes do
  efeito, preserva a configuração anterior quando existe e deixa recibo de
  término. Falha após gravar configuração é parcial; falta de prova é desconhecida.
- Timeout conserva o ID no pai, bloqueia repetição e reapresenta operações
  pendentes após reabrir a aba. O botão “Verificar operação pendente” e
  `tmpfs runtime-size --reconciliar ID --json` verificam recibo e estado atual
  sob trava; não executam o resize novamente. Sem recibo comprovado, permanece
  desconhecido. Backups/recibos ficam ao lado do drop-in com sufixos por ID e
  não são removidos automaticamente.
- KWin recusa erro de leitura antes de qualquer escrita e preserva regras
  alheias. A GUI apresenta indisponibilidade em vez de propagar a exceção.
- Sessões registram filhos próprios ainda não coletados mesmo se já encerrados;
  registro avulso de zumbi continua recusado e o código real do comando é preservado.
- Painel recomenda a aba de temporários por ocupação/inodes e diferencia
  ausência de recomendação de ausência de evidência. Pausa/frescor invalidam
  também medidor, cartões e mensagem vazia.

Validação final com Python 3.14.7 e Qt 6.12.0:

- Focados: **135 passed**. Após a revisão final, `./dev check`: **952 passed,
  2 skipped** headless (18,34 s) e **1187 passed, 2 skipped** Qt offscreen
  (29,03 s), sequencialmente. Os skips continuam sendo Edge ausente.
- O teste de backup antes instável passou sem mudança de prazo ou remoção de
  verificação; isso não é uma afirmação de que toda variabilidade de I/O foi eliminada.
- Janela própria no KDE/Wayland real, HOME/XDG privados e dados sintéticos:
  exposição da janela, navegação pelo alerta tmpfs, bloqueio de timeout e
  invalidação de frescor passaram. `./dev gui` abriu em HOME próprio e permaneceu
  por 5 s; somente essa instância foi encerrada com SIGTERM. Nenhum efeito
  privilegiado, regra do KWin ou sinal a processo de trabalho foi aplicado.
- Shell privilegiado testado sem pkexec em árvore descartável, com ferramentas
  simuladas; a aplicação real do novo resize via polkit/remount não foi repetida.
- Logs finais locais: `.scratch/dev-tests/run-g0z90paq` e `run-wd7tp0ii`.
  Evidências adicionais em `run-review-20261029/native-demo` e `official-smoke`.
  Logs/manifestos da primeira rodada e do foco inicial foram preservados nessa
  raiz de revisão antes de remover somente os próprios workspaces regeneráveis
  já concluídos. O limite de revisão de QA permanece 20; revisar retenção antes
  de abrir novas rodadas, sem elevar o teto ou limpar evidência alheia.

Apresentação preparada: README com banner SVG próprio, captura real com dados
sintéticos, instruções, recursos, CLI e limites; licença MIT, metadados SPDX,
avisos de terceiros, guia de contribuição e modelos de issue/PR. Links locais,
SVG e `License-Expression: MIT` do pacote instalado foram verificados. A captura
`docs/assets/dashboard.png` não expõe dados do host.

A publicação pública foi solicitada explicitamente pelo usuário. Revisão local
prévia: 785 blobs históricos (22.418.992 bytes) sem correspondência aos padrões
procurados de chaves privadas, tokens GitHub/OpenAI/AWS e credenciais em URL;
109 capturas rastreadas revisadas por folhas de contato, com inspeção adicional
individual. Isso não é garantia universal de ausência de informação sensível.
A publicação usa a branch de continuidade como padrão para apresentar esta
versão, preservando `main` e o PR #1. Não há merge ou release de produto neste lote.

Continuam pendentes retenção segura dos temporários, demais planos/IDs no pai,
prazo total/histórico e matriz física/soak de duas horas. Automação permanece
desligada. Próximo incremento técnico: retenção com identidade/lease e orçamento,
sem adotar ou apagar diretórios ambíguos.

### Publicação confirmada

Repositório **público** em https://github.com/Misael-art/Folego, licença **MIT**
reconhecida pelo GitHub e branch padrão `codex/portable-handoff-20261024`.
Apresentação e código publicados em `3f770b19dbff7e1b12a1620b4684a4673b3508b8`;
README e as duas imagens conferidos por leitura anônima e igualdade com os
arquivos locais. Descrição e dez tópicos aplicados; PR #1 atualizado e aberto.
CI desse SHA: núcleo sem Qt, Qt offscreen e contratos CLI **success**, tanto
no push quanto no PR; CodeRabbit skipped. Nenhum merge ou release foi criado.
Recibo local: `run-review-20261029/anonymous-publication-verification.json`.

## Avaliação: supervisão da acessibilidade do desktop — 2026-10-29

Pedido novo: Fôlego acompanhar entrada/acessibilidade, espelhar estado por
dispositivo e solicitar reparo manual ou automático, aguardando intervenções
dos outros projetos. Esta rodada avalia viabilidade, dependências e aceite;
não implementa nem ativa um executor novo. A solicitação de automação para
acessibilidade não amplia autorização para limpar dados, sinalizar trabalhos,
parar containers ou habilitar o executor genérico de recursos do Fôlego.

### Estado verificado e fontes oficiais existentes

- Fôlego em `e86d7d2`: há coleta de recursos, adapters somente leitura,
  coordenador, diário e workers; não há monitor ou executor de acessibilidade.
- PhaseZero, código verificado em `83c50a60`: o backend oficial é
  `linux/steamdeck/desktop_session.py`, registrado por
  `~/.config/phasezero/desktop-session.json`; CLI `pz steamdeck input status`.
  Guardião de entrada e watcher do teclado estavam ativos/habilitados na
  consulta. Supervisor `phasezero-controller-desktop.service` não instalado.
- RetroFE mantém propriedade do perfil Steam e atalhos em
  `Tools/launchers/retrofe/steam_desktop_session.py`; seu
  `desktop_environment.py` já delega a política local ao backend registrado
  do PhaseZero. Guardião de recuperação também estava ativo/habilitado.
- Consulta oficial de status retornou processo com exit 0, mas `ok=false`,
  `desktopReady=false`, `ownershipRecovered=true` e `touchscreen=missing`.
  USB observado, dispositivos enumerados pelo KWin habilitados, teclado virtual
  disponível em modo 1 e áudio enumerado sem mute. Enumeração não comprova
  movimento, clique, caractere digitado, toque físico, audição ou fala.

### Lacunas que precedem a automação coordenada

1. **Não existe exclusão mútua comum de reparos.** `guardian.lock` do PhaseZero
   protege instâncias de `watch`; `reconcile`/`capture` não adquirem essa mesma
   trava de operação. RetroFE tem locks próprios de perfil/atalhos, e o
   coordenador do Fôlego protege somente seus participantes. Ler “active” no
   systemd ou conferir lease antes do efeito não elimina a corrida posterior.
2. **Contrato de saúde/propriedade ainda precisa de qualidade explícita.** O
   status do PhaseZero não pode ser interpretado só pelo exit code; leituras
   vazias/indisponíveis e erros ao verificar identidade precisam continuar
   desconhecidos. A leitura booleana `process_alive` existente exige revisão
   de falhas de observação antes de servir como autorização ao Fôlego.
3. **Containers não estão cobertos como donos de dispositivos.** O adapter
   atual do Fôlego lista containers/imagens/volumes, não acesso a `/dev/input`.
   Dispositivo passado ao container continua sendo recurso do host. Identificar
   descritor aberto não prova captura exclusiva; processos/projetos precisam
   cooperar com o mesmo contrato de propriedade.
4. **FTS e login são outro nível.** Touchscreen continua ausente. O reparo FTS
   restrito está no PhaseZero; fallback físico e persistência não homologados.
   Units de usuário em `graphical-session.target` não certificam entrada no
   greeter SDDM. Fôlego aberto depois do login não resolve sozinho bloqueio
   ocorrido antes dele. Usar [systemd.special](https://freedesktop.org/software/systemd/man/latest/systemd.special.html#graphical-session.target)
   e [documentação Docker](https://docs.docker.com/engine/containers/run/#runtime-privilege-and-linux-capabilities)
   como referência desses limites.

### Incrementos e aceite propostos

| Ordem | Integração | Dependência e aceite |
| --- | --- | --- |
| 1 | Monitor somente leitura, CLI e painel Entrada/Acessibilidade | Usar registro do backend, validar schema/owner e orçamento total; representar saudável/degradado/desconhecido/ausente conforme capacidades do host. Pode avançar sem esperar reparo FTS. |
| 2 | Protocolo comum e reparo manual | Estender o backend oficial, sem copiar sua política para Fôlego. Todos os caminhos envolvidos publicam/adquirem lease/trava por domínio/dispositivo. Testar concorrência, falha, filhos vivos, reboot/PID reutilizado e falta de evidência em fixtures. |
| 3 | Supervisão automática limitada, independente da janela | Após o contrato comum: aguardar dono, reler estado, solicitar operação com ID, verificar resultado; cooldown, orçamento, disjuntor e intenção durável. Reconciliar timeout sem retry cego. Serviços existentes não significam que suas GUIs precisem ficar abertas. |
| 4 | Garantia operacional antes do login e transições físicas | PhaseZero é owner do reparo FTS/boot. Validar driver e toque real, SDDM, cold boot, logout/login, suspend/resume, dock/USB, Steam/Big Picture e frontend com emulador filho vivo. Falha física não pode ser aprovada por fixture. |

Fluxo requerido: observar → outro dono reparando/usando → aguardar sem efeito →
adquirir exclusividade e revalidar → intenção → pedir reparo ao owner → testar →
confirmar resultado ou manter parcial/desconhecido. Heartbeat vencido sozinho
não prova abandono. Trava ausente só é autoridade quando todos os writers usam
o protocolo. Nenhum restart global de KWin/Steam/USB nem reset de barramento
compartilhado deve ser usado como fallback automático.

Na interface: cards com ícone **e texto** para Deck/trackpads, toque, teclado
físico/virtual, mouse/controles externos, áudio/microfone; mostrar dono, última
verificação, motivo e estado “aguardando PhaseZero/RetroFE”. Botões “Verificar”
e “Solicitar reparo” usam o mesmo controlador e as mesmas portas de automação,
sem caminho manual que ignore propriedade. Tab/Enter, nomes acessíveis e
feedback sem depender só de cor fazem parte do aceite. Não gravar teclas ou
áudio para manter o monitoramento.

A política observada é teclado automático somente por toque na tela (modo 1),
com atalhos explícitos preservados. O termo “touchpad” no pedido pode significar
trackpad ou touchscreen; esclarecer antes de alterar esse comportamento. O
pedido termina por solicitar avaliação; implementação e ativação não foram
inferidas desta avaliação enquanto essa escolha de escopo estiver pendente.

Verificação desta rodada: leitura do anexo e dos fontes responsáveis,
`systemctl --user show` das quatro units, enumeração do kernel/KWin e CLI
oficial de status, sem gravação de configurações, coleta de teclas, restart,
sinal ou reparo no host. Alteração apenas documental: revisar diff/referências;
não há nova contagem de testes de produto. Próximo passo concreto: incremento
1 e contrato comum do incremento 2, preservando os executores oficiais.

## Implementação: supervisão de entrada independente — 2026-10-29

O usuário aprovou avançar e corrigiu a premissa conjuntural: **PhaseZero pode
não existir no host**. A avaliação acima é histórica; esperar esse projeto
não é pré-requisito de implementação ou operação. Owner: Fôlego para observação,
política e reabilitação restrita de entrada no KWin; os responsáveis externos
continuam donos de seus perfis, drivers e recuperações específicas.

### Incremento integrado

- Nova CLI `accessibility` e sexta aba, cartões com ícone/texto para oito
  capacidades e estado espelhado na central. Coleta por worker, comandos por
  QProcess e dados antigos/incompletos sem aprovação implícita. A central ganhou
  rolagem após a QA Wayland reproduzir altura excessiva com fontes/mensagens
  reais; navegação e controles continuam acessíveis em 800×600.
- Backend nativo Linux/KWin, sem Qt em core/actions/CLI e sem executar caminhos
  do registro de terceiros. Outros desktops e dependências ausentes preservam
  observações possíveis e informam o reparo não suportado. Identidade inclui
  boot, dono único D-Bus/UID, event e chave física; duplicidade protege.
- Único efeito: `enabled=true` de entrada identificada, seguido de leitura.
  Política própria captura somente estados habilitados, preserva desconectados
  e incorpora hotplug saudável. Não altera drivers, Steam, atalhos, perfis,
  áudio, USB, login do sistema, containers ou processos de trabalho.
- Coordenador/diário existentes, intenção durável, ID estável, reconciliação
  sem reaplicar, cooldown 60 s, até três tentativas/h e disjuntor persistente.
  Resultado incerto continua pendente; rearmar exige revisão explícita e
  configuração habilitada comprovada, sem operações pendentes.
- Leases genéricos para aplicações cooperantes, com boot/PID/starttime, filhos,
  slots estáveis e trava comum. Filho vivo/desconhecido e reparador morto
  preservam propriedade/incerteza. Schemas desconhecidos não liberam recursos.
  Docker/Podman presentes são consultados com campos restritos de dispositivos;
  exposição/consulta desconhecida bloqueia. Integrações legadas ativas ou
  desconhecidas aguardam sem serem interrompidas.
- Unit de usuário `folego-accessibility.service`, independente da janela,
  vinculada à sessão gráfica e opcional em instalações novas. A autorização
  específica de monitoramento/ativação foi registrada no AGENTS; não habilita
  o executor genérico de recursos nem arquivamento de fixtures.

Operação, matriz por host, pausa, desinstalação e protocolo estão em
[ACESSIBILIDADE.md](ACESSIBILIDADE.md). O README público distingue claramente
a política de entrada do executor automático de recursos ainda desligado.

### Evidências e limites

- Gate final `./dev check`, Python 3.14.7 gerenciado, HOME/XDG privados,
  suítes sequenciais: **994 passed, 2 skipped em 17,69 s** sem Qt e
  **1236 passed, 2 skipped em 28,37 s** com Qt 6.12.0 offscreen; diff check aprovado.
  Logs/run.json: `run-a1i86z0r` e `run-pooobcvm`. Os dois skips em cada perfil
  exigem Edge real ausente. Regressão final de consultas: 42 testes headless
  focados aprovados em 1,30 s antes desse gate completo.
- Primeira ampliação focada: 79 passed/3 failed. Corrigidos o seam do teste
  da consulta do diário e o piso da janela, sem afrouxar o aceite. A repetição
  passou com 82 testes. A QA nativa posterior encontrou 800×652 com mensagens
  reais: as duas tentativas falhas foram preservadas; rolagem corrigiu a causa.
- QA KDE/Wayland real em HOME próprio: janela exposta em 800×600 e 1280×800,
  navegação da central à aba, foco por Tab, cancelamento sem despacho e
  operação desconhecida impedindo retry. Consulta nativa do host somente
  leitura: KWin, entradas habilitadas e PhaseZero ativo. Launcher oficial
  `./dev gui` sobreviveu cinco segundos em HOME próprio; só seu processo
  foi encerrado. Capturas são do cliente em compositor real, não certificam
  arraste, toque físico ou leitor de tela.
- A regressão de prazo/saída usa exclusivamente consultas e descendentes
  descartáveis. Inclui líder encerrado com filho mantendo pipes: o grupo
  próprio é encerrado antes de reaproveitar/recolher sua identidade.
- Fontes, unidades, diário, orçamento, perda de resposta, PID reutilizado,
  boot anterior, filhos vivos/desconhecidos, containers, host sem PhaseZero,
  backend ausente e hotplug têm testes. Nenhuma entrada física foi desabilitada
  como fixture; nenhuma unit de terceiro foi reiniciada.

Evidência local privada em `.scratch/dev-tests/run-review-20261029/`:
`accessibility-native-3/{report.json,launcher-report.json,activation.json}` e
capturas; tentativas 1/2 e logs/run.json anteriores permanecem identificados.
Só gerados próprios concluídos e revisados foram removidos após preservar logs,
para respeitar o teto de vinte workspaces; guardas não foram ampliadas.

### Ativação autorizada neste host

Executados `./dev run accessibility enable --confirmar --json` e
`./dev run accessibility install --confirmar --json`. A unit do Fôlego foi
verificada `enabled`, `active/running`, status 0, com heartbeat recente e zero
reinícios observados. Política habilitada, baseline vazio e nenhuma operação
pendente: ciclo **waiting**, aguardando o PhaseZero ativo. Isso confirma a espera,
não comprova reparo físico ou transição após reboot. Não foram parados os
guardiões existentes, e o executor automático de recursos continua desligado.

A exclusividade só existe entre participantes do protocolo. Aplicações
não cooperantes podem intervir após a leitura; inventário não cobre todos os
descritores, capturas exclusivas ou daemons remotos. Não declarar garantia
universal de acessibilidade. FTS ausente, boot/SDDM, login/logout, suspensão,
dock, atalhos Steam, leitor de tela e soak contínuo de duas horas continuam
pendentes. Próximo passo: integrar writers interessados ao protocolo e validar
essas transições no alvo físico, sem desligar entradas de trabalho para testes.

### Fechamento e publicação

Implementação, testes e documentação publicados no commit
`02db56c8d7399ddb3e8ba546f66358ec01f9f73f`, na branch padrão de continuidade
`codex/portable-handoff-20261024`; SHA remoto conferido. Repositório público e
licença MIT novamente confirmados. [PR #1](https://github.com/Misael-art/Folego/pull/1)
reutilizado, aberto e atualizado com o comportamento final e seus limites.
CI desse SHA: núcleo sem Qt, Qt offscreen e contratos CLI **success** no push
e no PR; CodeRabbit/Sourcery **skipped**. Nenhum merge ou release.

Após atualizar o código de consultas, somente a unit do Fôlego foi reiniciada
para carregar a versão validada. Consulta final: `enabled`, `active/running`,
`ExecMainStatus=0`, `NRestarts=0` (reinícios por falha), heartbeat recente,
política habilitada, ciclo `waiting` pelo PhaseZero e nenhuma operação pendente.
Diário do host: **zero intenções de reparo de acessibilidade**. O fechamento
subsequente altera apenas este registro, sem mudar o código testado.
