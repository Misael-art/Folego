# Roadmap de resiliência do host

Atualizado em 11/11/2026. O Fôlego observa, explica e protege sua coleta e as
capacidades com recuperação autorizada. PhaseZero, SteamZero, RetroFE,
KDE/BigLinux e serviços do sistema mantêm seus responsáveis. As intervenções
seguem contratos específicos de identidade, coordenação e confirmação.
O diagnóstico de reinício abrupto permanece **indeterminado**.

## Revisão dos caminhos de autorrecuperação de 11/11

| Lacuna reproduzida | Correção e contrato exercitado |
| --- | --- |
| Perfil interno ausente virava desconhecido genérico | Diagnóstico específico para enumeração incompleta do Deck, com captura ALSA e preferência persistida comprovadas. Recuperação WirePlumber manual e automática opt-in pelo coordenador |
| Pendência de toque bloqueava microfone e saída de áudio | Escopo de efeitos compartilhado pelo diário, executor e GUI. Delegação de entrada protege todas as entradas do protocolo. Escopo legado incompleto protege todas as capacidades |
| Fonte virtual habilitada podia produzir sucesso sem captura física | Conferência do perfil, fonte física e das duas ligações de captura AEC/BigLinux antes de concluir o reparo |
| Falha KWin/lease de entrada bloqueava perfil de áudio independente | Revalidação por responsável e capacidade. A guarda de áudio depende de seu owner e preferências |
| Amostra repetida ou após lacuna podia completar a confirmação | Duas amostras distintas, recentes, do mesmo boot. Lacuna acima de 30 s reinicia a contagem |
| Timestamp futuro podia sumir do orçamento de perfis | Regressão do relógio bloqueia a solicitação e mantém tentativas e motivo visíveis |
| GUI não encaminhava consulta de perfil nem oferecia rearme específico | Roteamento pelo ID, seletor de operações e rearme por perfil. Perfil saudável com disjuntor aberto continua mostrando a suspensão |
| Resposta de configuração podia ser confundida com o reparo antigo pendente | Atualização da política preserva o ID do reparo e apresenta seu próprio resultado |
| Orçamento de energia se perdia ao reiniciar o processo | Histórico horário durável, incluindo devolução do perfil. Trava compartilhada entre instâncias do guarda |
| Devolução do perfil não gravava intenção própria | Novo ID ligado ao recibo anterior, intenção e orçamento antes do efeito, confirmação posterior e consulta após interrupção |
| Intenção interrompida de energia podia desaparecer sem confirmação | Estado desconhecido preservado quando o perfil observado não confirma o efeito. Boot divergente exige revisão |

A revisão percorreu os fluxos de diagnóstico, diário, política, monitor residente,
solicitação manual, GUI/CLI, perfil de energia e seus testes de falha. Os demais
efeitos continuam nos contratos existentes de seus owners. Permanecem os aceites
físicos de cold boot, suspend/resume, toque e voz após uma falha natural, além dos
itens de retenção e cobertura antes da GUI descritos abaixo. As tentativas horárias
anteriores à migração da energia eram voláteis e não podem ser reconstruídas.

## Evidência e limites que orientam o trabalho

- Os boots de 06/11 mostraram situações diferentes: perto de 23:42 havia ACPI
  em 97 °C e um `rustc` consumindo um núcleo; o boot de 23:50 durou cerca de
  14 segundos e teve abortos de `kscreen-doctor` antes da GUI; perto de 23:54
  havia ACPI em 83 °C, pressão de CPU elevada e 99 eventos Bluetooth HCI
  malformados. A troca de alimentação entre boots foi voluntária. Nenhum desses
  fatos prova a causa elétrica, térmica, de software ou de hardware do reset.
- O SD NTFS problemático não estava presente nos episódios posteriores. O
  contador Btrfs de corrupção acumulada era 6741, sem aumento observado; os
  demais contadores e o NVMe SMART não indicavam erro novo. `unsafe_shutdowns`
  é acumulado, não traz data de cada episódio.
- Em 07/11 às 09:11 houve novo corte. Build RetroDevStudio e QA Fôlego se
  sobrepuseram; `acpitz` marcou 100 °C com PSI memória/I/O alto durante essa
  janela. Na última amostra, ~3 minutos depois, ACPI 98 °C, bateria 68% em
  descarga, RAM disponível e PSI memória/I/O baixo. Nove objetos Git locais
  ficaram vazios, recuperados do SHA remoto; Btrfs sem delta novo. Isso torna
  a concorrência de cargas um risco observado, sem provar a causa física do
  reset. [Cronologia e recuperação](handoff/validation/reset-2026-11-07-0911.md).
- O histórico de 15 segundos só existe com a GUI monitorando. Um boot que
  termina antes de ela abrir não pode ser coberto por esse mecanismo. O journal
  perdeu o final de alguns boots; pstore está sem backend e os detectores de
  lockup estão desativados por flags de boot. Mudar flags/backend requer outra
  manutenção e teste específico, fora deste roadmap automático.
- A temperatura `acpitz` é da zona do sistema, não prova a temperatura da CPU.
  RPM só é mostrado quando existe sensor identificável. PSI de CPU mede tempo
  de espera por CPU, não percentual de uso. O pedido cooperativo aos agentes
  hoje é entregue localmente, sem confirmação de redução de carga.

## Ordem de entrega

