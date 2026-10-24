# Fôlego

Assistente Linux/KDE em Python/Qt para diagnosticar pressão de recursos e pedir
ações manuais reversíveis. A CLI funciona sem Qt. Automação real permanece
desligada; a aplicação não deve limpar o host nem encerrar trabalho útil por heurística.

## Retomar em outro host

O ponto de entrada é [NOVO-HOST](docs/NOVO-HOST.md). O estado do desenvolvimento,
ordem de trabalho e limites estão em [HANDOFF](docs/HANDOFF.md) e no
[diagnóstico consolidado](docs/DIAGNOSTICO-2026-10-24.md). Agentes devem ler
[AGENTS.md](AGENTS.md) antes de executar ações.

Cópia independente do disco: [Página privada de recuperação](https://chatgpt.com/space/page_c86741eb68348191a25318610e82b50d).

```bash
./dev setup --system-deps
./dev check
./dev gui
```

Em servidor sem desktop: `./dev setup --headless` e `./dev test-headless`.
O wrapper baixa uv **0.12.10**, verifica SHA-256, instala Python **3.14.7** e
sincroniza dependências de `uv.lock`. Tudo gerenciado fica em `.dev/`; testes
usam `.scratch/dev-tests/`, HOME privado e temporários exclusivos em disco.
Bibliotecas nativas requerem acesso administrativo. Veja o plano com
`./dev system-deps`; `--system-deps` aplica a instalação. Não é preciso ativar venv.

## Situação verificada

Em 18/10: 1134 testes com Qt 6.11.2 e 6.12.0; 917 sem Qt. Instalação GUI por
wheel em venv limpo no mesmo BigLinux, launcher GIO, remoção preservando dados e
fluxos KDE/Wayland passaram no escopo documentado. Escalas adicionais e hotplug
foram exercitados em compositor virtual; X11 usou Xvfb/KWin isolado.

**Soak de duas horas não recebeu aceite.** Houve tentativas interrompidas e
falhas do harness; a última parou com 2470 segundos registrados. Nenhum relatório
final de duas horas existe. Resultados novos do bootstrap ficam no diagnóstico
consolidado; não devem substituir silenciosamente os logs históricos.

## Mapa

- `src/folego/core`: telemetria e regras sem Qt.
- `actions`, `safely`, `orchestration`: executores, persistência, autorização e recuperação.
- `ui`: central, compacto, abas, bandeja e workers Qt.
- `tests`: contratos e fixtures descartáveis.
- `tools`: verificadores e suporte de desenvolvimento; não são serviços de produção.
- `packaging`: instalação, launcher opcional e remoção.
- `docs/reviews`: revisões, evidências e histórico preservado.

Não copie `.venv`, `.dev` ou os 5 GB antigos de `.scratch` para continuar.
O código, histórico Git, documentos e cápsulas selecionadas são o material de recuperação.
