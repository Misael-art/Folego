# Passagem para o próximo agente — atualizada em 02/11/2026

## CPU da GUI no pulso de entregas — 03/11/2026

A thread da GUI consumia ~35% de CPU: o pulso infinito de entregas redesenhava o
anel a cada quadro, inclusive minimizado. `_pulse_deliveries` agora redesenha em
passos de 1/8 e pausa com a janela minimizada. Host real (KDE/Wayland), GUI
reaberta pela bandeja e `./dev gui`: 353 → 55–57 ticks/10 s (inferência causal,
sem A/B). Removidos, com aprovação, 9 runs anônimos `passed` de QA. Testes:
headless **1185 passed, 2 skipped**; Qt **1503 passed, 2 skipped**. Próximo:
oportunidades levantadas no host (agrupar árvores Electron/navegador, MCP
duplicado, units falhadas, PSI, inventário de cache).

## Limits do Codex Web alinhado ao 6.1.17 — 03/11/2026

- `web_limits` passou a exigir `initializedAt` válido e a recusar eventos anteriores a ele, como faz o store do app.
- Janelas que começam antes do início da contagem mostram "contagem iniciada em …".
- A fonte informa que o número é um piso: só conta mensagens Pro enviadas pelo app.
- O motivo `unsupported` avisa que, se a verificação falhar, o app precisa de atualização. Hoje o seletor do composer no 6.1.17 está quebrado no ChatGPT, e a correção fica no upstream.
- A tabela do 6.1.17 confere com `WEB_LIMITS` (gpt6Weekly 200, solDaily 170, combinedDaily 200, combinedWeekly 50).
- Testes: headless 1185 passed/2 skipped; Qt offscreen 1502 passed/2 skipped.

## Atalho e data do Limits do Codex Web — 03/11/2026

O launcher não tem deep link nem API externa para a verificação de plano do
Limits; ela continua um clique do usuário no aplicativo (modo Automatic exigido,
conferido como `automatic` no host). Hover agora mostra data e resultado da
última verificação; botão direito do Codex Web ganhou **Abrir Limits no Codex Web**,
pelo mesmo abridor existente (`agent-open`). Menu separado em `options_menu`
para teste sem `exec`. Testes HOME novo: headless **1183 passed, 2 skipped**;
Qt **1500 passed, 2 skipped**. GUI reaberta pela bandeja, compacta.

## Codex Web pelo Limits e renovação do Claude — 03/11/2026

Correção do usuário: Codex Web é túnel da cota ChatGPT Web da conta Principal
(Pro), não a cota Codex da conta logada na raiz (MHMAIL). A leitura Codex da
raiz Web foi removida. Fonte agora: `launcher-data/limits.json` do próprio
aplicativo (mesma tabela oficial: GPT-6 Pro 200/7 d, GPT-5.6 Pro 170/24 h,
combinado 200/24 h; Pro 5x 50/7 d), janelas móveis contadas como no app.
No host o arquivo está `unsupported`, sem eventos desde 19/10: **?** até o usuário
refazer a verificação em Limits no aplicativo com a conta Pro.
Claude: token vencido com renovação válida pede ao cliente oficial
`claude doctor` (sem inferência, cwd temporário, variáveis `CLAUDE_CODE_*` do host
removidas), no máximo uma vez a cada 10 min por raiz; falha mantém **?**. Só no
coletor nativo; testes nunca executam o cliente. Host: Claude 70%, Grok 0%.
Testes com HOME novo: headless **1182 passed, 2 skipped**; Qt **1498 passed,
2 skipped**. Falha de `test_ui_capture_alerts` vista antes era resíduo de QSettings
de HOME reaproveitado pelo agente, não do código.

## Leitura de cota Codex Web, Claude e Grok — 02/11/2026

Sobre `51e3fed8ea5c728163f094feef9ca8288f6a954f`, mesma raiz/branch/PR #1.
**Grok:** o próprio CLI responde `_x.ai/billing` via ACP stdio (`initialize` +
billing, sem prompt, cwd temporário vazio, sai no EOF). `creditUsagePercent`
e `currentPeriod` viram janela (Semana/Mês/Dia) com reset; plano do
`subscription_tier`. Cache de 5 min por raiz/auth; troca de auth descarta.
**Codex Web:** a raiz Web usa a mesma consulta oficial do Codex da sua conta;
fonte rotulada como cota Codex da conta (turnos `chatgpt-web/` não trazem limite).
**Claude:** token de acesso vencido com renovação local válida não é mais
"login expirado"; mostra plano, validade da renovação e pede uso do Claude Code.
Fôlego continua sem renovar credenciais; a cota volta quando o cliente renovar.

No host (CLI, mesmo `collect`): Codex 30%, Web 18%, Grok 0% SuperGrok
(semana até 07/11), Claude **?** com token local vencido em 01/11. Sem processo
Grok remanescente. Testes: headless **1176 passed, 2 skipped**; Qt offscreen
**1492 passed, 2 skipped**, sequenciais, HOME/XDG/TMP privados no scratchpad
do agente — `./dev test` recusou por 20 workspaces retidos em `.scratch/dev-tests`
(nada apagado; inspecionar antes de liberar). GUI em execução ainda carrega o
código anterior até ser reaberta pela bandeja. Reaberta depois: "Sair do Fôlego"
via DBusMenu (PID 1827618, starttime conferido) e uma chamada `./dev gui`; novo
PID **2275351**, starttime **10748131**, compacto restaurado pela bandeja.
Anéis na GUI real: Codex 30, Codex Web 11, Claude ?, Grok 0.

## Medidores circulares animados de IA — 02/11/2026

Sobre `0239f4921e144ac839c5a4ead86c5d315bbf921d`, mesma raiz/branch/PR #1.
Código, testes e provas em `604f1f515cfcc929133d4393177addc0fd9baa47`.
Codex, Codex Web, Claude e Grok seguem o medidor circular do PhaseZero:
disco de identificação, percentual disponível no centro e arco de cota.
Nome completo Codex Web, entregas/presentes abaixo e largura de 280 px.
Dados vêm do monitor existente, sem importar/iniciar PhaseZero. Fontes sem
percentual, antigas ou incompletas mostram **?** com anel cinza; zero mostra
**0** com arco vazio. Padrão de cores da referência preservado entre temas
e transparência. Contas, hover, cliques e presentes mantêm seus contratos.

Transição de 450 ms entre valores conhecidos; número/descrição atuais desde
o início. Expiração/falha cancelam imediatamente. Entregas confirmadas fazem
a borda interna pulsar em 1,8 s, separada de cota/tickets. Sem contagem
confirmada ou widget visível, não pulsa; ocultação para todas as animações.
O monitor de consultas continua independente da visibilidade.

Focados **16 passed**, 1,48 s. `./dev check`: **1168 passed, 2 skipped**
headless, 25,31 s; **1484 passed, 2 skipped** Qt, 97,45 s. Python 3.14.7,
sequencial, HOME/XDG/TMP/Pulse privados. Oito cenários KDE/Wayland aprovados:
três combinações de tema/transparência, animações, expiração, clique/hover
nativos, presente por Qt, ocultação, Central/Voltar e saída. Inspeção visual
das capturas próprias em 135%, nomes inteiros e contadores sem sobreposição.
Abertura do cliente interceptada em memória; métricas/contas sintéticas.
[Provas, comandos e limites](handoff/validation/ai-quota-rings-2026-11-02/README.md).

Primeiro QA nativo não aprovado: hover abriu o painel durante calibração e
interceptou o clique. Corrigida a sequência do harness, mantendo 45 s e a
tentativa anterior. Baseline remoto já tinha Qt vermelho em duas variantes
de transparência de texto com fonte Ubuntu (alpha 250/244, linha 31).
Asserção preservada e nenhuma alegação de CI inteiramente verde.

GUI real atualizada pela saída da bandeja e uma chamada `./dev gui`, com
lock liberado e posição/preferências preservadas. Novo PID **1827618**,
starttime **10085542**, widget (2902,197;33,954), 280×217, central oculta.
Recibo privado `.scratch/dev-tests/run-ta5pjkkq/host-replacement/replacement-primary.json`,
com boot/identidade observados após a saída do launcher. Revalidar antes de
agir. QA/auxiliares encerrados, nenhum trabalho alheio sinalizado e nenhum
diretório anterior apagado. Sem release/merge/grant; b2 imutável.
Próximo passo: usuário conferir os sinais nas suas contas; Web/Grok continuam
sem fonte percentual confirmada. Matriz geral de desktop permanece parcial.

## Transparência dos fundos e painel contínuo — 02/11/2026

Sobre `fdceab8095c62a68e3efdc32f942b959a91608ce`, mesma raiz/branch/PR #1.
Código, testes e provas em `c28b8d4eedd763fb72b82922f87c1e6f6d4aa87e`.
Complemento do preenchimento primário e focados em `6c653cd20d6c984cc6717631444f660ae746fb89`.
Corrigidos estilos genéricos que pintavam rótulos/contêineres como caixas no
painel de contas. Popup sem moldura preta, superfície única arredondada,
filhos transparentes e cartão de janela de uso com seletor próprio.
Barra em opções/Aparência, 0% opaco a 100% sem fundo, padrão 0%. Muda pinturas
de fundo de todas as superfícies; conteúdo/contornos/indicadores continuam
opacos e windowOpacity fica 1. Prévia durante arraste sem I/O de configuração,
salvamento ao soltar e por teclado/acessibilidade, preservação entre temas e
restauração ao abrir. QSettings existente, `appearance/background_transparency`.
Inválido é informado sem sobrescrever; falha de gravação restaura o estado.

ARGB preparado antes de mapear. Raízes com WA_NoSystemBackground pintam QSS
explicitamente; diálogos e superfícies novas seguem o tema. Checkbox desmarcado
mantém contorno e estado distinto. Nenhum novo serviço, grant ou operação de
recurso. Fontes e dados das contas permanecem nos seus owners existentes.

`./dev check`: **1168 passed, 2 skipped** headless (50,68 s) e **1473 passed,
2 skipped** Qt (142,25 s). Após a regressão de checkbox, Qt final `./dev test`:
**1478 passed, 2 skipped**, 126,64 s. Focados finais **15 passed**, 3,84 s, incluindo preenchimento primário
e estados de checkbox.
Python 3.14.7, sequencial, HOME/XDG/TMP/Pulse privados. Host com carga 18–20,
sem encerrar trabalhos alheios. Duas execuções KDE/Wayland de sete cenários,
SNES/PS2 com 0/50/100%, cinco superfícies, salvamento, navegação e saída.
Composição real por portal sobre fundo próprio: alpha 8 bits, mistura de 50%
coincidiu exatamente nos dois pixels medidos; textos e indicadores opacos.
Captura pública retém somente recorte interno do fundo próprio na escala 135%.
[Provas e limites](handoff/validation/background-transparency-2026-11-02/README.md).

Tentativas interrompidas preservadas. Oráculo corrigido para medir popup nativo,
em vez de QWidget filho com preenchimento sintético de raiz. Perfis finais
separados para respeitar os 45 s existentes, sem somar tentativas como aprovação
ou ampliar watchdog. QA/auxiliares encerrados. Sem release/merge; b2 imutável.
GUI real substituída por Sair na bandeja e `./dev gui`, lock liberado e sem
sinais manuais/outros clientes encerrados. PID **586685**, starttime **7047120**,
widget (2702;32,885), 280×219, central oculta; posição e tema atuais preservados.
Recibo final privado `.scratch/background-transparency/replacement-primary.json`.
Revalidar identidade/boot antes de agir. Próximo passo: usuário regular a barra
em Central → opções → Aparência · consoles clássicos.

## Temas de consoles em toda a interface — 02/11/2026

Sobre `1cf92789aa10eaad608956cab6d5c9eb4799d82c`, mesma raiz/branch/PR #1.
Código, testes e provas em `4f64b091e04b62303f5b3848c14b2dee2ce681eb`.
Seletor no topo de opções: oito temas do anexo (SNES americano, SFC, Mega Drive,
Master System III, PC Engine, NES, TurboGrafx-16 e PS2). Padrão SNES americano.
Tokens compartilhados, receitas nos próprios widgets e atualização em uso de
central, compacto, prompts/submenus/Custom, contas e teclado, mesmo ocultos.
Ícones de controles e sinais redesenhados com a paleta; alertas preservam
semântica/texto. Sem recriar monitores, alterar grants ou fontes de conta.
Preferência `appearance/theme` na autoridade QSettings existente; restauração,
chave desconhecida informada sem sobrescrever e falha de gravação explícita.

Focados finais **46 passed**, 16,09 s. `./dev check`: **1168 passed, 2 skipped**
headless (48,15 s), **1465 passed, 2 skipped** Qt (120,81 s), Python 3.14.7,
sequencial, HOME/XDG/TMP/Pulse privados. Contraste texto/semântico/categorias
4,5:1 nas três superfícies, tinta dos botões, foco, persistência e views abertas,
ocultas e futuras. Doze cenários KDE/Wayland, oito temas selecionados e salvos
com clique nativo e navegação Qt no popup; capturas de quatro superfícies por
paleta. Inspeção visual das matrizes de widget/prompts/teclado e central.
Dados de demonstração, sem clipboard/processos/textos do usuário como fixtures;
teclado validado na apresentação, sem repetir efeitos de digitação/volume.
[Provas e limites](handoff/validation/console-themes-2026-11-02/README.md).

CI anterior do SHA base tinha Qt vermelho por larguras 91/88 na fonte Ubuntu;
política horizontal dos seis botões corrigida para preservar colunas iguais,
sem afrouxar a asserção. Núcleo/CLI anteriores verdes. Tentativas de QA
interrompidas preservadas; harness ajustado para clique nativo no seletor e
navegação no popup próprio. Sem novo release/merge; b2 continua imutável.
GUI real substituída pela ação Sair na bandeja e `./dev gui`, com lock
liberado, sem sinais manuais ou outros clientes encerrados. PID **389475**,
starttime **6736851**, widget (3108,315;187,814), 280×219, central oculta.
Posição atual do usuário preservada. Recibo privado
`.scratch/console-themes/replacement.json`; revalidar identidade/boot.
Consulta ampla lslocks excedeu o prazo antes da intenção, sem efeito; autoridade
confirmada por flock não bloqueante e fdinfo do inode exato, evitando varrer
outros processos. Próximo passo: usuário escolher a paleta em
Central → opções → Aparência · consoles clássicos.

