"""smoke_sort — pure sorting / interval / frequency utilities (CC-208).

Three pure functions, no imports, no randomness. Inputs are never mutated;
every result is a freshly built list.
"""


def insertion_sort(items):
    """Stable ascending insertion sort of numbers.

    Returns a new list; the input is not mutated. An empty list yields
    an empty list.
    """
    result = list(items)
    for i in range(1, len(result)):
        key = result[i]
        j = i - 1
        while j >= 0 and result[j] > key:
            result[j + 1] = result[j]
            j -= 1
        result[j + 1] = key
    return result


def merge_intervals(intervals):
    """Sort intervals by start, then merge overlapping or touching ones.

    Input: list of (start, end) tuples with start <= end.
    Output: sorted list of merged (start, end) tuples.
    The input is not mutated.
    """
    if not intervals:
        return []
    sorted_ivs = sorted(intervals, key=lambda iv: (iv[0], iv[1]))
    merged = [sorted_ivs[0]]
    for start, end in sorted_ivs[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def mode(values):
    """Return the most frequent element; on a tie the smallest value wins.

    Empty input returns None. The input is not mutated.
    """
    if not values:
        return None
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    max_count = max(counts.values())
    candidates = [v for v, c in counts.items() if c == max_count]
    return min(candidates)
