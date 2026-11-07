# Coleta passiva de energia e resets — 07/11/2026

Código: commit `02f586b` da branch de continuidade do Fôlego.

**Causa raiz indeterminada.** Fontes: journal por boot ID, ledger e histórico
privado do Fôlego, investigação PhaseZero em
`/home/misael/Projects/PhaseZero/docs/handoff/clean-host-development-20261024.md`
e cápsula privada em
`~/.cache/phasezero-dev/tmp/steamdeck-shutdown-investigation-20261107/`.
O caminho PhaseZero é referência do host de investigação; o produto portátil
não depende dele.

| Boot | Último ponto comprovado | Lacuna |
| --- | --- | --- |
| `0bbcc891…` | 53 amostras, 23:28:44–23:42:44; última ACPI 97 °C, 4,77 GiB disponíveis, swap 0,72 GiB, `rustc` 99,4% de um núcleo. | Journal termina 7 s depois. `acpitz` não mede especificamente o núcleo da CPU. |
| `64c34423…` | Journal 23:50:04–23:50:18; SteamZero `starting`. | Fôlego não iniciou: zero amostras não é período saudável. O marcador não comprova frame Gamescope. |
| `c325bc6f…` | 9 amostras, 23:52:03–23:54:26; última ACPI 83 °C, 6,43 GiB disponíveis, swap 16 KiB, PSI CPU 41,63%, I/O 0,86%, `electron` 134%. | Bluetooth HCI anormal às 23:54:30; journal prossegue até 23:54:37. Falta árvore histórica do Electron. |

O ledger entre 23:23 e 23:55 tem **zero operações Fôlego**. No boot atual,
baseline Btrfs tem delta zero; SMART da cápsula PhaseZero indicava
`media_errors=0` e `critical_warning=0`. Esses valores não datam os cortes.
A desconexão do carregador foi voluntária. Leitura de AC/bateria e custo de
processos de 07/11 não reconstituem o instante dos resets.

## Incremento no gravador existente

