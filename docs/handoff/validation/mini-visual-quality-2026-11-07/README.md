# Qualidade visual da mini horizontal — 07/11/2026

O pedido apontou leituras de CPU, temperatura e RAM contínuas e sem cor própria.
A diretriz do usuário é qualidade visual nos mínimos detalhes, registrada no
[design](../../../DESIGN.md) e no AI Memory do projeto em
`_rules/qualidade-visual-nos-minimos-detalhes.md`.

Cada leitura recebe uma pequena célula com fundo do tema, cantos de 6 px,
margens internas e intervalo de 6 px. Rótulo de 7 pt acima do valor de 9 pt
seminegrito mantém a faixa de 384 × 46 px lógicos. O valor indica sua própria
criticidade. A dica e a descrição acessível incluem o estado.

- CPU segue os limiares de uso da Central, 75% para atenção e 95% para crítico.
- RAM segue as frações configuradas de memória disponível no monitor.
- Temperatura segue o limite passivo ou crítico declarado pelo mesmo sensor,
  com a margem de aviso do monitor. ACPI continua identificada.
- Valores ausentes, antigos, parciais ou pausados usam apresentação neutra.
  Temperatura conhecida com limite ausente mantém o valor e informa que a
  criticidade é desconhecida.

O [recibo](result.json) registra 48 cenários em janela própria KDE/Wayland.
Os oito temas foram exercitados nos estados normal, atenção, crítico, antigo,
sem limite térmico e pausado. Todas as células e controles ficaram dentro de
384 × 46 px, com separação horizontal e sem sobreposição. O KWin confirmou
a geometria. Os dados são sintéticos, com HOME/XDG privados e áudio isolado.

| Estado | Tema claro | Tema escuro |
| --- | --- | --- |
| Normal | [SNES](snes-us-normal-wayland.png) | [PS2](ps2-normal-wayland.png) |
| Atenção | [SNES](snes-us-attention-wayland.png) | [PS2](ps2-attention-wayland.png) |
| Crítico | [SNES](snes-us-critical-wayland.png) | [PS2](ps2-critical-wayland.png) |
| Leitura antiga | [SNES](snes-us-no-data-wayland.png) | [PS2](ps2-no-data-wayland.png) |

Também foram capturados [limite térmico ausente](ps2-no-limit-wayland.png)
e [pausa](ps2-paused-wayland.png). A apresentação foi inspecionada na escala
fracionária do desktop. Toque, arraste físico e outras escalas requerem
observação própria.
