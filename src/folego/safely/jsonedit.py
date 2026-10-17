"""Surgical JSON editing: change one key, leave every other byte alone.

Chromium's config files are minified single-line documents that the browser
rewrites on exit, and they carry per-key protection hashes under
``protection.macs``. Re-serializing the whole document would churn those bytes
and give the browser a reason to discard the profile's preferences, so an edit
here is textual: a small scanner walks the *structure* (respecting strings and
escapes, which is what makes ``"a\":{\"b\":"`` harmless) to find the exact span
of the key path and replaces only that span.

A document that does not parse is refused rather than rewritten, because a
half-written Local State costs the user their whole profile.
"""
from json import JSONDecodeError, dumps, loads

WHITESPACE = " \t\n\r"
OPENERS = {"{": "}", "[": "]"}


class MalformedDocument(ValueError):
    """The bytes are not a JSON object; nothing may be written over them."""


class KeyConflict(ValueError):
    """The key path exists, or its parent does, but not as an object to descend into."""


def set_value(data: bytes, key_path: tuple[str, ...], value) -> bytes:
    """Return `data` with `key_path` set to `value`, byte-preserving elsewhere."""
    path = tuple(key_path)
    if not path:
        raise ValueError("key_path must name at least one key")
    text = _decode(data)
    _validate_object(text)

    body = _body_start(text, _first_non_ws(text, 0))
    missing_from = 0  # index in path where the document stops having a branch
    for depth, key in enumerate(path[:-1]):
        found = _member_span(text, body, key)
        if found is None:
            missing_from = depth
            break
        start, end = found
        if text[_first_non_ws(text, start)] != "{":
            raise KeyConflict(f"{'.'.join(path[:depth + 1])} não é um objeto")
        body = _body_start(text, start)
    else:
        missing_from = len(path) - 1

    leaf = path[missing_from]
    serialized = dumps(value, separators=(",", ":"), ensure_ascii=False)
    if missing_from < len(path) - 1:  # a whole branch is missing: create it
        keys = path[missing_from:]
    else:
        existing = _member_span(text, body, leaf)
        if existing is not None:
            start, end = existing
            if text[start:end] == serialized:
                return data
            return (text[:start] + serialized + text[end:]).encode()
        keys = (leaf,)

    fragment = f'"{keys[-1]}":{serialized}'
    for key in reversed(keys[:-1]):
        fragment = f'"{key}":{{{fragment}}}'
    opening = _first_non_ws(text, body)
    if opening < len(text) and text[opening] == "}":
        return (text[:body] + fragment + text[body:]).encode()
    return (text[:body] + fragment + "," + text[body:]).encode()


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MalformedDocument(f"não é UTF-8: {exc}") from exc


def _validate_object(text: str) -> None:
    try:
        doc = loads(text)
    except JSONDecodeError as exc:
        raise MalformedDocument(f"JSON inválido: {exc}") from exc
    if not isinstance(doc, dict):
        raise MalformedDocument("a raiz do documento não é um objeto")


def _first_non_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in WHITESPACE:
        i += 1
    return i


def _body_start(text: str, i: int) -> int:
    """Index just past the '{' of the object that starts at i."""
    return i + 1


def _string_end(text: str, i: int) -> int:
    """Index just past the closing quote of the string starting at text[i] == '"'."""
    j = i + 1
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == '"':
            return j + 1
        j += 1
    raise MalformedDocument("string não terminada")


def _value_end(text: str, i: int) -> int:
    c = text[i]
    if c in OPENERS:
        return _container_end(text, i)
    if c == '"':
        return _string_end(text, i)
    j = i
    while j < len(text) and text[j] not in ",}]" + WHITESPACE:
        j += 1
    return j


def _container_end(text: str, i: int) -> int:
    """End of the object/array starting at i, counting nesting and skipping strings."""
    stack = []
    j = i
    while j < len(text):
        c = text[j]
        if c == '"':
            j = _string_end(text, j)
            continue
        if c in OPENERS:
            stack.append(OPENERS[c])
        elif stack and c == stack[-1]:
            stack.pop()
            if not stack:
                return j + 1
        elif c in "}]":
            raise MalformedDocument("colchete desbalanceado")
        j += 1
    raise MalformedDocument("objeto não terminada")


def _member_span(text: str, body: int, key: str) -> tuple[int, int] | None:
    """Span of `key`'s value inside the object whose body starts at `body`."""
    i = _first_non_ws(text, body)
    if i < len(text) and text[i] == "}":
        return None
    while True:
        if i >= len(text) or text[i] != '"':
            raise MalformedDocument("chave de objeto inválida")
        name_end = _string_end(text, i)
        name = loads(text[i:name_end])
        i = _first_non_ws(text, name_end)
        if i >= len(text) or text[i] != ":":
            raise MalformedDocument("falta ':' após a chave")
        i = _first_non_ws(text, i + 1)
        value_end = _value_end(text, i)
        if name == key:
            return (i, value_end)
        i = _first_non_ws(text, value_end)
        if i < len(text) and text[i] == ",":
            i = _first_non_ws(text, i + 1)
            continue
        return None
