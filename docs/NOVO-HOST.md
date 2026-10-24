# Recuperar e desenvolver em outro host

## Requisitos reais

Use Linux em disco persistente, x86_64 ou aarch64, com Bash, acesso HTTPS e pelo
menos 4 GiB livres para o primeiro setup. KDE/Wayland é necessário para repetir
o aceite físico do compositor. Em outro desktop/servidor, o núcleo e Qt
offscreen continuam testáveis. Windows nativo não é alvo; WSL2 serve ao núcleo,
mas não certifica o KWin físico. Não usar `/run/user` ou tmpfs para o checkout.

Não é preciso instalar Python, pip, Qt do sistema ou uv previamente. O wrapper
baixa uv 0.12.10, verifica SHA-256 dos arquivos oficiais, instala Python 3.14.7
gerenciado e usa os hashes/versões de `uv.lock`. O perfil headless não instala Qt.
Contas GitHub/Codex precisam ser autenticadas novamente; credenciais não são exportadas.

## Recuperação principal pelo GitHub

Repositório privado: https://github.com/Misael-art/Folego

PR de continuidade: https://github.com/Misael-art/Folego/pull/1.
Todos os pontos de recuperação estão em [handoff/REMOTE.md](handoff/REMOTE.md).

Enquanto o PR não for integrado, continue na branch de entrega:

```bash
git clone --branch codex/portable-handoff-20261024 https://github.com/Misael-art/Folego.git
cd Folego
./dev setup --system-deps
./dev check
./dev gui
```

Faça login no GitHub com um helper de credenciais/`gh auth login` para clonar o
repositório privado. Não colocar token na URL, em scripts ou no histórico shell.
Se ainda não houver Git, baixe a cópia fonte da Página de recuperação, extraia e
execute `./dev setup --system-deps`; o instalador nativo inclui Git.

`./dev system-deps` mostra o plano. `./dev setup --system-deps` aplica pacotes
nativos via apt/dnf/pacman, com sudo quando necessário, sem ativar serviços ou
fazer upgrade da distribuição. Em sistemas rolling, mantenha a base suportada
pelo administrador; o wrapper não força atualização global. Sem privilégio,
use `./dev setup --headless` e peça a instalação das bibliotecas nativas quando
for trabalhar com GUI. O host usado na migração só executou o plano nativo.

## Cópia independente do disco antigo

A entrega guarda uma cópia na [Página privada de recuperação](https://chatgpt.com/space/page_c86741eb68348191a25318610e82b50d),
com links/identificadores registrados no PR e no recibo final. Baixe os anexos e confira
os hashes publicados na Página antes de extrair. O Git bundle contém o histórico
e a branch; a cópia fonte permite começar sem Git. Ambientes e caches são reconstruídos.

Com Git instalado, um bundle pode ser recuperado sem acesso a este disco:

```bash
git clone folego-history.bundle Folego
cd Folego
git switch codex/portable-handoff-20261024
git remote set-url origin https://github.com/Misael-art/Folego.git
./dev setup --headless
./dev test-headless
```

Se o bundle não selecionar uma branch automaticamente, use
`git clone -b codex/portable-handoff-20261024 folego-history.bundle Folego`.
A Página é uma cópia explícita feita nesta entrega; o chat/local workspace não
é tratado como sincronização automática de arquivos entre computadores.

Dados antigos do aplicativo, quando incluídos, são um anexo separado e privado.
Extraia primeiro em diretório de inspeção. Não sobrescrever HOME/XDG atual,
reativar grants, importar PIDs antigos ou executar planos arquivados. Não há
quarentena real ou backup de navegador identificado no inventário desta migração;
o pequeno estado local contém audit e material de selftest, preservados por precaução.

## Uso diário e organização

| Comando | Efeito |
|---|---|
| `./dev setup --headless` | Ferramentas/Python/dependências do núcleo em ambiente próprio |
| `./dev setup` | Ambiente GUI/dev com Qt fixado pelo lockfile |
| `./dev test-headless` | Coleta e executa testes sem importar Qt |
| `./dev test` | Suíte completa com Qt offscreen |
| `./dev check` | Duas suítes sequenciais e diff check |
| `./dev run --help` | CLI instalada no ambiente headless |
| `./dev doctor` | Diagnóstico somente leitura |
| `./dev gui` | GUI real, sem habilitar automação ou autostart |
| `./dev status` | Caminhos e consumo dos diretórios gerenciados |
| `./dev export --output .recovery/novo` | Snapshot fonte + Git bundle de checkout limpo/commitado |

Ferramentas, Python, venvs e caches: `.dev/`. Um setup por vez, downloads/instalações
com concorrência limitada e revisão ao chegar a 10 GiB. O wrapper não modifica
PATH/perfis globais e não usa `sudo pip`. O venv antigo `.venv` não é reutilizado.

Testes: `.scratch/dev-tests/run-*`, com HOME/XDG, TMPDIR, Hypothesis e basetemp
próprios. Um lock evita duas suítes simultâneas. Limites de revisão: 20 sessões,
4 GiB retidos e ao menos 1 GiB livre antes de começar. São guardas cooperativas,
não uma quota do kernel. Logs/run.json ficam disponíveis para inspeção; nada é
apagado automaticamente. Remover só material próprio concluído e revisado, com
nenhum processo ainda usando a árvore; não aplicar limpeza ampla por idade.

O runtime da sessão gráfica (`XDG_RUNTIME_DIR`) é preservado para D-Bus/Wayland;
aplicativo e testes recebem temporários próprios em disco. A proteção do produto
continua verificando o destino no ato de lançar filhos.

## Primeiro pedido ao agente no novo host

> Leia AGENTS.md, README.md, docs/HANDOFF.md, docs/DIAGNOSTICO-2026-10-24.md e
> docs/NOVO-HOST.md. Confira a branch e o commit recuperados. Prepare o ambiente
> com ./dev e valide primeiro o núcleo sem Qt. Preserve automação desligada e
> não toque em processos/dados de trabalho do host. Escolha a primeira pendência
> verificável da passagem, faça um incremento integrado com teste de regressão
> e atualize o estado com evidências reais, sem declarar o soak de duas horas aprovado.
