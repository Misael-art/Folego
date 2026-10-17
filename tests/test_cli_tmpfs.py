"""A face headless do M7: o que quebra quando o desktop é o problema tem de funcionar no TTY.

Os testes trocam o volume real pelo de `tmp_path`: o CLI varre, planeja e formata de
verdade, só o chão é falso. `fake_proc` garante montes vazios e nenhum holder.
"""
import json
import os
import shutil
import time
from dataclasses import replace

import pytest

from deck_wellness import cli, paths
from deck_wellness.actions.tmpfs.ledger import MAX_RETAINED_BYTES, Ledger
from deck_wellness.cli import main
from deck_wellness.core.tmpfs import TmpfsVolume
from deck_wellness.safely.audit import AuditLog

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


def tmpfs_env(tmp_path, fake_tmp, monkeypatch):
    """CLI e atos no mesmo chão falso: ledger, quarentena, raízes do guard e auditoria.

    As quatro costuras, não três: `AuditLog()` sem caminho escreve no
    `~/.local/state/deck-wellness/audit.jsonl` do host, e uma suíte de mutação que só
    troca ledger e destino deixaria rastro real fora do `tmp_path`. O arquivo de
    auditoria também é onde se conta o evento por transição.
    """
    root, volume = fake_tmp
    monkeypatch.setattr(cli, "_tmpfs_ledger",
                        lambda: Ledger(tmp_path / "state" / "tmp-ledger.jsonl"))
    monkeypatch.setattr(cli, "_tmpfs_dest", lambda: tmp_path / "retida")
    monkeypatch.setattr(cli, "_tmpfs_guard_roots", lambda: [tmp_path])
    monkeypatch.setattr(cli, "_tmpfs_now", lambda: time.time())
    monkeypatch.setattr(cli, "_tmpfs_audit",
                        lambda: AuditLog(tmp_path / "state" / "audit.jsonl"))
    return root, volume


def backdate(tmp_path, days: float) -> None:
    """Envelhece o `ts` de todas as linhas do ledger: é assim que se fabrica vencido.

    O orçamento da T8 decide idade pelo `ts` da linha, então mover o relógio no arquivo
    é exatamente o que o `expire` vai ver — sem tocar em relógio de processo.
    """
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * DAY))
    path = tmp_path / "state" / "tmp-ledger.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        row["ts"] = old
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_release_refuses_without_confirmation(tmp_path, fake_tmp, monkeypatch, capsys):
    tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    target = str(fake_tmp[0] / "qoder-cli-1000")
    code = main(["tmpfs", "release", target])
    assert code == cli.EXIT_NEEDS_CONFIRM
    assert "--confirmar" in capsys.readouterr().err


