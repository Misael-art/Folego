# Saúde do host — mockup e validação de apresentação

O [mockup](mockup.png) foi feito antes do código, a partir da captura da aba
Disco da revisão b5. Ele fixa a hierarquia: temperatura observada e tendência,
depois evidências de pressão, armazenamento, serviços e boots. A imagem é uma
direção visual, não uma leitura real do host ou prova do compositor.

A implementação trocou “Proteger dados” por **Orientação**: o botão abre um
roteiro e não copia arquivos nem repara volumes. Também acrescentou pressão de
CPU/I/O em linha própria, horário de coleta e botão **Copiar dados**. A
[captura Qt offscreen](offscreen.png) cobre a janela lógica de 800 × 600. A
[captura KDE/Wayland clara](wayland.png), a [captura escura](wayland-dark.png)
e os [recibos claro](wayland.json) e [escuro](wayland-dark.json) vêm de janelas
próprias com HOME/XDG privados e dados sintéticos. A UI abriu pela Central,
exibiu todas as linhas sem rolagem horizontal, abriu a orientação de calor e
permitiu rolar até as ações de espaço existentes. Não houve leitura de disco,
reparo, encerramento de processos ou alteração de serviços nessa prova.

As leituras reais do host durante a investigação tiveram ACPI 93 → 97 → 81 °C,
sem sensor RPM, tarefas recentes com CPU alta, contador Btrfs 6.741 estável,
avisos de metadados NTFS e uma unit legada em ciclo de falha. A relação entre
carga e calor é uma inferência temporal; nenhuma dessas observações prova a
causa dos reinícios abruptos. O scrub Btrfs não foi consultável sem permissão.
Teste offscreen e captura de janela Wayland não certificam tacômetro disponível,
leitor de tela, outro hardware ou manutenção física do volume.
