# Diagnóstico consolidado e estado da migração

Atualizações posteriores (29–30/10): a supervisão restrita de entrada tem autorização,
implementação e ativação próprias, descritas no [HANDOFF](HANDOFF.md) e no
[guia de acessibilidade](ACESSIBILIDADE.md). As afirmações históricas abaixo
sobre automação desligada continuam válidas para o executor de recursos e
não substituem esse registro posterior. O início com a sessão passou a ser
ligado por padrão, com opt-out na aba opções; temporários próprios e revisões
de operações receberam integração descrita na passagem. Consulte ali o aceite
vigente do soak; a matriz física permanece sem aceite integral.

## Conclusão

O desenvolvimento avançou e tem regressões/instalação/desktop com evidências,
mas o produto continua parcial. **Não há aceite de soak de duas horas, de
automação real nem de gestão integral da retenção.** Esta migração preserva o
working tree posterior à base `61179f5`, organiza sua recuperação e acrescenta
um ambiente de desenvolvimento que não depende deste host.

Referências atuais: `README.md`, `AGENTS.md`, `docs/HANDOFF.md`,
`docs/NOVO-HOST.md`. Revisões e logs completos permanecem em `docs/reviews/`.
Os pedidos originais recebidos estão em `docs/handoff/inputs/`.

## Correções e integração do produto

As rodadas anteriores corrigiram reuso/visibilidade de sugestões, seleção da CI
headless antes da importação de Qt, transações de configuração e parte dos
contratos de autorização/planos/recuperação. Mutações de produção de disco,
tmpfs, ajustes e processos passaram a usar o coordenador comum. Processos são
protegidos com evidência fresca de boot/starttime/sessões/exclusões/ancestrais,
e SIGTERM é acompanhado; sobrevivência é parcial. A GUI padrão usa QProcess.

O histórico saiu do loop gráfico com orçamento de leitura, e saúde/frescor
expiram sem uma nova amostra. Resultado desconhecido permanece visível e não
autoriza repetição. Runtime é descoberto por UID e temporários de filhos são
privados em destino verificado. Inventário de fixtures permanece protegido e
somente leitura. Não se habilitou arquivamento nem executor automático.

Na validação gráfica foram corrigidos: largura mínima excessiva da central,
texto cortado do compacto, fallback decorado no Wayland, controles de grupos,
retorno sem bandeja, workers ao fechar a central, pausa antes da primeira
leitura e bandeja disponível desde a abertura. Testes correspondentes foram
preservados/adicionados sem retirar verificações de nomes/quantidades/RSS.

## Resultados históricos comprovados em 18/10

| Evidência | Resultado e alcance |
|---|---|
| `desktop-validation/suite-qt611.log` | 1134 passed, 19,74 s; Qt 6.11.2 |
| `desktop-validation/suite-qt612.log` | 1134 passed, 21,09 s; Qt 6.12.0 em venv próprio |
| `desktop-validation/suite-headless.log` | 917 passed, 12,92 s; sem PySide6/shiboken6 |
| Wheel GUI e launcher GIO | Instalação não editable sem system-site-packages; entrypoint absoluto fora de shell ativado |
| Remoção GUI | Pacote removido e hashes do HOME descartável preservados; sem autostart |
| KDE Wayland físico | Ciclo de vida com/sem bandeja, pausa, fullscreen, teclado e SNI; janela fracionária a 135% |
| KWin Wayland privado | Escalas 100/150/200% e remoção de saída virtual; moldura inteira na saída restante |
| Xvfb + KWin X11 privado | Três escalas, arraste, foco e posição persistida; zero operações pelo gesto |
| Host filesystem somente leitura | Seis casos GUI, escrita disponível só no workspace/evidências |

Os caminhos da tabela são relativos a
`docs/reviews/2026-10-18/desktop-validation/`. A instalação limpa foi de Python
no mesmo BigLinux, não outra distribuição/VM limpa. Capturas de cliente não
são capturas de compositor. O Spectacle físico produziu uma captura real; o
Spectacle virtual retornou 0 sem arquivo e não foi usado como prova de imagem.
Uma captura que pegou janela diferente do alvo foi descartada.

Leitor de tela real, arraste físico Wayland, reativação de instância já aberta
pelo launcher, outra distribuição limpa e login físico X11 continuam pendentes.
Registro/Activate de SNI não garante ícone permanentemente visível no painel.

## Soak e falhas de preparação

Todas as durações abaixo são independentes e **não podem ser somadas**.

| Tentativa | Última duração | Desfecho |
|---|---:|---|
| `soak-wayland` | 760,5 s | Interrompida em repouso para usar wheel corrigido |
| `soak-final-wayland` | 2740,1 s | Sem relatório final, seguida de novo boot do host |
| `soak-retry-wayland` | 2080,6 s | Inventário de 52 itens carregado com janela aberta; +52 widgets ultrapassaram orçamento de repouso |
| `soak-controlled-wayland` | 6440,4 s | Raiz TMPDIR compartilhada chegou a 256 diretórios; novos filhos foram recusados antes do efeito |
| `soak-private-wayland` | 2470,5 s | Resposta interrompida, sem relatório final; PID/boot originais não existem na inspeção de 24/10 |

