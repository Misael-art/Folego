# Evidências da conferência — 18/10/2026

Estas evidências correspondem ao working tree identificado por [checkout.json](checkout.json), não apenas ao HEAD. São o estado **anterior às próximas correções**, e não devem ser reescritas para aparentar que a entrega anterior estava verde.

| Arquivo | Conteúdo |
|---|---|
| [suite-completa.log](suite-completa.log) | Saída completa da execução: 1 falhou, 1.019 passaram, 31,40 s |
| [regressao-painel.log](regressao-painel.log) | Mesma falha reproduzida isoladamente, 0,66 s |
| [ci-sem-qt.log](ci-sem-qt.log) | Trecho da coleta com a seleção atual da CI, bloqueando imports de Qt; lista extensa de testes omitida |
| [sondas.json](sondas.json) | Resultados observados dos cenários isolados do coordenador, grants, planos, configuração e inventário |
| [reproduzir.py](reproduzir.py) | Script para repetir as sondas, usando somente executores/runners falsos e estado temporário |
| [checkout.json](checkout.json) | Data UTC, HEAD, versões e SHA-256 de 182 arquivos da entrega examinada |

## Comandos e isolamento

A suíte completa foi executada da raiz do repositório, com Python do venv e `--basetemp` exclusivo em `.scratch`. Log original: `.scratch/continuity-review-39QoL5/pytest.log`.

```bash
rtk proxy bash -c '
review_dir=$(mktemp -d "$PWD/.scratch/continuity-review-XXXXXX")
.venv/bin/python -m pytest -o addopts= --basetemp="$review_dir/pytest" -q > "$review_dir/pytest.log" 2>&1
result=$?
tail -70 "$review_dir/pytest.log"
exit "$result"
'
```

A reprodução isolada usou o mesmo comando pytest, com outro basetemp e o alvo:

```text
tests/test_ui_dashboard.py::test_a_removed_suggestion_row_returns_hidden_to_the_pool
```

As sondas podem ser repetidas com:

```bash
rtk proxy .venv/bin/python docs/reviews/2026-10-18/evidencias/reproduzir.py
rtk proxy .venv/bin/python docs/reviews/2026-10-18/evidencias/reproduzir.py --ci-sem-qt
```

O segundo comando faz **apenas coleta**, reproduzindo a seleção literal de arquivos do job `pure`. Um import finder faz PySide6/shiboken6 parecerem ausentes; não desinstala nada. Isso prova a falha de seleção/importação, mas **não é instalação limpa nem execução remota da CI**. Na reprodução original, o mesmo código de seleção/bloqueio foi executado inline; esta opção do script o torna reutilizável.

As sondas comuns criam um diretório temporário em `.scratch` e o removem ao terminar. Nenhuma chamada sinaliza processo, altera temporários de aplicações, consulta Docker/Podman/libvirt ou modifica HOME/XDG real. Os efeitos são listas Python e arquivos descartáveis de diário/configuração. Os cenários de espera/revogação usam contexto controlado, sem esperar uma trava real: testes de integração interprocessos devem complementar a correção.

O script imprime o comportamento observado e sai normalmente; não é uma suíte que só passa se os bugs continuarem presentes. Após correções, o próximo agente deve criar testes normais das invariantes e guardar novos resultados em outro registro.

## Complemento: incidente do runtime da sessão

Adicionado depois da conferência inicial, a pedido do usuário:

- [Leitura do host e recibo do reparo anterior](runtime/host-leitura.json): `statvfs`, identificação do mount, variáveis TMPDIR/PYTEST_DEBUG_TEMPROOT do processo e do ambiente exportado pelo systemd; somente leitura. Não inclui o restante do ambiente nem segredos.
- [Sondas do caso runtime](runtime/sondas.json) e [script](runtime/reproduzir-runtime.py): política, inodes, UID diferente, falha de statvfs, readlink negado e mudança de pytest-current. O último cenário usa somente árvore sintética em `.scratch`, importando o reparo externo identificado pelo hash; não chama `repair()` nem escaneia processos reais.
- [Testes focados](runtime/testes-focados.log): **136 passed in 1.26s**, não uma nova execução da suíte completa.

Reprodução das sondas:

```bash
rtk proxy .venv/bin/python docs/reviews/2026-10-18/evidencias/runtime/reproduzir-runtime.py
```

Comando dos testes (ambiente temporário explicitamente no disco, além de basetemp exclusivo):

```bash
rtk proxy bash -c '
runtime_qa=$(mktemp -d "$PWD/.scratch/runtime-tests-XXXXXX")
mkdir -p "$runtime_qa/tmp" "$runtime_qa/pytest-root"
env TMPDIR="$runtime_qa/tmp" PYTEST_DEBUG_TEMPROOT="$runtime_qa/pytest-root" .venv/bin/python -m pytest -o addopts= --basetemp="$runtime_qa/base" -q tests/test_health_engine.py tests/test_tmpfs_holders.py tests/test_tmpfs_policy.py tests/test_tmpfs_inventory.py tests/test_tmpfs_plan.py tests/test_tmpfs_release.py tests/test_collector.py
'
```

Antes da execução, `findmnt -T "$PWD/.scratch" -n -o TARGET,FSTYPE` confirmou `/home btrfs`. O reparo externo não foi alterado. Seus 15 testes históricos foram relatados pelo usuário, não reexecutados nesta avaliação.

## Limites da conferência

Não houve correção de produção nesta revisão. Não se executaram ações de limpeza do host, daemons reais, instalação limpa, publicação ou commit. Nenhuma medição nova de compositor, acessibilidade, consumo prolongado ou desempenho em produção foi produzida. As conclusões sobre esses tópicos na avaliação são inspeção e critérios para a continuidade.
