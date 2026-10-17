# M7 — Espaços temporários: monitorar e liberar /tmp, /run/user/1000 e /dev/shm sem risco aos projetos

Data: 2026-10-15 · Milestone: M7 (novo, depois de M0–M6 do plano `final-plain-bream.md`)
Autor: Misael + agente · Status: aprovado em chat, aguardando revisão deste arquivo

## 1. Contexto: o problema medido neste host

O trabalho de agente neste Deck mora em tmpfs, e tmpfs é memória. Quando ele enche, o
`ENOSPC` não atinge só o agente: atinge o histórico do bash, o git e o próprio
Fôlego — com a SSD tendo ~159 G livres para lado nenhum.

Baseline medido neste host nesta sessão (2026-10-15, fuso -03), dentro da sessão real do
Plasma/Wayland:

| volume | tipo | total | usado | disponível | filhos no nível-1 |
|---|---|---|---|---|---|
| `/tmp` | tmpfs (sem `size=`, default = metade da RAM) | 7,24 GiB | 1,79 GiB | 5,45 GiB (24,7 % cheio) | 149 |
| `/run/user/1000` | tmpfs `size=1517624k,mode=700` | 1,45 GiB | ~0 GiB (0,1 %) | 1,45 GiB | 34 |
| `/dev/shm` | tmpfs `nosuid,nodev,usrquota` | 7,24 GiB | 0,12 GiB (1,7 %) | 7,11 GiB | 0 |

Falhas reais que este módulo precisa cobrir (as quatro que você marcou):

1. **`ENOSPC` em `/tmp` no meio de uma tarefa** — o caso mais caro: a tarefa morre e o
   lixo do agente morto fica ocupando a RAM que a próxima tarefa precisa.
2. **`/run/user/1000` cheio quebrando a sessão** — sockets de sessão (Wayland, PipeWire,
   D-Bus, portal) vivem ali; encher derruba o login gráfico, não só o agente.
3. **Sujeira de agente morto acumulando** — `/tmp/qoder-cli-1000/<chave-cwd>/<uuid-sessão>`,
   `node-compile-cache`, `tsx-1000`, `pytest-of-misael`, `playwright_chromiumdev_profile-*`
   sobrevivem ao processo e não têm dono além do uid.
4. **A própria limpeza virar o acidente** — apagar cego ali destrói monte FUSE, socket de
   sessão vivo e o scratch da sessão em curso. Esta é a restrição que manda no design.

Custo da predicação "nada está aberto nisso": varredura completa de `/proc/*/fd` medida
neste host em **0,079 s** (492 processos, 9.862 fd lidos, 192 refs dentro de
`/tmp` ∪ `/run/user/1000`). Ou seja: dá para provar que um item está livre antes de
mexer nele, e é barato.

## 2. Objetivos e não-objetivos

**Objetivos**
- Dar visibilidade contínua (foto + tendência + ETA até lotar) dos três volumes acima,
  refletida no sinal 🟢/🟡/🔴 da barra de título.
- Listar o que é liberável e o que é protegido, com o motivo de cada recusa, antes de
  qualquer mutação.
- Liberar RAM de forma **reversível**: o dado vai para a SSD e volta.
- Ter **registro, controle e gestão**: um ledger do que foi retido, com orçamento de
  retenção, para o destino SSD não virar o lixo novo.

**Não-objetivos**
- Automatizar limpeza sem clique (nada roda sozinho; nenhuma mutação sem `--confirmar`).
- Mutar `/dev/shm` (o guard do projeto blacklista o prefixo `/dev`; medimos e mostramos,
  não mexemos).
- Reescrever `safely/guard.py` para entender montes (a checagem de monte vive na política;
  ver §6).
- Tocar `/mnt/sdcard` (mdia EIO conhecida) ou qualquer caminho fora da watch-list.

## 3. Decisões aprovadas

