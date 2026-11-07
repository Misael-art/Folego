# Faixa mínima flutuante — proposta antes da implementação

Objetivo: consultar o estado essencial em uma faixa horizontal que possa ser
arrastada livremente, sem manter o painel de 280 px e várias linhas aberto.
Mesmo título de janela e mesmo monitor do widget existente; a troca de formato
não cria outro coletor nem outra instância.

```text
╭────────────────────────────────────────────────────────────╮
│ ⠿   ● Atenção   CPU 18%   ACPI 81°   RAM 66%    ⤢   ▦  ▾ │
╰────────────────────────────────────────────────────────────╯
  mover         estado      leituras breves       compacto  Central formatos
```

O estado usa palavra e cor, evitando depender só da cor. `ACPI` identifica a
zona do sistema; quando a fonte é desconhecida, a faixa mostra `— °C`. Métricas
velhas, ausentes ou ilegíveis viram travessão, nunca zero. Bateria, cooler, swap,
avisos completos, cotas e ações ficam no compacto/Central e no texto acessível
do estado; calor crítico ou bateria crítica continuam avisados pelo fluxo
existente. A faixa não expande atalhos por hover: isso preserva sua altura.

Os alvos de navegação ficam sempre visíveis: **Expandir** abre o compacto,
**Central** abre a janela completa e **Formatos** lista os cinco formatos com
marca no atual, sem um submenu adicional. Em cada formato, o mesmo menu permite
ir diretamente a qualquer outro; a Central mantém o menu de posição e passa a
incluir **Mini horizontal**. Não há ação por clique na área de arraste. O gesto
de arrastar usa o compositor no Wayland e persiste a posição apenas onde a
plataforma fornece coordenadas confiáveis. Trocas preservam o canto e ajustam
somente para manter a janela inteira na área útil.

Aceite: faixa de uma linha com áreas de controle sem sobreposição no Deck e em
largura de desktop; ida e volta entre mini, compacto, laterais, topo e Central;
retorno seguro após menu/bandeja; leitura sem sinais antigos; comportamento
sem atalhos ocultos no hover; KWin/Wayland real observado sem ações de recursos.

## Resultado da validação

Implementado no commit `710197bd8ca6590c2d598eff83feae11b10cfa10`.
Os testes cobrem todos os destinos diretos, a volta à mesma aba da Central,
arraste em X11, dados antigos e avisos de calor, bateria e falha de
posicionamento. `./dev check`: 1280 aprovados/2 ignorados headless e 1664
aprovados/2 ignorados Qt offscreen. As capturas locais
`.scratch/dev-tests-reviewed/mini-widget-20261107/mini-normal-wayland.png`,
`mini-critical-wayland.png` e `mini-kwin-real.png` foram revisadas; o KWin
confirmou o tamanho e a transição para o compacto no processo de QA. O arraste
físico em Wayland e o uso prolongado ainda dependem de observação em sessão
normal. A GUI residente não foi interrompida para o teste.
