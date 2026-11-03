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

from folego import cli, paths
from folego.actions.tmpfs.ledger import MAX_RETAINED_BYTES, Ledger
from folego.actions.tmpfs.release import ReleaseResult
from folego.cli import main
from folego.core.tmpfs import TmpfsVolume
from folego.orchestration import (ActionResult, Coordinated, Coordinator, Journal,
                                  Outcome)
from folego.safely.audit import AuditLog

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
    """CLI e atos no mesmo chão falso: ledger, quarentena, raízes, auditoria e coordenador.

    As cinco costuras, não três: `AuditLog()` sem caminho escreve no
    `~/.local/state/folego/audit.jsonl` do host, e uma suíte de mutação que só
    troca ledger e destino deixaria rastro real fora do `tmp_path`. O arquivo de
    auditoria também é onde se conta o evento por transição. O coordenador (F2)
    é a quinta: sem trocá-lo, o diário de intenção e a trava entre processos
    caem no estado real do host a cada mutação confirmada.
    """
    root, volume = fake_tmp
    monkeypatch.setattr(cli, "_tmpfs_ledger",
                        lambda: Ledger(tmp_path / "state" / "tmp-ledger.jsonl"))
    monkeypatch.setattr(cli, "_tmpfs_dest", lambda: tmp_path / "retida")
    monkeypatch.setattr(cli, "_tmpfs_guard_roots", lambda: [tmp_path])
    monkeypatch.setattr(cli, "_tmpfs_now", lambda: time.time())
    monkeypatch.setattr(cli, "_tmpfs_audit",
                        lambda: AuditLog(tmp_path / "state" / "audit.jsonl"))
    monkeypatch.setattr(cli, "_tmpfs_coordinator",
                        lambda: Coordinator(journal=Journal(tmp_path / "state"
                                                            / "operations.jsonl"),
                                            lock_path=tmp_path / "state"
                                            / "coordinator.lock"))
    # sexta costura (F2/entrega 6): a verificação do destino persistente lê a
    # tabela de montes DENTRO do ato; o host falso é "btrfs em volta, tmpfs no
    # volume". Sem ela o `/proc` falso (vazio) faria toda liberação recusar por
    # monte desconhecido — que é a resposta certa para um host ilegível.
    monkeypatch.setattr("folego.actions.tmpfs.release.read_mounts",
                        lambda proc_root=None: ((str(root), "tmpfs"),
                                                (str(tmp_path), "btrfs")))
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


