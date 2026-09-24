"""Smoke test validating the curated toolchain (TASK-STANOK-SMOKE-02).

This is a minimal pytest that asserts a trivially true condition, proving
that the test runner (pytest via scripts/run.sh) is available and functioning
inside the sandbox.
"""


def test_toolchain_smoke():
    """Assert a trivially true condition to prove the runner works."""
    assert 1 == 1
