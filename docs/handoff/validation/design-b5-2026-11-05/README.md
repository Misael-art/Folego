# Revisão de design da b5 — 05/11/2026

Owner da apresentação: `src/folego/ui`. Base da auditoria: `8033b0f`.
O [registro de design](../../../DESIGN.md) reúne o histórico e a direção
vigente. A primeira reprodução mostrava quatro cotas com atalhos abertos,
o rótulo de Grok abaixo da dobra e o cabeçalho lateral cortado pelo
estreitamento da área rolável. A janela superior tinha 132 px e espaçava
as métricas conforme a largura disponível.

## KDE/Wayland

O [recibo final](result.json) de `tools/verify_window_navigation.py --dock-modes`
registra 19 casos aprovados em janelas próprias. A Central foi mapeada em
900 × 620 na saída de 2560 × 1080, com cantos de alfa real. Os encaixes foram
exercitados na área útil de 948 × 593 em escala fracionária. Laterais de
112 px, topo de 120 px, hover dos atalhos, posição no compositor, rolagem até
a quarta cota, cabeçalho fixo, ida e volta pela Central e saída passaram.
O topo exibiu quatro cotas com badges e atalhos, com faixa de rolagem zero.

- [Lateral esquerda após rolar](dock-left-scrolled.png)
- [Lateral direita após rolar](dock-right-scrolled.png)
- [Topo com quatro cotas e atalhos](dock-top-scrolled.png)

As tentativas anteriores ficaram em `.scratch/dev-tests-reviewed/design-b5-native-20261105*`.
Elas detectaram altura insuficiente ao retornar ao compacto, sobreposição no
topo em escala fracionária, remapeamento inicial do KWin, calibração do ponteiro
e uma animação com referência Qt já destruída. A última revisão também mede a
largura do conteúdo dentro do viewport lateral. O recibo final é de uma execução
integral. Os dados de telemetria, contas e badges são de demonstração.

## Telas de diagnóstico

Capturas Qt offscreen de 800 × 600, com dados próprios de demonstração.
Exercitam composição e estados de tela. A aparência dos ícones nativos pode
variar com a integração do desktop.

- [Atividade recente](dashboard.png)
- [Disco antes da primeira análise](disk.png)
- [Título longo na biblioteca de prompts](custom_prompts.png)

Toque físico, leitor de tela, outras escalas de encaixe, áudio real de bateria
e uso prolongado requerem seus próprios ensaios.
