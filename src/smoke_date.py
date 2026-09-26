"""Pure date helpers over ISO ``YYYY-MM-DD`` strings.

Three pure functions, no I/O, no state:

- ``is_weekend(date_str)`` — ``True`` for Saturday/Sunday.
- ``add_business_days(date_str, n)`` — advance ``n`` business days
  (Monday–Friday); ``n=0`` returns the input unchanged; ``n`` is a
  non-negative int.
- ``month_name(date_str)`` — English month name (``"January"`` …
  ``"December"``).

All three raise ``ValueError`` on invalid input: a string that is not
strictly ``YYYY-MM-DD`` (zero-padded, no extra characters) or an
impossible calendar date (e.g. ``2026-02-31``).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def _parse(date_str: str) -> date:
    """Parse a strict ``YYYY-MM-DD`` string into a ``date``.

    Raises ``ValueError`` if the string is not exactly ``YYYY-MM-DD``
    or denotes an impossible calendar date.
    """
    if not isinstance(date_str, str) or not _ISO_RE.match(date_str):
        raise ValueError(f"not a YYYY-MM-DD date: {date_str!r}")
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise ValueError(f"impossible date: {date_str!r}") from None


def is_weekend(date_str: str) -> bool:
    """Return ``True`` iff ``date_str`` is a Saturday or Sunday."""
    return _parse(date_str).weekday() >= 5


def add_business_days(date_str: str, n: int) -> str:
    """Advance ``date_str`` by ``n`` business days (Monday–Friday).

    - ``n=0`` returns the input unchanged;
    - weekends are skipped: a Friday + 1 lands on the following Monday;
    - ``n`` must be a non-negative int (``ValueError`` otherwise).
    """
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise ValueError(f"n must be a non-negative int, got {n!r}")
    d = _parse(date_str)
    remaining = n
    while remaining:
        d += timedelta(days=1)
        if d.weekday() < 5:
            remaining -= 1
    return d.isoformat()


def month_name(date_str: str) -> str:
    """Return the English month name of ``date_str``."""
    return _MONTH_NAMES[_parse(date_str).month - 1]
