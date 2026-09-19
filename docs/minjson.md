# minjson — `src/minjson.py`

A minimal, dependency-free JSON module (hand-written parser/renderer; the
stdlib `json` module is NOT used). It exposes exactly two functions:

- `loads(text: str)` parses ONE JSON document into Python values — objects
  become `dict` (insertion order preserved, duplicate keys: last wins),
  arrays become `list`, strings use `\" \\ \/ \b \f \n \r \t \uXXXX` escapes
  (any other escape is malformed), numbers become `int` when they have no
  `.` and no exponent (otherwise `float`, `-0` -> `0`), `true`/`false`/`null`
  become `True`/`False`/`None`; only space/`\t`/`\n`/`\r` are skipped between
  tokens; any malformed input (trailing garbage, missing comma/colon,
  unclosed container, bad escape or number such as `01`, empty input) raises
  `ValueError`.
- `dumps(obj)` renders a value to compact JSON (`{a:1,b:[2,"x"]}` style: `,`
  and `:` separators, no spaces; dict keys in insertion order and must be
  `str`; `"` and `\` escaped, control chars below U+0020 as `\b \f \n \r \t`
  or `\u00XX`; non-ASCII emitted as-is; `bool` -> `true`/`false`, `None` ->
  `null`, `int` -> decimal, `float` -> `repr()` form) and round-trips:
  `loads(dumps(obj)) == obj` for every supported value.