def test_release_moves_the_item_and_prints_the_entry_id(tmp_path, fake_tmp, monkeypatch,
                                                        capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    target = str(root / "qoder-cli-1000")
    code = main(["tmpfs", "release", target, "--confirmar"])
    out = capsys.readouterr().out
    assert code == 0
    assert "liberado" in out
    assert not (root / "qoder-cli-1000").exists()
    assert any((tmp_path / "retida").rglob("blob.bin"))
    assert "tmpfs restore" in out, "a saída tem de dizer como desfazer"
    # os dois livros do §7: a liberação é uma transição registrada, não um unlink mudo
    assert _ledger_records(tmp_path)[-1]["state"] == "released"
    assert _audit_events(tmp_path, "tmpfs.release") == ["partial", "released"]


def test_release_of_a_protected_item_is_refused_with_its_reason(tmp_path, fake_tmp,
                                                                monkeypatch, capsys):
    """Protegido no plano é recusado no ato, e a recusa diz **por quê**.

    O handler repassa o `reason` do `classify`, que re-mediu o item agora (não o que o
    plano viu): `pytest-of-misael` está no chão há segundos e morre no piso de idade.
    Pinar a palavra genérica `refused` não valeria nada — toda recusa a contém, inclusive
    as erradas; o que se pinha é o motivo nomeado.
    """
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    code = main(["tmpfs", "release", str(root / "pytest-of-misael"), "--confirmar"])
    assert code == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "refused" in err and "piso" in err, err


def test_restore_without_confirmation_moves_nothing(tmp_path, fake_tmp, monkeypatch,
                                                    capsys):
    """`moves_nothing` é asserção sobre o chão, não sobre a saída: nada mudou."""
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    blob = root / "qoder-cli-1000"
    main(["tmpfs", "release", str(blob), "--confirmar"])
    entry_id = _ledger_records(tmp_path)[0]["entry_id"]
    code = main(["tmpfs", "restore", entry_id])
    assert code == cli.EXIT_NEEDS_CONFIRM
    assert "--confirmar" in capsys.readouterr().err
    assert not (blob / "blob.bin").exists(), "sem flag nada volta para o volume"
    assert any((tmp_path / "retida").rglob("blob.bin")), "e nada sai da SSD"
    assert _audit_events(tmp_path, "tmpfs.restore") == []


def test_restore_returns_the_item_to_its_original_path(tmp_path, fake_tmp, monkeypatch,
                                                       capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    blob = root / "qoder-cli-1000"
    main(["tmpfs", "release", str(blob), "--confirmar"])
    entry_id = _ledger_records(tmp_path)[0]["entry_id"]
    code = main(["tmpfs", "restore", entry_id, "--confirmar"])
    assert code == 0
    assert (blob / "blob.bin").read_bytes() == b"a" * 4096
    assert not any((tmp_path / "retida").rglob("blob.bin"))
    # a transição existe nos dois livros: a linha nova do ledger e o evento do mesmo nome
    rows = _ledger_records(tmp_path)
    assert [r["state"] for r in rows if r["entry_id"] == entry_id][-1] == "restored"
    assert _audit_events(tmp_path, "tmpfs.restore") == ["restored"]


def test_ledger_prints_ram_freed_against_ssd_retained(tmp_path, fake_tmp, monkeypatch,
                                                       capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar"])
    capsys.readouterr()
    code = main(["tmpfs", "ledger"])
    out = capsys.readouterr().out
    assert code == 0
    assert "qoder-cli-1000" in out
    # o nome do teste promete "RAM liberada contra SSD retida": as grandezas têm de aparecer,
    # e a vírgula é a regra de cópia do projeto, não enfeite
    assert "retido na SSD: 4,0 KB em 1 item(ns) · mais velho 0,0 d" in out
    assert "RAM liberada de fato: 4,0 KB" in out
    assert "orçamento" in out


def test_ledger_json_is_one_line_with_the_budget(tmp_path, fake_tmp, monkeypatch, capsys):
    tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    main(["tmpfs", "ledger", "--json"])
    raw = capsys.readouterr().out
    assert len(raw.strip().splitlines()) == 1, "sob --json o stdout é UMA linha"
    payload = json.loads(raw)
    assert payload["records"] == []
    assert payload["budget"]["retained_bytes"] == 0
    assert payload["budget"]["slack_bytes"] == MAX_RETAINED_BYTES


def test_ledger_warns_when_the_retention_bursts_the_budget(tmp_path, fake_tmp,
                                                           monkeypatch, capsys):
    """O aviso de estouro é produção; produção sem teste é enfeite.

    Semeado por uma linha direta do ledger: o `budget_view` lê o campo `bytes` do
    registro, não o disco (`ledger.py:158-176`), então o estouro se fabrica sem os
    3 GiB de arquivo falso que nenhum teste comportaria.
    """
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    Ledger(tmp_path / "state" / "tmp-ledger.jsonl").append(
        entry_id="estouro-1", src=str(root / "qoder-cli-1000"), volume=str(root),
        stored=str(tmp_path / "retida" / "estouro-1"), bytes=MAX_RETAINED_BYTES + 1,
        sha256="0" * 64, age_days=1.0, state="released", action_id="tmpfs.release")
    assert main(["tmpfs", "ledger"]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert "estourou o orçamento" in captured.err
    assert "tmpfs expire" in captured.err, "o aviso tem de dizer o que fazer"


def test_release_refuses_a_path_the_plan_never_classified(tmp_path, fake_tmp,
                                                          monkeypatch, capsys):
    """O portão do plano vale também na mutação: nada é liberado por caminho avulso.

    Sem este pino o ramo `item is None` do handler é código de produção órfão, e a
    alternativa (chamar `release_item` com `None`) não é uma falha limpa -- é
    `AttributeError` no meio de uma operação que apaga RAM.
    """
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    code = main(["tmpfs", "release", str(root / "nao-esta-no-plano"), "--confirmar"])
    assert code == cli.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "não está no plano" in err and "tmpfs plan" in err, err


def test_release_uses_the_guard_roots_of_the_seam(tmp_path, fake_tmp, monkeypatch,
                                                  capsys):
    """As raízes do guard vêm da costura, e o handler tem de repassá-las de verdade.

    É o único modo de observar o repasse: se o handler chamar com `allowed_roots=None`,
    `release_item` cai na linha `roots = list(allowed_roots) if allowed_roots else
    default_allowed_roots()` (citada por função para não apodrecer) -- e neste host,
    onde o repo e portanto o `tmp_path` do pytest vivem sob `$HOME`, isso aceitaria a
    liberação como se nada estivesse faltando. Um mutante invisível à suíte inteira é
    exatamente o que um pino de costura existe para matar.

    A raiz trocada é **errada mas não vazia**, e isso é o ponto: `roots = list(allowed_roots)
    if allowed_roots else default_allowed_roots()` lê a lista vazia como "não passei nada"
    e restaura os roots de produção, então `lambda: []` não mataria o mutante nenhum --
    passaria o teste pelo motivo errado. A mensagem é o vocabulário do próprio
    `safely/guard.py` (inglês desde o M0, precedentado em `test_tmpfs_release.py:225`); o
    que se afirma aqui é o efeito: recusado, nada retido, o item ainda no volume.
    """
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    monkeypatch.setattr(cli, "_tmpfs_guard_roots", lambda: [tmp_path / "guard-fora"])
    code = main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar"])
    assert code == cli.EXIT_REFUSED
    assert "allowed root" in capsys.readouterr().err
    assert not (tmp_path / "retida").exists(), "nada foi retido"
    assert (root / "qoder-cli-1000" / "blob.bin").exists(), "nada foi apagado"


def test_the_mutation_seams_default_to_the_ssd_not_ram(fake_home):
    """O corpo das costuras também é contrato, e nenhum teste de mutação o alcança.

    Todos os testes desta tarefa trocam `_tmpfs_dest` por `tmp_path` -- que é o certo,
    porque senão a suíte escreveria no host -- e por isso nenhum deles exercita o
    default. O default É a frase do docstring de `paths.py:25-27` ("Retenção de tmpfs:
    o destino é a SSD, nunca um tmpfs (RAM)"): trocar `tmp_quarantine_dir()` por
    `tmp_dir()`, ou por um caminho sob `/tmp`, sobreviveria à suíte inteira e gravaria
    a retenção no mesmo volume que se quer esvaziar. Sob `fake_home` os quatro caminhos
    caem no chão falso, então a asserção é de nome e de raiz, não de host.
    """
    dest = cli._tmpfs_dest()
    assert dest == paths.tmp_quarantine_dir()
    assert str(paths.data_dir()) in str(dest), dest
    assert not str(dest).startswith(("/tmp", "/run/user", "/dev/shm")), dest
    assert cli._tmpfs_ledger().path == paths.tmp_ledger_path()
    assert cli._tmpfs_audit().path == paths.audit_log_path()
    assert cli._tmpfs_guard_roots(), "o guard precisa de raízes padrão, não vazias"


def test_expire_requires_both_flags(tmp_path, fake_tmp, monkeypatch, capsys):
    """Semeado: a recusa tem de cair sobre uma vítima real, e o sem-flag é dry-run.

    `expire_over_budget` declara "nada vencido" **antes** de conferir as flags
    (`release.py:424-431`): com ledger vazio o exit 0 é o estado correto, e o corte
    original do plano pedia ali uma recusa sobre um caso que não existe. A semente é o
    mesmo truque do teste seguinte -- liberar e envelhecer o `ts`. O bloco de baixo é o
    XOR: sem flag nenhuma `expire` não recusa, ele lista, que é o comportamento honesto
    de uma ferramenta que mostra antes de apagar.
    """
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar"])
    backdate(tmp_path, 40)
    capsys.readouterr()

    code = main(["tmpfs", "expire", "--confirmar"])
    assert code == cli.EXIT_NEEDS_CONFIRM
    assert "--irreversivel" in capsys.readouterr().err

    assert any((tmp_path / "retida").rglob("blob.bin")), "a recusa não apaga"

    code = main(["tmpfs", "expire", "--dias", "14"])
    assert code == cli.EXIT_OK, "sem flag é dry-run, não recusa"
    assert "dry-run" in capsys.readouterr().out


def test_expire_dry_run_then_confirm(tmp_path, fake_tmp, monkeypatch, capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar"])
    capsys.readouterr()
    backdate(tmp_path, 40)

    code = main(["tmpfs", "expire", "--dias", "14"])
    listed = capsys.readouterr().out
    assert code == 0 and "dry-run" in listed
    assert any((tmp_path / "retida").rglob("blob.bin")), "dry-run não apaga"

    code = main(["tmpfs", "expire", "--dias", "14", "--confirmar", "--irreversivel"])
    assert code == 0
    assert not any((tmp_path / "retida").rglob("blob.bin"))
    assert _audit_events(tmp_path, "tmpfs.expire") == ["expired"]


def test_expire_reports_a_payload_that_vanished(tmp_path, fake_tmp, monkeypatch, capsys):
    """O laço `result.errors` do handler é produção, e a T10 enche essa lista.

    `expire_over_budget` devolve o payload sumido em `errors` e não no `reason`
    (`release.py:451`): sem o laço, a CLI anunciaria o ato como limpo enquanto o
    ledger sabia de um byte que não está mais lá. O aviso vai para o stderr, que é para
    onde toda suspeita desta CLI vai, e o stdout fica só com o veredito -- a aba da T13
    lê o stdout. O que **não** se mexe aqui é a contagem de `freed_bytes` neste caso: a
    T10 decidiu e nomeou a decisão
    (`test_expire_reports_the_bytes_it_frees_even_when_a_path_is_already_gone`), e a
    leitura dela é que um payload que já não existe devolveu esses bytes à SSD de todo
    jeito. Mudar isso seria reabrir a T10 por um teste da T12.
    """
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar"])
    backdate(tmp_path, 40)
    capsys.readouterr()
    for carne in (tmp_path / "retida").rglob("qoder-cli-1000"):
        shutil.rmtree(carne)

    code = main(["tmpfs", "expire", "--dias", "14", "--confirmar", "--irreversivel"])
    assert code == cli.EXIT_OK, "sem vítima apagada o ato não falhou, esvaziou"
    captured = capsys.readouterr()
    assert "aviso:" in captured.err and "já não existia" in captured.err, captured.err
    assert "aviso:" not in captured.out, "a suspeita não divide linha com o veredito"


def test_restore_of_an_unknown_id_is_refused_and_says_so(tmp_path, fake_tmp, monkeypatch,
                                                         capsys):
    """Pino de comportamento que já existe na T10 e nunca foi exercitado por nada.

    Verde no ato em que entra: o que o prende é a coerção (M17 -- suprimir o ramo faz o
    teste morrer), não a ordem de escrita.
    """
    tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    assert main(["tmpfs", "restore", "id-que-nao-existe",
                 "--confirmar"]) == cli.EXIT_REFUSED
    assert "desconhecida" in capsys.readouterr().err


def test_restore_of_an_entry_that_is_already_back_is_refused(tmp_path, fake_tmp,
                                                             monkeypatch, capsys):
    """O segundo ramo órfão da T10: `a entrada está restored` também não tinha teste."""
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar"])
    entry_id = _ledger_records(tmp_path)[-1]["entry_id"]
    assert main(["tmpfs", "restore", entry_id, "--confirmar"]) == cli.EXIT_OK
    capsys.readouterr()
    assert main(["tmpfs", "restore", entry_id, "--confirmar"]) == cli.EXIT_REFUSED
    assert "restored" in capsys.readouterr().err


def test_restore_without_the_flag_asks_for_the_flag_even_for_an_unknown_id(tmp_path,
                                                                          fake_tmp,
                                                                          monkeypatch,
                                                                          capsys):
    """(n): o exit code 2 promete que a flag resolve; a mensagem tem de prometer o mesmo.

    Vermelho antes da correção: `restore_item` olhava o ledger antes do portão, então um
    id inexistente sem flag devolvia `entrada desconhecida` **com** código 2 -- e o
    operador que acrescentasse a flag receberia exatamente a mesma recusa, agora com 1.
    """
    tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    assert main(["tmpfs", "restore", "id-que-nao-existe"]) == cli.EXIT_NEEDS_CONFIRM
    err = capsys.readouterr().err
    assert "--confirmar" in err and "desconhecida" not in err, err


def _ledger_records(tmp_path) -> list:
    """Lê o registro: a asserção cai sobre o arquivo, não sobre uma redação do teste."""
    path = tmp_path / "state" / "tmp-ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def _audit_events(tmp_path, kind: str) -> list:
    """Os `outcome`s de um tipo de evento, na ordem em que foram escritos.

    É a costura do ponto (a): sem trocar `_tmpfs_audit`, estes eventos iriam para o
    `~/.local/state/deck-wellness/audit.jsonl` do host. Contá-los aqui prova que o
    handler passou o audit de verdade -- um `audit=` esquecido daria lista vazia.
    """
    path = tmp_path / "state" / "audit.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        event = json.loads(line)
        if event["kind"] == kind:
            out.append(event["outcome"])
    return out


def test_tmpfs_plan_now_points_at_a_command_that_exists(fake_tmp, capsys):
    """O hint do plano só vale depois do `release` existir no argparse.

    A T11 não podia imprimi-lo: `tmpfs release` morria em `invalid choice`. Aqui ele é
    um caminho real, e este teste é o que impede a regressão de voltar a apontar para
    nada — a asserção cai sobre a saída do `plan`, não sobre uma redação solta.
    """
    assert main(["tmpfs", "plan"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "tmpfs release" in out and "--confirmar" in out
    ns = cli.build_parser().parse_args(["tmpfs", "release", "/algum/lugar",
                                        "--confirmar"])
    assert ns.sub == "release", "o hint aponta para um nome que o argparse conhece"


def test_release_json_is_one_line_and_restore_names_the_target(tmp_path, fake_tmp,
                                                               monkeypatch, capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    target = str(root / "qoder-cli-1000")
    code = main(["tmpfs", "release", target, "--confirmar", "--json"])
    raw = capsys.readouterr().out
    assert code == 0 and len(raw.strip().splitlines()) == 1
    payload = json.loads(raw)
    assert payload["ok"] is True and payload["freed_bytes"] == 4096
    assert payload["entry_id"]
    # o envelope dos três atos mutantes tem de nomear o ato: a T14 lê este stdout sem
    # passar pelo TuneJobs, e dois payloads com `acao` contra um sem seria três formas
    # de resposta para o mesmo tipo de pergunta
    assert payload["acao"] == "release"

    code = main(["tmpfs", "restore", payload["entry_id"], "--confirmar", "--json"])
    got = json.loads(capsys.readouterr().out)
    assert code == 0 and got["restored_to"] == target


def test_a_mutation_refusal_keeps_stdout_empty_and_stderr_explains(tmp_path, fake_tmp,
                                                                   monkeypatch, capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    code = main(["tmpfs", "release", str(root / "pytest-of-misael"), "--confirmar",
                 "--json"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_REFUSED
    assert captured.out == "", "recusa é stderr: a linha --json tem de ser parseável"
    assert "refused" in captured.err