| # | decisão | escolha |
|---|---|---|
| D1 | caminho de arquitetura | **B**: pacote irmão `actions/tmpfs/` + aba "temporários" na GUI |
| D2 | autoridade de mutação | **recusar primeiro**: só plano + clique por item |
| D3 | alerta | **foto + tendência** com ETA até lotar |
| D4 | elegibilidade | **duplo filtro**: tipo **e** allow-list de padrão |
| D5 | gestão do retido | ledger + orçamento de retenção (14 dias / 3 GiB) |
| D6 | alcance do sinal | pressão de tmpfs também aparece no título da janela |

## 4. Arquitetura: unidades e interfaces

Camada `actions/` — proibido importar PySide6 (`tests/test_layers.py`), então tudo aqui é
testável sem GUI. Nenhum leitura de `/proc` sai de `actions/`/`core/` para `ui/`.

```
src/folego/core/tmpfs.py     ← leitura: capacidades dos volumes em watch-list
src/folego/actions/tmpfs/
  __init__.py
  holders.py     quem está com fd aberto em cada caminho
  inventory.py   classificação dos filhos de nível-1 de um volume
  policy.py      duplo filtro + recusas, puro
  plan.py        plano refusal-first com digest
  release.py     copiar → verificar → remover, com orçamento
  ledger.py      registro append-only e orçamento de retenção
  trend.py       ETA até lotar a partir de amostras
```

A leitura de capacidade mora em `core/` e não em `actions/` porque o `MetricsCollector`
precisa dela para o sinal do título, e `core/` nunca importa `actions/` (a direção de
dependência que o projeto já usa: `actions/` consome `core/`). O resto do módulo fica em
`actions/tmpfs/`, onde `tests/test_layers.py` já exige ausência de Qt.

### `core/tmpfs.py`

```python
WATCHED = ("/tmp", "/run/user/1000", "/dev/shm")   # watch-list, não "todo tmpfs"

@dataclass(frozen=True)
class TmpfsVolume:
    path: str
    fs_type: str
    total_bytes: int
    used_bytes: int          # (f_blocks - f_bfree) * f_frsize
    avail_bytes: int         # f_bavail * f_frsize — o que o nosso uid realmente consegue

    @property
    def used_frac(self) -> float: ...        # 0,0 se total == 0
    def to_dict(self) -> dict: ...

def read_mounts(proc_root: str | None = None) -> tuple[tuple[str, str], ...]
def watched_volumes(*, proc_root=None, statvfs_fn=os.statvfs, watched=WATCHED) -> tuple
```

`watched_volumes` só emite caminho que `/proc/mounts` confirma como `tmpfs` **e** que está
na `WATCHED`. Isso é o que mantém `/run`, `/run/credentials/*` e os outros tmpfs de sistema
fora do relatório — a lista de montes do host tem muito mais tmpfs do que os três que
importam. `used_bytes` é o que conta para o sinal; `avail_bytes` é o que conta para a
decisão de escrita.

### `holders.py`

```python
@dataclass(frozen=True)
class HolderIndex:
    refs: dict[str, tuple[int, ...]]     # caminho-normalizado -> pids
    proc_count: int
    fd_count: int
    def refs_under(self, path: str) -> frozenset[int]: ...

def holder_index(*, prefixes=WATCHED, proc_root=..., pids=None) -> HolderIndex
```

Uma passada só: para cada pid em `proc_root`, `readlink` de cada `fd/*`; guarda quando o
alvo começa com um dos prefixos. Permissões negadas viram `EACCES` ignorado silencioso,
não erro (fd de outro uid não nos diz respeito, e não queremos travar por isso). Custo
esperado: O(total de fds), ~0,1 s neste host.

### `inventory.py`

```python
@dataclass(frozen=True)
class TmpfsEntry:
    path: str
    name: str
    volume: str
    kind: str              # "dir" | "file" | "symlink" | "socket" | "fifo" | "other"
    uid: int
    bytes: int             # measure_tree para dir; st_size para file
    files: int
    age_days: float        # desde o mtime mais recente dentro da árvore (newest_ns)
    is_mount_point: bool
    under_mount: bool
    holder_pids: tuple[int, ...]
    truncated: bool
    errors: tuple[str, ...]

def inventory(volume: TmpfsVolume, mounts, holders: HolderIndex, *,
              now=None, deadline_s: float = 10.0, lstat=os.lstat) -> tuple[TmpfsEntry, ...]
```

