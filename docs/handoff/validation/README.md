# Validação da migração em 24/10/2026

Cópia limpa do código, prefixo `.dev` inicialmente vazio, HOME privado e PATH
`/usr/bin:/bin`. O bootstrap baixou uv com SHA-256 fixado e Python 3.14.7
gerenciado; não usou Python/Qt instalados globalmente. Bibliotecas nativas são
as deste BigLinux x86_64: o instalador do sistema foi apenas inspecionado em
modo plano, sem instalar pacotes neste host.

| Execução | Evidência | Resultado |
|---|---|---|
| Bootstrap headless inicial | `bootstrap-headless.log` | Python baixado e ambiente próprio preparado |
| Repetição do bootstrap | `bootstrap-idempotent.log` | Ambiente reaproveitado sem atualizar o lock |
| Fixture de permissões | `focused-runtime.log` | 10 passed; chmod explícito mantém o teste válido sob umask 077 |
| Suíte headless final | `suite-headless-final.log` | 915 passed, 2 skipped, 22,07 s |
| Bootstrap GUI | `bootstrap-gui.log` | PySide6/Qt 6.12.0 em outro venv próprio |
| Suíte Qt final | `suite-gui-final.log` | 1132 passed, 2 skipped, 41,90 s |
| Abertura/ciclo de vida/saída offscreen | `offscreen-lifecycle/report.json` | Seis casos passaram, com captura de todas as abas |
| Doctor em HOME limpo | `doctor-clean-home.json` | JSON válido sem logs de bootstrap misturados ao stdout |
| Versões e origem de Python/Qt | `environment.json` | Headless sem Qt, GUI com Qt, system-site-packages false |

Os dois skips em cada suíte são verificações somente leitura de Edge real,
ausente no HOME isolado. O total continua 917/1134. Não se retirou teste para
obter verde. A primeira falha da fixture sob umask privado permanece em
`suite-headless.log`; o contrato de recusa de permissões públicas foi mantido.

Os 100 arquivos Python do pacote correspondem ao wheel testado em 18/10;
mudanças desta migração são suporte de desenvolvimento, metadados, documentação
e a correção da fixture de permissões. Esta execução não certifica outra
distribuição, ARM64 ou um compositor físico; tampouco conclui o soak de duas horas.

## Portabilidade entre usuários e sessões

A primeira CI Ubuntu 24.04 expôs fixtures dependentes de UID 1000/runtime real;
bootstrap, instalação nativa e consultas CLI passaram. O log original está em
`ci-first-failure.log`. As fixtures foram corrigidas para declarar UID atual ou
sessão-modelo; capacidade de tmpfs é testada com watch-list explícita quando
não depende do desktop. As recusas de propriedade da produção foram mantidas.

Repetição sem sessão, com UID 1001 em namespace isolado e filesystem do host
somente leitura: `suite-uid1001-headless.log`, **916 passed, 2 skipped in 15,57 s**.
O namespace teve registros NSS descartáveis montados apenas nele; `/etc` do host
não mudou. A nova regressão de runtime ausente eleva os totais para 918/1135.
O runtime inválido continua produzindo volume desconhecido; não vira zero/livre.

Perfil Qt no mesmo UID/contexto: `suite-uid1001-gui.log`,
**1133 passed, 2 skipped in 35,55 s**. `uid1001-environment.json` registra
UID/GID, resultado e origem do Python do runner. A produção permanece sem
alterações nesta correção de portabilidade das fixtures.