A raiz compartilhada tinha exatamente 256 entradas. O limite protegeu o host;
o harness é que havia agrupado tentativas anteriores no mesmo orçamento.
O cancelamento esperado de um filho já iniciado também foi recusado no preparo
quando o teto foi atingido; não se afirmou que houve um filho cancelado nesse caso.
Nenhum limite foi ampliado, nenhum diretório anterior foi apagado e falhas não
foram convertidas em verde.

Correções do harness: entrada da janela de QA desabilitada, aviso de métricas
sintéticas, registro de classes de widgets e inventário, TMPDIR/PYTEST_DEBUG_TEMPROOT
exclusivos dentro de `--state`, teto planejado de 141 preparos abaixo de 256,
resultados de workers em JSONL e observador por identidade de processo/boot.
Smokes curtos confirmaram efeitos/diário/restauração e propriedade dos diretórios;
não foram apresentados como horas reais nem como orçamento de CPU/I/O aprovado.

Na tentativa final arquivada: 42 workers/7 cancelamentos concluídos, widgets
181 → pico 189, filas limitadas e amostras com teto 600, sem falhas no último
registro. Isso cobre somente 2470 segundos. A tendência parcial de RSS excedia
o orçamento; o analisador recusa duração incompleta e saída não comprovada.
`soak-private-interrupted-analysis.json` e `interruption.json` são o fechamento
da auditoria. O `status: running` original e o monitor `watching` são últimos
registros históricos, não processos ativos nem um aceite.

RSS é residência observada. Um checkpoint de outra tentativa tinha 18.104 KiB
em swap; queda de RSS tem participação de paginação e não prova RAM liberada
ou ausência de vazamento. O heartbeat mede despacho Qt, não latência de frames.
Coletor sintético/janela inicialmente oculta não certificam inventário de
milhares de processos nem duas horas de composição visível.

## Ambiente portátil e validação da migração

O wrapper `dev` usa uv 0.12.10 com SHA-256 dos arquivos oficiais, Python 3.14.7
gerenciado, `uv.lock`, build backend fixado e venvs GUI/headless separados em
`.dev`. Não usa system-site-packages, pip global, perfis de shell ou o `.venv`
antigo. Dependências nativas só são aplicadas pelo comando explícito. Testes
usam HOME/XDG e temporários próprios em disco, lock sequencial e limites de revisão.

Foi feita cópia limpa do checkout, com prefixo gerenciado e HOME inicialmente
vazios e PATH `/usr/bin:/bin`. O bootstrap baixou o uv e Python, verificou a
integridade e instalou o perfil headless pelo lock. O teste de permissões de
runtime revelou uma fixture dependente do umask: `mkdir(0755)` sob umask 077
criava 0700. A fixture agora faz chmod explícito para continuar verificando a
mesma recusa de permissões públicas. O código de proteção não foi relaxado.

Após a correção: **10 testes focados passaram**; suíte headless limpa:
**915 passed, 2 skipped in 22,07 s**. Os dois skips são verificações somente
leitura que exigem Edge real, ausente no HOME descartável. O total coletado
permanece 917. Suíte GUI do mesmo ambiente reconstruído:
**1132 passed, 2 skipped in 41,90 s**; total 1134. Ciclo de vida offscreen:
seis casos passaram. Doctor retornou JSON válido com logs de bootstrap no stderr.
Logs finais e manifesto do ambiente estão em
`docs/handoff/validation/`. O teste usa bibliotecas nativas deste mesmo host;
não equivale a executar o instalador de pacotes em uma distribuição vazia.

O primeiro Actions em Ubuntu 24.04 passou no bootstrap e nas consultas CLI,
mas expôs fixtures que presumiam UID 1000 e runtime de uma sessão gráfica.
O runner usa UID 1001. As fixtures de `/proc`, reaper, watch-list e investigação
agora declaram o UID/contexto correto; os testes de capacidade não dependem de
um desktop real. Não houve relaxamento das proteções do produto. Uma regressão
adicional exige runtime ausente como volume desconhecido. Repetição headless
em namespace UID 1001, sem sessão gráfica: **916 passed, 2 skipped in 15,57 s**.
Essa nova regressão eleva os totais para 918 headless e 1135 Qt.
Perfil Qt no mesmo namespace: **1133 passed, 2 skipped in 35,55 s**.
O primeiro log da CI está preservado em `docs/handoff/validation/ci-first-failure.log`.

## Material preservado e o que reconstruir

Git conserva código, testes, revisão, capturas, logs e pedidos originais. A
cópia privada na conta guarda fonte/histórico e cápsulas de diagnóstico. O
wheel GUI histórico tem SHA-256
`fb3b1d38ef2cb14218eb55695cd6cdeff76a6d510a3b4efe3d9b9b711ea67607`;
seus 100 arquivos Python correspondiam ao pacote fonte. O bootstrap atual deve
reconstruir o ambiente do lock, não instalar silenciosamente esse wheel antigo.

Não é necessário levar os 5 GB antigos de `.scratch`, SDKs, caches ou venvs.
As cápsulas selecionadas conservam diários/fixtures sintéticas necessários à
inspeção, com caminhos e identidades originais; não devem ser executadas ou
reativadas no novo host. O pequeno estado real do Fôlego é exportado separado
e privado: audit, lock e selftest. Não foram encontrados dados de quarentena
real ou backups de navegador nesses diretórios do aplicativo.

Não se migram credenciais, tokens, browser sign-ins ou configurações globais
do Codex/GitHub. Autenticar novamente no novo host. Nenhum autostart, executor
automático ou serviço de limpeza é instalado por esta entrega.