`age_days` usa `newest_ns` do `TreeStat` (`actions/disk/measure.py:14`), não o mtime do
diretório pai — um diretório de sessão pode ter mtime antigo e arquivos recém-escritos, e
idade antiga errada aqui é exatamente o tipo de acidente que estamos evitando.
`measure_tree` já garante: não segue symlink, não cruza dispositivo, nunca levanta exceção
(`errors`/`truncated`). `/run/user/1000/doc` é o caso que prova essa garantia: `du` mostra
29 G através dele, e um walk que cruzasse o monte contaria memória de outra pessoa.

### `policy.py`

```python
DEFAULT_ALLOW_PATTERNS = (           # apenas /tmp; vazio para /run/user/1000 e /dev/shm
    "/tmp/qoder-cli-1000",
    "/tmp/node-compile-cache",
    "/tmp/tsx-1000",
    "/tmp/pytest-of-*",
    "/tmp/playwright_*",
    "/tmp/tmp*",
)
MIN_AGE_DAYS = 3.0
MAX_ITEM_BYTES = 2 * 1024**3
```

Os padrões são escritos na granularidade que o `inventory` mede — o **filho direto**
do volume. `/tmp/qoder-cli-1000` é a unidade, e não a sessão lá dentro, porque a
ferramenta recria o próprio diretório-raiz e a idade relevante é a do arquivo mais
novo da árvore inteira: enquanto qualquer sessão for recente, o container fica
protegido. Um padrão `/tmp/qoder-cli-1000/*` nunca casaria com um item inventariado.

```python
@dataclass(frozen=True)
class Policy:
    allow_patterns: tuple[str, ...] = DEFAULT_ALLOW_PATTERNS
    min_age_days: float = MIN_AGE_DAYS
    max_item_bytes: int = MAX_ITEM_BYTES
    volumes: tuple[str, ...] = WATCHED

@dataclass(frozen=True)
class Eligibility:
    ok: bool
    reason: str
    matched: str | None = None       # o padrão que abriu a exceção

def classify(entry: TmpfsEntry, policy: Policy, *, now=None) -> Eligibility
```

`classify` devolve **uma** razão por recusa, na ordem da tabela de §5 (primeira recusa
vence), e uma razão de sucesso que nomeia o padrão casado. Nada de booleano mudo: cada
linha do plano precisa ser explicável para você auditar.

### `plan.py`

```python
@dataclass(frozen=True)
class TmpfsPlan:
    generated_at: str
    volumes: tuple[TmpfsVolume, ...]
    reclaimable: tuple[EligibleItem, ...]
    protected: tuple[ProtectedItem, ...]     # todo item não-elegível, com motivo
    total_bytes: int
    scanned_entries: int
    digest: str                              # sha256 do conteúdo canônico do plano
    errors: tuple[str, ...]

def build_plan(volumes, entries, policy, *, now=None) -> TmpfsPlan
```

Invariantes que a UI e o CLI cobram: `len(reclaimable) + len(protected) == scanned_entries`
e cada item protegido tem `reason` não-vazio. É a mesma reconciliação de contagem que o
M5 provou (141 = 34+85+22+0); sem ela, "protegi tudo" pode significar "perdi itens".

### `release.py`

```python
@dataclass(frozen=True)
class ReleaseResult:
    ok: bool
    entry_id: str
    reason: str
    bytes: int
    stored: str
    sha256: str
    freed_bytes: int

def tree_digest(path: Path) -> tuple[str, int]        # (digest, bytes) por sha256_file
def release_item(plan, item, *, dest_root=None, ledger, audit, confirm=False,
                 statvfs_fn=os.statvfs) -> ReleaseResult
```

