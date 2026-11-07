# Design do Fôlego

O Fôlego ajuda a entender a pressão do Linux, localizar sua causa e revisar uma
ação sem perder o trabalho em andamento. O widget responde «como está agora?».
A Central responde «o que mudou, por quê e o que posso revisar?». Esta página
registra a linguagem visual, as decisões que chegaram ao produto e as propostas
que ainda precisam de evidência. A [passagem](HANDOFF.md) guarda datas, SHAs,
resultados e limites de cada rodada.

## Qualidade visual nos mínimos detalhes

Diretriz explícita do usuário em 07/11/2026. Cada ajuste deve cuidar de
legibilidade, alinhamento, espaçamento, contraste, hierarquia e acabamento no
tamanho real de uso. A revisão deve observar o conjunto e os pequenos grupos
de informação, inclusive quando uma área tem poucos pixels disponíveis.

Leituras próximas precisam de separação perceptível e relação clara entre
rótulo e valor. A criticidade pertence a cada métrica. CPU, temperatura e RAM
usam as cores semânticas do tema no valor, com estado textual na descrição
acessível e na dica. A intensidade visual deve orientar a leitura sem disputar
atenção com o estado geral, a navegação e a tarefa principal.

Na mini horizontal, pequenas células arredondadas agrupam CPU, temperatura e
RAM. O rótulo discreto fica acima do valor, com margens próprias e intervalos
regulares. CPU acompanha os limiares de uso da Central, RAM acompanha a folga
configurada e temperatura acompanha os limites fornecidos pelo mesmo sensor.
Uma medida sem avaliação válida usa apresentação neutra. Pausa e leitura
antiga retiram o valor e a cor anterior.

O aceite visual inclui estados normal, atenção, crítico e indisponível,
tema claro e escuro, tamanho lógico e escala do ambiente. Conferir cortes,
distância entre grupos, foco e acesso aos controles faz parte da entrega.
Capturas recentes e resultados de execução fundamentam o registro de aceite.
A diretriz também está registrada no AI Memory do projeto em
`_rules/qualidade-visual-nos-minimos-detalhes.md`.

## Calor e pedidos de alívio aos agentes

O alerta térmico usa o limite **do mesmo sensor** que fornece a temperatura.
Neste host, a zona ACPI informa 100 °C passivo e 105 °C crítico. Com esses
valores, 95–99 °C é aviso, 100–104 °C é urgência e 105 °C ou mais é limite
crítico do equipamento. Abaixo de 95 °C a leitura segue visível; nenhum valor
é transplantado para sensores sem limites ou para outra máquina. O card da aba
Disco e a avaliação geral compartilham a severidade; a bandeja avisa quando a
leitura atual entra numa faixa e repete com intervalo limitado. Pico passado
continua no histórico visual, sem disparar uma notificação como se fosse atual.
Fonte ausente, antiga ou inválida produz estado desconhecido. O rótulo ACPI
preserva a distinção em relação à temperatura direta da CPU.

**Controle antiestresse proposto, ainda sem executor:** o Fôlego pode publicar
uma solicitação local, com ID, boot, prazo e intensidade, para agentes que
aderirem explicitamente. Um agente participante confirma o recebimento e pode
adiar novos builds, reduzir jobs ou salvar um ponto de retomada antes de pausar
seu próprio trabalho. Falta de confirmação permanece desconhecida; não autoriza
sinal, congelamento ou fechamento pelo Fôlego. O pedido termina por prazo ou
recuperação térmica sustentada e tem orçamento e disjuntor para evitar oscilações.
O gatilho combina calor atual e pressão CPU/memória/I/O; PSI sozinho não atribui
culpa a um processo. Integração com Codex, Qoder ou outro agente só existe após
um canal suportado e autorização do respectivo owner. Limites de CPU por cgroup
são opção apenas para jobs iniciados em escopos próprios ou aderidos
explicitamente, com restauração e confirmação de identidade. Congelar cgroups
ou enviar SIGSTOP a agentes arbitrários pode deixá-los segurando locks, perder
heartbeats e tornar o resultado incerto; não faz parte desta proposta.

