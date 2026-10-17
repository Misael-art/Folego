from folego import paths


def test_data_dir_follows_xdg_data_home(fake_home):
    assert paths.data_dir() == fake_home / ".local" / "share" / "folego"


def test_config_dir_follows_xdg_config_home(fake_home):
    assert paths.config_dir() == fake_home / ".config" / "folego"


def test_backup_dir_is_under_data_dir(fake_home):
    assert paths.backup_dir() == paths.data_dir() / "backups"


def test_proc_root_defaults_to_real_proc(fake_home):
    assert paths.proc_root() == "/proc"


def test_proc_root_env_override(fake_home, monkeypatch, tmp_path):
    monkeypatch.setenv("DECKWELLNESS_PROC_ROOT", str(tmp_path / "proc"))
    assert paths.proc_root() == str(tmp_path / "proc")


def test_tmp_retention_lands_on_the_ssd_not_in_ram(fake_home):
    assert paths.tmp_ledger_path() == (
        fake_home / ".local" / "state" / "folego" / "tmp-ledger.jsonl")
    assert paths.tmp_quarantine_dir() == (
        fake_home / ".local" / "share" / "folego" / "tmp-quarantine")
