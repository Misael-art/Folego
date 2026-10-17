"""M2 primitive: change one key in a Chromium JSON file, touch nothing else.

Edge's files are minified single-line documents the browser rewrites on exit, and
they carry per-key protection hashes (``protection.macs``). Re-serializing the
whole document would churn every one of those bytes and invite the browser to
discard the profile's preferences. So the edit is textual: find the exact span of
the key path, replace that span, leave the rest of the file byte for byte alone.
Every test below asserts the untouched part stays identical, not just that the
result parses.
"""
import json

import pytest

from folego.safely.jsonedit import KeyConflict, MalformedDocument, set_value


def minified(doc: dict) -> bytes:
    return json.dumps(doc, separators=(",", ":")).encode()


# --------------------------------------------------------------- replacing a key

def test_replacing_an_existing_value_touches_only_that_value():
    data = minified({"browser": {"a": True, "b": "x"}, "c": 1})

    out = set_value(data, ("browser", "a"), False)

    assert json.loads(out) == {"browser": {"a": False, "b": "x"}, "c": 1}
    assert out == b'{"browser":{"a":false,"b":"x"},"c":1}'


def test_replacing_a_number_keeps_the_document_other_bytes_identical():
    data = minified({"perf": {"mode": 3, "on": False, "names": ["a", "b"]}})

    out = set_value(data, ("perf", "mode"), 1)

    assert data.replace(b"mode\":3", b"mode\":1") == out


def test_a_string_that_looks_like_the_key_is_not_edited():
    """"startup_boost" as a *value* must not be confused with the key path."""
    data = minified({"note": "startup_boost", "startup_boost": {"enabled": True}})

    out = set_value(data, ("startup_boost", "enabled"), False)

    assert json.loads(out)["note"] == "startup_boost"
    assert json.loads(out)["startup_boost"]["enabled"] is False


def test_a_key_repeated_in_sibling_objects_edits_only_the_named_one():
    data = minified({"x": {"enabled": True, "t": 1}, "y": {"enabled": False, "t": 2}})

    out = set_value(data, ("y", "enabled"), True)

    assert json.loads(out)["x"]["enabled"] is True
    assert json.loads(out)["y"]["enabled"] is True
    assert out.count(b'"enabled":true') == 2


def test_a_key_inside_an_array_element_is_left_to_the_array():
    """The scanner must know it is inside a list, not an object."""
    data = minified({"items": [{"enabled": True}, {"enabled": True}]})

    with pytest.raises(KeyConflict):
        set_value(data, ("items", "enabled"), False)


# ------------------------------------------------------------- inserting a branch

def test_a_missing_key_is_added_to_the_object_that_owns_it():
    data = minified({"startup_boost": {"last_browser_open_time": "13436417322947411"}})

    out = set_value(data, ("startup_boost", "enabled"), False)

    assert json.loads(out) == {"startup_boost": {"last_browser_open_time": "13436417322947411",
                                                 "enabled": False}}
    assert b'"last_browser_open_time":"13436417322947411"' in out
    assert out.startswith(b'{"startup_boost":{"enabled":false,')


def test_a_missing_branch_is_created_at_its_deepest_existing_ancestor():
    """background_mode has no section yet in a profile's Preferences: create the
    section, keep every other byte of a 400 kB document."""
    data = minified({"a": {"deep": 1}, "session": {"restore_on_startup": 5}})

    out = set_value(data, ("background_mode", "enabled"), False)

    assert json.loads(out) == {"background_mode": {"enabled": False},
                               "a": {"deep": 1},
                               "session": {"restore_on_startup": 5}}
    assert b'"session":{"restore_on_startup":5}' in out
    assert b'"a":{"deep":1}' in out


def test_inserting_next_to_a_string_containing_a_brace_does_not_split_it():
    data = minified({"weird": 'a":{"b":', "top": {"k": 1}})

    out = set_value(data, ("top", "k"), 2)

    assert json.loads(out)["weird"] == 'a":{"b":'
    assert json.loads(out)["top"]["k"] == 2


# ------------------------------------------------------------------- bad input

def test_a_corrupt_document_is_refused_before_anything_is_written():
    with pytest.raises(MalformedDocument):
        set_value(b'{"a":tru,', ("a", "b"), False)


def test_a_document_that_is_json_but_not_an_object_is_refused():
    with pytest.raises(MalformedDocument):
        set_value(b'[1,2]', ("a",), 1)


def test_descending_through_a_scalar_is_refused_not_silently_replaced():
    data = minified({"startup_boost": "yes"})

    with pytest.raises(KeyConflict):
        set_value(data, ("startup_boost", "enabled"), False)


def test_an_empty_key_path_is_refused():
    with pytest.raises(ValueError):
        set_value(minified({"a": 1}), (), 1)


# -------------------------------------------------------------- round-tripping

@pytest.mark.parametrize("value", [True, False, 0, 1, -3, "off", "", 2.5, None])
def test_every_supported_scalar_survives_the_edit(value):
    data = minified({"sec": {"k": "placeholder"}})

    out = set_value(data, ("sec", "k"), value)

    assert json.loads(out)["sec"]["k"] == value


def test_editing_a_document_that_already_holds_the_value_is_a_no_op():
    data = minified({"sec": {"k": False}})

    out = set_value(data, ("sec", "k"), False)

    assert out == data
