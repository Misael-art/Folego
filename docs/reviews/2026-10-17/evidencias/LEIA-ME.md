# Evidências da revisão do Fôlego

Revisão realizada em 17 de outubro de 2026, com código no commit `61179f55123b44a996aa6087d124474eb5e84b1e`. Python observado: 3.14.7; PySide6: 6.11.2. Os imports de `folego` e `folego.cli` foram conferidos e apontam para `src` deste checkout.

## Suíte existente

Primeira execução:

```bash
rtk proxy .venv/bin/python -m pytest -q
```

Resultado: 552 sucessos e 1 falha, entre 553 testes. O teste `test_the_mutation_seams_default_to_the_ssd_not_ram`, em `tests/test_cli_tmpfs.py`, rejeitou a fixture criada pelo pytest sob `/run/user/1000/codex-desktop/tmp`. Ele deduz o tipo de armazenamento pelo prefixo do caminho, mas o `fake_home` também é temporário. Esse resultado deve ser registrado como dependência ambiental do teste; a possibilidade de XDG real residir em tmpfs é um problema separado, descrito em R12.

Segunda execução, com diretório exclusivo pertencente ao ensaio:

```bash
rtk proxy bash -c 'qa_tmp=$(mktemp -d "$PWD/.scratch/review-pytest-XXXXXX"); .venv/bin/python -m pytest -o addopts= --basetemp="$qa_tmp" -q'
```

Resultado observado: `553 passed in 9.64s`. Não houve alteração de código ou teste entre essas execuções. O diretório de teste não é um diretório existente do usuário escolhido para limpeza: foi criado especificamente para este comando.

## Diagnósticos adicionais

```bash
rtk proxy .venv/bin/python docs/reviews/2026-10-17/evidencias/reproduzir.py
```

O script cria uma árvore descartável em `.scratch`, usa fixtures de dados e Qt offscreen e grava os resultados nesta pasta. Não consulta inventários de arquivos reais do usuário, não executa limpeza real nem envia sinais a processos do host. A tentativa de subprocesso usa um executável inexistente dentro da árvore descartável.

| Verificação | Resultado observado |
|---|---|
| Pasta antiga com descendente novo | Selecionada pelo plano legado de exclusão |
| `/proc` inexistente para holders | `proc_count=0`, mas elegibilidade verdadeira na política com os demais critérios satisfeitos |
| Medição de disco truncada e com erro | Item classificado como recuperável |
| Dois ciclos do ledger com mesma origem | Busca por caminho retorna o antigo restaurado apesar do novo ativo |
| Grupo selecionado desaparece | `IndexError` na atualização de lista |
| Executável do worker inexistente | Zero callbacks; uma mutação continua em voo |
| Item protegido na tabela tmpfs | Botão “Liberar” habilitado |

O script é uma reprodução descritiva do estado encontrado, não um conjunto de testes que afirma que esses comportamentos estão corretos. Depois das correções, alguns resultados devem mudar. A suíte de regressão deve transformar cada caso em uma asserção da proteção desejada.

## Imagens

As cinco imagens foram geradas e inspecionadas nesta revisão. São capturas de `QWidget.grab()` dos widgets reais com fixtures, em 1100 × 740, sem bordas do gerenciador de janelas. O tema offscreen não reproduz necessariamente o tema instalado no KDE.

1. `01-ajustes-inicial.png`: estado inicial sem consulta solicitada.
2. `02-disco-inicial.png`: estado inicial sem consulta solicitada.
3. `03-memoria-simulada.png`: pressão de memória e tmpfs sintéticos.
4. `04-processos-simulados.png`: candidato e grupos sintéticos; rodapé desatualizado observado.
5. `05-temporarios-simulados.png`: arquivo em uso sintético com botão habilitado.

As imagens sustentam avaliação de hierarquia, textos, tabelas e estados de widgets. Não provam funcionamento da bandeja, topmost, arraste, hotplug, teclado completo, leitor de tela ou disponibilidade real de recursos. Não foi executada uma sessão de limpeza end-to-end no desktop do usuário. As verificações no host descritas no plano são trabalho futuro.

## Fontes técnicas externas

Consultadas para fundamentar recomendações e limites, não como evidência de comportamento do código:

- [Linux PSI](https://docs.kernel.org/accounting/psi.html): semântica de pressão por recurso.
- [Linux cgroup v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html): controle e contabilidade por grupo.
- [Linux zram](https://docs.kernel.org/admin-guide/blockdev/zram.html): campos de `mm_stat` e memória usada.
- [systemd Control Group Interface](https://systemd.io/CONTROL_GROUP_INTERFACE/): gestão por serviços/scopes e delegação.
- [Qt Window and Dialog Widgets](https://doc.qt.io/qt-6/application-windows.html) e [QWindow](https://doc.qt.io/qt-6/qwindow.html): limites de posicionamento no Wayland e movimentação gerenciada pelo sistema.
- [Git worktree](https://git-scm.com/docs/git-worktree): inventário, remoção e prune de metadados.
- [Docker prune](https://docs.docker.com/engine/manage-resources/pruning/): diferenças entre classes de objetos e tratamento de volumes.
- [libvirt virsh](https://www.libvirt.org/manpages/virsh.html) e [backing chains](https://www.libvirt.org/kbase/backing_chains.html): gestão de VMs e dependências de discos.

As páginas Qt consultadas podem descrever versão posterior à instalada; as recomendações usam princípios de compatibilidade e devem ser testadas em PySide6/Qt efetivamente suportados. A página de manual systemd-run retornou HTTP 403 nesta sessão e não foi utilizada como evidência; a recomendação baseia-se na documentação oficial de interfaces de cgroups acessível.
