# Componentes de terceiros

A licença MIT do Fôlego cobre o código deste projeto. Ela não altera a licença
das dependências ou dos programas externos chamados pela aplicação.

## Interface gráfica

O perfil GUI usa **PySide6** e **Shiboken6**, distribuídos pelo projeto Qt for
Python. Os metadados dos pacotes 6.12.0 usados nesta entrega declaram
`LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`. Componentes Qt adicionais possuem
seus próprios avisos e condições, incluídos nos pacotes da distribuição.

O Fôlego não incorpora uma cópia modificada dessas bibliotecas neste repositório.
O wrapper instala os pacotes separadamente. Ao redistribuir uma aplicação com
essas bibliotecas, preserve os arquivos de licença e observe os termos aplicáveis
à forma de distribuição escolhida.

## Desenvolvimento e integração

As dependências de testes incluem **pytest** (MIT) e **Hypothesis** (MPL-2.0).
O bootstrap usa **uv**, distribuído separadamente sob MIT ou Apache-2.0.
Consulte os avisos incluídos em cada pacote e o lockfile para as versões exatas.

Python, KDE/KWin, systemd, util-linux, polkit e outras ferramentas do sistema
são componentes externos com licenças próprias. Seu uso pelo Fôlego não os
relicencia sob MIT. As ferramentas nativas são fornecidas pela distribuição Linux.