Destino: `paths.data_dir() / "tmp-quarantine" / <YYYYMMDDTHHMMSSZ> / <nome-sanitizado>` —
`~/.local/share/folego/tmp-quarantine/`, ou seja, na `/` da SSD. Cross-device é o
ponto, não um bug: o `Quarantine.move_in` do M5 recusa rename entre dispositivos
(`actions/disk/quarantine.py:131`) porque lá a promessa é zero-copy e instantânea; aqui a
promessa é tirar bytes da RAM, então o movimento é explicitamente copy → verify → unlink.

Sequência, com recusa antes de qualquer escrita:
1. `confirm is False` → recusa, nada muda (mesmo contrato de `disk`/`tune`).
2. re-checar elegibilidade **no momento da liberação** (o item pode ter ganhado holder
   desde o plano): mount point, tipo, uid, holder vivo.
3. checar `avail_bytes` do destino ≥ `2 * item.bytes` (folga para a cópia existir enquanto
   o original ainda está lá).
4. checar orçamento do ledger (§7).
5. copiar (`copytree` com `symlinks=True`, preservando modo), `tree_digest` na origem e no
   destino, exigir igualdade.
6. `fsync` do diretório destino e uma linha `partial` no ledger **antes** de apagar — o
   clone existe na SSD e o original ainda está lá; esse estado intermediário é registrado,
   não inferido.
7. `rmtree`/`unlink` da origem e uma segunda linha, `released`, com `freed_bytes`.
8. se a remoção da origem falhar, o ledger fica em `partial`: nada é perdido, o `ledger`
   mostra o par (clone + original) e o orçamento conta os bytes (eles ocupam a SSD).

Uma liberação nunca é feita dentro do processo da GUI: vai como filho matável via
`TuneJobs(argv_factory=…)` com `python -m folego tmpfs release <id> --confirmar`,
exatamente como `disk_tab.plan_argv`.

### `ledger.py` — ver §7.

### `trend.py`

```python
def eta_hours(samples: tuple[tuple[float, int], ...], capacity_bytes: int, *,
              now=None, min_samples: int = 3, horizon_s: float = 15*60) -> float | None
```

Regressão linear simples em `used_bytes × ts` sobre a janela; devolve `None` (nunca 0)
quando há menos de `min_samples` amostras, quando a inclinação é ≤ 0, ou quando o volume
já está cheio. A capacidade entra como argumento porque o ETA é sempre relativo ao teto do
tmpfs, não à mostra anterior. O poller da aba guarda as amostras em memória; persistência
de histórico não está nesta fase.

## 5. Recusas: o que impede a limpeza virar o acidente

`classify` avalia nesta ordem; a primeira falha é a razão reportada.

| # | teste | recusa | o que protege neste host |
|---|---|---|---|
| R1 | `is_mount_point` ou `under_mount` | `refused: é ponto de montagem / contém montagem` | `/run/user/1000/doc` (`xdg-document-portal` FUSE, `dr-x------`, 29 G visíveis ao `du`) |
| R2 | `kind` não é `dir`/`file` | `refused: tipo {kind} não é arquivo/árvore regular` | sockets de sessão (Wayland, PipeWire, D-Bus, `bus`, `gnupg`) |
| R3 | `uid != os.getuid()` | `refused: dono {uid} não é este usuário` | `/tmp/pamac-root`, lixo de outro uid |
| R4 | `holder_pids` não-vazio | `refused: {n} processo(s) com fd aberto: {pids}` | a sessão de agente em curso, o próprio Fôlego |
| R5 | `bytes > max_item_bytes` | `refused: {bytes} acima do limite por item` | cópia de 10 min travando a GUI |
| R6 | volume não está em `policy.volumes` | `refused: volume fora da watch-list` | `/run`, `/run/credentials/*`, qualquer tmpfs de sistema |
| R7 | `age_days < min_age_days` | `protegido: mais novo que {floor} dias` | scratch criado há 1 h por um agente vivo |
| R8 | nenhum padrão casa | `refused: fora da allow-list` | tudo que não conhecemos — o default do sistema |
| R9 | volume `/dev/shm` na mutação | `refused: resolved path is outside every allowed root` (via `guard`) | `/dev/shm` é medido e exibido, **nunca** mutável |