## Linguagem visual e estados

- **Hierarquia.** Estado, valor e ação aparecem em níveis separados. FÔLEGO é a
  marca dos cabeçalhos. A Central usa a fonte sans-serif da interface Qt/KDE,
  com pesos mais fortes para títulos e valores. O widget usa Noto Sans
  seminegrito no nome e preserva a leitura das métricas mesmo em barras estreitas.
- **Cor.** SNES americano é o padrão. Super Famicom, Mega Drive/Genesis,
  Master System III, PC Engine, NES, TurboGrafx-16 e PS2 completam a família.
  A inspiração vem dos contrastes, materiais e cores de controle dos consoles.
  Os tokens separam superfícies, texto, foco, ações e severidade. Texto e estado
  acompanham verde, âmbar e vermelho. A cor de saúde conserva o significado
  entre os temas. Testes verificam contraste de 4,5:1 nas superfícies opacas
  previstas. [Paletas](../src/folego/ui/palettes.py) · [Matriz dos temas](handoff/validation/console-themes-2026-11-02/README.md)
- **Controles.** A rolagem usa trilho discreto e polegar em cápsula, com
  área interativa de 12 px, polegar de 6 px e 8 px no hover. Medidores lineares
  têm pontas arredondadas. Chevrons, ícones do tema e fallbacks licenciados
  acompanham o foco e o estado indisponível. Rótulos acessíveis descrevem as
  ações de botões que exibem só ícone. [Estilo Qt](../src/folego/ui/theme.py) · [Modernização dos controles](handoff/validation/modern-controls-2026-11-04/README.md)
- **Cantos e transparência.** O painel de contas é uma superfície contínua,
  com rótulos e contêineres transparentes. Central e widget pintam caminhos
  arredondados com alfa real nos cantos, com espaço para a rolagem. A preferência
  de fundo vai de 0% opaco a 100% sem fundo, com conteúdo e contornos opacos.
  A janela conserva opacidade 1. A prévia de arraste fica na
  interface e a gravação ocorre ao soltar. As chaves de QSettings são
  `appearance/theme` e `appearance/background_transparency`. Valor inválido
  é informado e falha de gravação restaura a escolha. [Transparência](handoff/validation/background-transparency-2026-11-02/README.md) · [Cantos da Central](handoff/validation/central-rounded-2026-11-04/README.md)
- **Qualidade da leitura.** Aguardando, parcial, antigo, erro, vazio comprovado,
  proteção e resultado incerto têm mensagens próprias. Rótulos legíveis
  acompanham valores, estimativas e recusa. A interface apresenta o snapshot e
  as decisões do núcleo. Leitura pesada e operações passam pelos workers,
  com revisão, autorização e resultado pelo mesmo ID.

## Widget, encaixes e ações rápidas

A faixa [mini horizontal](handoff/validation/mini-widget-2026-11-07/README.md)
usa a mesma janela e os mesmos dados do widget: uma linha de leituras essenciais,
estado textual e cromático, alça de movimento e três caminhos visíveis
(compacto, Central, seletor de formatos). O seletor lista destinos diretamente
em todos os formatos. Alertas com fonte ausente não viram valores seguros; o
compacto e a Central mantêm o detalhamento.

1. **Conceito original.** O cabeçalho com “Central” e vários botões avulsos
   evoluiu para dois grupos. O teclado abre embaixo e seu chevron abre no topo.
   A grade abre a Central e seu chevron reúne ocultar, sair, contas e posições.
   A marca ganhou peso próprio e o flutuante preserva 280 px de largura.
   O botão de pausa e a memória livre ficam próximos do resumo. O flutuante
   cresce com alertas. [Mockup e primeira comparação](handoff/validation/compact-ui-2026-11-01/README.md) · [Cabeçalho compacto](handoff/validation/compact-header-quota-2026-11-03/README.md)
