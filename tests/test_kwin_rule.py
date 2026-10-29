from types import SimpleNamespace

import pytest

from folego.ui import kwin_rule


class FakeKConfig:
    """kwriteconfig6/kreadconfig6 over a dict, plus a recorded qdbus reconfigure."""

    def __init__(self, general_rules=""):
        self.data = {("General", "rules"): general_rules} if general_rules else {}
        self.reloads = 0

    def which(self, name):
        return f"/usr/bin/{name}" if name in {"kwriteconfig6", "kreadconfig6", "qdbus6"} else None

    def run(self, argv, **kwargs):
        tool = argv[0].rsplit("/", 1)[-1]
        if tool == "qdbus6":
            self.reloads += 1
            return SimpleNamespace(returncode=0, stdout="")
        group, key = argv[argv.index("--group") + 1], argv[argv.index("--key") + 1]
        if tool == "kreadconfig6":
            return SimpleNamespace(returncode=0, stdout=self.data.get((group, key), "") + "\n")
        if "--delete" in argv:
            self.data.pop((group, key), None)
        else:
            self.data[(group, key)] = argv[-1]
        return SimpleNamespace(returncode=0, stdout="")


def test_install_requires_confirmation():
    fake = FakeKConfig()
    with pytest.raises(ValueError):
        kwin_rule.install("Fôlego — widget", 10, 20, confirmed=False, run=fake.run, which=fake.which)
    assert fake.data == {}


def test_install_writes_one_owned_rule_and_keeps_the_others():
    fake = FakeKConfig(general_rules="abc-user-rule")
    result = kwin_rule.install("Fôlego — widget", 1500, 900, confirmed=True, run=fake.run, which=fake.which)
    group = kwin_rule.GROUP
    assert fake.data[("General", "rules")] == f"abc-user-rule,{group}"
    assert fake.data[("General", "count")] == "2"
    assert fake.data[(group, "wmclass")] == "folego" and fake.data[(group, "title")] == "Fôlego — widget"
    assert fake.data[(group, "above")] == "true" and fake.data[(group, "aboverule")] == "2"
    assert fake.data[(group, "acceptfocus")] == "false"
    assert fake.data[(group, "position")] == "1500,900" and fake.data[(group, "positionrule")] == "3"
    assert result["reloaded"] and fake.reloads == 1
    assert kwin_rule.installed(run=fake.run, which=fake.which)
    kwin_rule.install("Fôlego — widget", 1, 2, confirmed=True, run=fake.run, which=fake.which)
    assert fake.data[("General", "rules")] == f"abc-user-rule,{group}", "idempotente: não duplica"


def test_remove_drops_only_our_rule():
    fake = FakeKConfig(general_rules="abc-user-rule")
    kwin_rule.install("Fôlego — widget", 1, 2, confirmed=True, run=fake.run, which=fake.which)
    kwin_rule.remove(run=fake.run, which=fake.which)
    assert fake.data[("General", "rules")] == "abc-user-rule"
    assert not any(group == kwin_rule.GROUP for group, _ in fake.data)
    assert not kwin_rule.installed(run=fake.run, which=fake.which)


def test_without_kde_tools_nothing_is_attempted():
    fake = FakeKConfig()
    with pytest.raises(RuntimeError):
        kwin_rule.install("t", 0, 0, confirmed=True, run=fake.run, which=lambda name: None)
    assert kwin_rule.installed(run=fake.run, which=lambda name: None) is False
