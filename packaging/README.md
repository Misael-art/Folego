# Empacotamento e remoção

## Versões suportadas

- Linux com `/proc` e `/sys` (BigLinux/KDE, SteamOS/Steam Deck).
- Python **3.14.x** (bootstrap fixado em 3.14.7).
- CLI: sem Qt (usa só a biblioteca padrão).
- GUI: PySide6 **6.6+**; o ambiente do projeto usa 6.11.2.
- Wayland: capacidades de posicionamento/keep-above são declaradas não
  comprovadas; a janela compacta e a bandeja são a alternativa.
- Ferramentas externas são opcionais: `git`, `docker`, `podman`, `virsh`,
  `qemu-img`. Ausência não quebra o app (aparece no `doctor` e no `ecosystem`).

## Instalação reproduzível

Para desenvolver em host novo, use primeiro [o wrapper portátil](../docs/NOVO-HOST.md):
`./dev setup --system-deps` e `./dev check`. Ele mantém Python/Qt/caches próprios
em `.dev`, sem depender do venv antigo ou do Qt do sistema.

A instalação manual abaixo continua possível para quem já dispõe de Python compatível:

```bash
python3.14 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev,gui]'
folego --help
folego doctor
```

`run.sh` continua funcionando no checkout (`PYTHONPATH=src`). O entrypoint
instalado é `folego`; sem subcomando ele abre a GUI.

## Launcher desktop (opcional)

Ao abrir a GUI, o Fôlego verifica os atalhos `folego.desktop` no menu (`$XDG_DATA_HOME/applications`) e na Área de trabalho (`XDG_DESKTOP_DIR` de `user-dirs.dirs`): cria o que faltar, atualiza só os que ele mesmo criou (`X-Folego-Managed=true`) quando a instalação muda de lugar e preserva atalhos do usuário. Nunca cria autostart. Manualmente: `folego shortcuts`. O arquivo [folego.desktop](folego.desktop) é o modelo de referência (o teste garante que o gerado em `src/folego/shortcuts.py` coincide).
Quando a instalação é um venv, gere um launcher preso ao entrypoint absoluto,
para funcionar sem depender de um shell com o venv ativado:

```bash
rtk proxy python packaging/make_launcher.py --executable /caminho/venv/bin/folego --output /caminho/para/revisao/folego.desktop
```

O gerador não sobrescreve arquivos existentes e não instala autostart. Revise o
arquivo gerado antes de copiá-lo para o menu do usuário. A cópia estática abaixo
pressupõe que `folego` já esteja no PATH da sessão gráfica.

Para instalar só para o usuário:

```bash
install -Dm644 packaging/folego.desktop ~/.local/share/applications/folego.desktop
```

Para autostart opcional, copie o mesmo arquivo para
`~/.config/autostart/folego.desktop` e revise `Exec=`/`Hidden=`. O Fôlego **não**
instala autostart sozinho; `doctor` apenas reporta se o arquivo existe.

## Remoção preservando dados

```bash
pip uninstall folego
rm -f ~/.local/share/applications/folego.desktop ~/.config/autostart/folego.desktop
```

Não remova `~/.local/state/folego`, `~/.config/folego` ou
`~/.local/share/folego` sem antes exportar/inspecionar o diário, grants,
sessões e quarentenas. A remoção do pacote não deve apagar dados do usuário.

## Migração DeckWellness → Fôlego

```bash
folego migrate                 # dry-run: lista o que seria copiado
folego migrate --confirmar     # copia; a origem permanece
```

- A cópia nunca sobrescreve o destino: se ele já tem conteúdo, o legado vai para
  `migrated/deckwellness-<carimbo>/`.
- Links simbólicos bloqueiam o plano inteiro.
- Um marcador em `~/.local/state/folego/migration.json` registra
  `started`/`failed`/`completed`; uma execução interrompida não é repetida às
  cegas.
- Rollback = voltar a apontar a versão antiga para a árvore DeckWellness; nada
  foi apagado.

## CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) roda a suíte completa
com Qt offscreen e um smoke do CLI sem display. Nenhum job usa aplicações ou
configurações reais do usuário: `HOME`/XDG são temporários e as fixtures usam
`.scratch`.

O job puro usa `pytest --without-qt`: `tests/conftest.py` exclui módulos
`test_ui_*` e os dois módulos de workers antes da importação. Novos testes Qt
devem seguir essa organização. A validação local em 18/10/2026 usou um venv
  criado sem `--system-site-packages`, instalando apenas `.[dev]`: 917 testes
passaram sem PySide6/shiboken6. Isso não equivale à execução remota do Actions
nem à validação de instalação GUI/launcher em outra distribuição.

## Limites desta preparação

- Validação local nova em 18/10/2026: wheel GUI instalado sem system-site-packages
  (Qt 6.12), launcher por GIO com PATH do sistema sem venv ativado, remoção com
  estado preservado e testes em KDE/Wayland físico e KWin isolado. Resultados,
  escopos e estado do soak em
  [validação de desktop](../docs/reviews/2026-10-18/desktop-validation/README.md).
  Isso é instalação limpa no mesmo BigLinux, não outra distribuição/VM limpa.
- A validação visual real em KDE/Wayland (DPI, hotplug, foco, fullscreen) ainda
  tem limites: físico em 135%, outras escalas/hotplug em compositor virtual;
  leitor de tela e login físico X11 permanecem pendentes.
- A instalação em uma máquina Linux limpa e o ensaio prolongado de memória/
  QProcess ainda são evidências pendentes de F8.
- O empacotamento não inclui assinatura, repositório APT/Flatpak nem integração
  com a loja; isso fica para a distribuição.
