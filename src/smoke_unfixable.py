"""CC-212: trivial declared impl module.

Contract: `noop()` does nothing and returns None. The companion test
tests/smoke_unfixable_test.py is a deliberate contradiction (`assert False`)
that no change to this module can make pass — by design.
"""


def noop() -> None:
    """Do nothing."""
