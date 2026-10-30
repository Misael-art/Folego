# Instruções portáteis para agentes

Comece por `README.md`, `docs/HANDOFF.md`, `docs/DIAGNOSTICO-2026-10-24.md`
e `docs/NOVO-HOST.md`. Esses arquivos descrevem a situação atual; os registros
de 17/18 de outubro preservam o histórico e não devem ser lidos como aceite total.
Este projeto não depende do HOME, disco, venv, serviços ou skills do host anterior.

## Ambiente e verificação

- Linux, Python 3.14.7 e Qt/PySide6. Use `./dev`, que instala ferramentas em
  `.dev/`, usa `uv.lock` e mantém ambientes GUI/headless separados. Não use o
  Python do sistema, `pip --user`, `sudo pip` ou o antigo `.venv` para desenvolver.
- `./dev setup --system-deps` prepara também bibliotecas nativas suportadas;
  `./dev system-deps` apenas mostra o plano. Não executar instalações privilegiadas
  no host atual para repetir uma prova já disponível.
- `./dev test-headless`, `./dev test`, `./dev check`: suítes sequenciais, HOME/XDG
  privados, Qt offscreen e temporários exclusivos em disco. Não usar `/run/user`
  como TMPDIR, compartilhar basetemp ou rodar duas suítes completas em paralelo.
- Se `rtk` existir, prefixe comandos shell com `rtk`/`rtk proxy`; sem ele, use
  os comandos diretamente. Não é necessário instalar RTK para executar o wrapper.
- Não instalar ferramentas ou serviços globais por conveniência. Não alterar
  perfis de shell, limpar diretórios do usuário, habilitar autostart ou automação.
  `.dev` e `.scratch/dev-tests` têm limites de revisão; nada é apagado automaticamente.
- Pedido posterior de 29/10–30/10: **início com a sessão ligado por padrão**, com
  opção persistente na GUI/CLI para desligar. Autoriza o autostart do Fôlego e
  do seu monitor de entrada, preservando arquivos pessoais. Não amplia grants.
  Autoriza também retenção dos temporários gerados pelo próprio Fôlego, somente
  com identidade/encerramento e referências comprovados, em destino persistente
  limitado; preservar payloads, legados e estados incertos. Não adotar fixtures
  pytest, limpar caches compartilhados ou interromper a sessão física para QA.

## Contratos do produto

- `core`, `actions` e CLI não importam Qt. Widgets apresentam estado e pedem
  operações; sinais e I/O pesado saem do loop gráfico por workers.
- Ausente, parcial, ilegível, antigo e schema desconhecido não viram vazio,
  seguro, livre ou abandonado. Falta de evidência protege e bloqueia o efeito.
- Intenção durável antes do efeito, IDs estáveis e consulta/reconciliação.
  Resultado incerto não significa que nada ocorreu e não permite retry cego.
- Boot/starttime/pidfd, sessões `keep_active`, exclusões, ancestrais e propriedade
  precisam ser revalidados no ato. Idade, nome, PPID=1 e CPU baixa não autorizam sinal.
  SIGTERM exige acompanhamento; SIGKILL é manual, separado e confirmado.
- Projetos, Git, credenciais, bancos, modelos, volumes e discos virtuais são
  protegidos. Cópias de tmpfs exigem destino persistentemente comprovado, espaço,
  staging, verificação e recuperação. Preservar origem ou cópia certificada.
- Preset não amplia grant. Manual/Assistido/Automático são modos distintos.
  Executor automático e arquivamento de fixtures continuam desligados.
- Exceção autorizada em 29/10: supervisão automática **de entrada**, com política
  própria e unit `folego-accessibility.service`. Reabilitar somente entradas
  identificadas previamente habilitadas no KWin, por diário/coordenador,
  revalidação, orçamento e disjuntor. PhaseZero não é dependência; owners
  opcionais ativos/desconhecidos protegem o recurso. Não ampliar para drivers,
  Steam, áudio, boot, limpeza ou sinais. Testes de efeito continuam descartáveis.
- Testar efeitos só em árvores descartáveis e filhos criados pelo próprio teste.
  Nunca encher runtime real, sinalizar agentes/daemons de trabalho ou recriar
  serviços UUID para produzir evidência.

## Organização do desenvolvimento

1. Escolha uma pendência de `docs/HANDOFF.md`; reproduza o contrato que falha.
2. Entregue um incremento integrado em CLI/GUI quando aplicável; evite módulos
   sem chamada de produção e reescritas amplas antes de estabilizar contratos.
