# Runtime — implementação e verificação de 18/10/2026

Continua a entrega anterior; não substitui a avaliação nem certifica I1–I6.
Referência: [requisito runtime/KDE](../runtime-sessao-kde.md).

## Entregue e integrado

- `core/runtime.py`: descoberta por XDG_RUNTIME_DIR ou UID real; valida caminho
  absoluto, ancestrais sem symlinks, dono e modo 0700. Não muda runtime da sessão.
- `core/tmpfs.py`: watch-list padrão deixa de fixar UID 1000; runtime inválido ou
  statvfs negado fica representado como desconhecido. Cada volume tem qualidade,
  erro e identificação de runtime; inodes não suportados têm percentual `null`.
- Coletor propaga falhas de capacidade como fonte parcial. HealthEngine considera
  bytes/inodes esgotados e pressão do runtime; central, compacto e título/bandeja
  mostram o risco de aplicativos não abrirem. Aba tmpfs não apresenta números
  inventados ou tendência a partir de leitura falha.
- `safely/jobtemp.py`: novo diretório privado por execução, em monte não-RAM
  verificado, com piso de 64 MiB/16 inodes conhecidos e recusa ao atingir 256
  entradas retidas. TMPDIR e PYTEST_DEBUG_TEMPROOT separados; run.json identifica
  preparação, UID, pai e ambiente herdado. Não certifica término nem concede lease.
- `TuneJobs` e `session run` usam o preparador antes de iniciar o filho. Falha de
  preparação recusa sem iniciar. Configuração PhaseZero é lida sem executar shell;
  TMPDIR persistente explícito tem prioridade. Nenhum perfil é reescrito.
- `doctor` distingue ambiente herdado antigo de configuração de novos filhos.
  Não afirma ter alterado o ambiente de processos já abertos.
- `holders`: readlink individual negado torna o índice parcial. Opção explícita
  `include_process_refs=True` inclui cwd/maps (inclusive mapeamento sem fd),
  testada com proc sintético; ela ainda não foi ligada à decisão de remoção
  legada. O scanner padrão de liberação continua apenas fd: bloqueador registrado.
- CI agora fornece TMPDIR/PYTEST_DEBUG_TEMPROOT explícitos, fora de `base`.

## Evidência

`.scratch` verificado via `findmnt`: /home, btrfs, cerca de 54 GiB disponíveis.
Não foi usado o runtime real como destino de pytest. Python 3.14.7; Qt offscreen.

| Execução | Resultado |
|---|---|
| Foco inicial runtime/tmpfs/coletor/health/sessões/jobs/holders | 70 passed in 2.30s |
| Suíte intermediária | 1044 passed in 21.87s |
| Suíte após novas regressões | 1048 passed in 22.46s |
| Suíte final | **1049 passed in 28.50s**, `runtime-suite.log` |
| Venv sem Qt (`.scratch/i0-headless`) | **850 passed in 17.85s**, `runtime-headless.log` |

Testes novos em `test_runtime_protection.py` e `test_health_engine.py` cobrem
runtime de UID diferente, dono/modo/link inválidos, capacidade negada, bytes e
inodes esgotados, inodes sem suporte, fd opaco, cwd/maps, destino RAM, limite de
retenção, configuração PhaseZero versus ambiente antigo. `test_cli_sessions.py`
e `test_ui_tune_jobs.py` verificam o ambiente observado por filhos reais criados
pelo teste e a finalização do QProcess. Nenhum processo de trabalho é sinalizado.

Durante o desenvolvimento houve falhas de fixture (tabela sintética omitia o
monte RAM e um assert foi inserido no teste errado); ambas corrigidas. Uma
execução preparou um diretório vazio sob o caminho PhaseZero real ao ler a
configuração do host. Só esse run identificado foi removido, após verificar
manifesto e diretórios vazios. A prioridade do TMPDIR explícito foi corrigida e
os testes de configuração agora usam HOME e mounts descartáveis.

Reprodução:

```bash
rtk proxy bash -c '
qa_tmp=$(mktemp -d "$PWD/.scratch/runtime-pytest-XXXXXX")
mkdir -p "$qa_tmp/general" "$qa_tmp/pytest-root"
env TMPDIR="$qa_tmp/general" PYTEST_DEBUG_TEMPROOT="$qa_tmp/pytest-root" .venv/bin/python -m pytest -o addopts= --basetemp="$qa_tmp/base" -q
'
```

Para headless, substituir o Python por `.scratch/i0-headless/bin/python` e
adicionar `--without-qt`. Não reexecutar a sonda histórica C09 que injeta escrita
concorrente dentro de `_write`: ela espera sua própria trava no contrato atual.

## Aceite I2R/R1–R5 e pendências concretas

**R1 parcial:** diagnóstico integrado, falhas explícitas e alertas por bytes e
inodes. Falta identidade de mount/boot no snapshot do volume, crescimento por
runtime e orçamento medido de coleta. A descoberta não prova segurança para
mutação; é somente leitura. Falta atualizar frescor sem novas amostras (I2).

**R2 parcial:** prevenção efetiva em session run e QProcesses, testada com filhos.
Ainda faltam transação entre preparações concorrentes, orçamento total de bytes,
retenção/recuperação por ciclo de vida, boot/starttime e associação durável à
sessão no manifesto. O teto de entradas é preflight conservador, não quota de
kernel. Preparação de diretórios é síncrona; medir/mover I/O fora da GUI continua
necessário em I2. Não há adoção automática ou remoção desses diretórios.

**R3 não concluído:** não existe adaptador de raízes pytest registradas nem ação
de arquivamento. Fixtures legadas continuam fora da allow-list; current, locks,
mounts, exclusões e escritores precisam revalidação em todas as fronteiras.

**R4 não concluído:** nenhum novo arquivador/worker de emergência ou executor
automático foi habilitado. Dependências I1/I2 continuam abertas, inclusive grants
fechados/revogação/plano imutável. Não houve uso de reparo-terminal.sh.

**R5 parcial:** mensagem de risco integrada à central/compacto/título; não há
resultado de recuperação porque nenhuma ação nova de arquivamento existe.
As seis sondas originais ainda não foram todas convertidas: segurança de
pytest-current e arquivamento permanece pendente, sem simular aceite por falta
de uma rota de remoção.

F0/F1 mantêm entregas anteriores; F2 bloqueador, F3 ampliado mas parcial,
F4/F5 parciais, F6 desligado/sem controlador completo, F7 somente inventário
parcial, F8 com CI local testada mas sem instalação GUI limpa/soak prolongado.
Nenhuma validação real de compositor, unidade transitória, namespace tmpfs,
instalação wheel, screenshots ou acessibilidade foi realizada nesta retomada.
