"""CI skip-contract extractor (SPEC-CI-MINIMAL, nodeid revision 2026-10-20).

Reads a pytest junit-xml report and prints the nodeids of skipped tests, one
per line, sorted: <path>.py::<test-name> (a class-based test resolves to
<path>.py::<Class>::<test-name>). Nodeids come from the testcase's `file`
attribute when pytest emitted it; otherwise they are derived from the dotted
`classname` and validated against the working tree: the longest dot-prefix of
the classname whose "<dotted-path>.py" file actually exists in the current
directory becomes the module path, the remaining dot-components become the
class chain. Derivation is validated because junit-xml classnames are
pytest-version-dependent (pinned 8.3.3 emits the full dotted module path;
newer pytest may emit a bare import name) and a class component must not be
mistaken for a file path — anything that does not resolve to a real file
emits "<unresolved>::<name>" so the contract diff fails closed instead of
encoding a silently wrong id or dropping a skip.

Position-independent: the line numbers of skip statements no longer
participate in the contract — editing a test file cannot redden CI by moving
a line. Must run with the repo root as the working directory (the CI does:
`cd stanok` first). Regenerate the expected list with this same module, on
the pinned interpreter only.

Note: an xfail reported as <skipped type="pytest.xfail"> is extracted like a
skip; the secondary "N skipped" log-count check in the workflow catches such
substitutions.

Usage: python -m launcher.ci_skips <junit-xml>
"""
import os
import sys
import xml.etree.ElementTree as ET


def _nodeid(tc: ET.Element) -> str:
    name = tc.get("name") or ""
    f = tc.get("file")
    if f:
        return f"{f}::{name}"
    cls = tc.get("classname") or ""
    if cls:
        parts = cls.split(".")
        for k in range(len(parts), 0, -1):
            mod = os.sep.join(parts[:k]) + ".py"
            if os.path.isfile(mod):
                return "::".join([mod] + parts[k:] + [name])
    return f"<unresolved>::{name}"


def extract(xml_path: str) -> list[str]:
    """Return the sorted list of nodeids for skipped testcases."""
    root = ET.parse(xml_path).getroot()
    out: list[str] = []
    for tc in root.iter("testcase"):
        if tc.find("skipped") is not None:
            out.append(_nodeid(tc))
    return sorted(out)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m launcher.ci_skips <junit-xml>", file=sys.stderr)
        return 2
    for nid in extract(argv[0]):
        print(nid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