## Atalhos recolhíveis e temperatura — 02/11/2026

Sobre `b2969ac5280cc2ed477b258ddbe13701264c3332`, mesma raiz/branch/PR #1.
Código, testes e provas em `ee4a756203d7e1708e0ecda0d31d5383a88195ee`.
Seis atalhos pareados em duas linhas iguais, ocultos em repouso, animação
descendente de 140 ms e espera de 200 ms ao sair; menus preservam a escolha.
Teclado no cabeçalho, padrão embaixo e seta separada para cima. CPU/Tmp
alinhados e temperatura em °C à direita da CPU. O antigo Temp era ocupação
de tmpfs: agora Tmp, sem inventar relógio. CPU/SoC preferenciais, ACPI de
sistema como fallback identificado; ausente/ilegível permanece — °C. Leitura
no coletor, somente sysfs, sem Qt no núcleo ou ajuste de ventoinhas.

`./dev check`: **1168 passed, 2 skipped** headless (21,64 s) e **1453 passed,
2 skipped** Qt (45,89 s), Python 3.14.7 gerenciado, HOME/XDG/TMP/Pulse privados,
sequencial. Doze cenários finais KDE/Wayland: recolher/revelar, prompt e seis
macros com foco preservado, navegação e saída. Corrigida reconciliação de Enter
sintético do Qt ao fechar popup e entrar em outra superfície. Guardas de PID
e posição mantidos; tentativas anteriores preservadas e não somadas como
aprovação. Inspeção visual das capturas próprias: botões iguais, teclado
disponível, métricas legíveis e alinhadas. Temperatura da captura é demonstração.
[Provas e limites](handoff/validation/hover-actions-2026-11-02/README.md).
Sem release/merge ou ampliação de grants. GUI real substituída por Sair na
bandeja e `./dev gui`, com lock liberado, sem sinais manuais/outros clientes.
PID **234379**, starttime **6504957**, widget (3108,315;187,814), 280×219,
central oculta. Preservada a posição atual do usuário; revalidar identidade/boot
antes de agir. Recibo privado `.scratch/hover-actions/replacement.json`.
Sensor de sistema `acpitz` disponível no host, leitura real somente leitura;
não tratado como prova de temperatura de CPU. Próximo passo: usuário validar
o hover e a disposição dos controles na instância atual.

## Seletor com faixas laterais aprovado — 02/11/2026

Sobre `1512658a885c6574b1525bd69401c893a3c3be77`, mesma raiz/branch/PR #1.
Código, testes e provas em `0c592a162f0ed2c97ef0d769bc83861bea05b86b`.
Opção aprovada implementada no próprio Qt: 12 títulos em seis categorias com
faixas coloridas, cabeçalhos horizontais e copiar por linha. Painel até 480×540,
rolagem e rodapé fixo com Janelas/Edição/Terminal/Custom. Setas/Tab/Enter/Escape;
nomes longos quebram linha. Categorias no catálogo Qt-free, sem mudar os corpos
dos prompts. Custom preservado, carregado no worker e sem migração/regravação.
Menus fecham antes de copiar/solicitar macros para retornar o foco ao destino.

Focados finais **20 passed**, 5,61 s. `./dev check`: **1165 passed, 2 skipped**
headless (21,16 s), **1448 passed, 2 skipped** Qt (44,62 s). Python 3.14.7,
sequencial, HOME/XDG/TMP/Pulse privados. Onze cenários finais KDE/Wayland com
cliques em prompt e seis macros, foco e navegação. Clipboard/colagem integral
em Xvfb próprio; Custom/Mostrar área de trabalho em KWin/Xvfb/D-Bus isolados.
Guardas de ponteiro mantidos; rota entre saídas com escalas distintas corrigida
no harness após bloqueios. Auxiliares de QA encerrados.

Comparação visual conjunta e detalhe em [design-qa.md](../design-qa.md), resultado
passed. Corrigidos separadores/ícones afetados pelo estilo herdado e densidade
inicial. Último título pode exigir rolagem na fonte nativa, com rodapé preservado.
Ícones de tema com fallback Tabler/MIT incluídos no wheel; offline build e bytes
de todas as fontes/assets verificados, sem dados privados no pacote. Sem release,
merge, regra persistente ou ampliação de grants. [Provas e limites](handoff/validation/prompt-groups-2026-11-02/README.md).

Após o commit, GUI real substituída por Sair na bandeja e `./dev gui`, com lock
liberado, sem sinais manuais ou encerramento de outros clientes. Nova GUI
**126200**, starttime **6331748**, widget (439,695;97,407), 280×274,815, central
oculta; posição atual do usuário preservada. Recibo privado
`.scratch/prompt-groups/replacement.json`. Revalidar lock/PID/starttime/boot antes
de agir novamente. Próximo passo: usuário validar o seletor em Prompts. Publicação
de b2 continua imutável.

## Prompt de Product Design para seleção — 02/11/2026

Sobre `f82e9974937de69ce312ff5149551f13c12b33d6`, mesma raiz/branch/PR #1.
Código, testes e provas em `9b138147918266e3f725fb87d79c1dd5d530c72a`.
Incluído **Design e mockups para aprovação**, ID `design-mockups`, logo após
usabilidade. Texto integral do anexo do usuário, 9866 bytes UTF-8, SHA-256
`679b411c224337653971fe662e62a854f704a703203310f393c59bed06b0e8a9`.
Sem adicionar o preâmbulo genérico neste item; contexto dos demais preservado.
Biblioteca com 12 títulos, corpo embutido no Python, sem depender do caminho
do anexo. O conteúdo é um prompt para copiar, não uma instrução executada neste
lote. Não foram produzidos mockups nem alterado o design por causa do texto.

Focados: **11 passed** Qt (1,54 s) e **2 passed** headless (0,27 s), Python
3.14.7, sequenciais, HOME/XDG/TMP/Pulse privados. Cópia real do menu e colagem
Shift+Insert em Xvfb próprio preservaram texto/hash e Custom `123`. KDE/Wayland:
cinco cenários incluindo clique nativo no novo título; clipboard interceptado
somente no QA para não usar o físico como fixture. Aguardar escala do popup e
posicionar seu próprio widget corrigiu o oráculo sem afrouxar guardas. Não
repetidas suítes integrais neste incremento de conteúdo. [Provas e limites](handoff/validation/design-prompt-2026-11-02/README.md).

Fôlego substituído pela bandeja e launcher oficial, lock liberado e sem sinais
manuais. GUI **4108311**, starttime **5992098**, compacto (2958,549;116,584),
280×275, central oculta; posição do usuário preservada. Recibo privado
`.scratch/design-prompt/replacement.json`; revalidar identidade/boot. QA e
auxiliar encerrados. Sem release/merge; próximo passo: usuário selecionar o
novo título e colar o prompt no agente desejado.

## Atalhos padrão em Janelas, Edição e Terminal — 02/11/2026

Sobre `dca7f88b5608f83a4eebbe8ac0e55692dee84e26`, mesma raiz/branch/PR #1.
Código, testes e provas em `dc5ba8a6116bb2e988c780c6a20075207af4fad6`.
Pedido atual implementado: dez atalhos sugeridos, em três submenus de Prompts,
antes de Custom (continua o último). Janelas: Alt+Tab, Meta+W, Meta+Left/Right.
Edição: Ctrl+Z, Ctrl+Shift+Z, Ctrl+S, Ctrl+F. Terminal: Ctrl+Shift+C/V.
Catálogo Qt-free com IDs estáveis, exibe combinações sem registrar atalhos
globais; escolha solicita uma combinação pelo worker/backend existente.
Custom não é migrado nem regravado: padrões disponíveis também em instalação
existente, sem recriar exemplos removidos ou bloquear por arquivo inválido.
Editor da central informa onde encontrar os novos grupos.

Focados **44 passed**, 2,87 s. `./dev check`: **1162 passed, 2 skipped** headless
(28,75 s), **1441 passed, 2 skipped** Qt (57,80 s). Python 3.14.7, sequencial,
HOME/XDG/TMP/Pulse privados, limites do wrapper mantidos. KDE/Wayland: quatro
cenários de navegação mais seis macros por clique nativo. Desfazer/refazer
alteraram campo próprio; demais combinações chegaram a bindings Qt próprios,
com retorno do foco, sem arquivo/clipboard físico. As quatro associações globais
de Janelas foram conferidas somente por leitura. [Provas e limites](handoff/validation/default-shortcuts-2026-11-02/README.md).

Fôlego substituído pela bandeja e launcher oficial, sem sinais manuais. GUI
**4071137**, starttime **5940425**, widget (2958,549;116,584), 280×275, central
oculta; posição do usuário preservada. Recibo `.scratch/default-shortcuts/replacement.json`.
Revalidar identidade/boot antes de qualquer ação. QA e auxiliar encerrados.
Sem release/merge neste lote; próximo passo é o usuário validar os atalhos nos
aplicativos usados. Outros aplicativos podem remapear combinações.

## Presente verde para tickets de redefinição — 02/11/2026

Incremento sobre `0c1ca41f9c2eb9f75d146b8e0e9cadec8ea510fe`, mesma raiz/branch/PR #1.
Código, testes e provas em `a475b005fb7e0aff1795b4351d99a2eefc773a73`.
Pedido atual: pequeno presente verde piscando com quantidade ao lado das entregas.
Implementado na linha existente de 14 px, mantendo largura de 280 px. Soma
somente tickets confirmados das contas daquele provedor; 9+ no badge e número
exato/contas no tooltip. O clique escolhe uma conta com tickets, preferindo a
padrão. Hover comum continua na padrão; sem resgate ou alteração de cota.

Um timer de 800 ms alterna intensidade sem sumir com o número e para ao ocultar
ou encerrar. Validação única Qt-free, usada por badge/painel/CLI: desconhecido,
futuro, malformado, mais de 15 minutos ou validade conhecida passada não exibem
presente. Corrigido parser que descartava expiração passada de ticket disponível,
perdendo o limite de validade. Suporte visual comum aos quatro indicadores;
atualmente a fonte confirmada de tickets é Codex. Não criar ofertas por inferência.

Focados **43 passed** (2,02 s). `./dev check`: **1151 passed, 2 skipped** headless
(28,95 s), **1429 passed, 2 skipped** Qt (49,21 s). Python 3.14.7, sequencial,
HOME/XDG/TMP/Pulse privados. KDE/Wayland: cinco cenários com dados próprios,
timer real, clique nativo em presente, conta secundária e invalidação, sem
credenciais/resgate ou efeitos em outros clientes. Prova inicial detectou o
min-height do tema cortando o botão; corrigido e coberto. Evidência final aguarda
escala/DeferredDelete antes de fotografar o painel. [Provas e limites](handoff/validation/reset-gifts-2026-11-02/README.md).

GUI real substituída pela bandeja e `./dev gui`, sem sinais manuais: PID **3445610**,
starttime **5247515**, compacto (2804,553;185,362), 280×275, central oculta e
posição do usuário preservada. Recibo `.scratch/reset-gifts/replacement.json`;
revalidar identidade/boot antes de ações futuras. QA e seu auxiliar encerrados.
Sem merge/release; b2 publicado continua imutável. Próximo passo: usuário conferir
o presente nas contas cujas fontes confirmem tickets; demais fontes permanecem
sem aviso em vez de receber contagem inventada.

## Voltar e cabeçalhos sem controles de janela — 01/11/2026

Sobre `c2b67d5c013ecd712fc06f54b67fc6cb54b36399`, mesma raiz/branch/PR #1.
Código, testes e provas em `8494fd57945401dcbbbc8aeeb26e123d9dac3795`.
Pedido implementado nas duas interfaces, conforme hipótese comunicada durante
o lote (pergunta opcional de escopo não recebeu resposta). Central sem barra
nativa de minimizar/maximizar/fechar, com **Voltar** no cabeçalho. Mostra o widget
e oculta a central sem perder a aba/draft nem parar monitoramento. O widget usa
**Central** e **Controles**, com Ocultar widget e Sair do Fôlego. Encerramento
explícito pelo menu ou bandeja; fallback sem bandeja preserva rota de retorno.
Nenhum grant, operação de recursos ou regra persistente do KWin novo.

Verificação: `./dev check` com **1148 passed, 2 skipped** headless (22,62 s).
Qt final `./dev test`: **1424 passed, 2 skipped** (40,24 s); ajuste só visual
do ícone Central seguido de **51 passed** focados (4,50 s). Python 3.14.7,
sequencial, HOME/XDG/TMP/Pulse privados. Guarda de 20 workspaces respeitada;
sessões concluídas revisadas e preservadas em
`.scratch/dev-tests-reviewed/20261101-navigation`, sem remoção ou ampliação.

KDE/Wayland real: quatro casos aprovados, central sem moldura (frame=client no
compositor), Voltar sem bandeja, retorno à mesma aba com worker ativo e saída
por clique nativo em Controles. Menu sem foco usa popup após soltar o botão;
InstantPopup não manteve o menu aberto neste compositor. O primeiro oráculo
`noBorder` era inadequado ao KWin 6.7.4: representa política, não moldura
efetivamente desenhada. Ensaios incompletos preservados, sem virarem aprovação.
[Provas e screenshots](handoff/validation/navigation-2026-11-01/README.md).

Instância real substituída por Sair na bandeja e launcher oficial, sem sinais
manuais ou encerramento de clientes de IA. Nova GUI **1543441**, starttime
**2203999**, compacto (2946,635;121,240), 280×275; posição do usuário preservada,
central oculta. Acessibilidade nativa confirmou Voltar, Central e Controles na
instância nova. Recibo `.scratch/navigation-host/replacement.json`; identidade e
boot precisam ser revalidados antes de qualquer ação futura. Auxiliares de QA
encerrados. Versão não avançada, sem novo release/merge. Próximo passo: validação
do usuário; arraste físico e outro compositor não foram certificados neste lote.