`BatteryInfo` contém `voltage_uv`, `current_ua` e `power_uw` quando fornecidos
pelo kernel. São µV, µA e µW da **bateria**, não consumo líquido do host.
Corrente é magnitude; potência não é calculada a partir de tensão e corrente.
Valores opcionais ausentes/ilegíveis/implausíveis ficam `null`, preservando
percentual e estado básicos válidos. A fonte AC continua separada. A
[ABI do kernel](https://docs.kernel.org/power/power_supply_class.html) define
essas unidades e permite que o driver omita atributos.

Cada linha nova tem schema 2, horário local em milissegundos, `mono_ns` do boot,
`collector_read_ms`, energia e `source_issues` esparso (`missing`, `partial`,
`error`). Em schema 2, fonte não listada foi lida como `ok`; em schema 1,
qualidade e campos novos são **desconhecidos**. O leitor rejeita schema futuro,
boot ID divergente do arquivo e valor elétrico incoerente com fonte inválida.
`collector_read_ms` mede a fase de leitura, antes dos deltas de processos e da
gravação; não representa CPU total da GUI. `mono_ns` não cruza boots.
Persistem 15 s, 4 MiB/boot, 32 MiB total e fsync inicial/a cada quatro linhas
ou sob pressão. Não há rotação destrutiva.

## Custo e sondagens avaliadas

Janela atual de 20 s às 08:33 -03, fora dos incidentes: supervisor de entrada
Fôlego 0,649 s de CPU (~3,24% de um núcleo), serviço de desempenho 0,271 s
(~1,35%), GUI 1,580 s (~7,90%), incluindo renderização e outras tarefas.
RSS da GUI ~142 MiB. Não se isolou CPU do coletor; o novo campo de duração
permitirá medir sua fase de leitura na próxima abertura normal. Linha de
fixture schema 2 ~539 bytes: a esse tamanho, 4 MiB cobrem ~32 h a 15 s.
Retenção segura continua pendente no roadmap.

Consulta pontual limitada a 80 entradas Bluetooth/DRM do kernel nos últimos
cinco minutos levou ~11 ms e não encontrou entradas (código 1). Não representa
custo durante rajada. Polling de journal a cada cinco minutos poderia perder
os 4–11 s finais, duplicaria a retenção PhaseZero e exigiria tratar cursor
perdido como lacuna. O dossiê pós-boot poderá consultar cursor/boot ID com
orçamento e sinalizar saturação. SMART não ganhou polling: o Fôlego não tem
helper autorizado sem privilégio, e não cria diálogo administrativo periódico.

| Hipótese | Observação decisiva faltante |
| --- | --- |
| Calor | Pico/limite do mesmo sensor ou motivo térmico no instante do corte. |
| Energia | Tensão/corrente próximas do corte sob a mesma carga e motivo de reset. |
| Kernel/firmware | Pstore funcional ou captura remota de panic/lockup/reboot; owner PhaseZero. |
| GPU/Gamescope | Etapa/saída do launcher e erro DRM contemporâneo; owner SteamZero. |
| Bluetooth | Falha de transporte/controlador ou pilha encadeada ao reset. |
| RAM/disco | OOM, PSI sustentado, SMART novo ou delta Btrfs contemporâneo. |
| Supervisores | ID de operação, owner, efeito e falha encadeados; ledger vazio nos cortes. |

Não houve carga, mudança de perfil, fechamento de aplicações, scrub ou reset
induzido. Fixtures e Qt offscreen não certificam bateria física ou estabilidade.
PhaseZero mantém reparo ICC e journal 150 MiB/60 s; SteamZero investiga
Gamescope/GPU. Baseline, leases, orçamento, disjuntor e operações incertas
continuam sob os contratos dos seus owners.

## Reconciliação passiva de boots — incremento seguinte

Código: commit `1fb220f` na mesma branch/PR #3. Validação final:
`./dev check` sequencial, 1286 passed/2 skipped headless e 1670 passed/2 skipped
Qt offscreen; `git diff --check` aprovado. O ensaio KDE/Wayland abaixo usa
apenas o cartão em um processo próprio e não certifica a GUI residente.

O observador existente, consultado aproximadamente a cada cinco minutos pela
GUI ou manualmente pelo CLI `disk health`, agora associa os últimos três boots
encerrados do journal aos seus arquivos locais por boot ID. A leitura de cada
arquivo é limitada aos últimos 64 KiB e às últimas 80 amostras válidas; a
janela parcial fica indicada. O boot atual é lido pelo seu próprio ID, sem
substituir ausência por uma amostra de outro boot. Arquivo ausente vira
`missing`; arquivo ilegível ou janela sem linha completa vira `unknown`.
Schema 1 é `partial` porque não prova qualidade das fontes nem monotônico.
Linhas danificadas preservadas permanecem `partial`. Os arquivos não são
modificados por esta consulta.

Uma consulta limitada ao último evento **retido** no journal de cada boot
encerrado mede a distância até a última amostra. Usa monotônico quando ambos
os lados o fornecem; no histórico antigo usa relógio civil e sinaliza que um
ajuste de hora pode afetar a distância. Isso não prova o instante real do
reset. A informação integra o JSON do CLI e o cartão de reinícios na aba
Disco; **Copiar dados** preserva os campos completos, enquanto a tela mostra
uma frase curta. Duração da observação é exposta em milissegundos. A cache
em memória evita repetir as leituras dos boots anteriores a cada consulta do
mesmo observador. Não há novo daemon, nova escrita ou sondagem SMART.

No host real, a consulta encontrou 7 s e 11 s entre as últimas amostras dos
boots primeiro/terceiro e seus últimos eventos retidos (relógio civil,
schema 1). O boot intermediário de aproximadamente 14 s segue sem amostra:
seu estado de energia/calor/carga é desconhecido. Medições pontuais de duas
consultas do mesmo observador: 67,27/25,15 ms de parede e 11,89/4,45 ms de
CPU do processo Python. Isso não isola o custo dos subprocessos nem certifica
uso prolongado. O cartão foi aberto por um processo Qt próprio no KDE/Wayland
real, mostrou o resumo e encerrou; a GUI residente não foi reiniciada.

Persistem lacunas: a GUI não existe no boot curto; o último evento retido no
journal pode anteceder o corte; `acpitz` não mede a CPU; RPM permanece
desconhecida; os 4 MiB por boot podem se esgotar em aproximadamente 32 h no
tamanho de linha medido. Rotação segura, pstore e correlação temporal com
SMART/GPU exigem trabalho dos respectivos owners e validação real. Nenhuma
operação do ledger, lease, orçamento, disjuntor, serviço externo ou perfil
físico foi alterada neste incremento.
