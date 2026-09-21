# csvlite

`src/csvlite.py` is a minimal, dependency-free (stdlib only) CSV parser/renderer
exposing exactly two functions: `parse(text: str) -> list[list[str]]` and
`render(rows: list[list[str]]) -> str`. `parse` splits text into records
(`\n` or `\r\n` separated; a bare `\r` is ordinary field content, never a
separator) and fields (`,` separated), supporting RFC 4180 quoted fields
(`""` is an escaped literal quote; commas and newlines inside quotes are
literal), preserves spaces without trimming, produces no empty final record
for a trailing record separator (`parse("") == []`), and raises `ValueError`
on an unterminated quoted field. `render` joins fields with `,` and records
with `\n` (no trailing newline) and quotes a field only when it contains any
of `,`, `"`, `\n`, `\r`, doubling embedded quotes, so that
`parse(render(rows)) == rows` for any `rows`. The module is import-safe with
no side effects.
