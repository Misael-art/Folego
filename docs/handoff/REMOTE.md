# Entradas de recuperação remota

## Continuidade da prévia v0.2.0b18

- Branch de retomada Linux/CLI/Qt: `codex/audit-profile`.
- [Prévia com fonte completa, wheel, sdist e checksums](https://github.com/Misael-art/Folego/releases/tag/v0.2.0b18).
- Commit da tag `v0.2.0b18`: `955adc8ff388d352d7e9c200aacd4647bcf82ee6`.
- [PR de continuidade do Modo Auditor](https://github.com/Misael-art/Folego/pull/15), sobre o
  [PR que preserva a linha de desenvolvimento b15–b17](https://github.com/Misael-art/Folego/pull/9).
- O desenvolvimento Windows mantém seus pontos de revisão em
  [PR #10](https://github.com/Misael-art/Folego/pull/10),
  [#11](https://github.com/Misael-art/Folego/pull/11),
  [#12](https://github.com/Misael-art/Folego/pull/12),
  [#13](https://github.com/Misael-art/Folego/pull/13) e
  [#14](https://github.com/Misael-art/Folego/pull/14).
- Para reconstruir o ambiente, use o [guia do novo host](../NOVO-HOST.md).
  Históricos e recibos do host ficam no resgate privado com instruções próprias.

## Migração de 24/10

- Repositório público, licença MIT: https://github.com/Misael-art/Folego
- PR de continuidade, em draft: https://github.com/Misael-art/Folego/pull/1
- Branch com a entrega: `codex/portable-handoff-20261024`
- Commit inicial que preservou o working tree: `656aca882bdbe8623432d456d7ad759233f15fb2`
- Página privada com cópias e recibos:
  https://chatgpt.com/space/page_c86741eb68348191a25318610e82b50d

A publicação pública usa `codex/portable-handoff-20261024` como branch padrão
para apresentar a implementação e o README atuais. `main` conserva a base
histórica; o PR de continuidade mantém o histórico revisável, sem merge automático.

A Página contém os hashes e o recibo de verificação do pacote. O Git bundle
preserva histórico e refs; o ZIP fonte permite obter o wrapper antes de instalar
Git. Anexos privados de estado do aplicativo e QA histórica são para inspeção,
não para importar grants/PIDs/planos no novo host. Credenciais não são incluídas.

Para orientação operacional e o primeiro prompt ao novo agente, leia
[`../NOVO-HOST.md`](../NOVO-HOST.md) e [`../HANDOFF.md`](../HANDOFF.md).