## Apagar em Chromium, opção de captura e sons — 01/11/2026

Sobre `cc2f3bf993d0e49726da399ae16bc6c24c2f39d5`, mesma raiz/branch/PR #1.
Edição corrigida em `6396a527c03e1ed7e44a74a7ce5e8f2e942241ee`.
Captura, sons e gates finais em `c59670d8fcaa9ea65784a1a4cccb89ca1d10a018`.
Chrome próprio reproduziu a falta de EditableText apesar de Text/entry editável.
Agora seleciona o campo exato por AT-SPI, aguarda a seleção inteira, revalida
foco/identidade/tamanho e envia um Backspace. Sem Ctrl+A global, clipboard ou
conteúdo em logs; confirmação trata o terminador de campo vazio. Quatro casos
DOM passaram: contenteditable com estado controlado/textarea, com/sem seleção.

Opções, com rolagem e controles legíveis: **Incluir widget flutuante no print**
marcado por padrão. Desmarcado oculta widget/teclado antes do Spectacle próprio
e os restaura ao fechar/cancelar, inclusive posição confirmada no KWin. Somente
Print do Fôlego; não afeta atalhos/capturas externas. Falha de abertura restaura.

Sons ligados por padrão: quatro melodias de conclusão e três de franquia (20%,
zero, reposição confirmada), preview e opt-out na GUI. Monitor único compartilhado
com central/widget, ativo enquanto o app estiver aberto. Todas as contas;
desconhecido/vencido não cria transição, histórico antigo não toca ao iniciar e
primeira conclusão nativa posterior à abertura ainda avisa mesmo se o provedor
antes era indisponível. IDs deduplicados e fila limitada a sete identidades.

Volume temporário de pelo menos 85%, desmute e restauração por canal/mudo,
preservando ajuste concorrente do usuário. Usa saída já padrão, sem mudar perfil,
serviço ou grants. Intenção privada antes do efeito, servidor/saída/boot revalidados,
registro pendente reconciliado na abertura; desconhecido bloqueia restauração
cega. Registro em `~/.local/state/folego/audio-volume.json`. Código Qt só na UI;
núcleo/CLI continuam independentes. O wrapper de testes agora isola também Pulse.

`./dev check` final: **1148 passed, 2 skipped** headless (29,23 s), **1422 passed,
2 skipped** Qt (52,45 s), Python 3.14.7 gerenciado, sequencial, HOME/XDG/TMP
privados. KDE/Wayland: **11 casos** com captura incluída/oculta, fechamento do
filho Spectacle sem salvar região e retorno do widget/teclado/posição. Áudio:
sete sons reais em PipeWire/Pulse/WirePlumber próprios, saída nula, namespaces,
runtime físico e dispositivos ocultos; canais/mudo originais restaurados.
Leitura somente consulta de recibo na instância real também confirmou restauração
e igualdade com os valores anteriores. Não foi disparado preview físico pelo QA.
[Provas, screenshots, falhas e limites](handoff/validation/editing-capture-audio-2026-11-01/README.md).

GUI substituída por saída normal da bandeja, lock liberado e launcher oficial.
Instância final **1211686**, starttime **1722544**, compacto em (19;132,185),
280×274,815, central oculta; posição escolhida pelo usuário preservada. Histórico
de substituição em `.scratch/capture-sounds/final/replacement.json`; nunca usar
PID deste registro sem nova identidade/boot. Nenhum cliente de IA, agente ou
serviço de áudio/entrada físico foi encerrado. Auxiliares de QA encerrados.

Versão continua posterior à tag v0.2.0b2, sem novo release/merge. Próximo passo:
usuário validar o campo específico do Codex e audibilidade/identidades com
**opções → Testar som**. Provas não certificam todos os clientes, saída física,
imagem final salva ou capturas externas. Limites do motor de recursos permanecem.

## Custom: textos e macros pessoais — 01/11/2026

Incremento sobre `eeba357f287da7a4f18c879d6a8665e810d02954`, na mesma raiz,
branch e PR #1. Código/QA em `2f80a594f27b6d93725c152f0c2e6e12fea02d39`.
Pedido atual implementado: último item **Custom** em Prompts,
submenu de textos/macros e editor na aba **prompts** da janela principal, com
**+ Texto**, **+ Macro**, Salvar, Remover e Atualizar. O exemplo inicial é
literalmente **123**, sem espaços, tanto no título quanto no clipboard.
Macro inicial **Mostrar área de trabalho**; outras macros aceitam um atalho
de teclado. A pergunta opcional sobre comandos de terminal não foi respondida;
adotado o modelo de atalho, conforme o exemplo do usuário. Não há shell.

Configuração própria privada e limitada, defaults só quando ausente, vazio
persistido respeitado, revisão contra gravação concorrente/menu antigo e
arquivo desconhecido preservado. Leitura/gravação/desktop fora do loop Qt.
No ensaio nativo, qdbus transitório desfazia Mostrar área de trabalho ao sair;
corrigido com QtDBus persistente fornecido pela GUI, mantendo core/CLI sem Qt.
Já visível não alterna, efeito enviado uma vez e estado confirmado.

Gates finais: headless **1133 passed, 2 skipped**, 39,93 s; Qt **1402 passed,
2 skipped**, 52,08 s. Python 3.14.7 gerenciado, sequencial, HOME/XDG/TMP privados.
Tentativas anteriores preservadas: deadline variável no teste Hypothesis de
backup (repetição focada passou sem mudar limite) e expectativa antiga das abas,
atualizada para incluir prompts. Workspaces completos revisados/preservados
em `.scratch/dev-tests-reviewed/20261101-custom`, sem excluir fixtures.

KDE/Wayland real: nove casos aprovados, widget 280×275, edição/salvamento em
HOME próprio, contas e teclado com cliques/AT-SPI em campos descartáveis.
Clipboard Xvfb confirmou cópia/colagem exata de 123. Macro desktop e Ctrl+A
acionadas pelo submenu no KWin/Xvfb/D-Bus em namespaces privados, runtime
físico oculto: desktop confirmado, repetição não alterna, seleção do alvo
próprio confirmada. Não minimizou janelas físicas nem reiniciou serviços.
[Provas, screenshots e limites](handoff/validation/custom-prompts-2026-11-01/README.md).

A instância anterior 710222 já estava ausente, sem lock GUI, antes da tentativa
de substituição; nenhum efeito de encerramento foi enviado. `./dev gui` lançado
uma vez, instância **935427** com starttime **1403407**, lock e bandeja confirmados.
Compacto aberto e central oculta; posição atual do compositor apenas limitada à
área útil (604;318,185; 280×274,815), sem alterar regra do KWin. AT-SPI confirmou
o botão Prompts e a nova aba na instância real. Metadados locais e log em
`.scratch/custom-prompts`. Não encerrar PID só por este registro histórico.

Este incremento ainda não integra a tag imutável v0.2.0b2 publicada abaixo;
versão não avançada e sem novo release/merge. Próximo passo: validar Custom
nas aplicações usuais do usuário; publicar outro marco somente com versão,
artefatos e gates de distribuição correspondentes. Demais limites continuam.

## Release 0.2.0b2 publicada e instância substituída — 01/11/2026

