"""TOON (Token-Oriented Object Notation) encoder for Lion.

Lightweight implementation of the TOON format for token-efficient
structured data exchange between agents. No external dependencies.

TOON spec: https://toonformat.dev/reference/spec.html

Key savings vs JSON:
- No braces/brackets
- Tabular arrays declare fields once, then stream row values
- Minimal quoting (only when needed)
"""


def encode(data):
    """Encode Python data to TOON format.

    Supports: dicts, lists of dicts (tabular), lists of primitives,
    strings, numbers, booleans, None.
    """
    if isinstance(data, dict):
        return _encode_dict(data, indent=0)
    if isinstance(data, list):
        return _encode_root_list(data)
    return _encode_value(data)


def _encode_dict(d, indent=0):
    """Encode a dict to TOON key-value pairs."""
    lines = []
    prefix = "  " * indent

    for key, value in d.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(_encode_dict(value, indent + 1))
        elif isinstance(value, list):
            lines.append(_encode_list_field(key, value, indent))
        elif value is None:
            lines.append(f"{prefix}{key}: null")
        else:
            lines.append(f"{prefix}{key}: {_encode_value(value)}")

    return "\n".join(lines)


def _encode_list_field(key, items, indent=0):
    """Encode a list as a TOON field."""
    prefix = "  " * indent

    if not items:
        return f"{prefix}{key}[0]:"

    # Check if all items are dicts with same keys (tabular)
    if all(isinstance(item, dict) for item in items):
        return _encode_tabular(key, items, indent)

    # Primitive list: inline comma-separated
    if all(isinstance(item, (str, int, float, bool)) or item is None for item in items):
        values = ",".join(_encode_value(v) for v in items)
        return f"{prefix}{key}[{len(items)}]: {values}"

    # Mixed list: use hyphen notation
    lines = [f"{prefix}{key}[{len(items)}]:"]
    for item in items:
        if isinstance(item, dict):
            dict_line = _encode_dict(item, indent + 2)
            lines.append(f"{prefix}  - {dict_line.strip()}")
        else:
            lines.append(f"{prefix}  - {_encode_value(item)}")
    return "\n".join(lines)


def _encode_tabular(key, items, indent=0):
    """Encode a list of dicts as a TOON table."""
    prefix = "  " * indent

    # Get field names from first item
    fields = list(items[0].keys())
    fields_str = ",".join(fields)

    lines = [f"{prefix}{key}[{len(items)}]{{{fields_str}}}:"]

    for item in items:
        values = []
        for field in fields:
            val = item.get(field)
            values.append(_encode_value(val))
        lines.append(f"{prefix}  {','.join(values)}")

    return "\n".join(lines)


def _encode_root_list(items):
    """Encode a root-level list."""
    if not items:
        return "[0]:"

    if all(isinstance(item, dict) for item in items):
        return _encode_tabular("", items, 0).lstrip()

    values = ",".join(_encode_value(v) for v in items)
    return f"[{len(items)}]: {values}"


def _encode_value(value):
    """Encode a single value to TOON."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return _quote_if_needed(value)
    if isinstance(value, list):
        # Inline list for nested lists
        inner = ",".join(_encode_value(v) for v in value)
        return f"[{len(value)}]: {inner}"
    return str(value)


def _quote_if_needed(s):
    """Quote a string only if it contains special characters."""
    if not s:
        return '""'

    # Needs quoting if it contains special chars or looks like a number/bool
    needs_quote = False
    special = {':', '"', '\\', '[', ']', '{', '}', ','}
    if any(c in s for c in special):
        needs_quote = True
    elif s.lower() in ('true', 'false', 'null'):
        needs_quote = True
    elif s[0] == ' ' or s[-1] == ' ':
        needs_quote = True
    else:
        try:
            float(s)
            needs_quote = True
        except ValueError:
            pass

    if needs_quote:
        return f'"{s}"'
    return s