3. Rode o teste focado e a suíte pertinente. Registre comando, ambiente, contagem,
   evidência e limitações. Não ampliar limites para transformar uma falha em verde.
4. Atualize a passagem e faça commits pequenos e descritivos. Não descartar o
   working tree com reset/clean/checkout em massa. Preserve alterações existentes.
5. Offscreen não certifica compositor. Um loop acelerado não prova horas reais.
   Tentativa interrompida não é aprovada; não somar durações de tentativas.

A entrega de migração autorizou commit, push e PR; não autorizou merge,
publicação de release do produto, autostart ou ações automáticas no host.
A solicitação posterior de 29/10 autoriza exclusivamente o monitor de entrada
descrito acima e sua persistência na sessão do usuário; as demais proibições
permanecem.

## Coleção Projects: continuidade e organização

- Política comum: [../AGENTS.md](../AGENTS.md), especialmente autonomia, testes, GitHub e recursos (§§5–10); raiz/branch em [registro central](../.workspace/projects.json). A orientação atual de raiz única substitui recomendações históricas de criar worktrees/clones por tarefa; os contratos técnicos e gates deste projeto permanecem obrigatórios. Em outro host, preserve este mesmo método em um único checkout registrado, sem recriar caminhos antigos.
- Antes de implementar, leia `README.md`, `docs/HANDOFF.md` e `docs/DIAGNOSTICO-2026-10-24.md`, identifique causa, owner, dependências e aceite. Procure a solução oficial existente e integre nela; não introduza soluções concorrentes, aliases ambíguos ou refatorações fora do pedido. Neste host, a única raiz é `/home/misael/Projects/Folego`.
- Execute o lote até implementar, testar, revisar e preservar a continuidade. Resolva decisões reversíveis pelo contexto; não pare em planos nem peça confirmação para editar/testar o que já está autorizado. Comunique descobertas, bloqueios e entrega, sem narrar cada comando ou pequeno avanço.
- Antes de operações pesadas, confira espaço do destino, RAM e carga; estime saídas e retenção. Reutilize ferramentas/ambientes compatíveis, limite jobs e encerre somente processos temporários próprios. Não mate trabalhos alheios, limpe caches compartilhados ou apague evidência para obter um gate verde.
- Ferramentas, Python e ambientes ficam em `.dev/`; QA em `.scratch/dev-tests/`, com limites do wrapper. Reutilize `./dev`; rode `./dev check` sequencialmente quando pertinente. Preserve a distinção GUI/headless.
- Faça os checks pertinentes a toda alteração; para documentos, revise diff, referências e coerência. Para código, cubra comportamento/regressão e execute os gates aplicáveis, sem desativá-los. Para alterações de GUI/launcher, percorra o fluxo no KDE/Wayland real disponível, em sessão própria. Qt offscreen valida contratos, sem aprovar o compositor, arraste físico ou soak de duas horas. Teste efeitos somente em filhos/árvores próprios; automação do produto permanece desligada.
- Reutilize a autenticação válida e os helpers existentes. Nunca peça senha/token no chat, copie sessões ou grave credenciais em código/log. Se faltar acesso indispensável, solicite uma única ação pelo fluxo oficial, preserve o estado e avance no trabalho independente; não repita permissões já concedidas.
- Confira remoto, PRs e checks do SHA antes do lote e ao publicar; reutilize o PR da mesma branch/objetivo. Revise arquivos explícitos, segredos e tamanho, faça commit/push do incremento autorizado e confirme o SHA remoto. Sem stage global de resgates, push forçado, merge de pesquisas ou publicação de dados privados. Não faça polling contínuo de CI.
- PR cabe ao incremento revisável; release somente a marco elegível com versão/artefatos/notas e gates completos, dentro da autorização de publicação vigente. Não gerar release por manutenção destas regras. Preserve limites de merge/deploy e falhas preexistentes; acesso autenticado não amplia autorização.
- Fontes e receitas ficam no Git; bancos, ROMs, assets privados, SDKs, builds, caches e pacotes de resgate seguem owner/destino próprios e recuperação verificável. `.gitignore` não é backup. Novo arquivo acima de 10 MiB exige revisão; downloads acima de 70 MB são manuais, inclusive o pacote dividido, com origem/tamanho/hash/destino preparados.
- Ao fechar, mantenha apenas os gerados necessários e atualize o handoff existente com SHA, testes no host, limites de validação, bloqueio e próximo passo. Não declare produto pronto quando faltar evidência do alvo real, nem deixe um único exemplar de trabalho útil sem proteção identificada.
