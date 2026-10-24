# Evolução do Fôlego

Avaliação de 17 de outubro de 2026 sobre o commit `61179f55123b44a996aa6087d124474eb5e84b1e`. O objetivo é transformar o Fôlego em um assistente residente que mantenha o ambiente responsivo, cuide dos recursos deixados por agentes e ofereça operação manual ou automática por presets, com uma interface coesa e um controle flutuante.

A recomendação é **evoluir a base existente**, preservando Python, Qt, a CLI sem dependência gráfica e as proteções de dados. Antes de ligar a automação, é necessário unificar as regras de segurança, corrigir o ciclo de vida dos executores e medir resultados reais. Hoje o produto é uma caixa de ferramentas manual com boa cobertura de testes, especializada no host original; ainda não é um gestor geral de sessões de agentes, containers e máquinas virtuais.

## Documentos

| Documento | Conteúdo |
|---|---|
| [Avaliação técnica](01-avaliacao-tecnica.md) | Capacidades atuais, falhas reproduzidas, riscos, lacunas e qualidade de engenharia |
| [Arquitetura e presets](02-arquitetura-e-presets.md) | Motor de ações, segurança, sessões de agentes, limpeza, containers, VMs e automação |
| [Experiência e proposta visual](03-experiencia-visual.md) | Cinco telas atuais, direção estética, botão flutuante, estados, animações e acessibilidade |
| [Plano de ação](04-plano-de-acao.md) | Etapas, dependências, entregáveis, critérios de aceite e matriz de validação |
| [Prompt para agente de código](05-prompt-implementacao.md) | Instrução pronta para executar a evolução em incrementos verificáveis |
| [Evidências e limites](evidencias/LEIA-ME.md) | Como reproduzir, resultados dos testes e alcance da avaliação visual |

## Decisões principais

1. Medir pressão de memória, CPU, I/O e capacidade dos volumes; não confundir RAM ocupada com um problema por si só.
2. Registrar a procedência dos processos e artefatos. Idade, nome e ociosidade geram candidatos, mas não autorizam encerramento ou exclusão automática.
3. Usar um executor comum para GUI, CLI e automação, com exclusão mútua entre processos, operações recuperáveis e resultados parciais explícitos.
4. Introduzir presets com permissões persistidas e revogáveis. A instalação começa em modo manual; trocar de preset não amplia silenciosamente a autorização.
5. Separar monitoramento residente, painel compacto e central completa. O controle flutuante tem alternativa pela bandeja e respeita as limitações de Wayland.
6. Adicionar containers e VMs por adaptadores de seus gerenciadores. Discos virtuais, snapshots, volumes e projetos ficam protegidos de limpezas genéricas.

## Resultado da verificação

A suíte existente contém 553 testes. Na configuração padrão desta sessão houve 552 sucessos e uma falha: um teste presume que o temporário usado pelo pytest não está sob `/run/user`. Reexecutada em um diretório temporário exclusivo dentro de `.scratch`, a suíte terminou com **553 sucessos em 9,64 s**. Isso não demonstra ausência de defeitos: sete verificações adicionais revelaram comportamentos relevantes que os testes existentes não cobrem.

Foram produzidas cinco renderizações dos widgets atuais com dados sintéticos. Elas fundamentam a revisão de estrutura e texto, mas não validam compositor, bandeja, leitor de tela ou desempenho no desktop real. Esta entrega acrescenta documentação e um script de diagnóstico isolado; não implementa a reformulação nem executa limpeza no host.

## Primeiro incremento recomendado

Executar F0 e F1 do [plano](04-plano-de-acao.md): consolidar a linha de base, bloquear os caminhos inseguros e corrigir as falhas reproduzidas. Em seguida, implementar o motor comum e a interface manual. A automação só deve ser disponibilizada depois dos respectivos critérios de aceite.
