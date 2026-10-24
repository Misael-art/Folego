"""F8 doctor: read-only diagnostics, corrupt state is an error, no creation."""
import json

from folego import cli, doctor


def test_doctor_does_not_create_state(fake_home):
    state = fake_home / ".local" / "state" / "folego"
    assert not state.exists()
    report = doctor.collect()
    names = {check.name for check in report.checks}
    assert "schema automação" in names and "schema diário" in names
    assert "ferramenta git" in names
    assert not state.exists(), "doctor não pode criar diretório/arquivo/lock"


def test_corrupt_state_is_an_error_not_a_warning(fake_home):
    state = fake_home / ".local" / "state" / "folego"
    state.mkdir(parents=True)
    (state / "automation.json").write_text("lixo{")
    (state / "grants.json").write_text("lixo{")
    report = doctor.collect()
    errors = {check.name: check.detail for check in report.errors}
    assert "schema automação" in errors and "schema grants" in errors
    assert report.status == "error"


def test_autostart_is_reported_without_installing_anything(fake_home):
    report = doctor.collect()
    autostart = next(check for check in report.checks
                     if check.name == "autostart")
    assert "desativado" in autostart.detail
    assert not (fake_home / ".config" / "folego").exists()
    assert not (fake_home / ".config" / "autostart").exists()


def test_autostart_is_read_from_the_standard_xdg_location(fake_home):
    path = fake_home / ".config" / "autostart" / "folego.desktop"
    path.parent.mkdir(parents=True)
    path.write_text("[Desktop Entry]\nExec=folego\n", encoding="utf-8")

    report = doctor.collect()
    autostart = next(check for check in report.checks
                     if check.name == "autostart")
    assert "presente" in autostart.detail and str(path) in autostart.detail

    path.write_text("[Desktop Entry]\nExec=folego\nHidden=true\n",
                    encoding="utf-8")
    autostart = next(check for check in doctor.collect().checks
                     if check.name == "autostart")
    assert "presente e oculto" in autostart.detail


def test_doctor_cli_json_is_one_object(fake_home, capsys):
    code = cli.main(["doctor", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == cli.EXIT_OK
    assert payload["acao"] == "doctor" and payload["ok"] is True
    assert payload["healthy"] is True
    assert payload["errors"] == 0
    assert any(check["name"] == "python" for check in payload["checks"])
