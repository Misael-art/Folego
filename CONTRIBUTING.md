# Contribuir com o Fôlego

O projeto está em desenvolvimento. Uma contribuição deve preservar o trabalho
do usuário mesmo quando a coleta falha ou uma operação perde a resposta.

## Preparar o ambiente

Leia o [README](README.md), o [HANDOFF](docs/HANDOFF.md) e as instruções de
[AGENTS.md](AGENTS.md). Use Linux e o wrapper oficial:

```bash
./dev setup
./dev check
```

Para trabalhar apenas no núcleo, use `./dev setup --headless` e
`./dev test-headless`. Não reutilize ambientes antigos ou pacotes Python globais.

## Propor uma mudança

1. Consulte as issues e o handoff para localizar a implementação responsável.
2. Descreva o problema com um caso reproduzível e o comportamento esperado.
3. Faça uma mudança pequena, integrada ao fluxo existente, com regressão relevante.
4. Rode os testes focados e as suítes pertinentes, sequencialmente.
5. Abra um pull request explicando problema, solução, validação e limitações.

Não use arquivos privados, processos alheios ou o runtime real como fixtures.
Testes de efeitos devem criar os próprios filhos e árvores descartáveis.
Mudanças de GUI precisam distinguir Qt offscreen de validação no compositor real.

## Contratos que precisam continuar verdadeiros

- Núcleo, ações e CLI não importam Qt.
- Ausente, ilegível, parcial e antigo não significam vazio ou seguro.
- Resultado incerto não autoriza repetir uma mutação.
- Intenção durável precede o efeito; recuperação precisa preservar dados.
- Automação e arquivamento de fixtures continuam desligados.

Ao relatar um problema, informe distribuição, versão do Python/Qt, comando,
resultado esperado e resultado observado. Revise logs antes de anexar: remova
credenciais, nomes privados e conteúdo desnecessário à reprodução.

As contribuições ao código do Fôlego seguem a [licença MIT](LICENSE).
Preserve os avisos de componentes de terceiros.
