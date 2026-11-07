# Resumo superior legível — 05/11/2026

O quadro superior reunia marca, estado, RAM usada/total, memória livre,
consumo do aplicativo e alertas numa frase grande. Agora o título reúne
marca/estado; três linhas alinhadas mostram Disponível, Em uso e Aplicativo.
A explicação, os alertas e a ação ficam separados. O texto original do sinal
continua no tooltip; a cópia de diagnóstico inclui as linhas em texto simples.
Quando a saúde perde validade, os valores são substituídos por —.

`./dev test tests/test_ui_dashboard.py tests/test_ui_layout.py
tests/test_ui_main_window_tabs.py tests/test_ui_console_themes.py
tests/test_ui_transparency.py -q`: **103 testes passaram** na execução final.
As tentativas anteriores encontraram o estado de coleta ausente e uma espera
de teste que observava a animação antes da solicitação enfileirada; ambas
foram corrigidas. O teste aguarda o sinal de término e continua exigindo a
duração configurada de 260 ms. Uma tentativa intermediária teve importação
incorreta no teste, corrigida antes do gate final. Todos esses logs permanecem
em `.scratch/dev-tests-reviewed/hero-text-*`; não contam como aprovação.

O [recibo Wayland](result.json) passou nos oito temas em janela e HOME/XDG
próprios. Capturas com dados sintéticos: [clara](central-light.png) e
[escura](central-dark.png). Os testes de layout mantêm o piso de 800 × 600.
Essas provas não certificam todas as escalas físicas, toque ou leitor de tela.
