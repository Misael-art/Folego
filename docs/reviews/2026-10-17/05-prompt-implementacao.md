# Prompt para implementar a evolução do Fôlego

Copie o bloco abaixo para um agente de código com acesso ao repositório. O prompt autoriza evolução do software e testes isolados; não autoriza limpeza, encerramento ou reconfiguração de recursos reais do usuário. O plano deve ser executado em incrementos, preservando o progresso entre sessões.

```text
Você é o agente responsável pela evolução do Fôlego, aplicação desktop Python/Qt
para manter um ambiente Linux responsivo durante o trabalho de agentes de IA e
outras aplicações. Trabalhe no repositório /home/misael/Projects/Folego.

OBJETIVO
Evoluir o projeto existente para oferecer diagnóstico confiável, prevenção de
resíduos, gestão de sessões e ações manuais/automáticas por presets. Redesenhar a
central e acrescentar controle flutuante moderno, leve, acessível e conectado a
resultados reais. Preservar dados, trabalhos em andamento e capacidade de recuperação.

LEITURA OBRIGATÓRIA
1. Instruções AGENTS.md aplicáveis e /home/misael/.codex/RTK.md.
2. docs/reviews/2026-10-17/README.md.
3. docs/reviews/2026-10-17/01-avaliacao-tecnica.md.
4. docs/reviews/2026-10-17/02-arquitetura-e-presets.md.
5. docs/reviews/2026-10-17/03-experiencia-visual.md.
6. docs/reviews/2026-10-17/04-plano-de-acao.md.
7. docs/reviews/2026-10-17/evidencias/LEIA-ME.md e reproduzir.py.
8. Código e testes dos componentes que você vai alterar, além das specs históricas
   relevantes em docs/superpowers. Elas descrevem versões anteriores; não confunda
   promessa no documento com comportamento implementado.

A revisão usa o commit 61179f55123b44a996aa6087d124474eb5e84b1e. Confira o HEAD e
as mudanças posteriores antes de assumir que um achado ainda existe. Preserve
alterações do usuário. Use rtk nas chamadas de shell, conforme as instruções locais.

ESCOPO E ORDEM
Execute F0 a F8 do plano em incrementos completos e verificáveis. Inicie por F0/F1:
crie regressões para os sete diagnósticos reproduzidos e corrija os caminhos
inseguros, a qualidade do inventário, lookup do ledger, finalização dos jobs,
seleção de grupos, ações de itens protegidos e parsers/mensagens incorretos.
Não pare apenas na elaboração de um novo plano ou em uma mudança cosmética.

Depois implemente os contratos e o coordenador comum de F2, com trava entre
processos, autorização, identidade, idempotência, recuperação e contabilidade.
Só então conecte a nova interface e o controle compacto. Automação depende do
aceite de F2/F3/F5; adaptadores avançados começam por inventário e não podem
oferecer botões de execução sem implementação real e testes.

Atualize um registro de progresso em docs/reviews/2026-10-17/progresso.md com:
etapa atual, tarefas concluídas, decisões, comandos/testes e resultados, riscos
restantes e próxima ação concreta. Se o contexto acabar, continue a partir dele.
Se uma capacidade depender de compositor, permissão ou ferramenta indisponível,
implemente a detecção e a alternativa prevista, documente o limite e continue o
trabalho independente. Nunca marque uma etapa como concluída sem cumprir o aceite.

ARQUITETURA
- Mantenha Python/Qt e a CLI headless. Não migre para Electron, aplicação web ou
  outro framework sem justificativa técnica e decisão explícita do usuário.
- Preserve core/actions sem dependência de Qt e toda mutação fora de widgets.
- GUI, CLI, workers e automático devem compartilhar política e executor.
- O plano é versionado e representa alvos, identidades, pré-condições, risco,
  autorização, limites e validade. O executor revalida tudo no momento de agir.
- Um único coordenador serializa mutações, inclusive entre processos distintos.
- Resultados estruturados distinguem sucesso, parcial, recusa, falha, cancelamento
  e estado desconhecido que exige recuperação. Timeout não é prova de término.
- Registre intenção antes dos efeitos; use staging identificado, reservas de
  espaço, verificação e recuperação para cópia, restore e purge.
- Não use locks cooperativos como prova de que aplicações externas não escrevem.
- Migre manifests/JSONL existentes com backup e schema versionado; nunca descarte
  estado corrompido silenciosamente para começar um estado vazio.

INVARIANTES DE SEGURANÇA
- Nenhuma mutação só porque a janela abriu ou uma métrica ficou vermelha.
- Desconhecido/ilegível/parcial não equivale a vazio, livre ou abandonado.
- Antiguidade, nome de processo, PPID=1 ou CPU baixa não autorizam encerramento
  automático. Processos externos descobertos ficam sujeitos a revisão manual.
- Automação atua apenas em recursos administrados, com procedência suficiente e
  grant explícito, persistido, limitado, vigente e revogável.
- Revalide identidade de PID e recurso; prefira pidfd quando disponível. Não mate
  processo protegido, ancestral do app ou árvore desconhecida por substring.
- SIGTERM exige acompanhamento. SIGKILL não é escalada automática de uma recusa.
- Projetos, .git, arquivos não salvos, credenciais, bancos, datasets, modelos,
  volumes e discos virtuais ficam protegidos por padrão.
- Elimine ou una a rota legada disk tmp; não mantenha um atalho menos seguro.
- Não adicione limpeza global de caches, git clean -fdx, docker system prune
  indiscriminado, drop_caches, swapoff ou ajustes globais de kernel como presets.
- VMs e containers usam adaptadores de seus gerenciadores. Não remova imagens
  por extensão/idade, não ignore backing chains e não confunda pausar VM com
  liberar memória.
- O destino de retenção precisa ser comprovadamente suportado, ter espaço e
  não estar no tmpfs de origem. Não assuma SSD a partir de um caminho XDG.
- Quarentena por rename não libera capacidade no mesmo volume. Bytes copiados
  não são RAM física recuperada. Mostre estimativa, transferência, retenção e
  variação observada separadamente.
- Falha após mutação exige reconciliação; não repita uma escrita incerta.
- Não elevar privilégios, instalar autostart ou alterar recursos reais do host
  apenas para testar. Use fixtures e processos/diretórios descartáveis do ensaio.

EXPERIÊNCIA
- Adote os tokens, hierarquia, navegação e fluxos da proposta visual, adaptando
  detalhes à implementação Qt e validando legibilidade/contraste.
- Modo (Manual/Assistido/Automático), preset e autorização são conceitos separados.
  Comece em Manual. Trocar preset não amplia silenciosamente permissões.
- Controle compacto com painel rápido e acesso à central. Ação rápida opcional
  usa apenas o grant salvo; sem grant, abre revisão. Arraste nunca executa.
- Saúde, modo e operação têm indicadores distintos. Animação representa estados
  reais: analisar, executar, verificar, concluir, parcial e falha. Não invente
  progresso por timer nem force o verde depois de uma operação bem-sucedida.
- Não animar continuamente em repouso. Respeitar movimento reduzido, bateria,
  janela oculta e orçamento de CPU. Preferir assets/ícones consistentes licenciados.
- Não mostrar consultas inexistentes, ações habilitadas para alvos protegidos ou
  mensagens de sucesso quando não há evidência do resultado.
- Wayland pode não permitir posição/topmost desejados. Detecte capacidades,
  teste no compositor disponível e entregue alternativa bandeja + janela compacta.
- Permita teclado, foco visível, nomes acessíveis e escalas 100/150/200%.

VALIDAÇÃO
Baseline documentado: 553 testes passam com basetemp exclusivo dentro de .scratch.
No temporário padrão desta sessão, um teste falha por uma premissa de caminho.
Reavalie isso antes de corrigir; não esconda a falha simplesmente ignorando o teste.

Escreva regressões significativas e testes de integração para concorrência,
recuperação, fontes ilegíveis, identidade trocada, mount novo, arquivo aberto,
ENOSPC, SIGTERM ignorado, resultado parcial, grants e dados stale. Exercite todos
os pontos de interrupção de operações com efeitos em filesystem.
Não modifique testes apenas para legitimar comportamento inseguro existente.

Após cada incremento, execute os testes pertinentes; ao integrar, execute a suíte
completa. Renderize/inspecione as telas alteradas com fixtures. Diferencie evidência
offscreen de validação real de KDE/Wayland, bandeja, leitor de tela e desempenho.
Meça custo do residente e latência da UI; metas propostas não são benchmarks já
alcançados. Não provoque pressão real de RAM/disco do usuário para obter números.

ENTREGA
Entregue mudanças reais e integradas, testes, documentação atualizada e registro
de progresso. Informe o que mudou, como foi validado e o que permanece limitado.
Não faça commit, push, publicação ou limpeza do host sem instrução específica.
Use decisões rotineiras para avançar autonomamente dentro deste escopo. Pergunte
apenas quando uma decisão necessária alterar de forma material segurança,
plataforma, autorização ou objetivo estabelecido.
```
