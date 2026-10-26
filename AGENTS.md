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

## Coleção Projects: continuidade e organização

- Este projeto tem um único checkout ativo por componente, sob a raiz de projetos escolhida pelo proprietário. Neste host, use somente `/home/misael/Projects/Folego`. Resgates antigos são arquivos de consulta, não outros ambientes de desenvolvimento.
- Leia também as instruções do diretório pai e o registro central `.workspace/projects.json`, quando presentes. A instrução atual de raiz única prevalece sobre sugestões históricas de criar clones ou worktrees por agente/tarefa. Não crie worktrees nem variantes paralelas sem pedido explícito do usuário.
- Preserve alterações locais. Faça mudanças pequenas no checkout existente, valide, revise arquivos/segredos/tamanho, faça commit e push do lote autorizado e confira o SHA remoto antes de declarar sincronização. Não faça stage global de material resgatado, push forçado ou merge automático de pesquisas.
- Mantenha código, documentos e receitas no Git. SDKs, caches, dependências, builds, ROMs, bancos, pacotes de migração, sessões e dados privados usam os destinos próprios, com manifestos e recuperação verificável; `.gitignore` não é backup. Novo arquivo acima de 10 MiB exige revisão e armazenamento apropriado.
- Continue autonomamente até a entrega verificável. Evite confirmações rotineiras e relatos de pequenos avanços. Interrompa apenas o que depender de informação, acesso ou autorização indispensável; registre causa e próxima ação, mantendo as partes independentes em andamento.
- Resgate e testes históricos não aprovam funcionamento neste host. Preserve critérios e evidências de cada produto. A autorização de continuidade não permite publicar conteúdo privado em repositório público nem fazer merge/release/deploy do produto.
