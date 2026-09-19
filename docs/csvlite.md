# csvlite

`src/csvlite.py` is a minimal, dependency-free (stdlib-only) RFC 4180-style CSV
module exposing exactly two functions.

`parse(text: str) -> list[list[str]]` converts CSV text into records of string
fields. Fields are separated by `,` and records by `\n` or `\r\n`; a bare `\r`
is an ordinary character, not a record separator. A field starting with `"` is
quoted and ends at the next `"`; inside quotes `""` is a literal `"`, and commas
and newlines are literal content. Unquoted fields run until the next `,` or
record separator with no trimming (spaces preserved). A trailing record
separator produces no empty final record, and `parse("")` returns `[]`. An
unterminated quoted field raises `ValueError`.

`render(rows: list[list[str]]) -> str` converts rows back to CSV text: fields
joined by `,`, records by `\n`, with no trailing newline. A field is quoted
only if it contains `,`, `"`, `\n`, or `\r`, and embedded `"` are doubled.
Round-trip is guaranteed: for any `rows`, `parse(render(rows)) == rows`.
