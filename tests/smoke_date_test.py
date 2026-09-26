"""Reference tests for src/smoke_date.py (TASK-STANOK-CC-169).

Covers the ticket contract:
- is_weekend: Saturday/Sunday detection vs weekdays.
- add_business_days: n=0, weekend skipping, month boundary, year boundary
  (Dec -> Jan).
- month_name: all 12 English month names.
- ValueError on invalid input for every function.
"""

import pytest

from smoke_date import add_business_days, is_weekend, month_name

# Not YYYY-MM-DD, or impossible calendar dates.
INVALID_DATES = [
    "",
    "not-a-date",
    "2026-1-1",          # not zero-padded
    "26-01-01",          # two-digit year
    "2026-01-01T00:00:00",  # datetime, not date
    "2026-01-01 ",       # trailing space
    "2026-13-01",        # month out of range
    "2026-00-10",        # month zero
    "2026-02-31",        # impossible day
    "2026-04-31",        # impossible day
    "2026-06-31",        # impossible day
    "2023-02-29",        # 2023 is not a leap year
]


def test_is_weekend_saturday_and_sunday():
    assert is_weekend("2026-01-03") is True  # Saturday
    assert is_weekend("2026-01-04") is True  # Sunday


def test_is_weekend_weekdays():
    # Thu, Fri, Mon, Tue, Wed
    for d in ("2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"):
        assert is_weekend(d) is False


def test_add_business_days_zero_returns_input_unchanged():
    assert add_business_days("2026-01-02", 0) == "2026-01-02"
    assert add_business_days("2026-01-03", 0) == "2026-01-03"  # Saturday stays


def test_add_business_days_friday_plus_one_is_monday():
    assert add_business_days("2026-01-02", 1) == "2026-01-05"


def test_add_business_days_skips_weekend_from_weekend_start():
    assert add_business_days("2026-01-03", 1) == "2026-01-05"  # Sat -> Mon
    assert add_business_days("2026-01-04", 1) == "2026-01-05"  # Sun -> Mon


def test_add_business_days_within_week():
    assert add_business_days("2026-01-05", 4) == "2026-01-09"   # Mon -> Fri
    assert add_business_days("2026-01-05", 10) == "2026-01-19"  # Mon -> next Mon


def test_add_business_days_month_boundary():
    # 2026-01-30 is a Friday; +1 business day crosses into February.
    assert add_business_days("2026-01-30", 1) == "2026-02-02"
    assert add_business_days("2026-01-30", 2) == "2026-02-03"


def test_add_business_days_year_boundary():
    # 2026-12-31 is a Thursday; +1 business day lands in 2027.
    assert add_business_days("2026-12-31", 1) == "2027-01-01"
    # 2026-12-25 is a Friday; +1 business day skips the weekend.
    assert add_business_days("2026-12-25", 1) == "2026-12-28"


def test_month_name_all_twelve():
    expected = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    for i, name in enumerate(expected, start=1):
        assert month_name(f"2026-{i:02d}-15") == name


def test_is_weekend_invalid_input_raises_value_error():
    for bad in INVALID_DATES:
        with pytest.raises(ValueError):
            is_weekend(bad)


def test_add_business_days_invalid_input_raises_value_error():
    for bad in INVALID_DATES:
        with pytest.raises(ValueError):
            add_business_days(bad, 1)


def test_add_business_days_negative_n_raises_value_error():
    with pytest.raises(ValueError):
        add_business_days("2026-01-05", -1)


def test_month_name_invalid_input_raises_value_error():
    for bad in INVALID_DATES:
        with pytest.raises(ValueError):
            month_name(bad)
