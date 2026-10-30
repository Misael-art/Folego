# Continuidade de I1 e frescor de I2

## Contratos implementados

- Planos novos têm `plan_version=2`, política 1, validade padrão de cinco minutos
  e snapshot profundamente imutável de parâmetros/identidade. A cópia serializada
  é independente. Digest inclui ID, criação, prazo, notas, política, ação e alvo.
- Envelope geral continua schema 1. Plano sem `plan_version` é legado v1:
  conserva digest/serialização histórica para consulta e recuperação; coordenador
  recusa iniciar uma intenção nova com esse formato. Nenhum diário é reescrito.
- Grants novos exigem recursos explícitos, limites não vazios, bytes inteiros
  não negativos, parâmetros reconhecidos (`bytes`/`volume` para `tmpfs.release`)
  e prazo de até 24 horas (padrão uma hora). CLI `grant add --resource JSON`
  recebe uma ResourceIdentity serializada, repetível. Caminhos exigem dev/inode.
  O grant compara identidade completa, não prefixo genérico de diretório.
- Grants antigos sem recursos ou sem validade limitada continuam legíveis,
  mas inativos; precisam nova revisão. Nada amplia sua autoridade por migração.
  Outros tipos de ação ficam fora do schema de grant suportado.
- `Coordinator.run` limita espera principal a cinco segundos por padrão,
  inclusive quando recebe `wait=None`. Config/grants têm espera limitada própria.
  Em execução por grant, a ordem é coordenador → config → grants. Escritores de
  config/grants não adquirem coordenador. Sob essas travas, recarrega modo, pausa
  e grant persistidos; prazo é verificado novamente antes da intenção.
- Locks de autorização permanecem até o retorno do executor e registro.
  Uma revogação/pausa concluída antes da entrada impede o efeito; uma solicitada
  depois aguarda o efeito iniciado e não o desfaz. Execução manual sem grant não
  depende de opt-in automático. Falha em obter autorização fecha a porta.
- Executor deve devolver ID, ação e alvo exatos. Journal também detecta ID
  divergente entre envelope/payload e resultado de ação/alvo diferente da intenção.
- Ponte preserva domínio e efeitos observados quando há OSError depois da entrada
  no executor, inclusive falha de saída da trava. Resposta é desconhecido, com ID,
  e nunca “nada foi feito”. Intenção sem resultado não é reaplicada após reinício.
- `folego operation ID --json` consulta o estado persistido sem mutação ou retry.
  Intenção pendente, ID ausente ou diário ilegível retornam desconhecido (5).
  Resultado concluído conserva outcome/efeitos e código correspondente.

## Frescor integrado à interface

Timer de um segundo invalida saúde vencida sem coletar nem ler histórico.
Falha de coleta e pausa de monitoramento invalidam imediatamente a leitura em
central, título, bandeja e compacto. Recomendações antigas ficam ocultas.
Uma amostra já enfileirada não restaura verde durante pausa. Retomar aguarda
amostra nova; ticks não contam como novas amostras para a histerese.

## Testes e limites do aceite

Regressões em `test_orchestration_models.py`, `test_orchestration_coordinator.py`,
`test_orchestration_journal.py`, `test_grants.py`, `test_cli_automation.py`,
`test_cli_operations.py` e `test_ui_main_window_tabs.py`:

- Mutação de objetos aninhados/entradas/exportação, alteração de prazo/ID e
  compatibilidade do digest legado.
- Revogação/pausa persistida enquanto outra thread aguarda uma trava real;
  alvo autorizado executa uma vez, outro alvo recusa sem efeito.
- Grant vazio, negativo, NaN, parâmetro inesperado, escopo ausente e inode trocado.
- Falha de unlock após escrita de bytes sintéticos preserva resultado/efeitos.
- Corrupção de identidade no diário não devolve sucesso de outra operação.
- Consulta CLI não altera bytes do histórico e não cria diário para ID ausente.
- Frescor sem snapshot novo, falha, pausa e amostra enfileirada durante pausa.

Suíte intermediária antes do novo comando: 1071 passaram em 21,36 s; testes
CLI de operação/automação: 12 passaram em 0,53 s. Resultados finais e logs são
registrados no progresso. `.scratch` verificado em btrfs, cerca de 54 GiB livres.
Todas as execuções pytest usam TMPDIR/PYTEST_DEBUG_TEMPROOT próprios fora de base.

Resultado final: **1074 passed in 19.42s**, em `autorizacao-suite.log`;
venv sem Qt: **873 passed in 13.45s**, em `autorizacao-headless.log`.
`git diff --check` passou. Nenhuma instalação limpa/soak ou certificação visual
real foi acrescentada. A execução completa usa o comando documentado no registro
runtime, e a headless troca o Python pelo `.scratch/i0-headless/bin/python` com
`--without-qt`.

**I1 permanece parcial.** Não há orçamento por frequência/bytes entre execuções
por grant, nem controlador automático habilitado. Escopo de identidade não prova
propriedade administrada, ausência de novos escritores ou identidade de mount.
Essas evidências precisam ser revalidadas pelo executor antes de permitir o
primeiro controlador. Ponte ainda cria plano após confirmação nos fluxos atuais;
revisão GUI/CLI e execução do mesmo plano persistido precisam integração.
Consulta por ID existe; reconciliação automática por ID ainda não existe.
Não reexecutar um comando mutante para tentar reparar estado desconhecido.

**C01/C02/C03/C04 receberam correções, não aceite integral.** C09 permanece
corrigido na transação de configuração. C10 foi tratado quanto a frescor;
visibilidade conjunta ainda está pendente. C05/C08/C11/C13 seguem pendentes.
R1/R2/R5 mantêm o estado parcial da entrega runtime anterior; R3/R4 não avançaram
neste incremento. Automação segue desligada no host. Não houve limpeza de dados
do usuário, sinais em processos de trabalho, autostart, commit ou publicação.

F0/F1: base/regressões preservadas; F2: bloqueador; F3: base ampliada;
F4/F5: parciais; F6: sem controlador completo, executor desligado;
F7: inventário parcial somente leitura; F8: CI local verificada, instalação
GUI limpa/soak/compositor ainda pendentes.