2. **Encaixe e retorno.** Uma faixa de dois tons escurece na borda sob o
   ponteiro e revela a seta. O fluxo aprovado leva da borda esquerda do
   flutuante à lateral direita, da direita à lateral esquerda e da superior
   ao topo. A alça da lateral fica na sua borda externa e retorna ao flutuante.
   O seletor de visualização oferece as cinco escolhas sem depender do hover. A
   geometria usa a área útil da saída e respeita painéis conhecidos. Qt anima
   a posição em 260 ms quando a plataforma permite. No Wayland, o KWin é
   responsável pela posição, com fade, leitura posterior e reposicionamento
   limitado após remapeamento. O caminho de retorno reaproveita a janela própria
   e a geometria flutuante. [Encaixe](handoff/validation/dock-widget-2026-11-03/README.md) · [Correção de remapeamento](handoff/validation/dock-remap-2026-11-04/README.md)
3. **Laterais.** A proposta de transferir a composição flutuante para a barra
   gerava largura excessiva e controles espremidos. A direção aprovada usa
   112–128 px, medidor de folga dominante e centralizado, leituras em pilha
   alinhadas à esquerda ou à direita conforme a lateral, memória livre,
   pausa larga e cotas menores em coluna. O rodapé revela os seis atalhos
   em pilha. A revisão b5 mantém cabeçalho e rodapé fora da rolagem, com
   medidor, leituras, avisos e cotas numa área independente. A última cota
   continua alcançável ao rolar quando a altura é insuficiente.
   [Barras adaptáveis](handoff/validation/dock-adaptive-2026-11-04/README.md)
4. **Topo.** O mockup foi revisto para tirar a pausa debaixo da folga. A
   composição aprovada começa com marca e folga à esquerda, seguida das cotas,
   leituras agrupadas e teclado/menu à direita com pausa centralizada abaixo.
   A prévia b4 usava 132 px a partir de 900 px de largura útil. Na b5 são
   120 px lógicos, com medidor de no mínimo 64 px, leituras em uma área de
   330 px e avisos ao lado. Abaixo de 900 px, o encaixe usa a composição em
   duas linhas de até 190 px. [Rodada do mockup e hover](handoff/validation/top-hover-2026-11-04/README.md)
5. **Atalhos.** Selecionar tudo, Apagar tudo, Prompts, Copiar, Colar e Print
   formam duas linhas de três no flutuante, uma coluna nas laterais e uma
   linha no topo. A gaveta começa recolhida, anima por 140 ms e aguarda 200 ms
   na saída. O teclado e seus menus preservam o foco da aplicação de destino.
   Copiar usa Ctrl+Insert. A edição tenta apenas o campo ativo verificável e
   a captura usa a seleção de região do Spectacle, com preferência de ocultar
   o flutuante temporariamente. Os botões da grade dividem a largura apesar
   das métricas diferentes das fontes Qt. [Edição, captura e áudio](handoff/validation/editing-capture-audio-2026-11-01/README.md)

## Medidores, contas e sons

- A folga resume a menor margem observada entre memória, swap e temporários.
  CPU, RAM, swap e Tmp têm valores rotulados. Temperatura e RPM compartilham
  uma linha no flutuante, em °C e RPM. ACPI identifica a zona térmica do
  sistema quando ela é a única fonte. Sensor ausente aparece com traço e
  zero RPM é uma medida válida. A leitura de hwmon é observacional.
  [Cooler e limite do host](handoff/validation/cooler-monitor-2026-11-04/README.md)
- Codex, Codex Web, Claude e Grok compartilham o padrão de disco do provedor,
  percentual no centro e anel semântico de cota. Somente cotas positivas
  confirmadas aparecem na faixa, em ordem decrescente. O menu mantém acesso a
  contas esgotadas ou desconhecidas. O detalhe separa janelas de consumo,
  reposições, tickets, validade e referência de assinatura. Reset esperado
  sozinho não confirma reposição. O anel anima mudanças, o retorno confirmado
  reaparece com transição e som, entregas pulsam na borda e tickets confirmados
  usam um presente verde. [Medidores](handoff/validation/ai-quota-rings-2026-11-02/README.md) · [Tickets](handoff/validation/reset-gifts-2026-11-02/README.md) · [Fontes e limites](COMPACTO.md)
