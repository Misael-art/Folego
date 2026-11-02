"""Portable development prompts. Selecting one copies text, never executes it."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Prompt:
    key: str
    title: str
    body: str
    include_context: bool = True


CONTEXT = """Trabalhe no projeto atual. Leia as instruções aplicáveis (AGENTS.md ou equivalente), README e a passagem de contexto existente antes de agir. Preserve alterações de outras pessoas, dados, credenciais e trabalhos em execução. Reutilize o ambiente e as ferramentas do projeto. Não amplie permissões nem publique, faça merge ou execute efeitos destrutivos sem autorização vigente. Diferencie fatos verificados, hipóteses e limitações. Não exponha segredos na resposta ou nos registros."""

# Category IDs are presentation-independent; prompt bodies and copy semantics
# remain in the same catalog used by every selection surface.
PROMPT_CATEGORIES = (
    ('context', 'Diagnóstico e continuidade', ('diagnose', 'continue')),
    ('development', 'Desenvolvimento e correção', ('implement', 'debug')),
    ('quality', 'Qualidade e segurança', ('review', 'tests', 'security')),
    ('performance', 'Desempenho', ('performance',)),
    ('design', 'Design e experiência', ('ux', 'design-mockups')),
    ('delivery', 'Documentação e entrega', ('handoff', 'delivery')),
)

PROMPTS = (
    Prompt('diagnose', 'Diagnosticar o estado real do projeto', """Faça uma análise profunda e baseada em evidências do projeto, sem alterar seu comportamento. Verifique a raiz canônica no host, branch, estado do Git e alterações locais; leia a documentação atual e confira o código que realmente está conectado à produção. Mapeie arquitetura, owners, dependências, entradas CLI/GUI, configuração e armazenamento. Separe o que está implementado, integrado, testado e ainda planejado. Identifique lacunas, falhas reproduzíveis, riscos, dívida técnica e boas práticas com benefício concreto. Execute apenas verificações pertinentes e de baixo impacto; antes de operações pesadas, confira recursos e orçamento. Entregue um diagnóstico com evidências e um roteiro priorizado, com aceite e dependências de cada próximo passo. Não declare prontidão com base somente na documentação ou em testes simulados."""),
    Prompt('continue', 'Continuar de onde o agente anterior parou', """Retome o desenvolvimento a partir da passagem mais recente, sem reiniciar o trabalho. Confira Git, diffs, commits, testes e pendências para reconciliar o relato com o estado real. Preserve decisões válidas e alterações existentes. Identifique o próximo incremento já autorizado, seu owner, dependências e critérios de aceite; se não houver autorização de implementação, apresente a proposta antes de alterar comportamento. Prossiga autonomamente nas decisões reversíveis dentro do escopo. Implemente, execute testes focados e os gates aplicáveis, revise o diff e atualize a passagem existente com o que mudou, evidências, limitações e próximo passo. Não confunda tentativa interrompida com verificação aprovada."""),
    Prompt('implement', 'Implementar uma melhoria com verificação', """Implemente a melhoria descrita no contexto desta tarefa. Primeiro localize o fluxo oficial existente, reproduza o problema ou registre o comportamento esperado e defina aceite observável. Faça um incremento coeso, com todas as chamadas de produção necessárias e tratamento de falhas. Evite soluções concorrentes, dependências desnecessárias e refatorações fora do pedido. Cubra regressões relevantes, rode o teste focado e os gates pertinentes. Para GUI, percorra o fluxo real no alvo disponível e confira foco, escala, acessibilidade e mensagens. Revise o resultado e reporte comportamento entregue, verificações, riscos restantes e instruções de validação. Publicação e efeitos externos dependem da autorização vigente."""),
    Prompt('debug', 'Investigar e corrigir um erro', """Investigue o erro observado até localizar a causa, em vez de mascarar o sintoma. Reproduza em um cenário controlado, registre ambiente e resultado esperado versus observado e siga o fluxo até o owner responsável. Use logs e evidências com dados sensíveis removidos. Teste hipóteses individualmente e preserve a evidência de tentativas que falharam. Implemente a menor correção integrada, com comportamento seguro para estados ausentes, parciais e incertos. Faça uma verificação de regressão que falharia antes da correção e execute os gates pertinentes. Explique a causa, a correção, as evidências e o que ainda não foi demonstrado."""),
    Prompt('review', 'Revisar mudanças antes de integrar', """Revise o diff atual sem editar arquivos. Confira o SHA ou a revisão exata e o escopo pretendido. Analise correção, regressões, contratos públicos, integração, concorrência, segurança, foco e acessibilidade quando aplicáveis, compatibilidade e recuperação. Siga as chamadas até o caminho de produção e confronte testes com cenários reais. Priorize problemas concretos e acionáveis com arquivo, linha, condição de falha e impacto; evite recomendações genéricas sem evidência. Informe cobertura e limitações da revisão e distinga defeitos comprovados de dúvidas. Não faça commit, push ou merge nesta revisão."""),
    Prompt('tests', 'Validar funções e regressões no host', """Planeje e execute a validação pertinente às mudanças atuais. Identifique os contratos e os gates oficiais. Use ambientes isolados, recursos limitados e dados descartáveis pertencentes ao teste. Faça testes focados antes das suítes completas; não rode suítes pesadas em paralelo nem afrouxe limites para obter verde. Para GUI, valide interações reais no compositor disponível, incluindo foco, teclado, áreas clicáveis, limites da tela e estados de erro. Não utilize contas, clipboard ou processos de trabalho como fixtures de efeito. Registre comando, ambiente, contagens e evidências. Declare separadamente simulação, execução real, falhas preexistentes e lacunas de validação."""),
    Prompt('performance', 'Investigar lentidão e uso de recursos', """Investigue o desempenho com medições reproduzíveis antes de otimizar. Defina o cenário lento, volume de dados, ambiente, orçamento e indicadores observáveis; confira CPU, RAM, disco e carga antes dos ensaios. Localize o gargalo no fluxo real, distinguindo I/O, bloqueio da interface, consultas, memória e trabalho repetido. Proponha a mudança de menor risco dentro do escopo autorizado. Compare antes e depois nas mesmas condições, confira resultados e regressões e mantenha limites de recursos e recuperação. Não interrompa tarefas de terceiros, limpe caches compartilhados ou altere configurações globais para melhorar números."""),
    Prompt('security', 'Avaliar segurança com evidências', """Faça uma avaliação defensiva do escopo atual, sem exploração de sistemas externos ou alterações de credenciais. Identifique ativos, limites de confiança, entradas controláveis e efeitos privilegiados. Siga caminhos concretos de entrada a efeito, considerando autenticação, autorização, arquivos, subprocessos, redirecionamentos, concorrência e exposição de segredos. Valide hipóteses somente em dados e processos descartáveis próprios. Relate achados com pré-condições, impacto, evidências, severidade justificada e correção sugerida; diferencie risco teórico de falha demonstrada. Não copie tokens ou sessões para o relatório. Se existir um fluxo de segurança oficial no projeto, utilize-o."""),
    Prompt('ux', 'Revisar a interface e a usabilidade', """Revise o fluxo de interface atual a partir de capturas e interações no alvo real disponível. Observe o objetivo do usuário, hierarquia, legibilidade, mensagens, acessibilidade, navegação, foco e esforço para concluir a tarefa. Confira estados de carregamento, desconhecido, parcial, erro e sucesso; telas pequenas, escala real e limites das janelas. Liste problemas com evidência e impacto, priorizando os que impedem uso ou induzem a interpretação errada. Proponha melhorias compactas e coerentes com os componentes existentes, com critérios claros de aceite. Não altere a interface nesta etapa de revisão."""),
    Prompt('design-mockups', 'Design e mockups para aprovação', """Atue como especialista sênior em Product Design, UX/UI, direção de arte digital e design systems.

