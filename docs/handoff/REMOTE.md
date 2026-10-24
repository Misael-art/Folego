# Entradas de recuperação remota

- Repositório privado: https://github.com/Misael-art/Folego
- PR de continuidade, em draft: https://github.com/Misael-art/Folego/pull/1
- Branch com a entrega: `codex/portable-handoff-20261024`
- Commit inicial que preservou o working tree: `656aca882bdbe8623432d456d7ad759233f15fb2`
- Página privada com cópias e recibos:
  https://chatgpt.com/space/page_c86741eb68348191a25318610e82b50d

Use a branch do PR enquanto ele não for integrado. `main` conserva a base
histórica; clonar apenas a branch padrão não recupera a evolução desta entrega.

A Página contém os hashes e o recibo de verificação do pacote. O Git bundle
preserva histórico e refs; o ZIP fonte permite obter o wrapper antes de instalar
Git. Anexos privados de estado do aplicativo e QA histórica são para inspeção,
não para importar grants/PIDs/planos no novo host. Credenciais não são incluídas.

Para orientação operacional e o primeiro prompt ao novo agente, leia
[`../NOVO-HOST.md`](../NOVO-HOST.md) e [`../HANDOFF.md`](../HANDOFF.md).