- A bateria válida mostra verde nas faixas altas, amarelo em 50%, laranja
  em 25% e vermelho a partir de 10% para baixo. Ao descarregar, a passagem
  por 75%, 50% e 25% toca avisos progressivos. Em 10% ou menos, o aviso
  repete a cada minuto. Tempo restante aparece quando o kernel fornece
  estimativa ou dados coerentes de energia e consumo. A pausa respeita a
  validade da leitura. As preferências de som e volume preservam ajustes
  feitos pelo usuário durante a reprodução. [Bateria](handoff/validation/battery-2026-11-04/README.md)

## Central, diagnóstico e biblioteca

- **Central.** A navegação lateral tem nomes com inicial maiúscula e 6 px
  de respiro de cada lado. FÔLEGO substituiu a marca em caixa mista.
  O botão Voltar foi retirado após a adoção de Modo widget e do menu de posição.
  O quadro superior usa título e estado, linhas para Disponível, Em uso e
  Aplicativo e espaços próprios para motivo, alertas e ação. Leituras inválidas
  são limpas. Na b5, Atividade recente destaca a última ação, seu resultado e
  horário, com automação, saúde por recurso e registro bruto nos detalhes
  expansíveis. O diagnóstico copiado conserva o conteúdo técnico.
  [Resumo superior](handoff/validation/hero-summary-2026-11-05/README.md)
- **Ajustes, Órfãos, Disco e Temporários.** Ajustes informa a configuração
  observada do navegador, com aplicar e reverter. Órfãos distingue indícios,
  proteções, candidatos e sobreviventes. SIGTERM e SIGKILL têm etapas separadas.
  Em Disco, plano, quarentena reversível, restauração e exclusão definitiva
  têm fronteiras visuais e operacionais. Temporários apresenta volumes, plano
  e itens retidos, com uso, folga e estimativa quando calculável. Na b5, tabelas
  sem linhas cedem espaço ao estado e à ação de consulta. [Especificação histórica de temporários](superpowers/specs/2026-10-15-temp-spaces-monitor-design.md)
- **Desempenho.** Estado do automático, proteção de projetos, sugestões,
  aplicativos observados, pontes MCP e regras descrevem camadas diferentes.
  A lista de apps precede as regras na b5. Manual, sugestões, Assistido e
  Automático têm autorização e comportamento próprios. [Modo Desempenho](MODO-DESEMPENHO.md)
- **Acessibilidade e Opções.** As capacidades de entrada usam cartões
  acionáveis com resultado por dispositivo. Verificar agora fica ao lado
  do estado, com Habilitar tudo em ação própria. Verificação de configuração
  e teste físico são evidências distintas. Aparência, captura/som, início com
  a sessão, operações pendentes e temporários próprios têm grupos separados
  em Opções. [Entrada e recuperação](ACESSIBILIDADE.md)
- **Prompts.** A direção aprovada usa seis faixas laterais de cor, cabeçalhos
  horizontais, copiar por linha, até 480 × 540 px e rodapé fixo com Janelas,
  Edição, Terminal e Custom. A comparação nativa corrigiu a herança de estilo,
  o fallback de ícone e a densidade. O catálogo passou de 12 a 13 itens com o
  prompt de implantação. O editor de textos e macros usa até duas linhas para
  o título e guarda o texto completo na dica e no formulário. Menu e macros
  têm navegação por teclado e retornam o foco ao destino. [Mockup aprovado e comparação](../design-qa.md) · [Editor Custom](handoff/validation/custom-prompts-2026-11-01/README.md)

## Saúde do host e guarda preventiva — 05/11/2026

O [mockup](handoff/validation/host-guard-2026-11-05/mockup.png) antecedeu a
implementação e reutiliza a aba Disco, a navegação lateral e a paleta existente.
A [captura Wayland clara](handoff/validation/host-guard-2026-11-05/wayland.png)
e a [escura](handoff/validation/host-guard-2026-11-05/wayland-dark.png) mostram
a revisão: o resumo da Central leva aos detalhes, o aviso térmico ocupa uma
única área de destaque, e pressão, NTFS, serviços, Btrfs e boots aparecem numa
lista contínua. A análise de espaço e a quarentena continuam abaixo, alcançáveis
pela mesma rolagem. Não foi criada uma décima aba nem uma grade de cartões.

