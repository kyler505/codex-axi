"""TOON v3.3 output boundary for JSON-shaped CLI documents."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NUMERIC_LIKE = re.compile(r"^[+-]?(?:\d|\.\d)")


def toon(value: Any) -> str:
    """Encode normalized JSON data as TOON v3.3 without a trailing newline."""
    return "\n".join(_root_lines(value))


def preview(value: str, *, limit: int = 800) -> tuple[str, int | None]:
    if len(value) <= limit:
        return value, None
    return value[:limit] + "...", len(value)


def _root_lines(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return _object_lines(value, 0)
    if _sequence(value):
        return _array_lines(value, 0, None)
    return [_scalar_text(value)]


def _object_lines(value: Mapping[str, Any], depth: int) -> list[str]:
    if not value:
        return ["  " * depth + "{}"]
    lines: list[str] = []
    indent = "  " * depth
    for raw_key, item in value.items():
        key = _key(str(raw_key))
        if _scalar(item):
            lines.append(f"{indent}{key}: {_scalar_text(item)}")
        elif _sequence(item):
            lines.extend(_array_lines(item, depth, key))
        else:
            lines.append(f"{indent}{key}:")
            lines.extend(_object_lines(item, depth + 1))
    return lines


def _array_lines(value: Sequence[Any], depth: int, key: str | None) -> list[str]:
    indent = "  " * depth
    prefix = f"{key}" if key is not None else ""
    table = _table(value)
    if table is not None:
        fields, rows = table
        field_text = ",".join(_key(field) for field in fields)
        header = f"{indent}{prefix}[{len(rows)}]{{{field_text}}}:"
        row_indent = "  " * (depth + 1)
        return [
            header,
            *(row_indent + ",".join(_scalar_text(row[field]) for field in fields) for row in rows),
        ]
    if all(_scalar(item) for item in value):
        encoded = ",".join(_scalar_text(item) for item in value)
        suffix = f" {encoded}" if value else ""
        return [f"{indent}{prefix}[{len(value)}]:{suffix}"]
    lines = [f"{indent}{prefix}[{len(value)}]:"]
    for item in value:
        item_indent = "  " * (depth + 1)
        if _scalar(item):
            lines.append(f"{item_indent}- {_scalar_text(item)}")
        elif isinstance(item, Mapping):
            lines.extend(_list_object_lines(item, depth + 1))
        else:
            lines.append(f"{item_indent}-")
            lines.extend(_array_lines(item, depth + 2, None))
    return lines


def _list_object_lines(value: Mapping[str, Any], depth: int) -> list[str]:
    indent = "  " * depth
    if not value:
        return [f"{indent}- {{}}"]
    items = list(value.items())
    first_key, first_value = items[0]
    key = _key(str(first_key))
    lines: list[str] = []
    if _scalar(first_value):
        lines.append(f"{indent}- {key}: {_scalar_text(first_value)}")
    elif _sequence(first_value):
        array = _array_lines(first_value, depth, key)
        lines.append(f"{indent}- {array[0].lstrip()}")
        lines.extend(array[1:])
    else:
        lines.append(f"{indent}- {key}:")
        lines.extend(_object_lines(first_value, depth + 1))
    if len(items) > 1:
        lines.extend(_object_lines(dict(items[1:]), depth + 1))
    return lines


def _table(value: Sequence[Any]) -> tuple[list[str], list[Mapping[str, Any]]] | None:
    if not value or not all(isinstance(row, Mapping) for row in value):
        return None
    fields = [str(key) for key in value[0]]
    if not fields or not all(
        list(row) == fields and all(_scalar(item) for item in row.values()) for row in value
    ):
        return None
    return fields, list(value)


def _sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _key(value: str) -> str:
    return value if _IDENTIFIER.fullmatch(value) else _quote(value)


def _scalar_text(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "null"
        if value == 0:
            return "0"
        return format(value, ".15g")
    if isinstance(value, int):
        return str(value)
    return _quote(str(value))


def _quote(value: str) -> str:
    if value and _safe_bare(value):
        return value
    escaped: list[str] = []
    for char in value:
        code = ord(char)
        if char == "\\":
            escaped.append("\\\\")
        elif char == '"':
            escaped.append('\\"')
        elif char == "\n":
            escaped.append("\\n")
        elif char == "\r":
            escaped.append("\\r")
        elif char == "\t":
            escaped.append("\\t")
        elif code < 0x20:
            escaped.append(f"\\u{code:04X}")
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'


def _safe_bare(value: str) -> bool:
    return (
        not _NUMERIC_LIKE.match(value)
        and value not in {"true", "false", "null"}
        and not value.startswith("-")
        and not any(char.isspace() or char in ':,[]{}#"\\' or ord(char) < 0x20 for char in value)
    )
