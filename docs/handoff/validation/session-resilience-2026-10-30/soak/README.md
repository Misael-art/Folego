# Ensaio contínuo aprovado — 30/10/2026

**7.200,057 segundos reais**, em uma execução independente, de
03:50:47 a 05:50:47 UTC. Produto e harness do commit
`a65b5f7f822ea55c520ad8e6b8598a00df741c5e`, sem alteração durante o ensaio.
Python 3.14.7 e Qt 6.12.0 gerenciados pelo projeto. Nenhuma duração anterior
foi somada; o orçamento de 18/10 permaneceu inalterado.

| Critério | Observado | Limite |
|---|---:|---:|
| CPU da UI e filhos coletados | 1,65% de um núcleo | 5% |
| Pico de crescimento de RSS após aquecimento | 0,49 MiB | 64 MiB |
| Tendência observada de RSS | −21,32 MiB/h | ≤4 MiB/h |
| Crescimento de descritores | 5 | 16 |
| Crescimento de widgets | 8 | 32 |
| Heartbeat p99 | ≤5 ms | ≤50 ms |
| Maior atraso do heartbeat | 197,00 ms | 500 ms |
| Leitura de disco do processo | 138,20 MiB/h | 512 MiB/h |
| Escrita de disco do processo | 33,83 MiB/h | 64 MiB/h |

Concluídos 120/120 workers e 20/20 cancelamentos próprios. Diário com 80
intenções e 80 resultados correspondentes, todos verificados; 40 backups.
Arquivo descartável restaurado byte a byte, 140 diretórios de filhos
contabilizados e nenhum filho/QProcess após encerrar. Filas limitadas e
buffer de amostras no teto de 600. Todos os checks do analisador passaram.

O alcance é **GUI Wayland minimizada, interação desabilitada, coletor sintético
e workers reais sobre arquivo descartável**. Heartbeat mede despacho Qt,
não frames do compositor. Não certifica duas horas de composição visível,
inventários grandes, todas as cargas do host, entrada física ou boot/login.
Nenhuma entrada foi desligada nem aplicação de terceiro interrompida.

O `/proc` sintético do harness não fornece boot ID. Os manifests de temporários
permanecem conservadoramente não certificados, sem arquivamento automático
nessa tentativa. Portanto, esse resultado **não homologa retenção contínua**.
Identidade/término com `/proc` real têm teste separado com filho próprio;
ausência de consumidores, recusa de estado desconhecido e preservação de
payloads têm regressões em árvores descartáveis.
Na consulta adicional com inventário real, o arquivamento foi conservado em
zero por propriedade de consumidores desconhecida; [recibo](../retention-real-proc.json).
Não se converteu esse bloqueio em prova de retenção efetiva.

No ponto intermediário, o processo tinha 24.316 KiB de VmSwap. RSS é residência:
a queda observada pode envolver paginação, não prova heap liberado ou ausência
de vazamento. Esse limite de interpretação não altera os critérios registrados
antes da execução.

- [Análise e orçamento](analysis.json), [relatório final](report.json).
- [Amostras integrais](samples.jsonl), [resultados dos workers](worker-results.jsonl).
- [Hashes da fonte](source-manifest.json), [proveniência e hashes dos artefatos](provenance.json).
- [Residência/paginação no ponto intermediário](paging-midpoint.json).

São artefatos de leitura, com caminhos do checkout normalizados e a árvore
descartável substituída por `<qa-state>`. Os conteúdos de fixtures/backups não
são distribuídos nem devem ser reativados; os hashes original/publicado estão
na proveniência. O analisador original conferiu seus estados na árvore real
de QA antes da publicação. O material original fica na raiz local ignorada
`run-review-20261029/soak-resilience-7200/`, sem processos ativos.
