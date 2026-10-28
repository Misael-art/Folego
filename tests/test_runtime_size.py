import pytest

from folego.core import runtime_size as rs

MIB = rs.MIB


def test_options_are_multiples_of_the_current_size_capped_by_ram():
    options = rs.options(1482 * MIB, 14 * 1024 * MIB)
    assert [o.multiplier for o in options] == [1, 2, 3, 4]
    assert [o.mib for o in options] == [1482, 2964, 4446, 5928]
    assert all(o.allowed for o in options)
    small_ram = rs.options(1500 * MIB, 4 * 1024 * MIB)
    assert [o.allowed for o in small_ram] == [True, False, False, False]
    assert "65% da RAM" in small_ram[1].reason


def test_options_refuse_unknown_sizes():
    with pytest.raises(ValueError):
        rs.options(0, 1024 * MIB)


def test_dropin_is_a_logind_login_section_in_mebibytes():
    text = rs.dropin_text(2964 * MIB)
    assert "[Login]\nRuntimeDirectorySize=2964M\n" in text
    with pytest.raises(ValueError):
        rs.dropin_text(10 * MIB)


def test_apply_is_one_pkexec_call_with_positional_arguments_only():
    argv = rs.apply_command(2964 * MIB, uid=1000)
    assert argv[:3] == ["pkexec", "/bin/sh", "-c"]
    script, *positional = argv[3:]
    # no value is interpolated into the shell text; all of them arrive as $1..$5
    assert "2964" not in script and "/run/user" not in script
    assert positional == ["folego-runtime-size", rs.DROPIN_DIR, rs.dropin_text(2964 * MIB),
                          rs.DROPIN_PATH, "2964", "/run/user/1000"]
    assert 'mount -o remount,size="$4"M "$5"' in script


def test_apply_refuses_another_users_runtime_or_root():
    with pytest.raises(ValueError):
        rs.apply_command(2964 * MIB, uid=1000, runtime="/run/user/1001")
    with pytest.raises(ValueError):
        rs.apply_command(2964 * MIB, uid=0)


def test_configured_size_reads_only_our_dropin(tmp_path):
    dropin = tmp_path / "60-folego-runtime-size.conf"
    assert rs.configured_size(str(dropin)) is None
    dropin.write_text(rs.dropin_text(4446 * MIB))
    assert rs.configured_size(str(dropin)) == 4446 * MIB
    dropin.write_text("[Login]\nRuntimeDirectorySize=20%\n")
    assert rs.configured_size(str(dropin)) is None


def test_mem_total_comes_from_meminfo(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemFree: 10 kB\nMemTotal:       14610000 kB\n")
    assert rs.mem_total_bytes(str(meminfo)) == 14610000 * 1024