Sua missão é analisar o projeto disponível e propor uma evolução visual refinada, coerente e viável, adaptada ao produto, ao público e à plataforma.

**O resultado desta etapa deve ser uma proposta visual com mockups para aprovação. Outro agente implementará posteriormente.** Não altere o código de produção, instale dependências ou execute migrações nesta etapa. Se precisar de código para representar a proposta, mantenha-o em um protótipo separado.

**1. Entenda o projeto antes de desenhar**

Investigue os materiais disponíveis: telas, aplicação em execução, capturas, documentação, identidade visual, componentes, assets e dependências instaladas.

Identifique:

- Finalidade do produto, público e tarefas principais.
- Plataformas, dispositivos e necessidades de densidade de informação.
- Jornadas críticas, navegação e hierarquia das ações.
- Linguagem visual atual e características da marca que merecem ser preservadas.
- Bibliotecas de componentes e ícones existentes, incluindo variações usadas em módulos e produtos derivados acessíveis.
- Restrições técnicas que afetem a viabilidade das propostas.

Diferencie fatos observados, hipóteses e recomendações. Não invente telas, funcionalidades ou evidências de inspeção. Caso não consiga acessar o produto, indique essa limitação e trabalhe com o material disponível.

Faça perguntas somente quando a informação ausente puder mudar substancialmente a proposta. Nas demais situações, explicite uma hipótese razoável e avance.