O título do aviso diferencia temperatura atual de pico recente e nomeia **ACPI**
quando é essa a fonte. O limite térmico só aparece quando o sensor correspondente
o fornece. RPM ausente permanece ausente. Contador Btrfs absoluto é distinguido
da diferença entre leituras, e o primeiro ponto de comparação não a inventa.
Avisos NTFS exibem janela, número e volume apenas como candidato quando há uma
única montagem compatível. Uma unit exibe a contagem atual do systemd, sem
afirmar que ela causou um reboot. O journal sem desligamento registrado é
inconclusivo, não um diagnóstico de causa.

Os botões dizem **Orientação** ou **Copiar dados**: não simulam backup ou
reparo. A manutenção do filesystem e a correção da unit continuam com seus
responsáveis; o Fôlego apresenta evidência, próximo passo e estado desconhecido.
O mockup sugeria “Proteger dados”, mas a entrega usa um verbo que corresponde ao
efeito real. A coleta lenta não entra no poll de dois segundos nem toca caminhos
montados do cartão. A revisão em 800 × 600 e KDE/Wayland está no
[recibo](handoff/validation/host-guard-2026-11-05/README.md).

## Revisões, propostas e aceite

| Achado ou direção | Disposição |
| --- | --- |
| Cabeçalho com texto “Central”, botão Voltar duplicado, tabelas vazias grandes e rolagem com setas | Substituídos por controles agrupados, retorno consistente, estados visíveis e rolagem em cápsula. |
| Barra lateral apenas escalada, alças em lados trocados, cantos desenhados sobre uma janela retangular | Composição por formato, alças espelhadas e pintura com alfa. |
| Pausa comprimida sob a folga, cotas intercaladas com métricas e faixa superior alta | Mockup revisto, grupos separados e segunda redução de altura na b5. |
| Barra lateral com quatro cotas, atalhos abertos e cabeçalho cortado quando o trilho aparece | Reproduzido na auditoria em 112 × 760. A b5 separa cabeçalho, rolagem e gaveta. |
| Atividade técnica sem hierarquia, regras antes dos apps e títulos longos com rolagem horizontal | A b5 oferece resumo expansível, prioriza aplicativos observados e limita os títulos a duas linhas com dica integral. |
| Caminhos de volume truncados e densidade de tabelas em escala elevada | Próxima revisão de colunas, nomes e detalhes de linha. Caminho completo deve continuar disponível. |
| Consulta, nenhuma ocorrência, coleta parcial, falha e dado antigo em todos os painéis | Validar o vocabulário e o foco em mais estados, especialmente Ajustes e tabelas preenchidas. |
| Leitura e operação no Steam Deck, monitor HD e widescreen | Usar área útil e escala lógica do desktop. Matriz Qt cobre janela de 800 × 600 e barras em 948 × 593, 1280 × 760, 1920 × 1080 e 2560 × 1080, conforme o cenário. Medir outras escalas e toque no alvo físico. |
| Leitor de tela, duração longa, áudio físico da bateria e tacômetro disponível | Aceites separados. Capturas, testes Qt e dados sintéticos têm escopo próprio. |

Para uma nova revisão, primeiro identifique a superfície, a fonte do dado e o
estado que a pessoa precisa entender. Compare uma janela estreita com a mais
larga, tema claro/escuro, conteúdo vazio e realista, títulos longos, foco e
abertura/fechamento. Guarde capturas próprias associadas ao SHA. Para geometria
e retorno, execute o verificador KDE/Wayland com janela própria. A
[validação da b5](handoff/validation/design-b5-2026-11-05/README.md) e a
[passagem](HANDOFF.md) indicam quais cenários foram executados, quais ainda
dependem de hardware e o que pode ser reproduzido com Qt offscreen.