| Prioridade | Melhoria | Estado e aceite |
| --- | --- | --- |
| P0 | Qualidade da energia e do histórico | **Entregue no código desta branch.** Bateria do Deck e AC separados; tensão/corrente/potência diretas quando disponíveis, com unidades explícitas e `null` na ausência. Schema 2 registra horário, monotônico por boot, qualidade e duração da fase de leitura; histórico schema 1 permanece legível sem qualidade presumida. Ignorar baterias de periféricos (`scope=Device`). Falha de escrita/capacidade continuam visíveis. Ativação da GUI depende da próxima inicialização normal. |
| P0 | Continuidade com retenção segura | **Pendente.** O aviso de capacidade agora começa a 85% dos limites, com margem para agir; não rotaciona nem apaga. Definir janela recente por boot, preservação de incidentes e critério explícito para retirar apenas amostras próprias já encerradas e sem referência. Antes de girar qualquer arquivo, provar identidade, fechamento e integridade; usar escrita atômica/recuperável, orçamento de I/O e limite persistente. Até esse aceite, o limite atual de 4 MiB/boot e 32 MiB total bloqueia a gravação e preserva bytes. |
| P0 | Dossiê de cada reinício | **Parcial no código.** A consulta lenta já correlaciona até três boots encerrados com o último evento retido no journal e as últimas 80 amostras válidas em no máximo 64 KiB por boot. Expõe boot sem amostra, qualidade, fonte antiga sem proveniência, intervalo real por monotônico quando disponível, lacuna entre amostra e journal, além de energia, calor, PSI e custo da coleta no último ponto. CLI e cartão Disco mostram o resumo; Copiar dados leva o relatório privado. Ainda faltam a cobertura de boot antes da GUI, retenção segura e evidência contemporânea de pstore/SMART/GPU; PhaseZero e SteamZero detêm esses owners. Não adicionar polling Bluetooth/DRM ou SMART sem cursor, orçamento e fonte autorizada. |
| P1 | Alertas de risco sustentado | **Implementado no código; validação física pendente.** Calor usa limite do sensor, pico recente e repetição limitada; bateria crítica em descarga tem aviso sonoro. PSI em 60 s exige amostras frescas e 15 s de confirmação, sem lacuna >20 s, e limita repetição na bandeja a 5 min por fonte. A Central mostra o risco sustentado mesmo sem bandeja; leitura perdida após alerta aparece como desconhecida até haver nova avaliação. As médias PSI de 60 s entram no histórico privado. Ainda falta validar entrega de aviso na sessão física; não deduzir falha térmica de CPU a 100%. |
| P1 | Estado de serviços externos | **Implementado no código, com escopo restrito.** Uma consulta `systemctl --user show` de até 2 s observa até oito units nomeadas; padrão: duas Fôlego, duas PhaseZero e uma SteamZero legada. O observador aceita outra lista explícita de unit/owner. Cada linha traz owner, fonte, habilitação e qualidade; unit desabilitada/inativa não vira falha. A varredura já existente de até 16 units em falha/reinício continua com owner quando conhecido. O estado da sessão gráfica segue dependente do observador de tela existente; sem restart nem dependência entre projetos. |
| P1 | Autodiagnóstico da coleta Fôlego | **Parcial.** Schema 2 registra duração da fase de leitura e relógio monotônico; o dossiê mostra intervalos reais recentes e a consulta informa sua própria duração. A sessão real mostrou p95 de 1,79 s em 227 pontos com intervalo anterior de 2 s; a GUI passa a ler a cada 5 s, preservando o histórico de 15 s. Falta medir o novo custo após reinício normal da GUI, tendência em uso prolongado e política de retenção. Recuperar somente erro reversível da própria coleta/configuração com intenção, revalidação e disjuntor; resultado incerto bloqueia repetição. Nenhum reset externo. |
| P2 | Alívio cooperativo verificável | **Parcial.** Pedido local opt-in preserva ID por até 90 s e o hook Codex registra uma única confirmação de recebimento por pedido. A interface distingue publicado, recebido e redução não comprovada. A verificação de redução efetiva e suporte a outros agentes continuam pendentes: PSI posterior não atribui causalmente a melhora a um agente. Sem canal suportado, não afirmar entrega; não suspender nem matar processos de trabalho. |
| P2 | Economia de energia com evidência física | **Pendente.** Medir em uso real o apagamento apenas do painel do Deck, despertar por entrada/alerta e pausa em fullscreen/dock. Registrar inibidores e estado desconhecido; manter a opção do usuário e reversão existentes. Brilho, perfis de energia e suspensão exigem decisão separada. |
| P2 | Recuperação de discos guiada | **Pendente.** Melhorar pré-checagem de cópia de resgate e documentação Linux para NTFS/Btrfs, com identidade, destino independente, espaço, desmontagem e verificação. Nenhum `fsck`, `ntfsfix`, `btrfs check --repair` ou scrub automático em volume ativo. |

## Apresentação ao usuário

A Central mostra uma frase curta de estado (“sem novos avisos”, “evidência
incompleta” ou “revisar”), fonte e idade. A aba Disco concentra a cronologia e
o motivo de cada qualidade; **Copiar dados** entrega os campos brutos. O
relatório de incidente separa **observado**, **possível** e **não determinado**.
Não usar número acumulado de Btrfs, último processo da CPU, falha de serviço ou
evento Bluetooth como diagnóstico de causa sem cadeia temporal suficiente.
Avisos repetidos têm histerese e limite para não gerar ruído nem carga.

## Guardas de implementação e validação

Coletas são somente leitura, limitadas em tempo, bytes e frequência, executadas
fora do loop gráfico. O armazenamento próprio permanece privado e limitado; se
estiver cheio/ilegível, o Fôlego relata a lacuna e preserva o material. Testes
de efeitos usam apenas arquivos e filhos descartáveis. Executar testes focados,
`./dev check` sequencial quando pertinente e observar a sessão KDE/Wayland real
sem provocar falha térmica, reset ou pressão artificial. Registros offscreen
validam contratos, não substituem o teste físico.
