# Temperatura e cooler no widget — 04/11/2026

Janela própria no KDE/Wayland, com HOME/XDG/TMPDIR privados e coletor real em
`/proc` e `/sys`. O widget estava mapeado quando a [captura](widget.png) foi
feita. A leitura do instante foi CPU 44% (`/proc/stat`), `acpitz` 83 °C e RPM
indisponível. A terceira linha mantém **ACPI 83 °C** e **— RPM** lado a lado,
sem quebrar o `°C` ou juntar temperatura ao percentual CPU.

O `sensors` e `/sys/class/hwmon` deste host expõem `acpitz`, GPU e NVMe, mas
nenhum `fan*_input` nem sensor de temperatura específico da CPU. O valor ACPI
é da zona térmica do sistema; a captura não certifica temperatura da CPU nem
rotação física. O teste de `fan*_input` com 2340 RPM usa somente árvore sysfs
descartável. A janela de QA terminou pelo próprio `force_close`, sem mexer na
instância residente ou em serviços.

`./dev test tests/test_temperature.py tests/test_ui_compact.py -q`: **44 passed**.
`./dev check`, sequencial, Python 3.14.7 gerenciado, HOME/XDG privados:
**1250 passed, 2 skipped** headless e **1612 passed, 2 skipped** Qt offscreen.
Testes Qt cobrem widget flutuante, duas laterais e barra superior. A captura
nativa cobre o flutuante; não houve ensaio físico do cooler neste hardware.
