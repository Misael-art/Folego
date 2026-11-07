# Roadmap de resiliência do host

Atualizado em 07/11/2026. Escopo: Fôlego observa, explica e protege a sua
própria coleta. PhaseZero, SteamZero, RetroFE, KDE/BigLinux e serviços do sistema
têm responsáveis próprios; aqui seus estados são evidência, não autorização para
alterá-los. O diagnóstico de reinício abrupto permanece **indeterminado**.

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
| P0 | Continuidade com retenção segura | **Pendente.** Definir janela recente por boot, preservação de incidentes e critério explícito para retirar apenas amostras próprias já encerradas e sem referência. Antes de girar qualquer arquivo, provar identidade, fechamento e integridade; usar escrita atômica/recuperável, orçamento de I/O e limite persistente. Até esse aceite, o limite atual de 4 MiB/boot e 32 MiB total bloqueia a gravação e preserva bytes. |
| P0 | Dossiê de cada reinício | **Pendente.** No boot seguinte, correlacionar com orçamento limitado último ponto válido, fim do journal, falhas das fontes, alimentação, temperatura, PSI, Btrfs, NVMe e serviços. Para Bluetooth/DRM, avaliar cursor por boot e teto de linhas/tempo, marcando cursor perdido e saturação como lacuna; não duplicar polling de 15 s. SMART só por leitura de baixa frequência com helper autorizado, sem diálogo administrativo periódico. Exibir observação, hipótese e desconhecido em campos distintos; nunca transformar coincidência em causa. Disponibilizar CLI e resumo da Central com exportação privada. |
| P1 | Alertas de risco sustentado | **Pendente.** Histerese e repetição limitada para temperatura conforme sensor/trip informado, bateria crítica em descarga e PSI sustentado. Alerta deve dizer fonte, idade e ação manual sugerida; leitura ausente suspende conclusão. Não deduzir falha térmica apenas de CPU a 100%. |
| P1 | Estado de serviços externos | **Pendente.** Inventário passivo, limitado e configurável, com owner e fonte explícitos para Fôlego, PhaseZero, SteamZero e sessão gráfica. Avisar sobre restart loop, falha ou ausência de evidência sem reiniciar unit, mudar perfil ou criar dependência entre projetos. |
| P1 | Autodiagnóstico da coleta Fôlego | **Parcial.** Schema 2 registra duração da fase de leitura e relógio monotônico; ainda falta mostrar intervalo real, atraso, erros e orçamento do worker/armazenamento. Recuperar somente erro reversível da própria coleta/configuração com intenção, revalidação e disjuntor; resultado incerto bloqueia repetição. Nenhum reset externo. |
| P2 | Alívio cooperativo verificável | **Pendente.** Evoluir o pedido local já existente para protocolo opt-in com IDs, ACK e expiração, medindo redução efetiva de carga. Sem canal suportado do agente, exibir “entregue, não confirmado”; não suspender nem matar processos de trabalho. |
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