R1–R3 e R9 são recusas de segurança; R4 é a prova de que nada está em uso; R5–R8 são a
política de "recusar primeiro". A allow-list default cobre **somente `/tmp`**: em
`/run/user/1000` nada é liberável por padrão, porque ali mora a sessão — um usuário que
queira liberar algo de lá passa `--permitir "<padrão>"` explicitamente, item por item.

`/dev/shm` permanece mutável-não: o `BLACKLIST_PREFIXES` de `safely/guard.py` inclui `/dev`
e a R9 só confirma o que o guard já faz. Não afrouxamos o guard para este módulo; a
propriedade afirmada é estreita ("medimos `/dev/shm`, não o mutamos") e ancorada em teste.

## 6. Onde a checagem de monte mora (e por que não no guard)

`guard.validate_target` responde "este caminho pode ser escrito por mim?" (blacklist de
prefixo, symlink, raiz permitida, uid, escrita). Ele não tem noção de monte, e um `mkdir`
dele dentro de `/run/user/1000/doc` passaria. Em vez de transformar o guard em um
verificador de montes — o que mudaria o comportamento de todos os chamadores existentes
(tunings, quarentena do M5, órfãos) — a recusa R1 vive na `policy.py` e é exercida pela
liberação **e** pela restauração, com teste próprio. O guard continua sendo a última
linha, e a propriedade "mutação atravessa monte" passa a ser negada em duas camadas
independentes: `measure_tree` não cruza dispositivo e `release_item` recusa ponto de
monte.

## 7. Registro, controle e gestão do que foi retido

Sem orçamento, liberar RAM só empurra o lixo para a SSD. `~/.local/state/folego/tmp-ledger.jsonl`,
append-only + `fsync`, com o mesmo mecanismo do `AuditLog` (`safely/audit.py:16`):

```json
{"ts": "...", "entry_id": "1728...-ab12cd34", "src": "/tmp/...", "volume": "/tmp",
 "stored": ".../tmp-quarantine/2026.../...", "bytes": 123, "sha256": "...",
 "age_days": 4.2, "matched_pattern": "/tmp/qoder-cli-1000",
 "holder_pids": [], "state": "released", "action_id": "tmpfs.release",
 "audit_event_id": "..."}
```

Estados: `released` → `restored` | `dropped` | `expired`, mais `partial` (cópia completou,
remoção não). Uma linha por **transição**; o estado vigente é o da última linha de cada
`entry_id`.

```python
RETENTION_DAYS = 14.0
MAX_RETAINED_BYTES = 3 * 1024**3

class Ledger:
    def records(self) -> dict[str, LedgerRecord]       # estado vigente por entry_id
    def retained_bytes(self) -> int
    def retained_count(self) -> int
    def oldest(self) -> LedgerRecord | None
    def over_budget(self, *, days=RETENTION_DAYS, max_bytes=MAX_RETAINED_BYTES) -> tuple[str, ...]
    def budget_view(self) -> BudgetView                # retido, idade máx, folga, por volume de origem
    def append(self, record) -> None
```

Regras de gestão, todas com dry-run antes:
- `release` recusa se `retained_bytes + item.bytes > MAX_RETAINED_BYTES`, e cita a entrada
  mais velha como a candidata a `expire`. A cota é um teto de *retenção*, não de destino
  físico: o espaço livre da SSD é checado à parte no passo 3 de `release.py`.
- `tmpfs ledger` mostra: bytes retidos, contagem, entrada mais velha, distribuição por
  volume de origem, e **RAM liberada × SSD ocupado** — o número que responde "estamos só
  trocando de lixo?".
- `tmpfs expire --confirmar --irreversivel` remove do mais antigo até caber no orçamento
  (idade > 14 d **ou** excesso de bytes), checando o guard em cada caminho e auditando por
  item. Sem `--confirmar` ele lista exatamente o que apagaria, como o `disk purge`.
- `tmpfs restore <id> --confirmar` devolve o item: recusa se o caminho de origem já existe,
  se o volume de origem não tem `avail_bytes` suficiente, se um monte apareceu no meio do
  caminho, ou pelo guard. Marca `restored`, devolvendo o byte ao orçamento.