[Release v0.2.0b2](https://github.com/Misael-art/Folego/releases/tag/v0.2.0b2),
prévia publicada em **01/11/2026 22:14:25 UTC**, tag/commit exato
`4802b79217390e4b6eb6f350ed0c0ab37a5ae005`. Autorização explícita do usuário
para substituir a versão atual, testar e distribuir. Sem merge. PR #1 existente
atualizado; permanece draft pelas pendências gerais fora deste marco de UI.

Fonte completa (11.505.841 bytes, com dev/uv.lock), wheel (356.243), sdist
(511.498) e SHA256SUMS (281) enviados. Digests GitHub iguais aos locais; os
quatro downloads públicos foram baixados sem autenticação e conferidos por
SHA-256/tamanho; manifesto aprovado e tag remota no SHA esperado.
[Recibo dos assets](handoff/validation/ai-accounts-keyboard-prompts-2026-11-01/release-b2.json),
[downloads](handoff/validation/ai-accounts-keyboard-prompts-2026-11-01/public-downloads-b2.json)
e [CI do tag](handoff/validation/ai-accounts-keyboard-prompts-2026-11-01/ci-b2.json).
Seis checks de código aprovados; CodeRabbit/Sourcery skipped. v0.2.0b1 preservada.

`./dev check` b2: **1113 passed, 2 skipped** headless (25,78 s),
**1378 passed, 2 skipped** Qt (40,00 s), Python 3.14.7 gerenciado, sequencial e
isolado. Wheel: 129 módulos idênticos ao checkout, nenhum arquivo privado;
CLI instalada sem Qt e remoção GUI preservando todos os hashes do HOME de teste.
Qt reaproveitado offline por requisitos com hashes do lock. Wheel final instalado
sem editable/PYTHONPATH passou nos oito casos KDE/Wayland. Contadores por conta,
clipboard isolado e abertura/deduplicação de Print também verificados. Fonte de
runtime `eda22c9` é byte a byte igual ao tag; commits posteriores são QA/docs.

AT-SPI restaurado após autorização e intenção/owner revalidados. GUI anterior
saiu pela bandeja sem sinal manual e liberou o lock. A b2 oficial está aberta no
compacto, na posição anterior (25,39; 280×275 lógicos), com central oculta.
Acessibilidade nativa confirmou sete botões e quatro indicadores visíveis na
instância nova. Nenhum agente, terminal ou sessão de trabalho encerrado;
preferências/grants do produto preservados. Auxiliares de QA encerrados.

Limites: Web/Grok sem fonte de percentual/reset/tickets; Claude sem percentual
atual na observação real anterior. Datas estimadas/pessoais não confirmam cobrança.
O teste de Print cobre abertura e deduplicação, sem salvar região. Não certifica
todos os clientes de destino, arraste físico, login X11, hardware ou outra
distribuição. Motor de recursos, matriz física e pendências gerais permanecem
no escopo anterior; não declarar o produto estável ou o executor automático ativo.
Próximo passo: validação do usuário nas aplicações que utiliza; continuar as
pendências gerais sem alterar a tag publicada. Registros abaixo preservam a
preparação e tentativas históricas; a pendência AT-SPI foi resolvida.

## Recuperação autorizada e preparação 0.2.0b2 — 01/11/2026

Pedido posterior autoriza substituir a instância, validar e publicar nova release.
O AT-SPI foi restaurado por um único reinício da unit registrada, após conferir
owner/PID/starttime e gravar intenção. Endpoint e owner D-Bus voltaram a responder;
nenhum agente/cliente de IA foi encerrado. A pendência abaixo está resolvida.

QA completo KDE/Wayland: hover por ponteiro real, troca de conta, teclado embaixo/
topo/embaixo, cliques A/B em campo próprio, selecionar/apagar via AT-SPI e
C/Shift+D/apagar em editor de outro processo descartável. Contadores 3/5/1,
abertura da padrão preserva 1 entrega da segunda conta e abertura desta conclui
só os avisos Codex, com recibo durável. Lookup de cliente substituído por janela
própria; não certifica todas as aplicações reais. Print abriu Spectacle próprio,
não duplicou pedido e foi encerrado sem salvar região; não prova arraste/salvar.
Clipboard: produção copiou e colou prompt integral em Xvfb próprio sem D-Bus físico.

Versão e lock avançam a **0.2.0b2**. `./dev check`: **1113 passed, 2 skipped**
headless (25,78 s), **1378 passed, 2 skipped** Qt (40,00 s), sequencial e isolado.
Instalação offline inicial sem metadata Qt no cache falhou; com requisitos com
hashes exportados do lock em ambientes novos passou, CLI sem Qt e remoção GUI
preservando todos os hashes do HOME de teste. Python gerenciado, sem downloads
novos. Nove workspaces anteriores foram preservados em revisão; os finais
são `run-fqx12mll` e `run-1i0zasue`.

[Provas e limites](handoff/validation/ai-accounts-keyboard-prompts-2026-11-01/README.md).
O wheel final tem 129 módulos idênticos ao checkout, sem arquivos privados.
Instalado sem editable/PYTHONPATH, passou nos oito casos KDE/Wayland. O harness
agora sincroniza geometria/movimento e confere a superfície própria antes de
clicar; falhas intermediárias de hover foram preservadas. A GUI antiga saiu pela
bandeja, liberou o lock; b2 oficial foi aberta e deixada no compacto na posição
anterior (25,39; 280×275 lógicos), sem sinal manual e sem encerrar clientes de IA.
SHA do tag, checks remotos e URL do release serão registrados após publicar. Sem merge; o executor automático de
recursos e a matriz física geral continuam nos limites anteriores.

## Contas, teclado por clique e biblioteca de prompts — 01/11/2026

Código: `3aae6c9692b2b5b312561e7a90cd8b4e01778f5b`, sobre `b5e400330495d1ca42985f519b4c5044ab07de2e`,
mesma branch e PR #1. Pedido atual: contas padrão/adicionais, painel legível,
teclado que digita nos campos e prompts robustos para copiar. Inventário nativo
compartilhado por cotas/entregas/abertura; registro opcional PhaseZero somente
leitura para labels e raízes, sem importar/executar o outro projeto. Inclui
perfis inativos, preserva Web local coexistente e exclui arquivados automáticos.
Referência mensal e recibos passam a respeitar a conta selecionada; abertura
sem vínculo comprovado não cai no perfil de outra conta. Neste host: três
Codex e três Web; as três Codex retornaram cotas/tickets. Web/Grok continuam
sem percentual verificável; Claude não retornou cota atual nesta observação.

Hover abre painel interativo com padrão primeiro, seletor à esquerda, consumo
em destaque, tickets/assinatura próximos ao topo e resets por janela. Widget
mantém 280 px. **Prompts**, junto de selecionar/apagar, oferece 11 textos de
boas práticas genéricos; escolher copia, sem colar/enviar automaticamente.

Clique real reproduziu o teclado tomando foco (texto vazio), lacuna do teste
anterior que apenas chamava o envio da tecla. Regra própria KWin restrita a
app-id/título do teclado, preparada em worker, impede foco. Confirmação nativa
inclui posição em pixels físicos e recusa de foco; sem ela, teclas não são
enviadas. QA real passou com A/B em campo próprio e C, Shift+D e apagar em
editor de outro processo descartável, sem o teclado ficar ativo, inclusive no
topo. Nenhuma permissão/serviço de entrada novo. Prompts também foram copiados
e colados integralmente em Xvfb próprio; clipboard físico não foi fixture.

`./dev check` final: **1113 passed, 2 skipped** headless (18,19 s),
**1378 passed, 2 skipped** Qt (33,00 s), Python 3.14.7 gerenciado, sequencial,
HOME/XDG/TMP privados. Sete workspaces concluídos foram revisados e preservados
integralmente em `.scratch/dev-tests-reviewed/20261101-ai-ui`, sem descarte nem
ampliação dos limites. [Evidências/manifesto](handoff/validation/ai-accounts-keyboard-prompts-2026-11-01/README.md).

**Pendência de reparo do ambiente causada pelo QA:** ensaios exploratórios de
Xvfb/D-Bus privados iniciaram o daemon antes de isolar seu ambiente de ativação.
Um subserviço adotou o pathname físico `/run/user/1000/at-spi/bus_0`; o owner
original `at-spi-dbus-bus.service` permaneceu vivo, mas novas conexões ficaram
recusadas. A tentativa Wayland posterior confirmou hover por ponteiro real e
teclas, depois recusou selecionar/apagar por indisponibilidade AT-SPI. Não é
aprovação integral nem se soma a tentativas anteriores. Autorização específica
foi pedida via pergunta assíncrona para `systemctl --user restart
at-spi-dbus-bus.service`; **aguardar resposta antes do reinício**. Não executar
novamente os ensaios exploratórios. O verificador dedicado de clipboard usa
D-Bus desconectado e Xvfb próprio; passou sem acessar esses canais físicos.

Instância real anterior do Fôlego preservada enquanto o reparo aguarda resposta;
não declarar reabertura da versão nova. Próximo passo: com autorização, conferir
owner/identidade, restaurar somente a unit registrada, validar seu endpoint,
repetir o fluxo Wayland em campos próprios e só então sair/reabrir Fôlego pela
bandeja nativa. Não reiniciar sessão, clientes de IA, agentes, drivers ou outros
serviços. Sem novo release/merge; v0.2.0b1 continua no código anterior.

## Comparação com PhaseZero e contexto Claude — 01/11/2026

Código: `ae87aaad7e751c9151cbbd601fd8b4e2032d9c4c`, sobre
`64313445e25f9fff4d932b2dc702889e0f7a77b6`, mesma branch/PR #1. O usuário
indicou `/home/misael/Projects/PhaseZero/` como referência da solicitação de IAs.
Comparados quota_meter.py/tray e handoff na revisão PhaseZero `53d62e2d`:
Web conta mensagens locais de 3/24 h; Grok usa dia mensal informado. Não há ali
fonte adicional de percentual de franquia desses serviços. Alterações existentes
do outro projeto foram preservadas; Fôlego não depende dele em execução.

Adaptada a identidade do cache Claude aos metadados nativos `oauthAccount`:
conta/organização em `~/.claude.json`, além da credencial/diretório. Baseline
reproduziu 90% de A herdados por B (esperado 40%) com o mesmo token. Contexto
alterado agora descarta uso/perfil anteriores e respostas durante a troca;
metadata ilegível bloqueia reutilização. Retry-After continua válido para o
mesmo token, inclusive A → B → A, sem compartilhar a cota entre organizações.

`./dev check` final: **1099 passed, 2 skipped** headless (18,25 s),
**1360 passed, 2 skipped** Qt (32,86 s). Suítes sequenciais, Python 3.14.7,
HOME/XDG/TMP privados; conta/organização reais não foram trocadas para QA.
Quatro novas regressões e reprodução da base com fonte imutável do Git.
[Evidências e limites](handoff/validation/ai-details-editing-2026-11-01/README.md).

A inspeção do plugin AT-SPI não respondeu e foi cancelada antes de qualquer ação.
Reabertura pela bandeja nativa/DBusMenu com owner/PID conferidos: **Sair** encerrou
GUI e seu próprio auxiliar de entrada normalmente, com liberação do flock e sem
sinais. Nova GUI oficial deixada no modo compacto, posição dentro da tela.
Nenhum agente/serviço alheio encerrado; regras KWin e grants preservados.
Web/Grok e validação física por aplicação continuam nos limites abaixo.
Sem novo release/merge; a prévia v0.2.0b1 continua no código anterior.

## Hover das IAs, edição de campo e saída real — 01/11/2026

Código: `079d39e08a2b8261649a36152cf3a50959ffc33b`, sobre
`cb7857479c71c89dc4aa70ebdfce2d26a93708cd`, na branch/PR #1 existentes.
Pedido do usuário: corrigir dados do hover, manter contadores/abertura das IAs,
acrescentar Selecionar tudo/Apagar tudo e reabrir para validação. O trecho final
da transcrição foi considerado conversa incidental.

Widget sem foco habilita agora dicas em janela inativa. Codex consulta GETs
de uso/tickets do próprio provedor, com credencial existente válida, sem refresh
ou resgate; fallback local continua limitado. Descobre/deduplica diretórios
nativos ativos no HOME selecionado. Hover separa uso e reposição com contagem
regressiva, tickets/validade, créditos extras e referência mensal. Botão direito:
atualizar, detalhes com rolagem, referência mensal pessoal persistente e site.
Dias 29–31 respeitam meses curtos; referência não confirma cobrança.

Claude inclui uso extra/perfil quando disponíveis. Mensalidade pelo início da
assinatura ativa é estimativa identificada. Cache em memória com chave de
credencial/diretório, uso por 5 min e perfil por 6 h; HTTP 429 respeita
Retry-After, sem encurtar espera superior a uma hora. Revalida conta, validade
e reset inclusive na CLI. Nenhum token/conversa é persistido nesse cache.
**Limite remanescente:** Web/Grok continuam sem percentual/reposição/tickets
verificáveis nas fontes desta integração; campo desconhecido e link para
consultar o provedor. Não declarar completas todas as funções dos quatro serviços.
No host, Codex retornou janelas/tickets em três raízes; Claude respondeu HTTP 429
na consulta de uso posterior à leitura do perfil. Sem contornar ou ignorar o limite.

Dois botões finos, largura preservada em 280 px. AT-SPI de produção altera
somente o campo editável em foco, com proprietário/identidade/estado/tamanho
revalidados. Não lê conteúdo, toca clipboard ou substitui a edição por atalhos
globais de terminal. Aplicação sem interface editável informa indisponibilidade.
Também corrigida a saída: central oculta + widget Tool não encerravam o loop Qt;
o shutdown normal agora solicita `QGuiApplication.quit()` explicitamente.

`./dev check` final: **1095 passed, 2 skipped** sem Qt (20,83 s),
**1356 passed, 2 skipped** Qt (39,30 s), Python 3.14.7 gerenciado, sequencial,
HOME/XDG/TMP privados. Skips seguem exigindo Edge real. KDE/Wayland próprio:
evento de ajuda Qt mostra os campos, teclado embaixo/topo/embaixo e edição de
texto em campo próprio sem perder foco. Teste de saída reproduziu a falha antes
e saiu sem watchdog após a correção. Wrapper de QA remove agora as três
variáveis de caminho nativas dos provedores; HOME privado não adota HOME físico.
Falhas intermediárias e workspaces revisados preservados integralmente, sem
remover regressões ou afrouxar limites. [Evidências](handoff/validation/ai-details-editing-2026-11-01/README.md).

A instância antiga fechou o widget, mas manteve o processo/lock pelo defeito
reproduzido. SIGTERM único por pidfd após conferir argv/starttime; flock liberado.
Nova GUI oficial aberta, modo widget acionado por AT-SPI, botões e novos campos
confirmados visíveis, posição ajustada à área disponível sem mudar regras KWin.
Fôlego deixado aberto para validação. Nenhum agente/terminal encerrado, grant ou
opção de início alterado. Sem novo release/merge; v0.2.0b1 permanece anterior.
Próximo passo: validação física do usuário no hover e nos campos das aplicações
que usa; não presumir cobertura de todos os clientes nem do compositor X11.

## Avisos de entregas e Fôlego reaberto — 01/11/2026

Implementação: `91125ecb4417293f8fdf4f9773b9ea0c7009f3c5`, sobre
`c9d1af66b0466ed751f718cbbde231d444b67d33`, na mesma branch/PR #1. Pedido
posterior do usuário autoriza os contadores e o encerramento/reabertura somente
do Fôlego para validação. Nenhuma aplicação de agente ou terminal foi encerrada.

O widget conserva 280 px de largura e acrescenta 14 px acima das franquias:
contagem por sessões principais concluídas, desde a primeira ativação do novo
monitor, deduplicada e persistente. Fontes nativas Codex/Web, Claude e Grok,
worker separado a cada 5 s; ferramentas/subagentes não contam. Ausência de
evidência aparece como `?`; mínimo positivo parcial como `2+`. O próximo pedido
retira o aviso antigo; nova conclusão gera novo aviso. Recibos em hash próprios,
sem conversas/credenciais. Estado desconhecido não é substituído.

Clique abre a aplicação desktop ou seu terminal ancestral identificado, com
revalidação de PID/starttime e confirmação de foco antes de marcar somente os
avisos exibidos como vistos. Falha preserva a contagem; conclusão posterior ao
clique permanece. Nenhum comando é enviado aos agentes. Um atalho nativo pode
ser aberto uma vez quando não há janela identificada. Não seleciona conversa
ou aba interna. Dependências e orçamentos no [guia](COMPACTO.md).

`./dev check` no código final: **1079 passed, 2 skipped** headless (20,57 s) e
**1339 passed, 2 skipped** Qt (37,21 s), sequenciais, Python 3.14.7 gerenciado,
HOME/XDG/TMP privados. Skips ainda exigem Edge real. KDE/Wayland real: sessões
sintéticas 2/5/1, clique do widget → foco de janela própria → recibo persistente,
sem apagar avisos dos demais provedores. A busca de produção somente leitura
encontrou janelas locais dos quatro provedores; o foco real de cada um fica para
validação do usuário. Tentativa inicial sem isolamento de `CODEX_HOME` preservada
e roteiro corrigido. [Evidências e limites](handoff/validation/agent-deliveries-2026-11-01/README.md).

A instância antiga, oculta e sem SNI registrado, não respondeu à saída AT-SPI.
Após conferir identidade/argv, SIGTERM único por pidfd e liberação de flock
confirmada; `./dev gui` lançou a atual uma vez. Modo widget acionado pela GUI;
AT-SPI confirmou os quatro indicadores novos visíveis. Fôlego deixado aberto
no HOME real para o usuário validar, sem mudar grants ou opções de início.

Este incremento pertence ao código/PR; **v0.2.0b1 continua apontando ao código
anterior**. Sem novo release ou merge nesta rodada. Limites gerais e próximos
contratos pendentes abaixo permanecem. Os workspaces de QA próprios concluídos
foram preservados integralmente quando revisados para retenção, sem afrouxar
orçamentos. Próximo passo: validação do usuário no widget deixado aberto.

## Widget compacto, monitor de IAs e prévia publicada — 01/11/2026

Implementação: `5ce16b1c05001ad3552c3cd26cd30ccdbfc73f63`, na branch
`codex/portable-handoff-20261024`. O usuário aprovou os mockups e autorizou
implementação, commit, push, PR e release nesta rodada. Essa autorização permite
esta prévia de distribuição, sem merge ou ampliação de grants/automação.

Entregue: widget de **280 × 216 px** no estado normal, controles de janela no
cabeçalho, recursos em duas linhas, faixa de IAs com detalhes por hover e abas
coloridas Copiar/Colar/Print/Teclado. A aba abre sempre embaixo; só a seta abre
no topo. Teclado próprio sem foco, posição confirmada pelo KWin e auxiliar de
entrada transitório próprio quando o host já permite uinput. Copiar usa
Ctrl+Insert, evitando Ctrl+C que interromperia tarefas de terminal. Captura abre
seleção de região do Spectacle e preserva a instância em andamento.

IAs têm coleta própria, independente do PhaseZero, também disponível em
`folego ai status --json`: Codex local e Claude por endpoint de uso de primeira
parte. Orçamentos de leitura, descarte por troca de conta, falha e vencimento;
reset passado não significa cota cheia. Web/Grok sem percentual confirmado
ficam desconhecidos. Token presente não prova renovação válida; não há refresh
ou cópia/gravação de credenciais. Consulte [configuração e dependências](COMPACTO.md).

Validação neste host: `./dev check` **1061 passed, 2 skipped** headless (18,47 s)
e **1320 passed, 2 skipped** Qt (34,04 s). Após tipografia final, nova suíte Qt:
**1320 passed, 2 skipped** (32,88 s); foco de 63 casos aprovado. Skips exigem
Edge real. Corrigido o isolamento do teste antigo de tuning que ligava o
argumento padrão antes do monkeypatch; produção não perdeu nenhuma proteção.

KDE/Wayland real: embaixo → topo → embaixo, geometria fracionária e digitação
em campo próprio. X11 privado: entrada, copiar/colar e Spectacle. Bootstrap
oficial: central → widget → central → saída, exit 0, HOME/XDG próprios e
systemctl simulado. Wheel instalado sem modo editable, CLI sem Qt e GUI com
runtime Qt 6.12.0 já gerenciado. Consulta real Codex/Claude aprovada somente
leitura; nenhum metadado de conta publicado. Tentativas falhas foram preservadas,
com correções de IPC curto, pixels fracionários e encerramento explícito de Qt.

[Release **v0.2.0b1**](https://github.com/Misael-art/Folego/releases/tag/v0.2.0b1)
publicada como **prévia** em 01/11/2026 14:04 UTC, tag/SHA remoto conferidos:
`5ce16b1c05001ad3552c3cd26cd30ccdbfc73f63`. Assets: fonte completo, wheel,
sdist e SHA256SUMS; tamanhos e digests SHA-256 remotos comparados aos locais.
O fonte completo de 11.072.417 bytes foi revisado como artefato de distribuição,
sem cache, estado ou credenciais; não virou blob novo do Git. A CLI/GUI do wheel
foram verificadas fora do checkout; dependências grandes não foram baixadas.

CI desse SHA: **seis jobs de código success**, CodeRabbit/Sourcery skipped.
PR de continuidade [#1](https://github.com/Misael-art/Folego/pull/1) reutilizado,
ainda draft, sem merge. Este registro posterior conserva o mesmo código da tag.
[Logs, capturas, comparação visual, recibos e limites](handoff/validation/compact-ui-2026-11-01/README.md).

Limites: esta prévia não resolve os quatro defeitos de contrato da avaliação
abaixo, nem certifica hardware/login/transições, todas as aplicações de destino
ou soak desta revisão. O executor automático de recursos permanece desligado.
A sessão de trabalho e os serviços reais não foram reiniciados para QA; reabrir
o Fôlego carrega a interface nova. Workspaces de QA concluídos revisados foram
preservados integralmente em `.scratch/dev-tests-reviewed`, sem apagar fixtures
ou aumentar limites. Próximo incremento recomendado continua sendo o P1 da cauda
do diário e os demais contratos abaixo, com regressões e aceite próprios.

## Avaliação de filosofia, contratos e oportunidades — 01/11/2026

Base examinada: `6732c4e140d714d2e06a7f95a2a44a0747823fbe`, conferida na
branch remota `codex/portable-handoff-20261024`; working tree inicialmente limpo.
Pedido de entendimento e avaliação, sem correção de código de produção nesta
rodada. As correções de 29/10 e o soak controlado de 30/10 foram considerados;
os achados históricos já corrigidos não foram reapresentados como bugs atuais.
PR #1 conferido aberto/draft, sem merge, com a mesma branch/SHA. Checks da base:
seis jobs de código `success`; CodeRabbit e Sourcery `skipped`. Esse estado remoto
não substitui a suíte local impedida pelo orçamento de QA descrito abaixo.

Propósito observado: tornar a pressão de recursos compreensível e permitir
intervenções revisadas que preservem trabalho e recuperação. A supervisão de
entrada amplia esse propósito para a continuidade do desktop, com owner e
autorização próprios. A arquitetura separa coleta/decisão de Qt, usa o
coordenador comum e conserva a distinção entre recusa, efeito parcial e resultado
desconhecido. O executor automático de recursos continua desligado.

Achados atuais, reproduzidos em memória com I/O e efeitos externos simulados:

1. **P1 — diário aceita cauda JSON sem terminador e autoriza novo executor.**
   `orchestration/journal.py:Journal.load` usa `splitlines()` sem recusar a última
   linha sem `\n`, ao contrário de `HistoryReader`. Uma escrita interrompida após
   o JSON e antes do terminador é aceita sem problemas; o próximo append cola
   dois objetos na mesma linha. Prova pelo `Coordinator.run`: diário inicial
   com um registro aceito, executor chamado, resultado `desconhecido` e diário
   final com JSON ilegível. Caminhos diretos pelo coordenador podem atingir o
   efeito sem uma intenção novamente interpretável. Recusar a cauda antes de
   qualquer append/efeito; cobrir a fronteira com regressão no coordenador.
2. **P2 — swap ilegível ou malformada é apresentada como ausente e válida.**
   `core/procfs.py:read_swaps` retorna lista vazia em falha e ignora linhas
   inválidas; `core/collector.py` marca a fonte `ok` apenas porque o arquivo
   existe. Nas duas provas: total/uso zero, qualidade `ok`, saúde `green` com as
   demais métricas normais. O card de swap apresenta “sem swap/zram”. Diferenciar
   inventário vazio comprovado de erro/parcialidade até a apresentação.
3. **P2 — corrida pode contrariar a preferência de início do monitor.**
   `startup.py:configure` solta a trava após salvar preferência/autostart e antes
   de instalar/desabilitar a unit. Prova com duas threads e serviço simulado:
   habilitação pausa antes de instalar; desabilitação termina; habilitação
   antiga retoma. Resultado: preferência false, `Hidden=true`, monitor habilitado
   e ambas as chamadas com `sucesso`. Serializar/revalidar também a etapa da unit
   para que uma escolha anterior não se sobreponha à preferência mais recente.
4. **P2 — reconciliação não arquiva revisão cujo resultado já está no diário.**
   Se o executor cai após gravar o resultado e antes de `_close`,
   `orchestration/review.py:reconcile` retorna o resultado conhecido sem encerrar
   o bundle `started`. Prova: sucesso devolvido e `_close` não chamado. A revisão
   deixa de aparecer em `pending()`, mas continua ocupando a pasta limitada a
   256 entradas em `prepare`. Finalizar o recibo de modo idempotente, preservando
   evidência e conflitos; consultar/reexecutar o mesmo ID não deve vazar slots.

Lacunas/oportunidades de produto e operação:

- “Resolver agora: memória” apenas solicita `memoria`, mapeada para a própria
  central; falta uma investigação útil como próximo passo. Concluir “Dar fôlego”
  preservando análise → mesmo plano/ID → confirmação → verificação → recuperação.
- O motor de saúde usa sobretudo RAM/PSI de memória e tmpfs; CPU e PSI de I/O
  já são coletados, mas não compõem o veredito. Tornar explícito o alcance do
  indicador e desenvolver diagnósticos desses recursos com evidência.
- Algumas sugestões prometem alívio ao fechar Edge/limpar `/tmp` apenas a partir
  de PSI alto. Vincular a orientação ao consumidor medido e distinguir hipótese
  de efeito verificado, sem ampliar grants ou habilitar automação de recursos.
- Retenção própria já existe, mas a passagem registra zero movimentos no ensaio
  com consumidores reais por observação incompleta. Fechar esse aceite e a
  recuperação de capacidade sem ignorar consumidores, adotar fixtures ou apagar
  estados desconhecidos. O diário autoritativo ainda é relido integralmente em
  consultas/appends; o leitor incremental de apresentação não resolve esse custo.
- A passagem conserva uma tabela histórica de “próximos incrementos” com itens
  posteriormente atendidos. Distinguir um resumo vigente do histórico para
  reduzir retrabalho; matriz física de entrada/desktop continua pendente.

Validação desta avaliação: quatro categorias de prova (duas variantes para
swap), usando `.dev/venv-headless/bin/python` 3.14.7, mocks e estado em memória;
nenhum efeito real de arquivo de usuário, systemd, processo alheio ou compositor.
`./dev test-headless tests/test_orchestration_journal.py
tests/test_snapshot_quality.py tests/test_session_resilience.py` foi recusado
**antes de coletar testes**, pelo teto preexistente de **20 workspaces de QA**.
Não se elevou limite, removeu evidência nem substituiu essa suíte por pytest fora
do wrapper. Espaço observado antes: 187 GiB livres, 4,1 GiB de RAM disponível;
nenhuma operação pesada foi iniciada. As provas em memória não certificam efeitos
reais nem uma correção. Revisão documental e `git diff --check` são os gates deste
incremento. Próximo lote recomendado: corrigir o P1 do diário e os três P2 com
regressões focadas, após revisão apropriada da capacidade de QA existente.

## Teclado virtual e tela de toque (30/10, tarde)

Contrato confirmado pelo operador: **só o toque na tela abre o teclado**; clique
pelo trackpad continua funcionando como ponteiro e não abre o painel. Tentativa
de modo 2 (abrir ao clicar) foi revertida em PhaseZero `a32add23`; KWin observado
em `mode=1`, kwinrc=1. Card do Fôlego indica quando, sem touchscreen, o clique não
abre (`degraded`, sugere Abrir teclado).

Causa da ausência do toque: `FTS3528:00` existe no ACPI/I²C, mas sem driver;
`i2c_hid_acpi` carregado e `AMDI0010:01` repete `controller timed out` desde o
boot (IRQ 11 com 4 interrupções; `AMDI0010:00` registra `lost arbitration`). Visto
também nos boots de 30/10 09:06 e 12:15. `intremap=off` existe no GRUB desde
julho; sem prova de relação, boot não foi alterado. O ID incerto
`58176bdf86c94e759e43f661630c5ce8` continua bloqueando repetição de reset I²C.
Próximo passo: desligamento completo pelo operador (não reinício), conferir
`FTS3528` em `/proc/bus/input/devices`; se persistir, comparar com boot SteamOS
para separar hardware de kernel. Gates: `./dev check` 1038/1292 passed.

## Retomada prioritária: incidente de entrada e autenticação sem dock

Base Fôlego `acbe99ee182d6a8bb00f98d5489fe194c1272672`. Cards agora são botões,
com habilitação manual por capacidade, resultado vinculado ao ID, verde só por
configuração verificada e amarelo em conflito/falha. Habilitar tudo, verificação
com horário/resumo e registro persistente ficam fora da rolagem. CLI/GUI usam o
coordenador existente, recibo de etapas, revalidação e consulta sem reaplicar.

Integração opcional PhaseZero: `reconcile-input` evita restaurar áudio ao clicar
em uma entrada; recuperação FTS delegada somente ao helper dedicado. Orçamento
manual de hardware usa os mesmos 60 s/três por hora. Abertura explícita de teclado
é permitida como escape durante pendência anterior, sem liberar seu ID. O pedido
de senha sem teclado relatado pelo operador motivou `recover-touch`/`persist-touch`:
confirmam teclado visível, mantêm modo temporário na troca de foco e restauram
após a autenticação; watcher cede pela trava comum. PhaseZero publicado em
`9ebb6487f036d052ddfa7837bc4200d2bfbfa63a`, PR #129, sem merge/release.

Host: teclado virtual visível confirmado pelo KWin, inclusive com ID de reparo
incerto; retorno ao modo 1. FTS continua ausente após reset dedicado e novo
timeout I²C. Tentativa posterior do operador sem dock perdeu autenticação e
terminou desconhecida (`58176bdf86c94e759e43f661630c5ce8`): preservar ID, não
repetir hardware nem declarar que nada ocorreu. Campo de teste não grava texto.
Cinco identidades habilitadas foram salvas; autostart continua true. GUI oficial
reaberta por saída semântica; monitor próprio e owner atualizados, Steam/RetroFE
preservados. Digitação no polkit sem dock ainda precisa de aceite do operador.

Gate final `./dev check`: **1037 passed, 2 skipped** headless (29,94 s),
**1291 passed, 2 skipped** Qt offscreen (50,21 s). PhaseZero focal **22 passed**
(6,37 s), runtime compatível gerenciado; wrapper core indisponível. Uma tentativa
intermediária falhou por deadline flutuante de backup; falha preservada, sem
relaxar limite. QA Wayland própria com efeitos simulados: cards/Tab/Espaço,
800×600/1280×800, estados e resumo; não homologa toque/login/auth física.
[Relatório, capturas e alcance](handoff/validation/accessibility-incident-2026-10-30/README.md).

Próximo aceite: operador confirmar teclado e digitação sem dock; investigar FTS
sem reiniciar a sessão de trabalho para QA, mantendo pendência desconhecida até
prova de término/revisão apropriada. O soak histórico abaixo não aprova esta nova
implementação. Limites do executor automático de recursos continuam inalterados.

Checkpoint de produto publicado: `617c2ad3b6ab3982094a261a1f0a8f2bdcd05bbd`,
SHA remoto conferido na branch padrão; PR #1 atualizado e ainda draft. CI desse
SHA: seis jobs de código success; CodeRabbit/Sourcery skipped. Repositório público
e MIT conferidos. PhaseZero `9ebb6487` remoto conferido, PR #129 atualizado;
CI ainda em andamento no último marco (a base tinha falha ShellCheck 0.9).
Esta nota posterior muda somente documentação/metadados de validação. Nenhuma
pendência física ou incerta foi liberada para obter esse checkpoint.

## Retomada vigente: resiliência e início com a sessão

Base deste incremento: `26b1567db77648c7a8a0fdbc4c41bd0884cbb2ac`. O usuário
autorizou todas as recomendações da revisão posterior de entrada e pediu uma
opção de início com a sessão **ligada por padrão**. O estado abaixo substitui
as pendências históricas equivalentes, sem promover aceites físicos antigos.

- **Opções:** sétima aba, preferência durável e autostart XDG gerenciado;
  sincronização da unit própria de observação no login. Desligar persiste após
  reabrir e não encerra um monitor já aberto. Entradas/units pessoais são
  preservadas. Nenhum grant de reparo/recursos é ampliado pelo início automático.
- **Leases:** limite de 32 considera participantes ativos; liberações validadas
  saem para recibos fechados. `accessibility lease-run` registra filhos antes
  de abrir o gate do comando; conclusão incerta preserva a propriedade, inclusive
  se o launcher morrer. PhaseZero continua opcional.
- **Temporários próprios:** manifesto ligado à raiz/diretório e processo/sessão;
  somente encerrados certificados, com ausência de consumidores/referências comprovada,
  podem ir por rename a `.retained`. Payloads não são apagados, legado/ambíguo
  permanece protegido. Cap 256, inventário limitado e orçamento de 1 GiB
  permanecem; esgotamento exige revisão. Não é retenção integral de dados do host.
- **Revisão e recuperação:** ajustes, tmpfs release/restore/expire/recover e
  disco restore/purge usam o mesmo plano durável confirmado e ID no pai, com
  evidência dos alvos/conteúdo e validação no coordenador existente. A aba
  opções consulta IDs, reapresenta revisões após reabrir e cancela somente as
  não iniciadas. Timeout não permite retry cego; o recibo encerra só o ID correto.
- **Monitor:** índice incremental limitado das pendências, sem apagar o diário;
  corrupção/parcialidade bloqueia. Alertas locais para serviço ausente,
  disjuntor e espera prolongada; anel de 32 transições. Frescor usa CLOCK_BOOTTIME
  para incluir suspensão. Esses registros não certificam movimento/toque físico.

### Validação desta rodada

Python 3.14.7 e Qt 6.12.0 gerenciados por `./dev`, HOME/XDG privados, suítes
sequenciais. Gate `./dev check`: **1014 passed, 2 skipped em 27,07 s** sem Qt;
**1263 passed, 2 skipped em 44,15 s** Qt offscreen. Foco final de 34 casos
passou em 6,07 s. Dois skips por perfil exigem Edge real, ausente nas fixtures.
Após corrigir o corte do rótulo em foco, repetição Qt: **1263 passed, 2 skipped
em 42,34 s**. Logs e resumo portátil em
`handoff/validation/session-resilience-2026-10-30/`.

Após o soak, incluída regressão do ciclo real do QProcess com boot observado:
somente o teste e a documentação mudaram; produto/harness permaneceram no SHA
congelado. Suíte Qt final **1264 passed, 2 skipped em 42,15 s**
(`run-nv7a7fry`), incluindo registro, sessão e certificação do término do filho
próprio com `/proc` real. O log GUI publicado corresponde a essa última suíte.
Consulta de retenção na raiz desse filho descartável, com inventário real de
consumidores/referências: **zero movidos**, pois a propriedade de consumidores
não pôde ser comprovada neste host. Preservação correta, sem ampliar permissões
ou ignorar processos; recibo em `retention-real-proc.json`. Isso não homologa
arquivamento efetivo com todos os consumidores reais presentes.

QA KDE/Wayland própria: 800×600 e 1280×800, navegação por Tab, início ligado,
desligamento persistido após reabrir, aplicação/restauração real de arquivo
descartável pelo protocolo de revisão, ID apresentado e revisão reapresentada/
cancelada sem efeito. Launcher oficial vivo por 5 s em HOME privado; encerrado
somente o processo próprio. `systemctl` da QA foi simulado para não tocar units
do host. Evidência local final em `run-review-20261029/session-resilience-native-6/`.

Falhas corrigidas e preservadas: primeira rodada focada 176 pass/6 fail;
confirmação Qt com botão padrão incorreto no gate intermediário
(`run-oix0iopc`, 1261 pass/1 fail/2 skip); QA nativa 1 com alvo de harness
incorreto e 3 com callback Qt após destruição do widget. Repetições finais
passaram após correções, sem relaxar orçamentos nem somar tentativas.
Logs/run.json das suítes passadas regeneráveis foram preservados antes de
retirar apenas seus diretórios temporários; teto de 20 sessões inalterado.

### Ativação e próximos aceites

Executado `./dev run startup enable --confirmar --json` neste host: preferência
true, desktop entry gerenciada `Hidden=false`, serviço `enabled`/`active`,
FragmentPath próprio. Reiniciada somente a unit do Fôlego para carregar a versão
validada. Política de entrada preexistente preservada, baseline vazio, ciclo
waiting pelo PhaseZero ativo; nenhum reparo físico provocado. O executor de
recursos continua desligado. O comando `startup status --json` confere a escolha.

**Soak aprovado:** 7200,057 s contínuos, fonte congelada, mesmo orçamento
preexistente, 120/120 workers, 20/20 cancelamentos, 80 intenções/resultados
válidos, arquivo restaurado e nenhum filho restante. CPU UI+filhos 1,65% de
um núcleo, pico de RSS +0,49 MiB, FD +5, widgets +8, heartbeat p99 ≤5 ms e
máximo 197 ms, leitura 138,20 MiB/h e escrita 33,83 MiB/h, dentro dos limites.
Não se somaram tentativas. [Relatório, amostras e alcance](handoff/validation/session-resilience-2026-10-30/soak/README.md).

A matriz física (boot/SDDM, logout/login, suspend/resume, dock,
Steam, leitor de tela e toque) permanece pendente: não suspender/desconectar
o host de trabalho para produzir prova. Integração de writers interessados
usa o protocolo opcional; não se altera aplicações de terceiros automaticamente.

Limite do harness de soak: o `/proc` sintético contém montagens mas não boot ID.
Os manifests de jobs ficam conservadoramente não certificados nesse ambiente;
o ensaio mede GUI/workers/cancelamentos e não homologa retenção contínua.
Um teste separado de identidade/término usa filho próprio e `/proc` real.
Na metade do ensaio havia 24.316 KiB de VmSwap: queda de RSS pode envolver
paginação e não comprova liberação de heap nem ausência de vazamento.

Demais pendências de produto: concluir “Dar fôlego”, política integral de
retenção/expiração revisada, limites restantes de coleta/cancelamento e
compactação autoritativa do diário. A leitura incremental do monitor não é
compactação nem substitui revalidação na execução. Sem merge/release neste lote.

Checkpoint publicado: `a65b5f7f822ea55c520ad8e6b8598a00df741c5e`, SHA remoto
conferido na branch padrão `codex/portable-handoff-20261024`. PR #1 atualizado,
repositório público e MIT confirmados. CI desse SHA: seis jobs de código success
(push + PR); CodeRabbit/Sourcery skipped. O soak está identificado por
`run-review-20261029/soak-resilience-7200/launch.json`, com boot/starttime e hashes
de fonte/política. `tools/watch_soak.py` observou apenas esse processo, sem sinais
ou retry, e encerrou com análise aprovada. Fonte do produto congelada nesse
SHA durante todo o ensaio; alterações documentais/testes posteriores não a modificam.

## Ponto de retomada

Projeto Linux/KDE, Python 3.14.7 + PySide6. CLI independente de Qt. O objetivo é
manter uma máquina com agentes e aplicações responsiva sem perder trabalho,
inventando o mínimo possível sobre recursos ausentes e preservando recuperação.

Base histórica: `61179f55123b44a996aa6087d124474eb5e84b1e`. A entrega posterior
estava quase toda no working tree; esta migração preserva esse material em Git,
sem reset, limpeza ou redução de escopo para fazer os testes passarem.

Leia `AGENTS.md`, `docs/DIAGNOSTICO-2026-10-24.md` e `docs/NOVO-HOST.md`.
Depois execute `./dev check`. Não depender do antigo `/home/misael`, venv,
serviços, arquivos de anexos ou da disponibilidade deste host.

## O que está integrado

- Coordenação de mutações de disco/tmpfs/ajustes/processos, intenção antes do
  efeito, IDs, planos v2 imutáveis com prazo e consulta por operação.
- Proteção fresca de sessões/exclusões/ancestrais, boot/PID/starttime e
  acompanhamento de SIGTERM. A GUI de produção pede sinais por QProcess.
- Frescor/qualidade de saúde, histórico em worker com leitura limitada e
  feedback de parcial/desconhecido sem converter isso em recusa sem efeito.
- Inventário protegido de fixtures pytest, runtime por UID e temporários
  privados de filhos em destino verificado. Não há arquivamento automático.
- Central e compacto parciais: fallback decorado Wayland, botões acessíveis,
  ciclo de vida sem bandeja corrigido, pausa antes da primeira leitura e
  bandeja mostrada na abertura. Launcher absoluto testado via GIO.
- Bootstrap portátil com versões fixadas, ambientes GUI/headless próprios e
  testes com HOME/TMPDIR isolados. É suporte de desenvolvimento, não autostart.

F0/F1 preservados; F2/F3 avançados, F4/F5 parciais, F6 desligado, F7 protegido/
somente leitura, F8 parcial. Não promover essa classificação a “produto concluído”.

## Próximos incrementos, em ordem

| Prioridade | Trabalho | Aceite concreto |
|---|---|---|
| 1 | Validar bootstrap no novo Linux e registrar versões/recursos | Ambientes sem system-site-packages, CLI sem Qt, duas suítes sequenciais; distinguir skip por Edge ausente |
| 2 | Política de temporários administrados e retenção | Hoje 256 diretórios acumulados recusam novos filhos. Definir lease/identidade, orçamento e revisão/expiração segura; não remover diretórios ambíguos nem adotar fixtures legadas |
| 3 | Repetir soak controlado com raiz exclusiva | 7200 segundos reais, perfil fixo, todos os resultados e filhos contabilizados, fixture restaurada e orçamento aprovado; nunca somar tentativas |
| 4 | Vincular revisão/ID no pai para todas as mutações | Ajustes/tmpfs/restore/purge devem preservar o plano confirmado e ID mesmo em timeout; reconciliação de domínio pelo mesmo ID, sem reaplicar desconhecidos |
| 5 | Prazo total/cancelamento e histórico durável | Limitar coleta e operações, acompanhar filhos, reduzir I/O restante na apresentação; indexação/compactação preservando intenções pendentes e corrupção |
| 6 | Concluir fluxo Dar fôlego | Analisar → revisar o mesmo plano → confirmar → executar → verificar → recuperar; um clique repetido gera no máximo uma operação e arraste gera zero |
| 7 | Fechar matriz real de desktop | Leitor de tela, arraste físico Wayland, retorno do launcher para instância já aberta, outra distribuição limpa e login físico X11 |
| 8 | Assistido antes de Automático | Controlador sem Qt com evidência real, cooldown/orçamentos/disjuntor persistidos e grants de frequência; simulação verificável antes de qualquer executor opt-in |

As tarefas 2/4/5 precisam de desenho e testes de falhas; não são autorização para
limpar o host. O limite de 256 protegeu corretamente antes do efeito. A correção
de isolamento do harness não resolveu a gestão de retenção do produto.

## Provas e limites

Matriz de desktop: `docs/reviews/2026-10-18/desktop-validation/README.md`.
O topo atualizado explica que os ensaios foram arquivados sem aceite de duas horas.
Há capturas reais de cliente e compositor, logs de suíte e falhas preservadas.

Contratos de produção e lacunas: `docs/reviews/2026-10-18/continuacao/`.
Referências detalhadas: `avaliacao-entrega.md`, avaliação de runtime e planos de
17/10 em `docs/reviews`. As instruções originais recebidas estão preservadas em
`docs/handoff/inputs`; não são uma segunda implementação nem aceites já cumpridos.

O novo host deve iniciar com configuração própria e automação desligada.
Planos, grants, PIDs, boot IDs e caminhos antigos não devem ser reativados ou
reescritos para parecerem locais. Backups/diário exportados servem à inspeção e
recuperação explícita; não restaurar sobre dados existentes automaticamente.

## Rotina de qualidade

Um incremento por contrato, teste focado que reproduza a falha, mudança ligada
ao produto, suíte pertinente e registro de evidência. Usar `uv.lock`; atualizar
dependências deliberadamente. Registrar limitações ao lado do resultado.
Evitar novos frameworks, executores paralelos e módulos sem integração.

Antes de encerrar cada rodada: `git diff --check`, revisar o diff, atualizar
esta passagem e apontar a próxima ação objetiva. Commits/PRs devem explicar
problema, comportamento final e validação; não fazer merge sem pedido.

## Recuperação organizada — 2026-10-26

Raiz única neste host: `/home/misael/Projects/Folego`. Checkout existente realocado sem duplicação, base `815cf002248e80e51010191ace556dbaaa2319ce`. Ambientes recriados por `./dev`; núcleo: 916 pass/2 skip; Qt offscreen: 1133 pass/2 skip. Isso não aprova compositor físico nem soak de duas horas. Próxima tarefa continua sendo retenção segura dos temporários administrados; automação permanece desligada.

## Runtime /run/user cheio — 2026-10-28

Caso real: `/run/user/1000` a 100% por `forge-sessions/1bf5a050/audio.raw` (1,5 GB) de uma
sessão BlastEm do SGDKForge cuja árvore foi adotada pelo `systemd --user`. O plano tmpfs
protegia tudo corretamente, mas não dizia por quê nem qual o caminho seguro.

- `folego tmpfs diagnose [--json]` (somente leitura): maiores itens do volume mais cheio,
  maiores arquivos, holders com raiz da árvore e marca de árvore órfã, dono conhecido e
  comando oficial de encerramento (`actions/tmpfs/diagnosis.py`, `OWNER_HINTS`). Não sinaliza.
- `folego tmpfs runtime-size [--vezes N --confirmar]` e controle na aba tmpfs: 1×–4× do tamanho
  atual com teto de 65% da RAM (`core/runtime_size.py`). Aplicar é um único `pkexec` com
  argumentos posicionais: drop-in `/etc/systemd/logind.conf.d/60-folego-runtime-size.conf`
  (`RuntimeDirectorySize`) + remount imediato preservando conteúdo. Fila própria de 180 s para
  a senha; bloqueado enquanto houver resultado desconhecido.
- Validação: `./dev check` 928 + 1149 pass (2 skips cada); CLI real no host mostrou o
  `audio.raw`, o PID 1915399 como árvore órfã e opções 1482/2964/4446/5928 MiB; aba renderizada
  offscreen com dados reais. Não validado: compositor KDE real. O encerramento da sessão SGDKForge pelo `session_coordinator.py stop` não foi
  executado pelo agente (permissão negada); continua pendente com o usuário.
- Aplicação real em 28/10 pelo usuário: `./dev run tmpfs runtime-size --vezes 2 --confirmar`
  levou `/run/user/1000` de 1.554.046.976 para 3.107.979.264 bytes (`df`: 2,9 GB, 1% usado), drop-in
  `/etc/systemd/logind.conf.d/60-folego-runtime-size.conf` com `RuntimeDirectorySize=2964M`;
  os 36 itens do runtime permaneceram. A sessão SGDKForge que enchia o volume foi encerrada pelo
  `stop` oficial; o `audio.raw` dela não existia mais no momento da cópia (corrigido no SGDKForge,
  commit local `e80538de`, push bloqueado pelo registro de recuperação daquele projeto).

## Atalhos de inicialização — 2026-10-28

`src/folego/shortcuts.py`: a cada abertura da GUI (e por `folego shortcuts`) cria o atalho no menu e na
Área de trabalho se faltar, apontando para `run.sh` do checkout (ou o entrypoint instalado); atualiza
somente arquivos com `X-Folego-Managed=true`; preserva atalhos do usuário e symlinks; nunca autostart.
Validação: 8 testes; `./dev check` 936 + 1157 pass (2 skips cada); no host criou
`~/.local/share/applications/folego.desktop` e `~/Área de trabalho/folego.desktop` (válidos no
`desktop-file-validate`), segunda execução `present`, e `gio launch` do atalho da Área de trabalho abriu a
janela real no KDE (instância própria encerrada com SIGTERM).

## Visão padrão redesenhada — 2026-10-28

Padrão comum de painéis de manutenção (o artigo de referência do Medium não pôde ser lido; o usuário
aprovou seguir o padrão): navegação lateral (`SidebarTabBar`, abas West com rótulos horizontais), topo
com medidor de folga (`HealthGauge`: menor fração livre entre memória, swap e tmpfs; veredito e cor do
mesmo relatório de saúde do título) e uma ação principal que só leva à recomendação mais urgente,
cartões por recurso (memória, CPU, swap/zram, temporários; nível em palavra e cor, limiares oficiais),
recomendações com estado vazio e atividade recente com os detalhes da amostra. Nenhum comportamento
de ação mudou; nada novo executa efeito.
Validação: 4 testes novos; `./dev check` 936 + 1161 pass (2 skips cada); janela real no KDE capturada
quatro vezes durante os ajustes (rótulos rotacionados, abas altas e detalhes cortados corrigidos).
Para rodar o gate foi preciso remover 17 workspaces de QA desta sessão (o wrapper recusa com 20
retidos); os 3 anteriores a 28/10 foram preservados.

## Modo widget — 2026-10-28

Botão "⧉ Modo widget" na visão central: abre o controle compacto como widget flutuante (cartão sem
borda, mini medidor, RAM/CPU/Swap/Temp, botão "⤢ Abrir Fôlego" que volta à UI padrão e recolhe o
widget) e recolhe a janela para a bandeja (`hide_window` mantém a garantia de caminho de volta).
O widget nunca recebe foco, fica fora da barra de tarefas e no Wayland usa `startSystemMove`.
Keep-above no Plasma/Wayland não é possível pelo app: `ui/kwin_rule.py` cria, com confirmação, uma
regra do KWin só para o widget (app id `folego`, título exato; acima, sem borda, fora de barra/Alt+Tab,
sem foco, posição inicial no canto inferior direito) via kwriteconfig6 + reconfigure; preserva outras
regras; `folego widget-rule [--remover]`. Recusa fica gravada para não perguntar de novo.
Validação: 10 testes novos/ajustados; `./dev check` 940 + 1170 pass (2 skips cada); execução real no
KDE/Wayland: janela recolhida, bandeja presente, widget visível com dados reais (sem criar a regra).
Pendente: aplicar a regra do KWin no host real (decisão do usuário) e validar keep-above/posição.

## Avaliação do projeto — 2026-10-29

Revisão da base `5575ea06f15103dd28e071b04b6df3ef37c0db81`, igual ao SHA remoto
da branch de continuidade e do PR #1. Pedido de avaliação: nenhum código de
produção corrigido nesta rodada. Arquitetura CLI/core sem Qt, coordenador e
proteções têm cobertura ampla; isso não fecha os contratos dos caminhos novos.

Achados reproduzidos, em ordem de prioridade:

1. **P1 — configuração persistente alterada apresentada como recusa.**
   `core/runtime_size.py:apply_command` substitui o drop-in antes de chamar
   `mount`; uma falha de remount deixa o arquivo novo. Já
   `cli.py:_cmd_tmpfs_runtime_size` converte qualquer retorno não zero em
   `recusa`, sem ID/intenção no coordenador. Prova: corpo do shell executado
   sem pkexec, com todos os destinos em árvore descartável e `mount` simulado
   retornando 32; o drop-in novo permaneceu. CLI simulada retornou `recusa`.
   Correção: integrar no coordenador, preservar estado anterior, registrar as
   etapas e reconciliar configuração persistente e montagem; falha após efeito
   precisa de resultado parcial/desconhecido e recuperação explícita.
2. **P1 — resultado desconhecido permite repetir o resize na GUI.**
   `ui/tmpfs_tab.py:show_runtime_result` ignora `outcome=desconhecido`, mostra
   “runtime não alterado” e solicita opções; a resposta reabilita o botão sem
   preencher `_uncertain_text`. Prova com payload de timeout e atualização
   simulada. Correção: usar o bloqueio de incerteza também neste fluxo, com ID
   estável e reconciliação antes de permitir outra mutação.
3. **P1 — falha ao ler regras do KWin pode desativar regras alheias.**
   `ui/kwin_rule.py:_rules` ignora o código de saída de `kreadconfig6` e usa
   stdout vazio como lista vazia. `install` então grava somente a regra própria
   em `General/rules`; `remove` pode gravar lista vazia. Prova com ferramentas
   simuladas: lista inicial `existing-user-rule` substituída por `folego-widget`
   após erro de leitura. Correção: recusar antes de qualquer escrita quando a
   leitura não for comprovada e preservar a configuração anterior.
4. **P2 — corrida no registro de filhos curtos.** `cli.py:_session_run` inicia
   o comando antes de registrar a sessão; se ele já saiu, `register` recusa o
   zumbi e um comando `exit 0` vira erro 1. A CI do PR #1 já falhou assim
   ([run 40795479345](https://github.com/Misael-art/Folego/actions/runs/40795479345),
   939 pass / 1 fail / 2 skip). Reproduzido localmente atrasando apenas o registro
   de um filho descartável. Correção: coordenar lançamento/registro e término,
   preservando o código real e a proteção dos filhos ainda vivos.
5. **P2 — painel confunde ausência de recomendações com saúde.**
   `core/suggestions.py:suggest` não cobre tmpfs; `DashboardTab._sync_rows`
   apresenta “Tudo dentro do orçamento” sempre que não há sugestões. Provas:
   runtime 100% cheio com medidor “Crítico”, e meminfo ausente com medidor
   “Desconhecido”, ambos com texto de recursos dentro do orçamento. Correção:
   cobrir tmpfs/inodes e derivar o estado vazio do relatório de saúde/frescor,
   com navegação para a aba de temporários.

Verificação no host atual, Python 3.14.7, ambientes existentes do `./dev`,
HOME/XDG privados, temporários em disco e suítes sequenciais:

- `./dev check`: **939 passed, 1 failed, 2 skipped** no perfil headless;
  parou antes de Qt. `test_backup.py::test_roundtrip_property` gerou
  `FlakyFailure`: uma execução levou 328,57 ms (deadline 200 ms) e a repetição
  interna 11,44 ms. Não se alterou deadline/limite nem se aprovou o gate.
- `./dev test`: **1170 passed, 2 skipped**, 30,27 s, Qt offscreen.
- Seis provas isoladas + repetição focada do teste de backup: **7 passed**;
  prova adicional do KWin: **1 passed**. As provas afirmam os comportamentos
  defeituosos observados; não são testes de aceite de uma correção. Backup
  passou na repetição focada; a falha anterior continua registrada.
- Evidência local, descartável e fora do Git: `.scratch/dev-tests/run-_rab54lb`,
  `run-29la1x1v`, `run-4poe65yr`, `run-t9dqu524` (logs/run.json), e
  `run-review-20261029/test_assessment_probes.py` (sete provas). O relato acima
  preserva os resultados no Git. Dois skips de Edge ausente permanecem.
- Revisão documental e `git diff --check`; não se aplicou regra do KWin,
  redimensionamento privilegiado, limpeza ou efeito em processo alheio.
  Compositor físico e soak não foram exercitados nesta avaliação.

Lacunas conhecidas permanecem: retenção dos 256 temporários sem lease/término
comprovado (`safely/jobtemp.py`), plano/ID confirmado no pai para todas as
mutações, prazo total e cancelamento, histórico sem compactação, soak real de
7200 segundos e matriz física de desktop. Próximo incremento recomendado:
fechar os três P1 acima com regressões nos fluxos oficiais, depois a corrida
de sessão/CI e a retenção segura; automação continua desligada.


## Correções da avaliação e apresentação pública — 2026-10-29

Implementação em `fac2d2b377fa6395885b059cdb50f74d60d68bf7`, sobre a avaliação `2fff195`.
Os cinco achados receberam correção integrada e testes de regressão:

- Resize usa `actions/tmpfs/runtime_size.py`, o coordenador comum e intenção
  durável. A consulta entrega o plano v2 com tamanho exato/ID; a GUI preserva
  esse plano. O filho revalida volume, UID, identidade e capacidade antes do
  efeito, preserva a configuração anterior quando existe e deixa recibo de
  término. Falha após gravar configuração é parcial; falta de prova é desconhecida.
- Timeout conserva o ID no pai, bloqueia repetição e reapresenta operações
  pendentes após reabrir a aba. O botão “Verificar operação pendente” e
  `tmpfs runtime-size --reconciliar ID --json` verificam recibo e estado atual
  sob trava; não executam o resize novamente. Sem recibo comprovado, permanece
  desconhecido. Backups/recibos ficam ao lado do drop-in com sufixos por ID e
  não são removidos automaticamente.
- KWin recusa erro de leitura antes de qualquer escrita e preserva regras
  alheias. A GUI apresenta indisponibilidade em vez de propagar a exceção.
- Sessões registram filhos próprios ainda não coletados mesmo se já encerrados;
  registro avulso de zumbi continua recusado e o código real do comando é preservado.
- Painel recomenda a aba de temporários por ocupação/inodes e diferencia
  ausência de recomendação de ausência de evidência. Pausa/frescor invalidam
  também medidor, cartões e mensagem vazia.

Validação final com Python 3.14.7 e Qt 6.12.0:

- Focados: **135 passed**. Após a revisão final, `./dev check`: **952 passed,
  2 skipped** headless (18,34 s) e **1187 passed, 2 skipped** Qt offscreen
  (29,03 s), sequencialmente. Os skips continuam sendo Edge ausente.
- O teste de backup antes instável passou sem mudança de prazo ou remoção de
  verificação; isso não é uma afirmação de que toda variabilidade de I/O foi eliminada.
- Janela própria no KDE/Wayland real, HOME/XDG privados e dados sintéticos:
  exposição da janela, navegação pelo alerta tmpfs, bloqueio de timeout e
  invalidação de frescor passaram. `./dev gui` abriu em HOME próprio e permaneceu
  por 5 s; somente essa instância foi encerrada com SIGTERM. Nenhum efeito
  privilegiado, regra do KWin ou sinal a processo de trabalho foi aplicado.
- Shell privilegiado testado sem pkexec em árvore descartável, com ferramentas
  simuladas; a aplicação real do novo resize via polkit/remount não foi repetida.
- Logs finais locais: `.scratch/dev-tests/run-g0z90paq` e `run-wd7tp0ii`.
  Evidências adicionais em `run-review-20261029/native-demo` e `official-smoke`.
  Logs/manifestos da primeira rodada e do foco inicial foram preservados nessa
  raiz de revisão antes de remover somente os próprios workspaces regeneráveis
  já concluídos. O limite de revisão de QA permanece 20; revisar retenção antes
  de abrir novas rodadas, sem elevar o teto ou limpar evidência alheia.

Apresentação preparada: README com banner SVG próprio, captura real com dados
sintéticos, instruções, recursos, CLI e limites; licença MIT, metadados SPDX,
avisos de terceiros, guia de contribuição e modelos de issue/PR. Links locais,
SVG e `License-Expression: MIT` do pacote instalado foram verificados. A captura
`docs/assets/dashboard.png` não expõe dados do host.

A publicação pública foi solicitada explicitamente pelo usuário. Revisão local
prévia: 785 blobs históricos (22.418.992 bytes) sem correspondência aos padrões
procurados de chaves privadas, tokens GitHub/OpenAI/AWS e credenciais em URL;
109 capturas rastreadas revisadas por folhas de contato, com inspeção adicional
individual. Isso não é garantia universal de ausência de informação sensível.
A publicação usa a branch de continuidade como padrão para apresentar esta
versão, preservando `main` e o PR #1. Não há merge ou release de produto neste lote.

Continuam pendentes retenção segura dos temporários, demais planos/IDs no pai,
prazo total/histórico e matriz física/soak de duas horas. Automação permanece
desligada. Próximo incremento técnico: retenção com identidade/lease e orçamento,
sem adotar ou apagar diretórios ambíguos.

### Publicação confirmada

Repositório **público** em https://github.com/Misael-art/Folego, licença **MIT**
reconhecida pelo GitHub e branch padrão `codex/portable-handoff-20261024`.
Apresentação e código publicados em `3f770b19dbff7e1b12a1620b4684a4673b3508b8`;
README e as duas imagens conferidos por leitura anônima e igualdade com os
arquivos locais. Descrição e dez tópicos aplicados; PR #1 atualizado e aberto.
CI desse SHA: núcleo sem Qt, Qt offscreen e contratos CLI **success**, tanto
no push quanto no PR; CodeRabbit skipped. Nenhum merge ou release foi criado.
Recibo local: `run-review-20261029/anonymous-publication-verification.json`.

## Avaliação: supervisão da acessibilidade do desktop — 2026-10-29

Pedido novo: Fôlego acompanhar entrada/acessibilidade, espelhar estado por
dispositivo e solicitar reparo manual ou automático, aguardando intervenções
dos outros projetos. Esta rodada avalia viabilidade, dependências e aceite;
não implementa nem ativa um executor novo. A solicitação de automação para
acessibilidade não amplia autorização para limpar dados, sinalizar trabalhos,
parar containers ou habilitar o executor genérico de recursos do Fôlego.

### Estado verificado e fontes oficiais existentes

- Fôlego em `e86d7d2`: há coleta de recursos, adapters somente leitura,
  coordenador, diário e workers; não há monitor ou executor de acessibilidade.
- PhaseZero, código verificado em `83c50a60`: o backend oficial é
  `linux/steamdeck/desktop_session.py`, registrado por
  `~/.config/phasezero/desktop-session.json`; CLI `pz steamdeck input status`.
  Guardião de entrada e watcher do teclado estavam ativos/habilitados na
  consulta. Supervisor `phasezero-controller-desktop.service` não instalado.
- RetroFE mantém propriedade do perfil Steam e atalhos em
  `Tools/launchers/retrofe/steam_desktop_session.py`; seu
  `desktop_environment.py` já delega a política local ao backend registrado
  do PhaseZero. Guardião de recuperação também estava ativo/habilitado.
- Consulta oficial de status retornou processo com exit 0, mas `ok=false`,
  `desktopReady=false`, `ownershipRecovered=true` e `touchscreen=missing`.
  USB observado, dispositivos enumerados pelo KWin habilitados, teclado virtual
  disponível em modo 1 e áudio enumerado sem mute. Enumeração não comprova
  movimento, clique, caractere digitado, toque físico, audição ou fala.

### Lacunas que precedem a automação coordenada

1. **Não existe exclusão mútua comum de reparos.** `guardian.lock` do PhaseZero
   protege instâncias de `watch`; `reconcile`/`capture` não adquirem essa mesma
   trava de operação. RetroFE tem locks próprios de perfil/atalhos, e o
   coordenador do Fôlego protege somente seus participantes. Ler “active” no
   systemd ou conferir lease antes do efeito não elimina a corrida posterior.
2. **Contrato de saúde/propriedade ainda precisa de qualidade explícita.** O
   status do PhaseZero não pode ser interpretado só pelo exit code; leituras
   vazias/indisponíveis e erros ao verificar identidade precisam continuar
   desconhecidos. A leitura booleana `process_alive` existente exige revisão
   de falhas de observação antes de servir como autorização ao Fôlego.
3. **Containers não estão cobertos como donos de dispositivos.** O adapter
   atual do Fôlego lista containers/imagens/volumes, não acesso a `/dev/input`.
   Dispositivo passado ao container continua sendo recurso do host. Identificar
   descritor aberto não prova captura exclusiva; processos/projetos precisam
   cooperar com o mesmo contrato de propriedade.
4. **FTS e login são outro nível.** Touchscreen continua ausente. O reparo FTS
   restrito está no PhaseZero; fallback físico e persistência não homologados.
   Units de usuário em `graphical-session.target` não certificam entrada no
   greeter SDDM. Fôlego aberto depois do login não resolve sozinho bloqueio
   ocorrido antes dele. Usar [systemd.special](https://freedesktop.org/software/systemd/man/latest/systemd.special.html#graphical-session.target)
   e [documentação Docker](https://docs.docker.com/engine/containers/run/#runtime-privilege-and-linux-capabilities)
   como referência desses limites.

### Incrementos e aceite propostos

| Ordem | Integração | Dependência e aceite |
| --- | --- | --- |
| 1 | Monitor somente leitura, CLI e painel Entrada/Acessibilidade | Usar registro do backend, validar schema/owner e orçamento total; representar saudável/degradado/desconhecido/ausente conforme capacidades do host. Pode avançar sem esperar reparo FTS. |
| 2 | Protocolo comum e reparo manual | Estender o backend oficial, sem copiar sua política para Fôlego. Todos os caminhos envolvidos publicam/adquirem lease/trava por domínio/dispositivo. Testar concorrência, falha, filhos vivos, reboot/PID reutilizado e falta de evidência em fixtures. |
| 3 | Supervisão automática limitada, independente da janela | Após o contrato comum: aguardar dono, reler estado, solicitar operação com ID, verificar resultado; cooldown, orçamento, disjuntor e intenção durável. Reconciliar timeout sem retry cego. Serviços existentes não significam que suas GUIs precisem ficar abertas. |
| 4 | Garantia operacional antes do login e transições físicas | PhaseZero é owner do reparo FTS/boot. Validar driver e toque real, SDDM, cold boot, logout/login, suspend/resume, dock/USB, Steam/Big Picture e frontend com emulador filho vivo. Falha física não pode ser aprovada por fixture. |

Fluxo requerido: observar → outro dono reparando/usando → aguardar sem efeito →
adquirir exclusividade e revalidar → intenção → pedir reparo ao owner → testar →
confirmar resultado ou manter parcial/desconhecido. Heartbeat vencido sozinho
não prova abandono. Trava ausente só é autoridade quando todos os writers usam
o protocolo. Nenhum restart global de KWin/Steam/USB nem reset de barramento
compartilhado deve ser usado como fallback automático.

Na interface: cards com ícone **e texto** para Deck/trackpads, toque, teclado
físico/virtual, mouse/controles externos, áudio/microfone; mostrar dono, última
verificação, motivo e estado “aguardando PhaseZero/RetroFE”. Botões “Verificar”
e “Solicitar reparo” usam o mesmo controlador e as mesmas portas de automação,
sem caminho manual que ignore propriedade. Tab/Enter, nomes acessíveis e
feedback sem depender só de cor fazem parte do aceite. Não gravar teclas ou
áudio para manter o monitoramento.

A política observada é teclado automático somente por toque na tela (modo 1),
com atalhos explícitos preservados. O termo “touchpad” no pedido pode significar
trackpad ou touchscreen; esclarecer antes de alterar esse comportamento. O
pedido termina por solicitar avaliação; implementação e ativação não foram
inferidas desta avaliação enquanto essa escolha de escopo estiver pendente.

Verificação desta rodada: leitura do anexo e dos fontes responsáveis,
`systemctl --user show` das quatro units, enumeração do kernel/KWin e CLI
oficial de status, sem gravação de configurações, coleta de teclas, restart,
sinal ou reparo no host. Alteração apenas documental: revisar diff/referências;
não há nova contagem de testes de produto. Próximo passo concreto: incremento
1 e contrato comum do incremento 2, preservando os executores oficiais.

## Implementação: supervisão de entrada independente — 2026-10-29

O usuário aprovou avançar e corrigiu a premissa conjuntural: **PhaseZero pode
não existir no host**. A avaliação acima é histórica; esperar esse projeto
não é pré-requisito de implementação ou operação. Owner: Fôlego para observação,
política e reabilitação restrita de entrada no KWin; os responsáveis externos
continuam donos de seus perfis, drivers e recuperações específicas.

### Incremento integrado

- Nova CLI `accessibility` e sexta aba, cartões com ícone/texto para oito
  capacidades e estado espelhado na central. Coleta por worker, comandos por
  QProcess e dados antigos/incompletos sem aprovação implícita. A central ganhou
  rolagem após a QA Wayland reproduzir altura excessiva com fontes/mensagens
  reais; navegação e controles continuam acessíveis em 800×600.
- Backend nativo Linux/KWin, sem Qt em core/actions/CLI e sem executar caminhos
  do registro de terceiros. Outros desktops e dependências ausentes preservam
  observações possíveis e informam o reparo não suportado. Identidade inclui
  boot, dono único D-Bus/UID, event e chave física; duplicidade protege.
- Único efeito: `enabled=true` de entrada identificada, seguido de leitura.
  Política própria captura somente estados habilitados, preserva desconectados
  e incorpora hotplug saudável. Não altera drivers, Steam, atalhos, perfis,
  áudio, USB, login do sistema, containers ou processos de trabalho.
- Coordenador/diário existentes, intenção durável, ID estável, reconciliação
  sem reaplicar, cooldown 60 s, até três tentativas/h e disjuntor persistente.
  Resultado incerto continua pendente; rearmar exige revisão explícita e
  configuração habilitada comprovada, sem operações pendentes.
- Leases genéricos para aplicações cooperantes, com boot/PID/starttime, filhos,
  slots estáveis e trava comum. Filho vivo/desconhecido e reparador morto
  preservam propriedade/incerteza. Schemas desconhecidos não liberam recursos.
  Docker/Podman presentes são consultados com campos restritos de dispositivos;
  exposição/consulta desconhecida bloqueia. Integrações legadas ativas ou
  desconhecidas aguardam sem serem interrompidas.
- Unit de usuário `folego-accessibility.service`, independente da janela,
  vinculada à sessão gráfica e opcional em instalações novas. A autorização
  específica de monitoramento/ativação foi registrada no AGENTS; não habilita
  o executor genérico de recursos nem arquivamento de fixtures.

Operação, matriz por host, pausa, desinstalação e protocolo estão em
[ACESSIBILIDADE.md](ACESSIBILIDADE.md). O README público distingue claramente
a política de entrada do executor automático de recursos ainda desligado.

### Evidências e limites

- Gate final `./dev check`, Python 3.14.7 gerenciado, HOME/XDG privados,
  suítes sequenciais: **994 passed, 2 skipped em 17,69 s** sem Qt e
  **1236 passed, 2 skipped em 28,37 s** com Qt 6.12.0 offscreen; diff check aprovado.
  Logs/run.json: `run-a1i86z0r` e `run-pooobcvm`. Os dois skips em cada perfil
  exigem Edge real ausente. Regressão final de consultas: 42 testes headless
  focados aprovados em 1,30 s antes desse gate completo.
- Primeira ampliação focada: 79 passed/3 failed. Corrigidos o seam do teste
  da consulta do diário e o piso da janela, sem afrouxar o aceite. A repetição
  passou com 82 testes. A QA nativa posterior encontrou 800×652 com mensagens
  reais: as duas tentativas falhas foram preservadas; rolagem corrigiu a causa.
- QA KDE/Wayland real em HOME próprio: janela exposta em 800×600 e 1280×800,
  navegação da central à aba, foco por Tab, cancelamento sem despacho e
  operação desconhecida impedindo retry. Consulta nativa do host somente
  leitura: KWin, entradas habilitadas e PhaseZero ativo. Launcher oficial
  `./dev gui` sobreviveu cinco segundos em HOME próprio; só seu processo
  foi encerrado. Capturas são do cliente em compositor real, não certificam
  arraste, toque físico ou leitor de tela.
- A regressão de prazo/saída usa exclusivamente consultas e descendentes
  descartáveis. Inclui líder encerrado com filho mantendo pipes: o grupo
  próprio é encerrado antes de reaproveitar/recolher sua identidade.
- Fontes, unidades, diário, orçamento, perda de resposta, PID reutilizado,
  boot anterior, filhos vivos/desconhecidos, containers, host sem PhaseZero,
  backend ausente e hotplug têm testes. Nenhuma entrada física foi desabilitada
  como fixture; nenhuma unit de terceiro foi reiniciada.

Evidência local privada em `.scratch/dev-tests/run-review-20261029/`:
`accessibility-native-3/{report.json,launcher-report.json,activation.json}` e
capturas; tentativas 1/2 e logs/run.json anteriores permanecem identificados.
Só gerados próprios concluídos e revisados foram removidos após preservar logs,
para respeitar o teto de vinte workspaces; guardas não foram ampliadas.

### Ativação autorizada neste host

Executados `./dev run accessibility enable --confirmar --json` e
`./dev run accessibility install --confirmar --json`. A unit do Fôlego foi
verificada `enabled`, `active/running`, status 0, com heartbeat recente e zero
reinícios observados. Política habilitada, baseline vazio e nenhuma operação
pendente: ciclo **waiting**, aguardando o PhaseZero ativo. Isso confirma a espera,
não comprova reparo físico ou transição após reboot. Não foram parados os
guardiões existentes, e o executor automático de recursos continua desligado.

A exclusividade só existe entre participantes do protocolo. Aplicações
não cooperantes podem intervir após a leitura; inventário não cobre todos os
descritores, capturas exclusivas ou daemons remotos. Não declarar garantia
universal de acessibilidade. FTS ausente, boot/SDDM, login/logout, suspensão,
dock, atalhos Steam, leitor de tela e soak contínuo de duas horas continuam
pendentes. Próximo passo: integrar writers interessados ao protocolo e validar
essas transições no alvo físico, sem desligar entradas de trabalho para testes.

### Fechamento e publicação

Implementação, testes e documentação publicados no commit
`02db56c8d7399ddb3e8ba546f66358ec01f9f73f`, na branch padrão de continuidade
`codex/portable-handoff-20261024`; SHA remoto conferido. Repositório público e
licença MIT novamente confirmados. [PR #1](https://github.com/Misael-art/Folego/pull/1)
reutilizado, aberto e atualizado com o comportamento final e seus limites.
CI desse SHA: núcleo sem Qt, Qt offscreen e contratos CLI **success** no push
e no PR; CodeRabbit/Sourcery **skipped**. Nenhum merge ou release.

Após atualizar o código de consultas, somente a unit do Fôlego foi reiniciada
para carregar a versão validada. Consulta final: `enabled`, `active/running`,
`ExecMainStatus=0`, `NRestarts=0` (reinícios por falha), heartbeat recente,
política habilitada, ciclo `waiting` pelo PhaseZero e nenhuma operação pendente.
Diário do host: **zero intenções de reparo de acessibilidade**. O fechamento
subsequente altera apenas este registro, sem mudar o código testado.

### Correção de teste temporal descoberta na CI de fechamento

A CI de `a65a0027c5f76b30f80c50509c84663c5f8fa3e9` aprovou todos os jobs do PR,
mas o Qt do push falhou no teste **preexistente**
`test_file_changed_mid_read_is_not_certified`: 1235 passed, 2 skipped e uma
falha. [Job preservado](https://github.com/Misael-art/Folego/actions/runs/40978896214/job/123813676422).
O leitor retornou corretamente “em andamento” quando seu passo excedeu 10 ms;
o teste assumia que o diagnóstico final ocorreria na primeira chamada. Isso
não demonstra uma falha do novo reparador nem autoriza aumentar o orçamento.

A fixture agora injeta o relógio já suportado pelo leitor, isolando a mudança
de arquivo da latência do runner. Outra regressão expira explicitamente o
mesmo orçamento de 10 ms durante a mudança e exige estado não certificado,
seguido de revalidação que lê o conteúdo novo. Nenhum limite ou código de
produção foi alterado. Focados: `./dev test-headless tests/test_history_reader.py`,
**12 passed em 0,44 s**. Resposta/log da CI preservados em
`accessibility-native-3/failed-ci-job.json`; não se apagou a falha nem se
reexecutou o job para obter verde sem uma correção.

Gate após corrigir a fixture: `./dev check`, mesmas ferramentas, perfis privados
e execução sequencial, **995 passed, 2 skipped em 19,66 s** sem Qt e
**1237 passed, 2 skipped em 32,50 s** com Qt. Diff check aprovado; logs/run.json
em `run-2usf6g4u` e `run-3ay4598a`. O código de produto segue o SHA `02db56c`;
este incremento altera apenas o teste e o presente registro de continuidade.
