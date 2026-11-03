# Revisão de disco vinculada e inventário de fixtures

## Integrado nesta retomada

**Disco, fluxo manual:** `disk plan --json` entrega um ActionPlan v2 para cada
item cuja revisão terminou. A GUI confirma esse snapshot e envia exatamente
seu JSON/ID ao filho (`--reviewed-plan`); não inventa outro plano depois do
consentimento. Expiração pede nova análise. Cliques repetidos durante a operação
geram no máximo um job. Repetir o mesmo plano concluído consulta o resultado,
com `queried=true`, sem mover outro objeto. Confirmação não cria grant.

`actions/disk/review.py` registra device/inode, ancestrais, mount ID/registro e
digest de metadados da árvore inteira. Recusa ao ultrapassar 10.000 entradas ou
dois segundos, ao encontrar montagem descendente, symlink, objeto especial,
outro dono ou nomes/extensões protegidos (Git, credenciais, bancos/modelos e
discos virtuais reconhecidos). Campos de revisão incompletos não viram identidade
comprovada. Item recusado deixa de entrar no total recuperável do JSON.

A ponte comum aceita o plano revisado e verifica ação, identidade e parâmetros.
Sem plano externo, a porta de quarentena faz a mesma revisão; falha entra como
recusa, sem mover conteúdo. Domínio revalida depois da preparação e imediatamente
antes do rename; verifica device/inode do objeto retido depois do rename.
Alteração após escrita do manifesto mantém origem viva e linha planejada,
reconciliável pelo mecanismo existente.

**C01, apresentação:** todos os handlers mutantes de disco/tmpfs, incluindo o
reparo disparado pela listagem, respeitam o veredito desconhecido/falha do motor
mesmo quando o domínio observou sucesso. Falha de registro final retorna código
5, ID e efeitos reais; JSON não sobrescreve o motivo com “ok” do domínio.
Testes realmente movem bytes em árvores descartáveis e injetam ENOSPC/EACCES no
registro final; verificam cópia preservada e intenção sem resultado.

**Runtime, inventário somente leitura:** novo adaptador `pytest-fixtures`,
integrado em `ecosystem`, descobre exclusivamente
`<runtime-validado>/codex-desktop/tmp/pytest-of-<usuário-do-UID>`.
Não amplia a allow-list de limpeza de `/run/user`. Distingue fixture atual,
lock presente, referências fd/cwd/maps, legado para revisão e referências opacas.
Roots simbólicos ou de dono/permissão desconhecidos recusam inventário.
Enumeração limitada a 256 entradas; incompletude aparece como erro.
Todas as fixtures continuam `protected=true`, `automatic_eligible=false` e
`root_registered=false`: descoberta por convenção não é adoção administrada.
Não existe método de arquivamento/remoção nesse adaptador.

```bash
folego ecosystem --adapter pytest-fixtures --json
folego disk plan --json
folego operation ID --json
```

## Evidência e reprodução

- 74 testes iniciais de CLI/GUI/coordenação/disco passaram.
- 140 testes de disco/tmpfs passaram após revisão e apresentação incerta.
- 74 testes focados do inventário/revisão/frontend passaram.
- Suíte intermediária: 1088 passaram em 24,62 s.
- Suíte posterior: 1091 passaram em 23,05 s.
- Houve falha intermitente de prazo do Hypothesis no teste de backup durante
  execução concorrente de suítes: 314,46 ms versus prazo de 200 ms; repetição
  interna mediu 10,76 ms. Log preservado em `review-headless-deadline.log`.
  Teste isolado passou em 1,29 s; não se alteraram prazo nem assertions.
- Suíte sem Qt sem outra suíte completa concorrente: 889 passaram em 17,93 s.
  O teste de projeto protegido foi acrescentado depois dessa execução; resultados
  finais estão no progresso e nos logs desta entrega.

