"""minjson — a minimal, dependency-free JSON parser and renderer.

Exposes exactly two functions:

    loads(text)  -> parse ONE JSON document into Python values
    dumps(obj)   -> render a Python value to compact JSON text

Hand-written parser/renderer: no stdlib ``json`` module is used.  All
malformed input to ``loads`` raises ``ValueError``; ``dumps`` raises
``TypeError`` for unsupported types and for non-``str`` dict keys.
"""

_DIGITS = "0123456789"
_HEX = _DIGITS + "abcdefABCDEF"
_WS = " \t\n\r"

_STRING_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}

_SHORT_ESCAPES = {
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def _is_digit(c):
    return c in _DIGITS


class _Parser:
    """Recursive-descent parser for a single JSON document."""

    def __init__(self, text):
        self.s = text
        self.i = 0
        self.n = len(text)

    def error(self, msg):
        raise ValueError("malformed JSON at position %d: %s" % (self.i, msg))

    def skip_ws(self):
        while self.i < self.n and self.s[self.i] in _WS:
            self.i += 1

    def value(self):
        self.skip_ws()
        if self.i >= self.n:
            self.error("unexpected end of input")
        c = self.s[self.i]
        if c == "{":
            return self.object()
        if c == "[":
            return self.array()
        if c == '"':
            return self.string()
        if c == "-" or _is_digit(c):
            return self.number()
        if c == "t":
            return self.keyword("true", True)
        if c == "f":
            return self.keyword("false", False)
        if c == "n":
            return self.keyword("null", None)
        self.error("unexpected character %r" % c)

    def keyword(self, word, value):
        if self.s.startswith(word, self.i):
            self.i += len(word)
            return value
        self.error("invalid literal at position %d" % self.i)

    def object(self):
        self.i += 1  # consume '{'
        obj = {}
        self.skip_ws()
        if self.i >= self.n:
            self.error("unclosed object")
        if self.s[self.i] == "}":
            self.i += 1
            return obj
        while True:
            self.skip_ws()
            if self.i >= self.n or self.s[self.i] != '"':
                self.error("expected string key")
            key = self.string()
            self.skip_ws()
            if self.i >= self.n or self.s[self.i] != ":":
                self.error("expected ':' after key")
            self.i += 1  # consume ':'
            obj[key] = self.value()  # duplicate keys: last wins
            self.skip_ws()
            if self.i >= self.n:
                self.error("unclosed object")
            c = self.s[self.i]
            if c == ",":
                self.i += 1
                self.skip_ws()
                if self.i >= self.n:
                    self.error("unclosed object")
                if self.s[self.i] == "}":
                    self.error("trailing comma in object")
            elif c == "}":
                self.i += 1
                return obj
            else:
                self.error("expected ',' or '}' in object")

    def array(self):
        self.i += 1  # consume '['
        arr = []
        self.skip_ws()
        if self.i >= self.n:
            self.error("unclosed array")
        if self.s[self.i] == "]":
            self.i += 1
            return arr
        while True:
            arr.append(self.value())
            self.skip_ws()
            if self.i >= self.n:
                self.error("unclosed array")
            c = self.s[self.i]
            if c == ",":
                self.i += 1
                self.skip_ws()
                if self.i >= self.n:
                    self.error("unclosed array")
                if self.s[self.i] == "]":
                    self.error("trailing comma in array")
            elif c == "]":
                self.i += 1
                return arr
            else:
                self.error("expected ',' or ']' in array")

    def string(self):
        # self.s[self.i] == '"'
        self.i += 1
        out = []
        while True:
            if self.i >= self.n:
                self.error("unterminated string")
            c = self.s[self.i]
            if c == '"':
                self.i += 1
                return "".join(out)
            if c == "\\":
                self.i += 1
                if self.i >= self.n:
                    self.error("unterminated escape sequence")
                e = self.s[self.i]
                if e == "u":
                    self.i += 1
                    if self.i + 4 > self.n:
                        self.error("incomplete \\u escape")
                    hexdigits = self.s[self.i:self.i + 4]
                    for ch in hexdigits:
                        if ch not in _HEX:
                            self.error("invalid \\u escape: %r" % hexdigits)
                    self.i += 4
                    out.append(chr(int(hexdigits, 16)))
                elif e in _STRING_ESCAPES:
                    self.i += 1
                    out.append(_STRING_ESCAPES[e])
                else:
                    self.error("invalid escape sequence '\\%s'" % e)
            elif ord(c) < 0x20:
                self.error("raw control character in string")
            else:
                out.append(c)
                self.i += 1

    def number(self):
        start = self.i
        if self.i < self.n and self.s[self.i] == "-":
            self.i += 1
        if self.i >= self.n or not _is_digit(self.s[self.i]):
            self.error("invalid number")
        if self.s[self.i] == "0":
            self.i += 1
        else:
            while self.i < self.n and _is_digit(self.s[self.i]):
                self.i += 1
        # leading zero followed by another digit is malformed (e.g. "01")
        if self.i < self.n and _is_digit(self.s[self.i]):
            self.error("invalid number: leading zero")
        is_float = False
        if self.i < self.n and self.s[self.i] == ".":
            is_float = True
            self.i += 1
            if self.i >= self.n or not _is_digit(self.s[self.i]):
                self.error("invalid number: fraction needs digits")
            while self.i < self.n and _is_digit(self.s[self.i]):
                self.i += 1
        if self.i < self.n and self.s[self.i] in "eE":
            is_float = True
            self.i += 1
            if self.i < self.n and self.s[self.i] in "+-":
                self.i += 1
            if self.i >= self.n or not _is_digit(self.s[self.i]):
                self.error("invalid number: exponent needs digits")
            while self.i < self.n and _is_digit(self.s[self.i]):
                self.i += 1
        text = self.s[start:self.i]
        return float(text) if is_float else int(text)


def loads(text):
    """Parse ONE JSON document ``text`` into Python values.

    Returns dict/list/str/int/float/bool/None.  Raises ``ValueError`` on
    any malformed input (trailing garbage, missing separators, unclosed
    containers, invalid escapes or numbers, empty input, ...).
    """
    if not isinstance(text, str):
        raise ValueError("loads expects a str")
    p = _Parser(text)
    value = p.value()
    p.skip_ws()
    if p.i != p.n:
        p.error("trailing characters after JSON document")
    return value


def _encode_string(s):
    out = ['"']
    for c in s:
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif c in _SHORT_ESCAPES:
            out.append(_SHORT_ESCAPES[c])
        elif ord(c) < 0x20:
            out.append("\\u%04x" % ord(c))
        else:
            out.append(c)  # non-ASCII emitted as-is
    out.append('"')
    return "".join(out)


def _encode(obj):
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if obj is None:
        return "null"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return repr(obj)
    if isinstance(obj, str):
        return _encode_string(obj)
    if isinstance(obj, dict):
        parts = []
        for key, value in obj.items():
            if not isinstance(key, str):
                raise TypeError("dict keys must be str, got %r" % type(key).__name__)
            parts.append(_encode_string(key) + ":" + _encode(value))
        return "{" + ",".join(parts) + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(_encode(v) for v in obj) + "]"
    raise TypeError("unsupported type: %r" % type(obj).__name__)


def dumps(obj):
    """Render Python value ``obj`` to compact JSON text.

    Compact separators ("," and ":"), dict keys in insertion order.
    Round-trips: ``loads(dumps(obj)) == obj`` for every supported value.
    """
    return _encode(obj)
