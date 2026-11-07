# Cabeçalho compacto e faixa de cotas — 03/11/2026

[Captura](compact.png) · [Recibo do QA Wayland](native.json).

A captura mostra uma janela própria do Fôlego no KDE/Wayland, com HOME/XDG e
áudio privados, dados sintéticos e largura de 280 px lógicos. Claude e Codex
tinham cotas confirmadas (8% e 31%); Codex Web e Grok estavam desconhecidos.
O cabeçalho une as duas posições do teclado e o acesso direto à Central com o
menu de ocultar/sair/contas. Os indicadores ocultos continuam no menu.

O QA percorreu Central/Voltar, temas SNES e PS2, transparência, transição de
percentual, expiração que retira o indicador, retorno com animação, hover e
clique nativos no indicador, ticket por Qt, parada do pulso ao ocultar e saída
explícita pelo menu. A abertura do cliente foi interceptada em memória. A
tentativa inicial falhou quando o widget cresceu sob o ponteiro antes do clique
no menu; seu registro permanece em `.scratch/dev-tests/run-header-quota-20261103`.
Na repetição, o drawer foi estabilizado antes desse clique. Depois da revisão
final da animação de reabertura, o mesmo QA passou novamente nos oito casos;
a captura e o recibo publicados são dessa execução final. Não houve uso de
contas, clipboard, agentes ou áudio pessoais.

`./dev check` após a alteração: 1241 passed, 2 skipped no headless e 1570
passed, 2 skipped no Qt offscreen. Os dois skips do perfil privado dependem de
Edge real. Qt offscreen e o QA visual não certificam leitor de tela, todas as
escalas/compositores nem uso prolongado na sessão pessoal.
