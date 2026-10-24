# Continuidade — 18/10/2026

Registro mais recente:
[processos, ajustes e histórico](processos-ajustes-historico.md).
Suíte final: **1127 passed in 24.92s** (`process-ui-suite.log`); sem Qt:
**917 passed in 14.82s** (`process-headless.log`). Os registros abaixo descrevem
os incrementos anteriores; suas pendências foram atualizadas nos documentos
posteriores, preservando este histórico.

Working tree anterior preservado; nenhum commit, autostart, limpeza do host ou
ação sobre daemons/processos de trabalho. Python 3.14.7, PySide6 6.11.2,
QT_QPA_PLATFORM=offscreen pela fixture. Os resultados históricos em
`../evidencias` permanecem intactos.

## Implementação e cobertura

| Achado | Mudança / teste | Limite |
|---|---|---|
| C06 | `dashboard_tab`: linha reutilizada volta visível; callback em slot Qt; teste original preservado, teste adicional de conteúdo/callback/foco | Validação de compositor pendente |
| C07 | `--without-qt` exclui módulos Qt antes da importação; CI usa opção e basetemp exclusivo | Actions remoto não executado |
| C01 parcial | Falha de resultado final retorna desconhecido com ID e efeitos observados; intenção bloqueia retry após reinício. Exceção/violação de contrato no executor vira desconhecido. Escritas curtas do diário são completadas | Consulta/reconciliação de domínio e matriz completa de quedas ainda pendentes |
| C02 parcial | Prazo e validade do objeto grant são verificados após adquirir a trava | Revogação persistida, pausa e ordem conjunta de locks ainda pendentes; espera ilimitada ainda disponível |
| C04 parcial | Mesmo ID com plano diferente recusa, comparando todos os campos serializados; testes após reinício para ação/alvo/parâmetros/prazo | Snapshot profundamente imutável, schema/política e consentimento ponta a ponta pendentes |
| C09 | ConfigStore lê/altera/grava sob a mesma trava; teste intercala outra instância antes da aquisição para preset e modo | Ordem com coordenação da execução ainda pendente em C02 |
| C12 parcial | CLI ecosystem serializa o snapshot já coletado; teste conta uma chamada e verifica evidência serializada | Referências/contextos/URIs dos adaptadores continuam incompletos |

Testes: `test_orchestration_coordinator.py`, `test_orchestration_journal.py`,
`test_automation_config.py`, `test_ecosystem_adapters.py`, `test_ui_dashboard.py`.
Os testes novos usam estado descartável, executores/runners falsos e verificação
de não repetição/efeitos. O teste original de retorno da mesma linha continua.

## Execuções

- Regressão original isolada: falhou antes da correção.
- Painel + ensaio de widgets: 17 passaram antes do novo teste de foco.
- Coordenação/disco/tmpfs focados: 45 passaram.
- Configuração/CLI de automação: 19 passaram.
- Adaptadores: 15 passaram.
- Painel final com teste de foco: 17 passaram.
- Suíte completa intermediária: 1023 passaram (34,01 s); depois 1030
  passaram (23,09 s). Não são os totais finais do checkout.
- Houve dois segfaults intermitentes em `allWidgets` no teste longo. Logs
  `qt-segfault-inicial.log` e `qt-segfault-intermitente.log` preservados.
  Fixture de descarte explícito fecha/deleta janelas após cada teste Qt,
  enquanto wrappers estão vivos, sem importar Qt nos testes puros.
- Suíte completa após descarte explícito: **1033 passed in 19.60s**.
- Repetição justificada pela intermitência: **1033 passed in 20.55s**,
  `suite-repetida.log`; primeira execução final em `suite.log`.
- Venv `.scratch/i0-headless`, sem system-site-packages, apenas `.[dev]`;
  `find_spec` confirmou ausência de PySide6 e shiboken6. Execução final:
  **835 passed in 15.48s**, em `headless.log`.

Comando completo (basetemp sempre exclusivo fora da RAM):

```bash
rtk proxy bash -c 'qa_tmp=$(mktemp -d "$PWD/.scratch/continuacao-pytest-XXXXXX"); .venv/bin/python -m pytest -o addopts= --basetemp="$qa_tmp" -q'
```

Headless: mesmo comando com `.scratch/i0-headless/bin/python` e `--without-qt`.
O script histórico `../evidencias/reproduzir.py` injeta concorrência dentro de
`ConfigStore._write`; com a nova transação isso espera sua própria trava. Sua
reexecução foi interrompida somente no processo de sonda criado nesta sessão.
Não usar esse hook antigo para validar C09: usar os testes novos que intercalam
antes da aquisição. O script histórico não foi reescrito como evidência nova.

## Estado real F0–F8 / próxima implementação

F0 mantém base/histórico. F1 tem a regressão de visibilidade corrigida; acompanhar
estabilidade Qt. F2 continua parcial/bloqueador: priorizar grant fechado por
ação/recurso, releitura de revogação/pausa sob ordem de locks, plano imutável e
mesmo snapshot desde revisão; identidades de disco e todas as entradas mutantes.
F3 tem base, mas frescor sem amostras e proteção atual no ato permanecem.
F4/F5 são parciais: botão Dar fôlego, revisão/recuperação, visibilidade conjunta,
fallback Wayland e acessibilidade ainda precisam implementação/validação.
F6 tem peças sem controlador integrado; execução automática segue desligada.
F7 permanece inventário parcial e somente leitura. F8 tem CI corrigida e
instalação CLI editable local sem Qt, mas wheel/launcher em Linux limpo,
budgets/retenção e soak prolongado não foram validados.

Nenhuma certificação KDE/X11/Wayland, screenshots de frontend, instalação GUI
limpa, soak de horas ou teste destrutivo em daemon real foi realizado nesta
continuidade. I0 recebeu implementação e execução local; I1 não está completo;
I2–I6 não devem ser marcados concluídos por estas correções.
