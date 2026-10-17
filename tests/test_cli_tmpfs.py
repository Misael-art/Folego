"""A face headless do M7: o que quebra quando o desktop é o problema tem de funcionar no TTY.

Os testes trocam o volume real pelo de `tmp_path`: o CLI varre, planeja e formata de
verdade, só o chão é falso. `fake_proc` garante montes vazios e nenhum holder.
"""
import json
import os
import time
from dataclasses import replace

import pytest

from deck_wellness import cli
from deck_wellness.cli import main
from deck_wellness.core.tmpfs import TmpfsVolume

DAY = 86_400
GIB = 1024 ** 3


@pytest.fixture
def fake_tmp(tmp_path, fake_proc, monkeypatch):
    """Um tmpfs de mentira montado em `tmp_path/tmp`, com as três sortes de item.

    As unidades são os **filhos diretos** do volume — é o que `inventory` mede, e é
    o que uma ferramenta recria sozinha (`/tmp/qoder-cli-1000`, não a sessão dentro
    dela). Duas trocas fazem o chão falso virar um host: `WATCHED` passa a ser a
    raiz de `tmp_path`, e os padrões default passam a ser os caminhos reais dela —
    sem isso nada num chão temporário casaria com a allow-list do `/tmp` verdadeiro.
    """
    root = tmp_path / "tmp"
    eligible = root / "qoder-cli-1000"
    stranger = root / "de-outro-lugar"
    young = root / "pytest-of-misael"
    for item in (eligible, stranger, young):
        item.mkdir(parents=True)
    (eligible / "blob.bin").write_bytes(b"a" * 4096)
    (stranger / "velho.bin").write_bytes(b"c" * 1024)
    (young / "vivo.bin").write_bytes(b"b" * 2048)
    old = time.time() - 10 * DAY
    for item, name in ((eligible, "blob.bin"), (stranger, "velho.bin")):
        os.utime(item / name, (old, old))
        os.utime(item, (old, old))
    volume = TmpfsVolume(str(root), "tmpfs", 8 * GIB, 1 * GIB, 7 * GIB)
    monkeypatch.setattr(cli, "_tmpfs_volumes", lambda **kw: (volume,))
    monkeypatch.setattr(cli, "WATCHED", (str(root),))
    monkeypatch.setattr(cli.tmpfs_policy_mod, "DEFAULT_ALLOW_PATTERNS",
                        (str(eligible), str(young)))
    return root, volume


def test_tmpfs_status_prints_each_watched_volume(fake_tmp, capsys):
    root, volume = fake_tmp
    code = main(["tmpfs", "status"])
    out = capsys.readouterr().out
    assert code == 0
    assert str(root) in out
    assert "8,0 GB" in out and "1,0 GB" in out


def test_tmpfs_status_json_is_one_parseable_line(fake_tmp, capsys):
    main(["tmpfs", "status", "--json"])
    raw = capsys.readouterr().out
    assert len(raw.strip().splitlines()) == 1
    payload = json.loads(raw)
    assert payload["volumes"][0]["used_pct"] == 12.5
    assert payload["worst"]["path"] == str(fake_tmp[0])


def test_tmpfs_plan_is_a_dry_run_that_names_both_sides(fake_tmp, capsys):
    root, _ = fake_tmp
    code = main(["tmpfs", "plan"])
    captured = capsys.readouterr()
    assert code == 0
    assert "recuperáveis 4,0 KB em 1 item(ns); protegidos 2" in captured.out
    assert "piso" in captured.out                 # pytest-of-misael: novo demais
    assert "fora da allow-list" in captured.out   # de-outro-lugar: sem padrão
    assert "impressão" in captured.out
    assert (root / "pytest-of-misael" / "vivo.bin").exists()