- Auditoria: cada transição do ledger é também um evento em `audit.jsonl` com `kind`
  `tmpfs.release|tmpfs.restore|tmpfs.expire`, `action_id = entry_id` e `risk`
  `reversible`/`irreversible`, para a tela de auditoria do M6 enxergar sem caso especial.

## 8. Sinal no título, CLI e GUI

**Título.** `Snapshot` ganha `tmpfs: tuple[TmpfsVolume, ...] = ()` (`core/snapshot.py:62`),
preenchido pelo collector com syscalls baratos (`statvfs` + leitura do `mounts`), sem walk
de árvore nem varredura de fd no poller de 2 s. `ui/title_signal.py:31` acrescenta:
🔴 se qualquer volume em watch tiver `used_frac ≥ 0,90`; 🟡 se `≥ 0,75`; o texto passa a
trazer o pior volume, ex. `Fôlego 🔴 · ... · /tmp 93%`. As regras existentes de RAM,
PSI e RSS próprio não mudam.

**CLI** (`python -m folego tmpfs …`, recusando em stderr para o stdout `--json`
continuar sendo uma linha parseável):

```
tmpfs status [--json]                      capacidades + usado/avail + pior volume (só leitura)
tmpfs plan   [--raiz /tmp] [--dias 3] [--permitir PAT]* [--json]
                                           refusal-first: elegíveis + protegidos + digest
tmpfs release <caminho-ou-id> --confirmar  copy→verify→unlink + ledger
tmpfs ledger [--json]                      registro e orçamento de retenção
tmpfs restore  <entry-id> --confirmar      volta para a origem
tmpfs expire   [--dias 14] [--max-bytes N] [--confirmar --irreversivel]
                                           seca a retenção que estourou o orçamento
```

**GUI.** Quinta aba, "temporários", criada em `ui/main_window.py:47-57` pela mesma fábrica
dos tabs existentes:
- tabela de volumes: caminho, tipo, total/usado/disponível, barra de ocupação, ETA;
- tabela do plano com colunas "candidato" (bytes, idade, padrão casado, holders) e
  "protegido" (motivo R1–R9) — a segunda é a primeira, por decisão D2;
- botão "Atualizar plano" (filho matável, com cancelamento) e por linha "Liberar", que abre
  diálogo de confirmação repetindo caminho, bytes e pids donos;
- painel do ledger: retido, mais velho, folga do orçamento, botões "Restaurar"/"Expirar".
O tooltip da bandeja passa a incluir a linha do pior volume em watch quando `≥ 75 %`; nada
de clique pela bandeja (mutação continua pedindo a janela).

## 9. Erros e falhas parciais

- `/proc` ilegível, monte sumido, `statvfs` falhando → item vira `errors` do plano, nunca
  exceção que some com a lista (contrato herdado de `measure_tree`).
- Volume que não está mais montado: `watched_volumes` o omite (não inventamos ocupação de
  algo que não é tmpfs).
- Fill race: entre `plan` e `release` o item pode ganhar holder, virar ponto de montagem,
  ou ser apagado por outra pessoa — o passo 2 de `release.py` re-classifica e recusa.
- Queda no meio da cópia: nada foi apagado; o clone parcial fica registrado como `partial`
  e o `ledger` mostra (o orçamento conta bytes `partial`, porque eles ocupam a SSD).
- Queda depois do ledger e antes do `rmtree`: o original ainda existe, a linha `released`
  também, e um novo `release` do mesmo item é recusado como "já no ledger" — a correção é
  manual e fica registrada no motivo da recusa.
- Deadline da varredura de holders e do `measure_tree` são limitados por tempo; truncado é
  sinalizado no item, e truncado **não** é elegível para liberação.

## 10. Testes (TDD, um teste por comportamento, sempre vendo falhar antes)

Fixtures existentes: `fake_home`, `fake_proc`, `never_touch_real_edge_config`
(`tests/conftest.py`), `paths.proc_root()` como seam de `/proc`. **Nenhum teste escreve em
`/run/user/1000`, `/tmp` real ou `/dev/shm` reais** — tudo em `tmp_path`, com
`statvfs_fn`/`lstat`/`clock` injetados.

