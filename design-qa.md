# Seletor de prompts — verificação do mockup aprovado

final result: passed

Referência: [mockup aprovado](docs/handoff/validation/prompt-groups-2026-11-02/reference.png).
Implementação: [painel Qt no KDE/Wayland](docs/handoff/validation/prompt-groups-2026-11-02/prompts.png).
Comparação conjunta: [antes do refinamento](docs/handoff/validation/prompt-groups-2026-11-02/comparison-before.png),
[final](docs/handoff/validation/prompt-groups-2026-11-02/comparison-final.png),
[detalhe de Design](docs/handoff/validation/prompt-groups-2026-11-02/comparison-design-detail.png).
Nas comparações, referência à esquerda e implementação à direita.

## Alvo e normalização

- Componente nativo Qt, tema escuro, 12 prompts, seis categorias, hover no prompt
  de mockups e rodapé com Janelas/Edição/Terminal/Custom.
- Viewport pretendido: popup de até 480 × 540 px lógicos, adaptado à área da
  tela. O widget de recursos mantém seus 280 px.
- Referência gerada: 1122 × 1402 px com título/margens de apresentação. Região
  do painel recortada em (66,96,990,1148), escala uniforme para largura 480:
  480 × 557 px. A legenda 480 × 540 é uma intenção do mockup, não uma captura
  de software com medidas exatas; não se deformou a imagem para esconder isso.
- Captura nativa final: 648 × 729 px, densidade 1,35, normalizada uniformemente
  para 480 × 540. O detalhe usa a mesma largura/escala e isola a faixa de Design.
- Limite esperado: métricas da fonte nativa e altura máxima podem deixar o último
  título abaixo da dobra. A rolagem o revela e o rodapé permanece visível. O texto
  não é truncado para simular densidade da imagem gerada.

## Histórico das correções

1. Primeiro render: [P2] estilo herdado do botão de origem aumentava separadores
   e o fallback de ícone virava um bloco. Corrigidos reset local de estilos,
   dimensões explícitas dos separadores e fallback vetorial de biblioteca.
   Evidência inicial privada: `.scratch/prompt-groups-preview/top.png`.
2. Primeira comparação nativa: [P2] densidade excessiva deixava o título da
   categoria Entrega parcialmente oculto pelo viewport. Reduzidos espaçamentos,
   altura mínima das linhas e margens do cabeçalho, mantendo tamanho da fonte.
   Evidência: `comparison-before.png`.
3. Comparação final: seis âncoras de categoria legíveis, títulos horizontais,
   faixas e divisores alinhados, hover completo, rodapé fixo. `comparison-final.png`
   e o detalhe foram abertos juntos e inspecionados. Sem P0/P1/P2 acionáveis.

## Superfícies obrigatórias

- **Tipografia:** fonte sans-serif nativa Qt/KDE; cabeçalho 15 pt, corpo e
  categorias 10 pt, categorias em negrito. Títulos integrais e quebra de linha
  quando necessário. Nomes/corpos de prompts preservados, inclusive SHA do anexo.
- **Espaçamento:** hierarquia, faixas de 3 px, divisores de 1 px e rodapé conforme
  referência; altura limitada com rolagem, linhas com pelo menos 24 px. Teste
  adicional em painel 340 × 320 verifica quebra e rodapé dentro dos limites.
- **Cores:** tokens existentes de superfície/texto/borda e seis acentos da proposta.
  O nome da categoria acompanha a cor. Fonte/hover/foco têm estados distintos.
- **Ícones e imagens:** ícones nativos de copiar/avançar; fallback original de
  Tabler Icons sob MIT, com licença e SVGs incluídos no wheel. Não há arte raster
  nova na interface nem dependência do mockup no runtime.
- **Conteúdo:** 12 escolhas em seis grupos, ordem aprovada; copiar fecha o painel.
  Rodapé abre os dez atalhos e o Custom existente sem regravar sua biblioteca.

## Interações e limites

- `./dev check`: 1165 passed/2 skipped headless; 1448 passed/2 skipped Qt.
- Onze cenários KDE/Wayland finais: navegação, clique em prompt, seis macros de
  Edição/Terminal e saída. Foco retornou ao campo próprio; clipboard interceptado
  no QA nativo. Cópia e colagem reais do texto integral verificadas separadamente
  em Xvfb próprio, sem usar o clipboard físico como fixture.
- Custom: Mostrar área de trabalho e macro de teclas validados em KWin/Xvfb e
  D-Bus próprios, isolados antes dos daemons. Nenhuma operação sobre trabalhos
  ou serviços do usuário. Auxiliares encerrados.
- Teclado (setas, Tab, Enter, Escape), cópia única, cobertura das categorias,
  dimensões e rolagem cobertos em Qt. Não é certificação de leitor de tela,
  de todos os aplicativos de destino ou de conformidade WCAG integral.
- [P3] O ícone do tema KDE pode ter o desenho de duas folhas dobradas, enquanto
  o fallback e o mockup usam dois contornos simples; a ação e o rótulo são iguais.

Checklist concluído: estrutura e conteúdo; estilo local; foco/cópia/fechamento;
macros/Custom; responsividade; regressão; comparação visual; assets no pacote.
