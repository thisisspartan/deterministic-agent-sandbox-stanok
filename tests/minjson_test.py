#!/usr/bin/env python3
"""Reference tests for src/minjson.py (ticket TASK-STANOK-PY-02).

Plain script (no pytest/unittest): exit 0 = all pass, non-zero = fail.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.minjson import loads, dumps  # noqa: E402


def check(name, cond, detail=""):
    if not cond:
        print("FAIL: %s %s" % (name, detail))
        sys.exit(1)
    print("ok: %s" % name)


def expect_value_error(name, text):
    try:
        loads(text)
        check(name, False, "(no exception raised)")
    except ValueError:
        check(name, True)
    except Exception as e:
        check(name, False, "(raised %r instead)" % (e,))


def main():
    # --- loads: scalars and containers ---
    check('loads("{}") == {}', loads("{}") == {})
    check('loads("[]") == []', loads("[]") == [])
    check('loads(\'{"a": 1}\') == {"a": 1}', loads('{"a": 1}') == {"a": 1})

    # duplicate keys: last occurrence wins
    check('loads(\'{"a": 1, "a": 2}\') == {"a": 2}',
          loads('{"a": 1, "a": 2}') == {"a": 2})

    # numbers: int vs float
    check('loads(\'{"n": [1, 2.5, -3, 1e2, -0]}\') == {"n": [1, 2.5, -3, 100.0, 0]}',
          loads('{"n": [1, 2.5, -3, 1e2, -0]}') == {"n": [1, 2.5, -3, 100.0, 0]})
    check('loads(\'{"n": 1}\')["n"] is int',
          isinstance(loads('{"n": 1}')["n"], int)
          and not isinstance(loads('{"n": 1}')["n"], bool))
    check('loads(\'{"n": 1e2}\')["n"] is float',
          isinstance(loads('{"n": 1e2}')["n"], float))

    # strings: escapes
    check('loads(\'{"s": "A\\u0042\\n\\"q\\""}\') == {"s": \'AB\\n"q"\'}',
          loads('{"s": "A\\u0042\\n\\"q\\""}') == {"s": 'AB\n"q"'})
    check('loads(\'{"s": "x\\b\\f\\r\\t/y\\//"}\') == {"s": \'x\x08\x0c\r\t/y//\'}',
          loads('{"s": "x\\b\\f\\r\\t/y\\//"}') == {"s": "x\x08\x0c\r\t/y//"})

    # true/false/null
    check('loads(\'{"t": true, "f": false, "n": null}\') '
          '== {"t": True, "f": False, "n": None}',
          loads('{"t": true, "f": false, "n": null}')
          == {"t": True, "f": False, "n": None})

    # whitespace between tokens
    check('loads(\'  { "a" : [ 1 , 2 ] }  \') == {"a": [1, 2]}',
          loads('  { "a" : [ 1 , 2 ] }  ') == {"a": [1, 2]})

    # nesting and top-level values
    check('loads("[[1], [[2]]]") == [[1], [[2]]]',
          loads("[[1], [[2]]]") == [[1], [[2]]])
    check('loads("null") is None', loads("null") is None)
    check('loads("-0") == 0 and is int',
          type(loads("-0")) is int and loads("-0") == 0)
    check('loads(".5") is invalid', _raises(lambda: loads(".5")))

    # --- loads: malformed input must raise ValueError ---
    expect_value_error('loads(\'{"a": 1}x\') raises ValueError', '{"a": 1}x')
    expect_value_error('loads(\'{"a": 1,}\') raises ValueError', '{"a": 1,}')
    expect_value_error('loads(\'{"a" 1}\') raises ValueError', '{"a" 1}')
    expect_value_error('loads(\'{"a": "\\q"}\') raises ValueError', '{"a": "\\q"}')
    expect_value_error('loads(\'{"a": "\\u00G1"}\') raises ValueError',
                       '{"a": "\\u00G1"}')
    expect_value_error('loads(\'{"a": 1.2.3}\') raises ValueError', '{"a": 1.2.3}')
    expect_value_error('loads(\'{"a": 01}\') raises ValueError', '{"a": 01}')
    expect_value_error('loads("") raises ValueError', "")
    expect_value_error('loads("{") raises ValueError', "{")
    expect_value_error('loads("[1") raises ValueError', "[1")
    expect_value_error('loads("1 2") raises ValueError', "1 2")
    expect_value_error('loads("1,") raises ValueError', "1,")
    expect_value_error('loads("[1 2]") raises ValueError', "[1 2]")
    expect_value_error('loads("\"abc") raises ValueError', '"abc')
    expect_value_error('loads("-") raises ValueError', "-")
    expect_value_error('loads("1e") raises ValueError', "1e")
    expect_value_error('loads("1e+") raises ValueError', "1e+")
    expect_value_error('loads(".5") raises ValueError', ".5")
    expect_value_error('loads("01") raises ValueError', "01")

    # --- dumps ---
    check('dumps({"a": 1}) == \'{"a":1}\'', dumps({"a": 1}) == '{"a":1}')
    check('dumps([1, "x", None, True]) == \'[1,"x",null,true]\'',
          dumps([1, "x", None, True]) == '[1,"x",null,true]')
    check('dumps({"s": \'a"b\\nc\'}) == \'{"s":"a\\"b\\nc"}\'',
          dumps({"s": 'a"b\nc'}) == '{"s":"a\\"b\\nc"}')
    check('dumps({"f": 1.5}) == \'{"f":1.5}\'', dumps({"f": 1.5}) == '{"f":1.5}')
    check('dumps({"s": "\\"a\\\\b"}) == \'{"s":"\\"a\\\\b"}\'',
          dumps({"s": '"a\\b'}) == '{"s":"\\"a\\\\b"}')
    check('dumps(0) == "0"', dumps(0) == "0")
    check('dumps(True) == "true"', dumps(True) == "true")
    check('dumps(None) == "null"', dumps(None) == "null")
    check('dumps({"a": {"b": 1}}) == \'{"a":{"b":1}}\'',
          dumps({"a": {"b": 1}}) == '{"a":{"b":1}}')
    # control chars: short forms and \u00XX fallback
    check('dumps({"s": "\\u0001\\u0008\\u000c\\u001f"}) == '
          '\'{"s":"\\u0001\\b\\f\\u001f"}\'',
          dumps({"s": "\x01\x08\x0c\x1f"}) == '{"s":"\\u0001\\b\\f\\u001f"}')
    # non-ASCII emitted as-is
    check('dumps({"s": "\\u00e9"}) == \'{"s":"\\u00e9"}\'',
          dumps({"s": "\u00e9"}) == '{"s":"\u00e9"}')

    # --- round-trip ---
    obj = {"a": [1, 2.5, "x\ty", None], "b": {"c": True}}
    check("round-trip loads(dumps(obj)) == obj", loads(dumps(obj)) == obj)

    print("ALL PASS")


def _raises(fn):
    try:
        fn()
        return False
    except ValueError:
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