Verificações de efeitos estão em `test_cli_disk.py`, `test_cli_tmpfs.py`,
`test_disk_coordinated.py`, `test_disk_review.py`, `test_ui_disk_tab.py` e
`test_pytest_fixture_adapter.py`. Incluem inode/árvore/montagem alterados,
prazo vencido, metadados mudados antes do rename, retorno pelo mesmo ID,
projeto Git protegido e bytes preservados sob falha de registro.

Capturas do frontend Qt real, com dados de fixture e cancelamento obrigatório:
[plano](review-images/disk-plan.png), [revisão](review-images/disk-review.png).
QA visual encontrou corte inicial de texto no QMessageBox; largura mínima foi
ajustada e o diálogo completo foi recapturado/inspecionado. Botões em português,
cancelamento por padrão e validade em hora local. Reprodução:

```bash
rtk proxy bash -c '
qa_tmp=$(mktemp -d "$PWD/.scratch/review-visual-XXXXXX")
mkdir -p "$qa_tmp/general" "$qa_tmp/pytest-root"
env TMPDIR="$qa_tmp/general" PYTEST_DEBUG_TEMPROOT="$qa_tmp/pytest-root" .venv/bin/python tools/verify_disk_review.py --output "$qa_tmp/images"
'
```

Suíte: mesmo preparo de diretórios, seguido por
`.venv/bin/python -m pytest -o addopts= --basetemp="$qa_tmp/base" -q`.
Headless: `.scratch/i0-headless/bin/python` e `--without-qt`.
`.scratch` foi verificado em btrfs, não no runtime. Nenhuma saturação do host,
limpeza de recursos do usuário, daemon, autostart, commit ou publicação.

**Estado final verificado:** 1092 passaram em 23,82 s (`review-suite.log`);
890 passaram sem Qt em 14,99 s (`review-headless.log`). `git diff --check` passou.
Depois da repetição do prazo, a suíte sem Qt revelou limite AF_UNIX em basetemp
longo (`review-headless-path-limit.log`). A fixture agora vincula o socket real
na mesma árvore descartável por um alias curto de directory-fd em `/proc/self/fd`;
não usa runtime real e mantém assertions de tipo/dono/tamanho. Suíte final passou
sem alterar os testes de integridade ou os prazos de Hypothesis.

O relatório textual de `disk plan`, assim como o JSON, exclui da estimativa
recuperável os itens recusados na revisão. A etapa de revisão não autoriza grants
nem inicia execução; os efeitos continuam dependentes de confirmação manual.

## Aceites ainda abertos

- **I1/C04 parcial:** quarentena agora vincula revisão/confirmação/execução e ID.
  Restore/purge/tmpfs/ajustes/processos ainda precisam o mesmo fluxo.
  Snapshot/rechecagem não fornece lease contra escritores novos; a janela
  entre a última revalidação e rename não é exclusão cooperativa. Check posterior
  não é rollback universal. Não habilitar automação a partir dessa evidência.
- **C01 ampliado:** apresentação CLI verificada com efeitos reais descartáveis;
  matriz completa de interrupção/reconciliação por ID ainda pendente.
- **C03:** orçamento/frequência entre execuções por grant ainda falta.
- **I2R/R3 parcial:** catálogo legado integrado somente leitura; raízes ainda
  não registradas/adotadas, sem ciclo de vida/lease, exclusões e autorizações
  suficientes para arquivamento. Troca de pytest-current foi testada por nova
  leitura, sem alegar proteção de um arquivador inexistente.
- **R4 não habilitado**, R1/R2/R5 mantêm limites da entrega anterior. C05,
  C08, C11, C13 e acesso conjunto do desktop continuam pendentes.
- Capturas offscreen em 800×600/escala padrão não certificam KDE/X11/Wayland,
  DPI 150/200%, hotplug ou leitor de tela. Soak prolongado e instalação limpa
  permanecem pendentes.

F0/F1 preservados; F2 bloqueador; F3 parcial; F4 com fluxo de quarentena
integrado; F5 parcial; F6 desligado/sem controlador completo; F7 inventários
somente leitura; F8 ainda sem aceite integral. Nenhuma automação foi ligada.