def test_tmpfs_plan_json_reconciles_and_carries_a_digest(fake_tmp, capsys):
    main(["tmpfs", "plan", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["reclaimable"]) + len(payload["protected"]) == \
        payload["scanned_entries"] == 3
    assert len(payload["digest"]) == 64
    assert len(payload["reclaimable"]) == 1 and len(payload["protected"]) == 2, \
        "o plano tem de listar os dois lados"


def test_tmpfs_plan_only_takes_roots_from_the_watch_list(capsys):
    """`--raiz` fora da watch-list é recusa **nomeada**, não tabela vazia.

    A asserção tem de cair sobre a mensagem que diz *o que* está errado
    (`fora da watch-list: /home/misael`), e não sobre a substring genérica
    `watch-list`: a recusa valleira — `nenhum volume da watch-list montado` — contém a
    mesma palavra, então pinar só a palavra deixaria sobreviver à mutação que apaga o
    filtro de `_tmpfs_roots`. O código de saída pinnado embaixo é o acordo do exit code.
    """
    code = main(["tmpfs", "plan", "--raiz", "/home/misael"])
    err = capsys.readouterr().err
    assert code == cli.EXIT_REFUSED
    assert "fora da watch-list" in err
    assert "/home/misael" in err, "a recusa diz qual caminho recusou"


def test_tmpfs_plan_permitira_adds_a_pattern_and_flips_the_item(fake_tmp, capsys):
    root, _ = fake_tmp
    stranger = str(root / "de-outro-lugar")
    main(["tmpfs", "plan"])
    assert "fora da allow-list" in capsys.readouterr().out
    main(["tmpfs", "plan", "--permitir", stranger])
    out = capsys.readouterr().out
    assert "fora da allow-list" not in out
    assert f"· {stranger} ·" in out, "o item entrou na lista de liberáveis"


def test_bare_tmpfs_subcommand_is_refused_in_pt_br(capsys):
    """`tmpfs` sozinho é recusa nossa, não usage do argparse.

    É o ramo do `main()`: sem `required=True` no subparser, `ns.sub` chega `None` e a
    mensagem sai em pt-BR com o código de "precisa de confirmação". Trocar o `.get(None)`
    por `_TMPFS_HANDLERS[ns.sub]` aqui vira `KeyError` no terminal do usuário.
    """
    code = main(["tmpfs"])
    err = capsys.readouterr().err
    assert code == cli.EXIT_NEEDS_CONFIRM
    assert "desconhecido" in err
    assert "(nenhum)" in err
    assert "None" not in err, "a frase é de usuário, não do repr de Python"


def test_unknown_tmpfs_subcommand_is_refused(capsys):
    """Nome que não existe: quem recusa é o argparse, e o código coincide com o nosso.

    A validação de `choices` acontece antes de qualquer handler, então a mensagem é a
    dele (`invalid choice`, em inglês — como já é para `disk` e `tune`). O que se pinha
    aqui é o acordo: argparse sai com 2 e `EXIT_NEEDS_CONFIRM` é 2. Se alguém mudar um
    dos dois, este teste acorda.
    """
    code = main(["tmpfs", "limpar-tudo"])
    assert code == cli.EXIT_NEEDS_CONFIRM
    assert "invalid choice" in capsys.readouterr().err


def test_tmpfs_status_refuses_when_no_watched_volume_is_mounted(fake_tmp, monkeypatch,
                                                                capsys):
    """Host sem o volume montado não é host saudável: recusa, não tabela vazia.

    É o caso real de um `/run/user/1000` que não existe (sessão sem systemd-user) ou de
    um chroot: imprimir "Espaços temporários:" com zero linhas embaixo deixa o operador
    achar que a RAM está limpa quando nada foi medido.
    """
    monkeypatch.setattr(cli, "_tmpfs_volumes", lambda **kw: ())
    assert main(["tmpfs", "status"]) == cli.EXIT_REFUSED
    assert "nenhum volume" in capsys.readouterr().err
    assert main(["tmpfs", "plan"]) == cli.EXIT_REFUSED


def test_tmpfs_plan_refuses_when_the_counts_do_not_reconcile(fake_tmp, monkeypatch,
                                                             capsys):
    """O CLI confere a própria conta antes de chamar o plano de completo.

    Hoje `build_plan` particiona `entries` em `reclaimable` + `protected`, então a conta
    fecha por construção e este ramo é inalcançável pelo caminho normal — exatamente
    como o `partial` da T9. Continua sendo guarda: se um dia a varredura com prazo
    descartar entradas, a CLI tem de dizer "incompleto" em vez de apresentar um plano
    parcial como se fosse a verdade. Entra pela costura do módulo, não por um plano
    inventado à mão: `scanned_entries` 4 contra duas listas de 1 é o que um descarte
    produziria.
    """
    volumes, entries = cli._scan_tmpfs()
    politica = cli.tmpfs_policy(volumes=[v.path for v in volumes])
    real = cli.tmpfs_plan.build_plan(volumes, entries, politica)
    quebrado = replace(real, scanned_entries=real.scanned_entries + 1)
    monkeypatch.setattr(cli, "_build_tmpfs_plan",
                        lambda *a, **kw: quebrado)
    assert main(["tmpfs", "plan"]) == cli.EXIT_REFUSED
    assert "não fechou" in capsys.readouterr().err


def test_tmpfs_plan_json_refuses_too_when_the_counts_do_not_reconcile(fake_tmp,
                                                                      monkeypatch,
                                                                      capsys):
    """`--json` é a face em que a conta errada custa mais caro: ninguém lê o aviso.

    Na primeira versão o guard de conciliação morava depois do `return EXIT_OK` do
    `--json`: um script que rodasse `tmpfs plan --json` recebia exit 0 com um plano
    parcial, e o consumidor que mais confia no código de saída era justamente o que
    ficava sem nada. O payload continua saindo — um script precisa ler o que existe
    para saber o que falta — mas o exit code passa a dizer a verdade nas duas faces.
    """
    volumes, entries = cli._scan_tmpfs()
    politica = cli.tmpfs_policy(volumes=[v.path for v in volumes])
    real = cli.tmpfs_plan.build_plan(volumes, entries, politica)
    quebrado = replace(real, scanned_entries=real.scanned_entries + 1)
    monkeypatch.setattr(cli, "_build_tmpfs_plan", lambda *a, **kw: quebrado)
    assert main(["tmpfs", "plan", "--json"]) == cli.EXIT_REFUSED
    captured = capsys.readouterr()
    assert len(captured.out.strip().splitlines()) == 1
    payload = json.loads(captured.out)
    assert payload["scanned_entries"] != len(payload["reclaimable"]) + \
        len(payload["protected"])
    assert "não fechou" in captured.err


def test_tmpfs_roots_refuses_once_even_with_three_volumes(fake_tmp, monkeypatch,
                                                          capsys):
    """A recusa de `--raiz` é uma linha, não uma linha por volume montado.

    O filtro vivia dentro da compreensão `[v for v in _tmpfs_volumes() if v.path in
    _tmpfs_roots(raiz)]`, que reavalia o lado direito a cada iteração: no host real,
    com `/tmp`, `/run/user/1000` e `/dev/shm`, um `--raiz` fora da watch-list escrevia
    a mesma frase três vezes. Aqui o chão falso ganha dois volumes extra só para
    contar linhas — o que se pinha é o número de avisos, não o exit code.
    """
    root, volume = fake_tmp
    extras = tuple(TmpfsVolume(f"{root}/outro-{i}", "tmpfs", 8 * GIB, 0, 8 * GIB)
                   for i in range(2))
    monkeypatch.setattr(cli, "_tmpfs_volumes", lambda **kw: (volume, *extras))
    assert main(["tmpfs", "plan", "--raiz", "/home/misael"]) == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert err.count("fora da watch-list") == 1, err
    assert main(["tmpfs", "status", "--raiz", "/home/misael"]) == cli.EXIT_REFUSED
    assert capsys.readouterr().err.count("fora da watch-list") == 1


def test_tmpfs_plan_says_a_zero_item_scan_is_not_proof_of_cleanliness(fake_tmp,
                                                                       capsys):
    """O contrato que a T3 assinou e cobrou aqui: ilegível não é limpo.

    `inventory.inventory` engole o `OSError` do `listdir` de propósito — fail-closed,
    sem item nada é liberado — e o comentário da própria função diz que quem
    apresenta (esta CLI, a aba da T13) tem de declarar que a lista pode estar vazia
    por permissão. Sem essa linha, um `/tmp` com EACCES imprime `scanned 0 item(ns)`
    seguido de `Dry-run comprovado`: a mesma ilusão de RAM limpa que a recusa de
    volume não montado foi construída para evitar, um andar abaixo dela. Rodando como
    root o `chmod 000` não nega leitura e este pino falha alto, igual aos dois pinos
    de `shutil.Error` da T10 — decidido na T14, que roda no host.
    """
    root, _ = fake_tmp
    root.chmod(0o000)
    try:
        assert main(["tmpfs", "plan"]) == cli.EXIT_OK
        out = capsys.readouterr().out
        assert "nenhum item lido" in out
        assert "não é prova de limpeza" in out
    finally:
        root.chmod(0o755)
