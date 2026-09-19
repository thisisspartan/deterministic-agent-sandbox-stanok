"""csvlite — minimal RFC 4180-style CSV parser/renderer (stdlib only).

`parse(text)` converts CSV text to a list of records (list of str fields);
`render(rows)` converts rows back to CSV text. See docs/csvlite.md.
"""

_QUOTE = '"'
_SEP = ","


def _is_record_sep(text, i):
    """True if position i starts a record separator (\\n or \\r\\n).

    A bare \\r (not followed by \\n) is an ordinary character, never a
    record separator.
    """
    return text[i] == "\n" or (text[i] == "\r" and i + 1 < len(text)
                               and text[i + 1] == "\n")


def parse(text):
    """Parse CSV *text* into a list of records (each a list of str fields).

    Rules:
      * fields separated by `,`; records separated by `\\n` or `\\r\\n`;
        a bare `\\r` is a literal character inside a field;
      * a field starting with `"` is quoted and ends at the next `"`;
        `""` inside quotes is a literal `"`; commas and newlines inside
        quotes are literal content;
      * unquoted fields run until the next `,` or record separator —
        no trimming, spaces are preserved;
      * a trailing record separator does not create an empty final
        record; `parse("")` returns `[]`;
      * an unterminated quoted field raises `ValueError`.
    """
    n = len(text)
    if n == 0:
        return []

    rows = []
    row = []
    i = 0
    while i < n:
        if text[i] == _QUOTE:
            # Quoted field: ends at the closing `"`; `""` is a literal `"`.
            # Everything else (commas, \n, \r\n, bare \r) is literal content.
            buf = []
            i += 1
            closed = False
            while i < n:
                c = text[i]
                if c == _QUOTE:
                    if i + 1 < n and text[i + 1] == _QUOTE:
                        buf.append(_QUOTE)
                        i += 2
                    else:
                        closed = True
                        i += 1
                        break
                else:
                    buf.append(c)
                    i += 1
            if not closed:
                raise ValueError("unterminated quoted field")
            row.append("".join(buf))
        else:
            # Unquoted field: until `,` or a record separator; no trimming.
            buf = []
            while i < n and text[i] != _SEP and not _is_record_sep(text, i):
                buf.append(text[i])
                i += 1
            row.append("".join(buf))

        if i >= n:
            rows.append(row)
            return rows

        c = text[i]
        if c == _SEP:
            i += 1
            if i >= n:
                # Trailing comma: the final field of the record is empty.
                row.append("")
                rows.append(row)
                return rows
            continue

        if _is_record_sep(text, i):
            # Consume \n or \r\n; a trailing separator yields no new record.
            i += 2 if c == "\r" else 1
            rows.append(row)
            row = []
            continue

        # Anything else (only reachable after a closing quote) is malformed.
        raise ValueError("unexpected data after closing quote")

    return rows


def render(rows):
    """Render *rows* (list of list of str) to CSV text.

    Fields joined by `,`, records joined by `\\n`, no trailing newline.
    A field is quoted only if it contains `,`, `"`, `\\n` or `\\r`;
    embedded `"` are doubled. Round-trips with `parse`:
    `parse(render(rows)) == rows`.
    """
    def _field(f):
        if any(ch in f for ch in (",", '"', "\n", "\r")):
            return _QUOTE + f.replace('"', _QUOTE * 2) + _QUOTE
        return f

    return "\n".join(",".join(_field(f) for f in row) for row in rows)
