# Widget compacto, IAs e atalhos — 01/11/2026

Escopo autorizado: implementar os mockups aprovados e preparar commit, PR e
release no GitHub. A distribuição é uma prévia `0.2.0b1`, sem merge e sem
certificar as pendências gerais do produto. Base: `f6fa3e2`.

## Comportamento

- Widget de 280 × 216 px lógicos no estado normal; alertas e feedback podem
  crescer em altura. Cabeçalho com minimizar, ampliar para a central e sair;
  recursos em duas linhas, pausa e quatro indicadores de IAs.
- Monitor próprio, sem import/execução do PhaseZero: Codex local, Claude por
  consulta de uso de primeira parte, Web/Grok desconhecidos quando a fonte não
  fornece cota. Reset/observação vencida não cria 100%; token presente não
  comprova renovação. Falha e troca de conta invalidam a leitura.
- Abas Copiar/Colar/Print/Teclado. Edição por Ctrl+Insert/Shift+Insert, sem
  Ctrl+C que possa interromper trabalhos no terminal. Print abre seleção nativa
  de região, sem afirmar que um arquivo foi salvo. Solicitação em andamento não
  é repetida. Aba do teclado abre sempre embaixo; somente a seta abre no topo.
- Teclado e auxiliar de entrada próprios, sem autostart/serviço novo, instalação,
  ampliação de permissões, alteração de dispositivos existentes ou preferências
  do teclado nativo. IPC curto no runtime; payloads/TMPDIR em disco persistente.

## Verificação

Host Linux BigLinux/Manjaro, Python 3.14.7 e Qt/PySide6 6.12.0 gerenciados em
`.dev`, suítes sequenciais com HOME/XDG privados. `./dev check` passou com
**1061 passed, 2 skipped** headless (18,47 s) e **1320 passed, 2 skipped** Qt
(34,04 s). Os skips exigem Edge real, ausente nas fixtures. Após o ajuste final
de tipografia, a suíte Qt passou novamente: **1320 passed, 2 skipped em
32,88 s**; o log final está em `qt-pytest.log`.
Foco de 63 testes: IAs, CLI, atalhos, compacto e revisão de sessão passou.

Comandos de QA: `.dev/venv-gui/bin/python tools/verify_compact_ui.py --input
--state CAMINHO_PRIVADO`. No X11, usar Xvfb próprio e
`FOLEGO_QA_PRIVATE_DISPLAY=$DISPLAY`; o harness recusa clipboard fora desse
display. Nenhum dado/processo de trabalho foi usado como fixture.

- **KDE/Wayland real:** embaixo → topo → embaixo, geometria confirmada pelo KWin,
  escala fracionária considerada pelos pixels de renderização; uma tecla no
  campo próprio em foco, pausa/retomada, retorno à central e encerramento sem
  auxiliar próprio restante. [Recibo](wayland.json).
- **X11 privado:** mesmas posições e entrada; copiar/colar texto sintético na
  área de transferência desse servidor. [Recibo](x11.json).
- **Print real no X11 privado:** Spectacle abriu sua seleção de região; segundo
  pedido preservou a mesma instância; somente esse filho de QA foi encerrado.
  Não certifica salvar, editar ou capturar o desktop físico. [Recibo](capture.json).
- **Bootstrap oficial:** `folego.app.main`, central → compacto → central → sair,
  exit 0. HOME/XDG próprios; systemctl simulado para não alterar serviços do host.
  [Recibo](launcher.json).
- **Consulta real somente leitura:** Codex e Claude retornaram cotas; Web/Grok
  ficaram desconhecidos. Resposta e metadados de contas não foram publicados.

Tentativas anteriores preservadas: confirmação de geometria integral recusou
a geometria fracionária equivalente; IPC em caminho persistente longo excedeu
o limite do socket Unix; uma prova GUI terminou com erro de destruição Qt após
os passos. Corrigidos comparação de pixels, socket próprio curto e destruição
explícita das janelas ainda com wrappers vivos. Somente a tentativa final com
exit 0 conta como aprovada. Um primeiro teste do bootstrap errou a assinatura
estática de `QApplication.exec`; corrigido no harness, com novo HOME privado.

A primeira suíte headless falhou no teste antigo de revisão de tuning: seu
monkeypatch não substituía o argumento padrão já ligado ao construtor, e o teste
consultava o Edge real. A dependência passou a ser injetada explicitamente na
fixture. Não se fechou o navegador nem se afrouxou proteção de produção.

O teto de 20 workspaces de QA foi revisado manualmente. Quatro execuções
concluídas com sucesso e runner ausente, depois os próprios lotes concluídos
desta tarefa, foram movidos integralmente no mesmo disco para
`.scratch/dev-tests-reviewed`, preservando payloads, logs e recibos. A revisão
inicial está em `review-compact-20261101.json` nesse destino. Não houve adoção
de fixtures, exclusão de payload, alteração dos limites ou limpeza compartilhada.

Pacotes: wheel e sdist produzidos offline; 122 módulos Python do wheel comparados
byte a byte ao fonte. Wheel instalado sem modo editable em `.dev/release-0.2.0b1`:
CLI executada sem Qt; GUI exercitada com Qt 6.12.0 já gerenciado. A tentativa de
resolver o extra GUI totalmente offline não encontrou seus wheels no cache;
nenhum download grande foi iniciado. A reutilização do runtime compatível foi
explicitamente verificada, sem importar o Fôlego do checkout. Isso não certifica
instalação de dependências em outra distribuição. [Recibo](wheel.json),
[inventário e hashes](package-check.json).

## Revisão visual

Fonte: [mockup aprovado](design.png), 1536 × 1024. Captura de cliente nativa:
[compact.png](compact.png), 378 × 292 pixels para 280 × 216 lógicos (135%).
[Comparação normalizada](comparison.png): recorte do mockup 797 × 591 convertido
para largura 280, ao lado do cliente na mesma largura. As capturas não são
imagens do compositor completo. Estados de teclado: [topo](keyboard-top.png) e
[parte inferior](keyboard-bottom.png).

Tipografia, espaçamento, paleta, ícones e conteúdo foram conferidos na imagem
combinada e no cliente legível. O ajuste final aumentou fonte/contraste dos
indicadores. A hierarquia, as duas linhas, a faixa de IAs, as abas coloridas e
as áreas separadas de clique foram preservadas. Variações aceitas: ícones de
janela seguem o tema Qt/KDE; as abas usam rótulos completos sem ícones para
preservar a leitura em 280 px; altura ajusta ao texto e à fonte do desktop.
Não há imagens decorativas substituídas por placeholders.

Resultado visual do incremento: **passed**. A matriz geral de compositor,
hardware, leitor de tela, transições físicas e soak desta revisão continua
pendente; o soak de outra revisão não é promovido a evidência deste código.
Aplicativos de destino precisam aceitar os atalhos alternativos de edição.
Dependências e configuração: [guia do compacto](../../../COMPACTO.md).