| arquivo | comportamento provado |
|---|---|
| `test_core_tmpfs.py` | parse de `/proc/mounts` fake; `used = total - avail_free` reconcilia; só a watch-list aparece (`/run`, `/run/credentials` ficam fora); volume sumido é omitido |
| `test_paths.py` (estender) | `tmp_quarantine_dir()` e `tmp_ledger_path()` caem sob XDG data/state, na SSD, e seguem o seam de `HOME` |
| `test_collector.py` (estender) | o `Snapshot` traz os volumes lidos; um volume que falha não derruba a coleta nem vira número inventado |
| `test_tmpfs_holders.py` | índice a partir de `/proc` fake com `fd/*` symlink; assertion **não-vazia**: com holder o item é recusado, sem holder o mesmo item é elegível |
| `test_tmpfs_inventory.py` | `age_days` vem de `newest_ns`; socket/fifo/symlink classificados; `under_mount` detecta `/run/user/1000/doc`; truncado vira flag |
| `test_tmpfs_policy.py` | uma recusa por R1…R8, na ordem; o padrão casado aparece no sucesso; `/tmp/.X11-unix` nunca é elegível com a allow-list default |
| `test_tmpfs_plan.py` | `len(reclaimable)+len(protected) == scanned_entries`; digest determinístico para entrada igual, muda com idade |
| `test_tmpfs_release.py` | happy path copy+verify+unlink com bytes reais liberados; recusa sem `--confirmar`; recusa quando destino não tem folga; recusa quando item ganhou holder entre plano e liberação; recusa > `MAX_ITEM_BYTES`; falha pós-cópia deixa original íntegro |
| `test_tmpfs_ledger.py` | transições e estado vigente; a N-ésima liberação que estoura o orçamento é recusada; `over_budget` ordena da mais velha; `partial` conta como retido |
| `test_tmpfs_trend.py` | ETA determinístico com relógio injetado; < 3 amostras → `None`; inclinação negativa → `None`; cheio → `None` |
| `test_cli_tmpfs.py` | `plan` sem flag não muda nada e imprime recusas em stderr; `--json` stdout é uma linha parseável; `release` sem `--confirmar` sai recusado |
| `test_ui_tmpfs_tab.py` | argv do filho igual ao do terminal; volumes e plano vindos de payload plano; `Liberar` repetindo caminho, bytes e pids; diálogo negado não chama o filho; recusa do filho exibida como recusa; ledger com `Restaurar`/`Expirar` por linha |
| `test_ui_main_window_tabs.py` (estender) | quinta aba na ordem; o snapshot enche a aba sem nenhuma varredura própria; fechar a janela derruba os filhos do tmpfs |
| `test_ui_tune_jobs.py` (estender) | `release`/`restore`/`expire` contam como mutação: a segunda é recusada enquanto a primeira está em voo |
| `test_title_signal.py` (estender) | 🔴 por `/tmp` a 95 % com RAM folgada; 🟡 a 80 %; comportamento inalterado sem tmpfs no snapshot |
| `test_layers.py` (estender) | `actions/tmpfs/*` não importam Qt; `ui/tmpfs_tab.py` não contém `open("/proc`, `procfs.`, `sysfs.`, `/mnt/` |
| `test_tools_verify_tmpfs.py` | os comparadores do script de host provados fora do host: texto real do `df`, linha real de `mountinfo`, contagem que não fecha, proteção que virou elegível e ledger que mudou — nenhum deles toca `/tmp` real |

Cobertura de mutação voluntária: inverter um comparador de idade, remover o teste de
monte, trocar `f_bavail` por `f_bfree` — cada um desses tem de matar ao menos um teste.

## 11. Verificação no host (evidência independently auditável)

`tools/verify_tmpfs.py`, no mesmo espírito do `tools/verify_m3.py`:

- `statvfs` dos três volumes cruzado com `df -B1` (bytes exatos, com tolerância de
  amostragem declarada) e `findmnt`/`/proc/self/mountinfo` para os montes — `/proc/mounts`
  não serve de testemunha, é o mesmo arquivo que o app lê;
- reconcile de contagens: `candidatos + protegidos == varridos` (fechamento interno,
  asserção dura) e `varridos == filhos de nível-1` com tolerância declarada — filhos de
  nível-1 nascem e morrem durante o walk de 317 itens;
- tempo real da varredura de holders, com `proc_count`/`fd_count` impressos (a promessa de
  0,079 s é re-medida, não citada);
- prova de proteção: `/run/user/1000/doc`, `/run/user/1000/bus` e o scratch da **nossa**
  sessão aparecem como protegidos, cada um com motivo;
- falsificabilidade: um diretório sintético criado em `/tmp` com nonce no nome, dono nosso,
  sem holder, idade forçada — tem de sair elegível; o mesmo diretório com um fd aberto
  nosso tem de sair recusado R4;
- um ciclo real `release → ledger → restore → ledger` nesse ítem sintético, com sha256
  conferido nos dois lados por `sha256sum` (programa de fora, não o digest da aplicação),
  apagando a prova no fim;
- o ledger e o audit do ciclo vão para um scratch sob XDG state, e um tripwire por hash de
  `tmp-ledger.jsonl` e `audit.jsonl` prova que a execução não escreveu no registro do host;
- o §13.2 pedia hash do conteúdo dos três volumes antes/depois das leituras: num tmpfs vivo
  isso nunca fecha (outros processos escrevem o tempo todo), então a prova é um hash de
  árvore de um diretório quieto (`/tmp/.X11-unix`) ao redor de `status` e `plan`, mais o
  tripwire acima — a substituição é declarada, não escondida;
- `--sem-ciclo` roda somente leitura, para que a evidência possa ser colhida sem escrever
  um byte em tmpfs real;
- **nunca** libera nada de scratch de agente vivo, e não roda `expire` contra o ledger real
  sem `--confirmar --irreversivel` explícitos.
- saída em log estável `.scratch/m7-verify-tmpfs.log` para auditoria.

## 12. Riscos residuais e fora desta fase

- Um agente que escreva no item no instante da liberação (depois da checagem de holder)
  perde a corrida. A mitigação é o re-check + a janela de cópia curta por cota de 2 GiB; a
  eliminação exigiria `fcntl` no item, adiado conscientemente.
- Persistir histórico de tendência para calcular ETA fora da janela de 15 min: adiado.
- Autostart/agendamento de `expire`: fora — toda mutação continua pedindo clique.
- `/dev/shm` mutável: fora, por decisão de segurança do guard.
- `/tmp` de outros usuários e do root: fora (R3).
- `disk tmp` (`actions/disk/tmpclean.py`, delete irreversível só de `/tmp` por idade):
  continua existindo e testado como está; a aba nova não o expõe e o caminho guardado para
  a watch-list é `tmpfs`. Unificar os dois é trabalho futuro, não desta spec.

## 13. Critério de aceite do M7

1. Suite completa verde com os testes de §10, cada um visto falhar antes de existir.
2. `tmpfs status` e `tmpfs plan` sem flags não alteram um byte (a prova é o hash de árvore
   do diretório quieto antes/depois, o tripwire do ledger/audit do host e as asserções de
   dry-run da suíte — ver §11).
3. `tools/verify_tmpfs.py` roda no Deck e produz: contagens reconciliadas, custo medido de
   holders, proteções provadas (doc/bus/sessão), e um ciclo `release→restore` com sha256
   conferido — tudo registrado em log estável.
4. O título fica 🔴 com `/tmp` ≥ 90 % em teste de suíte, sem tocar em RAM real.
5. O ledger mostra o saldo "RAM liberada × SSD retido" e o `expire` dry-run lista exatamente
   o que um `expire --confirmar` apagaria.
6. Nada em `~/.config/microsoft-edge`, nenhum projeto em `/mnt/sdcard` e nenhum socket de
   sessão foi tocado (auditável em `audit.jsonl`).
