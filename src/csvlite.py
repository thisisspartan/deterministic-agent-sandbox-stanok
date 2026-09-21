"""csvlite — minimal RFC 4180 CSV parser/renderer.

Stdlib only, import-safe (no side effects). Exposes exactly two functions:

- ``parse(text) -> list[list[str]]``: parse CSV text into records of string
  fields. Fields are separated by ``,``; records by ``\\n`` or ``\\r\\n``
  (a bare ``\\r`` is ordinary field content). Quoted fields start with
  ``"`` and end at the next unescaped ``"``; ``""`` is an escaped literal
  ``"``. A trailing record separator yields no empty final record.
  An unterminated quoted field raises ``ValueError``.

- ``render(rows) -> str``: render rows to CSV. Fields joined by ``,``,
  records by ``\\n``, no trailing newline. A field is quoted only if it
  contains ``,``, ``"``, ``\\n`` or ``\\r``; embedded ``"`` are doubled.
  ``parse(render(rows)) == rows`` for any ``rows``.
"""

__all__ = ["parse", "render"]

# Characters that force quoting in render().
_QUOTE_TRIGGERS = (",", '"', "\n", "\r")


def parse(text: str) -> list[list[str]]:
    """Parse CSV *text* into a list of records (lists of string fields).

    Raises ``ValueError`` on an unterminated quoted field or a bare ``\\r``
    appearing where only ``,`` or a record separator may follow a quoted
    field (a bare ``\\r`` is never a separator; it is ordinary content
    only inside a field).
    """
    rows: list[list[str]] = []
    i, n = 0, len(text)
    while i < n:
        fields: list[str] = []
        while True:
            if i >= n:
                # Trailing comma: the final field is empty (a comma is not a
                # record separator, so this does record an empty field).
                fields.append("")
                rows.append(fields)
                break
            if text[i] == '"':
                # Quoted field: ends at the next unescaped quote.
                i += 1
                buf: list[str] = []
                closed = False
                while i < n:
                    c = text[i]
                    if c == '"':
                        if i + 1 < n and text[i + 1] == '"':
                            buf.append('"')  # "" -> literal "
                            i += 2
                        else:
                            closed = True
                            i += 1
                            break
                    else:
                        buf.append(c)  # , \n \r are literal inside quotes
                        i += 1
                if not closed:
                    raise ValueError("unterminated quoted field")
                fields.append("".join(buf))
            else:
                # Unquoted field: runs until the next `,` or record
                # separator (`\n` or `\r\n`). A bare `\r` is literal.
                buf = []
                while i < n:
                    c = text[i]
                    if c == ",":
                        break
                    if c == "\n":
                        break
                    if c == "\r" and i + 1 < n and text[i + 1] == "\n":
                        break
                    buf.append(c)
                    i += 1
                fields.append("".join(buf))
            # Consume the delimiter following the field.
            if i >= n:
                rows.append(fields)  # last record: no trailing separator
                break  # end of text
            c = text[i]
            if c == ",":
                i += 1  # next field on the same record
            elif c == "\n":
                i += 1
                rows.append(fields)
                break  # next record
            else:  # c == "\r"
                if i + 1 >= n or text[i + 1] != "\n":
                    raise ValueError("bare \\r after quoted field is not a valid separator")
                i += 2
                rows.append(fields)
                break  # next record
    return rows


def _render_field(field: str) -> str:
    """Render one field, quoting it only when necessary."""
    if any(ch in field for ch in _QUOTE_TRIGGERS):
        return '"' + field.replace('"', '""') + '"'
    return field


def render(rows: list[list[str]]) -> str:
    """Render *rows* to CSV text: ``,`` joins fields, ``\\n`` joins records,
    no trailing newline. Round-trips losslessly through :func:`parse`."""
    return "\n".join(",".join(_render_field(f) for f in row) for row in rows)