def test_release_keeps_observed_effects_unknown_if_final_record_fails(tmp_path, fake_tmp, monkeypatch, capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    def full(self, result):
        raise OSError(28, "final journal full")
    monkeypatch.setattr(Journal, "append_result", full)
    target = root / "qoder-cli-1000"
    assert main(["tmpfs", "release", str(target), "--confirmar", "--json"]) == 5
    payload = json.loads(capsys.readouterr().out)
    assert payload["outcome"] == "desconhecido" and payload["ok"] is False
    assert "não persistido" in payload["reason"]
    assert payload["effects"]["bytes"] == 4096
    copies = list((tmp_path / "retida").rglob("blob.bin"))
    assert len(copies) == 1 and copies[0].read_bytes() == b"a" * 4096
    assert not target.exists()
    state = Journal(tmp_path / "state/operations.jsonl").state_of(payload["operation_id"])
    assert state.intent is not None and state.result is None


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
    assert "no SSD" in out and "variação observada" in out, \
        "a contabilidade fina separa lógico, alocado e observado"
    # os dois livros do §7: a liberação é uma transição registrada, não um unlink mudo
    assert _ledger_records(tmp_path)[-1]["state"] == "released"
    assert _audit_events(tmp_path, "tmpfs.release") == ["staging", "partial", "released"]


def test_release_refuses_a_ram_destination_through_the_cli(tmp_path, fake_tmp, monkeypatch,
                                                           capsys):
    """F2/entrega 6: o destino é verificado no ato — tmpfs não é retenção.

    O `/proc` falso declara o destino como tmpfs (e o resto como btrfs): a
    liberação tem de recusar antes de copiar, a origem fica intacta e a recusa
    entra no diário como `recusa` — nunca como sucesso silencioso.
    """
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    dest = tmp_path / "retida"
    dest.mkdir(parents=True)
    monkeypatch.setattr("folego.actions.tmpfs.release.read_mounts",
                        lambda proc_root=None: ((str(dest), "tmpfs"),
                                                ("/", "btrfs")))

    code = main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar"])

    captured = capsys.readouterr()
    assert code == cli.EXIT_REFUSED and "RAM" in captured.err
    assert (root / "qoder-cli-1000" / "blob.bin").exists(), "a origem está intacta"
    assert list(dest.iterdir()) == [], "nada foi copiado"
    assert _ledger_records(tmp_path) == [], "nem linha staging"
    records = _journal_records(tmp_path)
    assert [r["kind"] for r in records] == ["intent", "result"]
    assert records[1]["result"]["outcome"] == "recusa"


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


def test_ledger_separates_bytes_that_left_ram_from_ssd_retained(tmp_path, fake_tmp,
                                                                 monkeypatch, capsys):
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar"])
    capsys.readouterr()
    code = main(["tmpfs", "ledger"])
    out = capsys.readouterr().out
    assert code == 0
    assert "qoder-cli-1000" in out
    # o nome do teste promete "saiu da RAM contra SSD retida": as grandezas têm de aparecer,
    # e a vírgula é a regra de cópia do projeto, não enfeite
    assert "retido na SSD: 4,0 KB em 1 item(ns) · mais velho 0,0 d" in out
    assert "saiu da RAM e não voltou: 4,0 KB" in out
    assert "RAM liberada de fato" not in out, "o histórico não se apresenta como RAM livre"
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
    assert payload["victims"] == [], "sem retenção não há vítima de expiração"


def test_ledger_json_lists_the_effective_expire_victims(tmp_path, fake_tmp, monkeypatch,
                                                        capsys):
    """R07: a aba confirma o expire com as vítimas efetivas — que vêm daqui."""
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    Ledger(tmp_path / "state" / "tmp-ledger.jsonl").append(
        entry_id="estouro-1", src=str(root / "qoder-cli-1000"), volume=str(root),
        stored=str(tmp_path / "retida" / "estouro-1"), bytes=MAX_RETAINED_BYTES + 1,
        sha256="0" * 64, age_days=1.0, matched_pattern=None, holder_pids=(),
        state="released", action_id="tmpfs.release", audit_event_id="e" * 32)
    main(["tmpfs", "ledger", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["victims"] == [{"entry_id": "estouro-1",
                                   "bytes": MAX_RETAINED_BYTES + 1,
                                   "src": str(root / "qoder-cli-1000")}]


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


def test_ledger_names_an_inconsistent_jsonl_instead_of_hiding_it(tmp_path, fake_tmp,
                                                                 monkeypatch, capsys):
    """Linha ilegível aparece no relatório (JSON e texto); a leitura segue com o resto."""
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    book = Ledger(tmp_path / "state" / "tmp-ledger.jsonl")
    book.append(entry_id="ok-1", src=str(root / "qoder-cli-1000"), volume=str(root),
                stored=str(tmp_path / "retida" / "ok-1"), bytes=10,
                sha256="0" * 64, age_days=1.0, state="released",
                action_id="tmpfs.release")
    with book.path.open("a", encoding="utf-8") as fh:
        fh.write("{quebrado}\n")

    assert main(["tmpfs", "ledger", "--json"]) == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["problems"] and "linha 2" in payload["problems"][0]
    assert [r["entry_id"] for r in payload["records"]] == ["ok-1"]

    assert main(["tmpfs", "ledger"]) == cli.EXIT_OK
    err = capsys.readouterr().err
    assert "ledger inconsistente" in err and "linha 2" in err
    assert "recusadas" in err


def test_an_inconsistent_ledger_refuses_tmpfs_mutations_through_the_cli(
        tmp_path, fake_tmp, monkeypatch, capsys):
    """A porta do ledger vale na CLI: recusa no stderr e código de recusa, sem stdout."""
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    book = Ledger(tmp_path / "state" / "tmp-ledger.jsonl")
    book.path.parent.mkdir(parents=True, exist_ok=True)
    book.path.write_text("{quebrado}\n", encoding="utf-8")

    code = main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_REFUSED and "ledger inconsistente" in captured.err
    assert captured.out == ""

    code = main(["tmpfs", "restore", "qualquer-id", "--confirmar"])
    assert code == cli.EXIT_REFUSED
    assert "ledger inconsistente" in capsys.readouterr().err

    code = main(["tmpfs", "expire", "--confirmar", "--irreversivel"])
    assert code == cli.EXIT_REFUSED
    assert "ledger inconsistente" in capsys.readouterr().err

    code = main(["tmpfs", "recover", "--confirmar"])
    assert code == cli.EXIT_REFUSED
    assert "ledger inconsistente" in capsys.readouterr().err
    # achado da entrega 7: o veredito do recover confirmado falava `sucesso` por
    # cima da recusa do ledger; o diário agora diz `recusa`, como a CLI sempre disse
    verdict = [r for r in _journal_records(tmp_path)
               if r["kind"] == "result"][-1]["result"]
    assert verdict["outcome"] == "recusa"

    code = main(["tmpfs", "recover"])
    assert code == cli.EXIT_REFUSED, "nem o dry-run decide com mapa incompleto"
    assert "ledger inconsistente" in capsys.readouterr().err


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


def test_the_mutation_seams_default_to_the_retention_paths(fake_home):
    """O corpo das costuras também é contrato, e nenhum teste de mutação o alcança.

    Todos os testes desta tarefa trocam `_tmpfs_dest` por `tmp_path` -- que é o certo,
    porque senão a suíte escreveria no host -- e por isso nenhum deles exercita o
    default. O default É a frase do docstring de `paths.py` ("Retenção de tmpfs: o
    destino é a SSD, nunca um tmpfs (RAM)"). O que **não** se afirma aqui é prefixo de
    caminho: isso dependia do temporário do host (R12/F0). O tipo do monte decide, e
    a decisão tem teste próprio abaixo com a regra de `safely/mounts.py`.
    """
    dest = cli._tmpfs_dest()
    assert dest == paths.tmp_quarantine_dir()
    assert str(paths.data_dir()) in str(dest), dest
    assert cli._tmpfs_ledger().path == paths.tmp_ledger_path()
    assert cli._tmpfs_audit().path == paths.audit_log_path()
    assert cli._tmpfs_guard_roots(), "o guard precisa de raízes padrão, não vazias"
    coord = cli._tmpfs_coordinator()
    assert coord.journal.path == paths.operations_journal_path()
    assert coord.lock_path == paths.coordinator_lock_path()


def test_the_default_destination_is_judged_by_its_mount_not_by_its_path(fake_home):
    """A premissa ambiental removida: o monte do destino decide, não o prefixo.

    Sob `fake_home` o destino cai no temporário do pytest, que pode estar em tmpfs
    (o da revisão estava) ou em disco. Os dois veredictos são válidos: o que não
    pode existir é aceitar em silêncio um destino que é RAM — por isso a asserção
    cobre os dois ramos em vez de presumir o host.
    """
    from folego.core.tmpfs import read_mounts
    from folego.safely import mounts as mount_rules

    dest = cli._tmpfs_dest()
    verdict = mount_rules.destination_verdict(dest, mounts=read_mounts(None))
    if verdict.ok:
        assert verdict.fs_type not in mount_rules.RAM_FS_TYPES
        assert verdict.mount, "um destino aceito precisa nomear seu monte"
    else:
        assert verdict.reason.startswith("refused")
        assert ("RAM" in verdict.reason or "conhecido" in verdict.reason), verdict.reason


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
    assert code == cli.EXIT_PARTIAL, \
        "suspeita relatada não vira sucesso limpo nem no código de saída"
    captured = capsys.readouterr()
    assert "aviso:" in captured.err and "já não existia" in captured.err, captured.err
    assert "aviso:" not in captured.out, "a suspeita não divide linha com o veredito"
    verdict = [r for r in _journal_records(tmp_path)
               if r["kind"] == "result"][-1]["result"]
    assert verdict["outcome"] == "parcial", \
        "suspeita relatada nunca vira sucesso limpo no diário"
    assert verdict["errors"] and "já não existia" in verdict["errors"][0]


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
    `~/.local/state/folego/audit.jsonl` do host. Contá-los aqui prova que o
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


def _journal_records(tmp_path) -> list:
    """O diário de intenção do coordenador (F2), lido do chão falso.

    Sem trocar o coordenador no fixture, este arquivo cairia no estado real do
    host; sem lê-lo, a integração passaria sem provar registro nenhum.
    """
    path = tmp_path / "state" / "operations.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


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


def test_mutation_refusals_carry_the_outcome_on_stdout_with_json(tmp_path, fake_tmp,
                                                                 monkeypatch, capsys):
    """Entrega 7: com --json, a recusa sai como objeto único no stdout.

    O consumidor de máquina não depende do stderr nem de inferir pelo código: o
    mesmo `outcome`/`exit` do protocolo viajam no objeto (e o veredito acrescenta
    `operation_id`/`effects` quando a operação chegou a ser coordenada); o stderr
    continua sendo a voz humana. Antes da entrega 7 o stdout ficava vazio e a aba
    só podia dizer "o filho não respondeu".
    """
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    # recusa antes da porta: o alvo nem está no plano
    code = main(["tmpfs", "release", str(root / "nao-existe"), "--confirmar", "--json"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_REFUSED
    payload = json.loads(captured.out)
    assert payload["acao"] == "release" and payload["ok"] is False
    assert payload["exit"] == cli.EXIT_REFUSED and payload["outcome"] == "recusa"
    assert "não está no plano" in payload["reason"]
    assert "refused" in captured.err
    # recusa do domínio depois do plano: o veredito viaja junto no objeto
    code = main(["tmpfs", "release", str(root / "pytest-of-misael"), "--confirmar",
                 "--json"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_REFUSED
    payload = json.loads(captured.out)
    assert payload["outcome"] == "recusa" and "refused" in payload["reason"]
    assert payload["operation_id"] and "effects" in payload
    assert "refused" in captured.err


def test_missing_confirm_answers_exit_2_on_both_faces(tmp_path, fake_tmp, monkeypatch,
                                                      capsys):
    """Entrega 7: sem --confirmar o desfecho é `falta confirmar` (2) no código e no JSON."""
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    code = main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--json"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_NEEDS_CONFIRM
    payload = json.loads(captured.out)
    assert payload["exit"] == cli.EXIT_NEEDS_CONFIRM and payload["ok"] is False
    assert payload["outcome"] == "recusa"
    assert "exige --confirmar" in payload["reason"]
    assert payload["reason"] in captured.err


def test_a_partial_release_is_exit_3_with_the_domain_numbers(tmp_path, fake_tmp,
                                                             monkeypatch, capsys):
    """Entrega 7: parcial tem código próprio (3) e o objeto diz o desfecho real.

    A recusa de remoção da origem deixa clone na SSD: parte do efeito existe, e a
    CLI devolve o mesmo `parcial` que o diário registrou — nunca 1 ("recusa"), que
    diria que nada aconteceu.
    """
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    target = str(root / "qoder-cli-1000")

    def fake_release(**_kwargs):
        partial = ReleaseResult(
            False, "1700-abcd",
            "parcial: o clone está em /ssd/1700-abcd e registrado como partial; "
            "a origem não foi removida (Operation not permitted); nada foi perdido",
            bytes=4096, stored="/ssd/1700-abcd", freed_bytes=0,
            allocated_bytes=8192, ram_observed_bytes=None)
        verdict = ActionResult(
            action="tmpfs.release", outcome=Outcome.PARTIAL, target_key=target,
            reason=partial.reason,
            effects={"entry_id": partial.entry_id, "bytes": partial.bytes,
                     "stored": partial.stored, "sha256": "",
                     "freed_bytes": 0, "allocated_bytes": 8192,
                     "ram_observed_bytes": None})
        return Coordinated(result=partial, verdict=verdict)

    monkeypatch.setattr(cli.tmpfs_coordinated, "release", fake_release)
    code = main(["tmpfs", "release", target, "--confirmar", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_PARTIAL
    assert payload["exit"] == cli.EXIT_PARTIAL and payload["outcome"] == "parcial"
    assert payload["ok"] is False and payload["entry_id"] == "1700-abcd"
    assert payload["bytes"] == 4096 and payload["freed_bytes"] == 0
    assert payload["allocated_bytes"] == 8192 and payload["ram_observed_bytes"] is None
    assert payload["reason"].startswith("parcial:")
    # a face humana devolve o mesmo código e o motivo no stderr
    code = main(["tmpfs", "release", target, "--confirmar"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_PARTIAL and "parcial:" in captured.err


def test_an_unexpected_error_is_a_documented_failure(capsys, monkeypatch):
    """Entrega 7: exceção vira `falha` (4) com objeto no --json, não traceback cru."""
    def boom(_ns):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(cli._TMPFS_HANDLERS, "ledger", boom)
    code = main(["tmpfs", "ledger", "--json"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_FAILED
    payload = json.loads(captured.out)
    assert payload["ok"] is False and payload["exit"] == cli.EXIT_FAILED
    assert payload["outcome"] == "falha" and "kaboom" in payload["reason"]
    assert "falha: RuntimeError: kaboom" in captured.err
    assert "FOLEGO_TRACEBACK" in captured.err, "o traceback tem porta de saída"


def test_interrupting_a_command_is_desconhecido_not_cancelamento(capsys, monkeypatch):
    """Ctrl-C no meio não prova ausência de efeitos: 5, nunca 6 (reservado)."""
    def interrupted(_ns):
        raise KeyboardInterrupt

    monkeypatch.setitem(cli._TMPFS_HANDLERS, "ledger", interrupted)
    code = main(["tmpfs", "ledger", "--json"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_UNKNOWN
    payload = json.loads(captured.out)
    assert payload["exit"] == cli.EXIT_UNKNOWN and payload["outcome"] == "desconhecido"
    assert "interrompido" in captured.err


def test_every_outcome_has_one_documented_exit_code():
    """O protocolo não pode ganhar desfecho sem código, nem dois códigos iguais."""
    assert set(cli.EXIT_BY_OUTCOME) == set(Outcome)
    codes = [cli.EXIT_BY_OUTCOME[o] for o in Outcome]
    assert len(set(codes)) == len(codes)
    assert cli.EXIT_BY_OUTCOME[Outcome.OK] == cli.EXIT_OK == 0
    assert cli.EXIT_BY_OUTCOME[Outcome.REFUSED] == cli.EXIT_REFUSED == 1
    assert cli.EXIT_BY_OUTCOME[Outcome.CANCELLED] == cli.EXIT_CANCELLED == 6


def test_a_confirmed_release_is_journaled_intent_before_result(tmp_path, fake_tmp,
                                                               monkeypatch, capsys):
    """F2: a mutação real passa pelo coordenador — intenção no diário, depois resultado.

    A ordem é o contrato, e aqui ela é observável: a linha `intent` tem de existir
    antes da `result`, com a ação, o alvo e os parâmetros reais do ato; o veredito
    nomeia o efeito que o stdout anunciou.
    """
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    code = main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar",
                 "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK
    # o envelope do sucesso diz o desfecho e o código por si (entrega 7)
    assert payload["exit"] == cli.EXIT_OK and payload["outcome"] == "sucesso"

    records = _journal_records(tmp_path)
    assert [r["kind"] for r in records] == ["intent", "result"], \
        "o diário registra a intenção antes do efeito"
    intent, result = records[0]["plan"], records[1]["result"]
    assert intent["action"] == "tmpfs.release"
    assert intent["target"]["key"] == str(root / "qoder-cli-1000")
    assert intent["params"] == {"bytes": 4096, "volume": str(root)}
    assert len(intent["digest"]) == 64
    assert result["outcome"] == "sucesso" and result["operation_id"] == \
        records[0]["operation_id"]
    assert result["effects"]["entry_id"] == payload["entry_id"]
    assert result["effects"]["freed_bytes"] == 4096
    # contabilidade fina (6b): o alocado é medido no clone que ficou, e o
    # observado atravessa o veredito — os dois números são o mesmo nos dois canos
    esperado = sum(p.stat().st_blocks * 512
                   for p in (tmp_path / "retida").rglob("*")
                   if p.is_file() and not p.is_symlink())
    assert payload["allocated_bytes"] == esperado
    assert result["effects"]["allocated_bytes"] == esperado
    assert isinstance(payload["ram_observed_bytes"], int)
    assert result["effects"]["ram_observed_bytes"] == payload["ram_observed_bytes"]


def test_a_confirmed_mutation_the_domain_refuses_is_journaled_as_recusa(tmp_path,
                                                                        fake_tmp,
                                                                        monkeypatch,
                                                                        capsys):
    """Recusa do domínio não apaga a operação do diário: o ato foi intentado e negado.

    O chão é o mesmo do teste de costura do guard: raízes erradas fazem o domínio
    recusar *depois* de o plano classificá-lo elegível — o caso em que a porta do
    coordenador abriu e quem disse não foi a revalidação do ato.
    """
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    monkeypatch.setattr(cli, "_tmpfs_guard_roots", lambda: [tmp_path / "guard-fora"])

    code = main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar"])

    assert code == cli.EXIT_REFUSED
    assert "allowed root" in capsys.readouterr().err
    records = _journal_records(tmp_path)
    assert [r["kind"] for r in records] == ["intent", "result"]
    verdict = records[1]["result"]
    assert verdict["outcome"] == "recusa"
    assert "allowed root" in verdict["reason"]
    assert not (tmp_path / "retida").exists(), "nada foi retido"


def test_a_corrupt_journal_blocks_the_mutation_before_any_copy(tmp_path, fake_tmp,
                                                               monkeypatch, capsys):
    """Diário ilegível fecha a porta: sem intenção registrável, o ato não roda.

    Falhar fechado é o ponto: um diário com linha quebrada (escrita interrompida,
    edição à mão) poderia esconder uma intenção sem resultado — mutar em cima disso
    é como reaplicar às cegas. O arquivo não pode ganhar nada por cima do problema.
    """
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    journal = tmp_path / "state" / "operations.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text("lixo\n", encoding="utf-8")

    code = main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar"])

    assert code == cli.EXIT_REFUSED
    assert "diário inconsistente" in capsys.readouterr().err
    assert journal.read_text() == "lixo\n", "nada foi anexado por cima do problema"
    assert not (tmp_path / "retida").exists(), "a porta fechou antes de copiar"
    assert (root / "qoder-cli-1000" / "blob.bin").exists(), "a origem está intacta"


def test_an_unconfirmed_release_never_touches_the_journal(tmp_path, fake_tmp,
                                                          monkeypatch, capsys):
    """Dry-run é dry-run: recusa de flag não vira operação registrada."""
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    code = main(["tmpfs", "release", str(root / "qoder-cli-1000")])
    assert code == cli.EXIT_NEEDS_CONFIRM
    assert "--confirmar" in capsys.readouterr().err
    assert _journal_records(tmp_path) == []
    assert not (tmp_path / "state" / "operations.jsonl").exists()


def test_restore_and_expire_are_journaled_too(tmp_path, fake_tmp, monkeypatch, capsys):
    """Os três atos mutantes entram pela mesma porta: nenhuma rota fica de fora."""
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar", "--json"])
    entry_id = json.loads(capsys.readouterr().out)["entry_id"]

    assert main(["tmpfs", "restore", entry_id, "--confirmar"]) == cli.EXIT_OK
    capsys.readouterr()  # a linha humana do restore não pode entrar no JSON do release
    records = _journal_records(tmp_path)
    assert [r["plan"]["action"] for r in records if r["kind"] == "intent"] == \
        ["tmpfs.release", "tmpfs.restore"]
    restored = records[-1]["result"]
    assert restored["outcome"] == "sucesso"
    assert restored["effects"]["entry_id"] == entry_id
    assert restored["effects"]["restored_to"] == str(root / "qoder-cli-1000")

    main(["tmpfs", "release", str(root / "qoder-cli-1000"), "--confirmar", "--json"])
    second_entry = json.loads(capsys.readouterr().out)["entry_id"]
    backdate(tmp_path, 40)
    assert main(["tmpfs", "expire", "--dias", "14", "--confirmar",
                 "--irreversivel"]) == cli.EXIT_OK
    assert capsys.readouterr().err == "", "sem suspeita, sem aviso"

    records = _journal_records(tmp_path)
    expire_intents = [r for r in records if r["kind"] == "intent"
                      and r["plan"]["action"] == "tmpfs.expire"]
    assert len(expire_intents) == 1, "uma operação de expire, uma intenção"
    assert expire_intents[0]["plan"]["params"] == {"days": 14.0,
                                                   "max_bytes": MAX_RETAINED_BYTES}
    assert records[-1]["kind"] == "result", "o expire é a última operação"
    verdict = records[-1]["result"]
    assert verdict["outcome"] == "sucesso"
    assert verdict["effects"]["freed_bytes"] == 4096
    assert verdict["effects"]["victims"] == [second_entry]


def _seed_staging(tmp_path, *, entry_id, src, stored):
    """A linha `staging` como o release a teria deixado antes do primeiro byte."""
    Ledger(tmp_path / "state" / "tmp-ledger.jsonl").append(
        entry_id=entry_id, src=str(src), volume=str(src), stored=str(stored),
        bytes=0, sha256="", age_days=1.0, matched_pattern=None, holder_pids=(),
        state="staging", action_id="tmpfs.release", audit_event_id="")


def test_tmpfs_recover_dry_run_then_confirm(tmp_path, fake_tmp, monkeypatch, capsys):
    """O recover da CLI: inventário sem flag, descarte confirmado, diário junto."""
    root, _ = tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    origem = root / "qoder-cli-1000"          # viva: o clone inacabado é redundante
    clone = tmp_path / "retida" / "20261017T000000Z" / "qoder-cli-1000"
    clone.mkdir(parents=True)
    (clone / "blob.bin").write_bytes(b"a" * 4096)
    _seed_staging(tmp_path, entry_id="st-1", src=origem, stored=clone)

    code = main(["tmpfs", "recover", "--json"])
    got = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK and got["dry_run"] is True
    assert got["dropped"] == ["st-1"] and got["kept"] == []
    assert clone.exists(), "dry-run não toca no clone"
    assert _ledger_records(tmp_path)[0]["state"] == "staging"

    code = main(["tmpfs", "recover", "--confirmar", "--json"])
    got = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_OK and got["ok"] is True and got["dropped"] == ["st-1"]
    assert not clone.exists()
    assert _ledger_records(tmp_path)[-1]["state"] == "dropped"
    assert (origem / "blob.bin").exists(), "a origem é a âncora e continua intacta"
    records = _journal_records(tmp_path)
    assert [r["kind"] for r in records] == ["intent", "result"]
    assert records[0]["plan"]["action"] == "tmpfs.recover"
    assert records[0]["plan"]["target"] == {"schema": 1, "kind": "group",
                                            "key": "tmpfs.staging", "detail": {}}
    assert records[1]["result"]["outcome"] == "sucesso"
    assert records[1]["result"]["effects"]["dropped"] == ["st-1"]


def test_tmpfs_recover_keeps_the_clone_when_the_origin_is_gone(tmp_path, fake_tmp,
                                                               monkeypatch, capsys):
    """Origem sumida: a CLI preserva o clone e o desfecho é parcial — como o diário.

    Decisão manual pendente não é sucesso: a CLI devolve o mesmo `parcial` que o
    veredito registrou (entrega 7), em vez de um 0 que diria "acabou".
    """
    tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    clone = tmp_path / "retida" / "stamp" / "sumida"
    clone.mkdir(parents=True)
    (clone / "unico.bin").write_bytes(b"z" * 16)
    _seed_staging(tmp_path, entry_id="st-2", src=tmp_path / "origem-que-sumiu",
                  stored=clone)

    code = main(["tmpfs", "recover", "--confirmar"])

    out = capsys.readouterr().out
    assert code == cli.EXIT_PARTIAL
    assert "decisão manual" in out and "não foi tocado" in out
    assert clone.exists() and _ledger_records(tmp_path)[-1]["state"] == "staging", \
        "sem certificação e sem origem, nada se apaga"
    verdict = _journal_records(tmp_path)[-1]["result"]
    assert verdict["outcome"] == "parcial"
    assert verdict["effects"]["kept"] == ["st-2"]


def test_tmpfs_recover_with_a_clean_ledger_says_there_is_nothing(tmp_path, fake_tmp,
                                                                 monkeypatch, capsys):
    tmpfs_env(tmp_path, fake_tmp, monkeypatch)
    code = main(["tmpfs", "recover", "--confirmar"])
    out = capsys.readouterr().out
    assert code == cli.EXIT_OK and "nada a recuperar" in out
    assert _ledger_records(tmp_path) == []