**2. Faça uma auditoria visual e de experiência**

Avalie a interface como um sistema integrado, incluindo:

- Hierarquia visual, composição, alinhamento, espaçamento e ritmo.
- Tipografia, legibilidade, largura de leitura e densidade.
- Paleta, contraste, superfícies, bordas, sombras e cores semânticas.
- Iconografia: significado, família, espessura, tamanho, alinhamento óptico e consistência.
- Botões, campos, tabelas, cards, menus, abas, diálogos e demais componentes existentes.
- Navegação, descoberta de funções, feedback e prevenção de erros.
- Estados de carregamento, vazio, erro, sucesso, seleção, foco e indisponibilidade.
- Responsividade, textos longos, conteúdo realista e necessidades de acessibilidade.
- Coerência entre telas, módulos, temas e componentes de terceiros.

Priorize os problemas por impacto na compreensão, conclusão das tarefas e consistência. Relacione cada problema relevante à tela ou ao componente observado.

Não trate “premium” como excesso de efeitos. Busque precisão, identidade, clareza, acabamento e qualidade de interação.

**3. Use referências de forma criteriosa**

Consulte as fontes oficiais atualizadas e escolha as referências mais adequadas ao projeto:

- **Apple Human Interface Guidelines:** clareza, hierarquia e convenções de plataforma.
  [https://developer.apple.com/design/human-interface-guidelines/](https://developer.apple.com/design/human-interface-guidelines/)
- **IBM Carbon Design System:** componentes, organização visual, dados e experiências complexas.
  [https://carbondesignsystem.com/](https://carbondesignsystem.com/)
- **Google Material Design:** cores, tipografia, componentes, estados e layouts adaptativos.
  [https://m3.material.io/](https://m3.material.io/)
- **Microsoft Fluent:** coerência entre plataformas, componentes e fundamentos visuais.
  [https://fluent2.microsoft.design/](https://fluent2.microsoft.design/)
- **Adobe Spectrum:** ferramentas, controles, estados e consistência entre produtos.
  [https://spectrum.adobe.com/](https://spectrum.adobe.com/)
- **Atlassian Design System:** navegação, colaboração, produtividade e tokens semânticos.
  [https://atlassian.design/](https://atlassian.design/)

Escolha uma referência principal e referências complementares apenas quando agregarem valor. Explique o que será aproveitado e como será adaptado à identidade do projeto.

Essas referências orientam decisões; não exigem adotar suas bibliotecas ou reproduzir sua aparência. Evite misturar linguagens incompatíveis ou aplicar a mesma estética a qualquer produto.

**4. Revise ícones, assets e badges de marca**

Inventarie os conjuntos de ícones existentes e proponha uma família principal compatível com o produto. Priorize o reaproveitamento quando a qualidade for adequada.

Defina regras para:

- Grade, tamanhos, espessura de traço e alinhamento.
- Uso de variantes preenchidas e contornadas.
- Cores e estados.
- Associação entre ícone, significado e rótulo.
- Ícones personalizados quando houver uma necessidade que o conjunto existente não resolva.

Apresente uma amostra visual dos ícones propostos aplicada à interface.

Trate logotipos e badges de plataformas separadamente dos ícones funcionais. Apple Pay, App Store, Google Play, Microsoft Store, Steam e similares só devem aparecer quando forem pertinentes às funcionalidades e aos canais reais do produto.

Para esses assets, consulte as diretrizes oficiais vigentes de cada marca. Não redesenhe, distorça, recolora ou invente badges de parceria, compatibilidade ou certificação. Arquivos de comunidade, inclusive no Figma, são referências secundárias cuja origem e permissão de uso precisam ser verificadas.

**5. Defina uma direção visual própria**

Formule um conceito visual adequado ao contexto e explique como ele melhora as tarefas do usuário.

Especifique:

- Paleta com funções semânticas e valores de cor.
- Hierarquia tipográfica.
- Escala de espaçamento e grade.
- Densidade e regras de composição.
- Raios, bordas, elevação e superfícies.
- Iconografia e linguagem dos assets.
- Estados de interação e comportamento responsivo.
- Princípios de movimento, quando necessários, incluindo redução de animações.

Considere temas claro e escuro quando forem relevantes ao produto; não crie variações sem necessidade.

Evite soluções decorativas automáticas, como gradientes, transparências, sombras ou cantos excessivamente arredondados. Cada escolha deve contribuir para identidade, compreensão ou usabilidade.

**6. Produza mockups concretos para aprovação**

Não encerre com uma análise textual. Entregue representações visuais reais usando as ferramentas disponíveis.

Selecione telas que representem a jornada principal e os maiores desafios do projeto. Cubra, quando aplicável:

- Uma tela principal ou de entrada.
- Uma tela de maior complexidade ou densidade.
- Uma tarefa crítica, incluindo seu estado de feedback.
- Uma adaptação para outra largura ou dispositivo relevante.
- Uma prancha de componentes, cores, tipografia e ícones.

Adapte a quantidade ao tamanho do produto. Para projetos amplos, apresente um mapa de cobertura e escolha telas representativas; não afirme ter revisado visualmente telas que não foram examinadas.

Use textos legíveis, conteúdo plausível, dimensões identificadas e proporções viáveis. Preserve as funções essenciais e destaque explicitamente propostas que alterem fluxos.

Quando houver uma decisão estética importante ainda em aberto, mostre duas direções na mesma tela, com o mesmo conteúdo e viewport, e recomende uma delas. Desenvolva o conjunto principal na direção recomendada, identificando-a como proposta sujeita à aprovação.

Se usar imagens geradas por IA para explorar estilo, diferencie essas imagens dos mockups que servirão de referência precisa para implementação.

Se não houver ferramenta para produzir os visuais, informe a limitação e entregue a especificação possível, sem afirmar que os mockups foram criados.

**7. Revise e refine antes de apresentar**

Inspecione os mockups produzidos e corrija inconsistências perceptíveis.

Verifique:

- Clareza da ação principal e da hierarquia.
- Consistência entre telas e componentes.
- Legibilidade, contraste e uso de sinais além da cor.
- Espaçamento, alinhamento e equilíbrio de densidade.
- Estados relevantes e prevenção de erros.
- Conteúdo longo, vazio ou incompleto.
- Viabilidade de implementação com a base existente.
- Preservação da capacidade funcional do produto.

Use WCAG 2.2 nível AA como referência quando aplicável. Diferencie verificações possíveis no mockup das que exigirão uma implementação funcional, como navegação por teclado e leitores de tela.

Faça uma rodada explícita de refinamento após a primeira versão. Não declare conformidade ou testes que não tenha realizado.

**8. Prepare a passagem para o agente implementador**

Entregue, junto aos mockups:

- Resumo dos problemas prioritários e das melhorias propostas.
- Direção visual recomendada e referências utilizadas.
- Comparação antes/depois quando houver material de origem.
- Tokens propostos com nomes semânticos e valores.
- Componentes a manter, ajustar, substituir ou criar.
- Mapeamento de ícones e assets, com fontes e condições de uso verificadas.
- Comportamentos, estados e regras responsivas que as imagens não demonstram.
- Priorização das mudanças e dependências relevantes.
- Critérios objetivos de aceitação para a implementação.
- Hipóteses, limitações e decisões pendentes de aprovação.

Mantenha a documentação proporcional ao projeto e vinculada aos visuais apresentados. O próximo agente deve conseguir implementar a proposta aprovada sem precisar reinventar decisões essenciais.

**Critério de conclusão**

Esta etapa termina com uma proposta visual inspecionada, refinada e pronta para decisão. Apresente claramente o que recomenda aprovar e quais escolhas ainda precisam ser resolvidas.

A aprovação dos mockups será a referência para uma etapa posterior de implementação, executada por outro agente.""", include_context=False),
    Prompt('handoff', 'Preparar uma passagem de contexto confiável', """Atualize a passagem de contexto existente para outro agente continuar sem adivinhar. Reconcilie documentação com código e Git. Registre raiz canônica, branch, SHA, alterações locais preservadas, decisões aceitas, arquivos relevantes, comandos de validação e resultados reais. Separe entregue, pendente, bloqueado e não verificado. Informe owners, dependências, critérios de aceite, limites de autorização e o próximo passo concreto. Não duplique manuais nem transforme planos antigos em aceite. Remova segredos dos exemplos e preserve evidências úteis em destino apropriado."""),
    Prompt('delivery', 'Conferir prontidão para PR e distribuição', """Confira se o incremento está pronto para revisão e, quando houver autorização vigente, para distribuição. Revise arquivos explícitos, segredos, tamanho, versão, notas, artefatos e gates do SHA exato. Verifique remoto, branch, PR existente e checks sem polling contínuo. Reutilize o PR do mesmo objetivo. Identifique diferenças entre código testado e artefato distribuído e documente instalação, atualização e recuperação. Faça commit, push, PR ou release somente para ações já autorizadas e com seus critérios satisfeitos; não faça merge nem publique por inferência. Quando faltar um gate, preserve o trabalho e informe a lacuna concreta."""),
)


def text(key):
    prompt = next(p for p in PROMPTS if p.key == key)
    return CONTEXT + '\n\n' + prompt.body if prompt.include_context else prompt.body
