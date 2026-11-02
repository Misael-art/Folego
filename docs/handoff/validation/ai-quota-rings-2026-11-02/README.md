# Medidores circulares de IA — 02/11/2026

Codex, Codex Web, Claude e Grok agora usam o desenho circular do medidor do
PhaseZero (`linux/ai/quota_meter.py`, `render_icon`): trilha cinza, arco de
disponibilidade, disco de identificação e número central. A apresentação vive
no `QuotaButton` do Fôlego, sem importar ou iniciar PhaseZero. O monitor, as
fontes de conta, limites de frescor, cliques, painéis e presentes existentes
continuam sendo as autoridades de dados e operações.

O número representa a cota disponível da conta padrão. Arco verde acima de
60%, amarelo entre 21–60%, vermelho até 20%; **0** tem arco vazio e **?** não
tem arco de disponibilidade. Web/Grok permanecem **?** nas fontes atuais.
Identificação azul para Codex/Web, coral para Claude e cinza para Grok.
Cores do medidor seguem a referência nos temas claros/escuros e mantêm
opacidade com fundo transparente. Nome completo Codex Web cabe na faixa de
280 px do compacto. Entregas e presentes ficam separados abaixo dos nomes.

Transição de 450 ms somente entre percentuais conhecidos e visíveis. Número
e descrição acessível mostram o valor atual imediatamente; expiração/falha
cancelam a transição e retiram a cota anterior. Entregas confirmadas fazem a
borda interna pulsar em 1,8 s, sem representar cota ou tickets. Falha de leitura
das entregas interrompe o pulso. Ocultar interrompe todas as animações; o
monitor de consultas continua independente. A referência local tem anel
atualizado por observação; a transição e o pulso atendem ao pedido de animação.

## Validação

- Focados: **16 passed**, 1,48 s. [Log](focused.txt). Expiração durante animação,
  falha, zero/desconhecido, atualização de frescor sem reiniciar transição,
  pulso somente com contagem confirmada/visível, quatro colunas com presentes,
  temas/transparência e regressões existentes de conta/clique/tickets.
- `./dev check`: **1168 passed, 2 skipped** headless, 25,31 s; **1484 passed,
  2 skipped** Qt, 97,45 s. [Núcleo](headless.txt) · [Qt](qt.txt). Python 3.14.7
  gerenciado, HOME/XDG/TMP/Pulse privados, sequencial. Carga do host observada
  em 10–12; nenhum trabalho alheio interrompido. Os dois skips dependem de
  Edge real ausente no perfil privado.
- `tools/verify_window_navigation.py --ai-quota-rings`: **oito cenários
  aprovados** em KDE/Wayland real, dentro do watchdog existente de 45 s.
  [Resultado](native.json). Central/Voltar, três combinações SNES/PS2 e
  transparência, pulso em fases distintas, transição, expiração, clique nativo
  no provedor, hover nativo, presente por Qt, ocultação e saída por Controles.
  A abertura de cliente foi interceptada em memória; não se acionaram agentes,
  credenciais, clipboard, som ou recursos pessoais. Métricas e contas sintéticas.
- Primeira tentativa **não aprovada**: calibração do ponteiro deixou o hover
  abrir o painel antes do clique, que fechou o popup. [Registro](native-attempt.json).
  Harness ajustado para verificar hover, fechar o popup próprio e enviar o
  clique nativo na mesma posição. Tentativa original preservada; sem ampliar
  prazo, somar tentativas ou alterar o comportamento do produto para QA.
- Baseline remoto `0239f4921e144ac839c5a4ead86c5d315bbf921d`: núcleo e CLI verdes;
  Qt falhava em duas parametrizações do teste preexistente de transparência de
  texto (`test_ui_transparency.py:31`, alpha máximo 250/244 com fonte do Ubuntu).
  [Execução observada](https://github.com/Misael-art/Folego/actions/runs/41463952503).
  Não se afrouxou nem alterou essa asserção; o gate local atual passou.

## Revisão visual

![Medidores no tema escuro](rings-dark.png)

[Compacto claro](compact-light.png) · [escuro](compact-dark.png) ·
[fundo transparente](compact-transparent.png) · [transição](transition.png) ·
[cota vencida](expired.png) · [pulso claro](pulse-bright.png) · [pulso baixo](pulse-dim.png).

Capturas Qt de janelas próprias mapeadas no compositor, escala 135%; não são
capturas do desktop pessoal. Inspecionadas: círculos/números legíveis, nomes
inteiros, presentes/contagens sem sobreposição e largura de 280 px preservada.
Não certifica todas as escalas/compositores, leitor de tela ou soak de duas horas.

## Host

GUI anterior encerrada normalmente pela bandeja, com lock liberado, e uma
única chamada `./dev gui`. Novo PID **1827618**, starttime **10085542**;
widget em (2902,197; 33,954), 280×217, central oculta. Preferências e posição
atuais preservadas. Sem sinais manuais ou outros clientes encerrados.
Recibo privado em
`.scratch/dev-tests/run-ta5pjkkq/host-replacement/replacement-primary.json`;
revalidar boot/identidade antes de agir. QA e auxiliares próprios encerrados.
As três suítes deste lote e o QA nativo estão em seus perfis privados de
`.scratch/dev-tests`; nenhum diretório anterior foi removido.

Sem novo serviço, grant, merge ou release; `v0.2.0b2` continua imutável.
