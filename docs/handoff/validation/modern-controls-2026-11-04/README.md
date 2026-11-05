# Controles e rolagem coerentes — 04/11/2026

Revisão motivada pelas capturas do usuário. O tema central era parcial:
algumas barras herdavam setas/trilho do desktop, enquanto prompts e widget
tinham duas receitas locais diferentes. A revisão cobriu o tema compartilhado,
Central, opções, prompts, teclado, widget e os controles usados nas demais abas.

| Achado | Ajuste aplicado |
| --- | --- |
| Rolagem com setas e trilho rígido | Área de 12 px, polegar de 6 px arredondado, destaque de 8 px por hover/pressão, sem setas. Versões vertical e horizontal. |
| Três estilos de rolagem | Uma receita global; removidas as receitas locais de prompts e widget. Tabelas e editores recebem o mesmo padrão. |
| Medidores de 8 px com contorno e raio maior que a altura | Trilho e preenchimento em cápsula, sem contorno adicional. Valores e cores de alerta preservados. |
| Seta nativa em caixa nos seletores | Chevron vetorial com contraste claro/escuro e área de abertura uniforme. |
| Botão de menu pequeno com indicador duplicado | Controle plano de 32 × 32, foco visível e realce do tema. |
| Navegação encostada à borda e retorno duplicado | Abas com 6 px de folga nos dois lados e inicial maiúscula; marca FÔLEGO; cabeçalho sem Voltar. Modo widget e o menu de posição mantêm o retorno. |
| Nome longo de grupo impedindo janela de 800 px no Ubuntu | O seletor de grupos pode encolher; a lista aberta mantém o texto completo. O teste de 800 px foi preservado. |

Os 111 testes focados finais passaram, incluindo quatro casos novos de arraste e
navegação por teclado das barras verticais/horizontais em tema claro/escuro.
O [recibo KDE/Wayland](result.json) final passou nos oito temas: abertura nativa
do seletor, navegação Qt no popup, persistência, Central/widget, prompts e
teclado. Capturas: [Central clara](central-light.png), [opções escuras](options-dark.png)
e [prompts claros](prompts-light.png). Os dados são sintéticos, com HOME/XDG
privados e áudio indisponível para efeitos de QA.

Uma execução local completa iniciada antes do ajuste de navegação passou nos
1247 testes headless, mas a fase Qt foi interrompida sem recibo final. O log
parcial e `interruption.json` estão preservados em
`.scratch/dev-tests-reviewed/modern-controls-gui-interrupted-before-navigation-20261104`;
essa execução não comprova o gate completo. O gate remoto do commit publicado
é a verificação integral desta entrega.

O CI inicial de `cb5f16b` detectou a largura mínima de 826 px após a nova
aparência dos seletores. A correção em `d1fd7a6` passou nos 46 testes locais
de layout e abas; a falha inicial não foi ignorada nem o limite de 800 px
ampliado.

O CI da revisão conjunta `d39ace0` aprovou os seis jobs de produto, incluindo
as suítes completas sem Qt, Qt offscreen e consultas da CLI em HOME privado.
O código visual e a correção de largura estão nessa revisão; as execuções
canceladas do SHA intermediário não são contabilizadas como aprovadas.

Tentativas nativas anteriores ficaram preservadas em `.scratch/dev-tests-reviewed/modern-controls-native-*`.
Elas completaram etapas visuais, mas falharam em entrada/saída posterior e não
contam como jornadas aprovadas. O roteiro agora revalida a posição KWin antes
de clicar e aguarda o reposicionamento do compacto. Como o popup Wayland não
é uma janela KWin independente, a abertura final do menu é nativa e o clique
em Sair usa coordenadas locais Qt; clique físico no item do popup não foi
certificado por esse ensaio.

A revisão não certifica todas as escalas, toque, leitor de tela ou diálogos
externos. Tabelas extensas e agrupamento de opções ainda podem receber uma
rodada própria de organização de conteúdo; não são regressões comprovadas
nem requisitos deste ajuste de controles.
