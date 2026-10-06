"""Reference tests for src/smoke_runs.py (TASK-STANOK-CC-196).

A "run" is a maximal contiguous subsequence where each element is
exactly +1 from the previous.

Covers the ticket contract:
- count_runs: every ticket vector, empty list -> 0.
- longest_run: every ticket vector, empty list -> 0.
- run_starts: every ticket vector, empty list -> [].
- Cross-checks on a fixed deterministic list of 200 ints
  (random.Random(11) sample with repeats):
  * count_runs == 1 + number of adjacent breaks (0 for empty);
  * longest_run matches a brute-force O(n^2) reference;
  * the sum of run lengths derived from run_starts by walking the
    list equals len(nums).
- None of the three functions mutates the input list.
"""

import random

from smoke_runs import count_runs, longest_run, run_starts


# Fixed deterministic list of 200 ints with repeats (seed 11).
NUMS = [random.Random(11).randint(0, 9) for _ in range(200)]


def test_count_runs_empty():
    assert count_runs([]) == 0


def test_count_runs_single():
    assert count_runs([1]) == 1


def test_count_runs_one_run():
    assert count_runs([1, 2, 3]) == 1


def test_count_runs_two_runs():
    assert count_runs([1, 2, 4, 5]) == 2


def test_count_runs_all_singletons():
    assert count_runs([5, 3, 1]) == 3


def test_count_runs_three_runs():
    assert count_runs([1, 2, 4, 5, 7]) == 3


def test_longest_run_empty():
    assert longest_run([]) == 0


def test_longest_run_single():
    assert longest_run([1]) == 1


def test_longest_run_one_run():
    assert longest_run([1, 2, 3]) == 3


def test_longest_run_two_runs():
    assert longest_run([1, 2, 4, 5]) == 2


def test_longest_run_all_singletons():
    assert longest_run([5, 3, 1]) == 1


def test_longest_run_three_runs():
    assert longest_run([1, 2, 4, 5, 7]) == 2


def test_run_starts_empty():
    assert run_starts([]) == []


def test_run_starts_one_run():
    assert run_starts([1, 2, 3]) == [1]


def test_run_starts_three_runs():
    assert run_starts([1, 2, 4, 5, 7]) == [1, 4, 7]


def test_run_starts_all_singletons():
    assert run_starts([5, 3, 1]) == [5, 3, 1]


def test_count_runs_matches_break_count_on_200_list():
    expected = 1 + sum(
        1 for i in range(len(NUMS) - 1) if NUMS[i + 1] != NUMS[i] + 1
    )
    assert count_runs(NUMS) == expected


def test_count_runs_empty_break_count():
    # The break-count formula degenerates to 0 for the empty list.
    assert count_runs([]) == 0


def _brute_longest(nums):
    """Brute-force O(n^2) reference: try every start index."""
    best = 0
    for i in range(len(nums)):
        length = 1
        for j in range(i + 1, len(nums)):
            if nums[j] == nums[j - 1] + 1:
                length += 1
            else:
                break
        best = max(best, length)
    return best


def test_longest_run_matches_brute_force_on_200_list():
    assert longest_run(NUMS) == _brute_longest(NUMS)


def _run_lengths_from_starts(nums, starts):
    """Walk the list; each run begins where the next start value occurs."""
    total = 0
    si = 0
    i = 0
    while i < len(nums):
        assert nums[i] == starts[si]
        length = 1
        while i + 1 < len(nums) and nums[i + 1] == nums[i] + 1:
            i += 1
            length += 1
        total += length
        si += 1
        i += 1
    assert si == len(starts)
    return total


def test_run_lengths_sum_to_len_on_200_list():
    starts = run_starts(NUMS)
    assert _run_lengths_from_starts(NUMS, starts) == len(NUMS)


def test_run_starts_count_equals_count_runs_on_200_list():
    assert len(run_starts(NUMS)) == count_runs(NUMS)


def test_input_not_mutated_by_count_runs():
    xs = [1, 2, 4, 5, 7]
    count_runs(xs)
    assert xs == [1, 2, 4, 5, 7]


def test_input_not_mutated_by_longest_run():
    xs = [1, 2, 4, 5, 7]
    longest_run(xs)
    assert xs == [1, 2, 4, 5, 7]


def test_input_not_mutated_by_run_starts():
    xs = [1, 2, 4, 5, 7]
    run_starts(xs)
    assert xs == [1, 2, 4, 5, 7]
