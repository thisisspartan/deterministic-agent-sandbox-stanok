"""CC-306 minesweeper engine tests — M1..M7 with negatives.

Fixtures are hand-pinned: every expected adjacency / relocation / flood set
below was derived by hand (or by the independent reference helpers defined in
this file) from the seeded layout — never captured from the engine under test.
Fixture seeds were found offline and pinned literally:
  3x3 single mine at (2,2) -> seed 5; at (1,1) -> seed 2; at (2,1) -> seed 6.
  9x9/10 with a mine at (1,1)/(5,5) -> seed 6; at (1,5) -> seed 16.
  6x6/4 partial flood from (1,1) -> seed 2.
"""

import dataclasses
import random

import pytest

try:
    from src import minesweeper_engine as eng
except ImportError:
    import minesweeper_engine as eng


# ---------- local reference helpers (independent of the engine under test)

def ref_cells(w, h):
    return [(x, y) for y in range(1, h + 1) for x in range(1, w + 1)]


def ref_mines(seed, w, h, n):
    return frozenset(random.Random(seed).sample(ref_cells(w, h), n))


def ref_adj(mines, w, h):
    out = []
    for y in range(1, h + 1):
        row = []
        for x in range(1, w + 1):
            row.append(sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                           if (dx or dy) and (x + dx, y + dy) in mines))
        out.append(tuple(row))
    return tuple(out)


def ref_reveal(mines, adj, w, h, start):
    """M6 expected opened set from opening non-mine `start`."""
    if adj[start[1] - 1][start[0] - 1] != 0:
        return {start}
    opened = set()
    frontier = [start]
    seen = {start}
    while frontier:
        cx, cy = frontier.pop()
        opened.add((cx, cy))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if 1 <= nx <= w and 1 <= ny <= h and (nx, ny) not in seen \
                    and (nx, ny) not in mines and adj[ny - 1][nx - 1] == 0:
                seen.add((nx, ny))
                frontier.append((nx, ny))
    for z in list(opened):  # numeric border: 8-neighborhood of any revealed zero
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = z[0] + dx, z[1] + dy
                if 1 <= nx <= w and 1 <= ny <= h and (nx, ny) not in mines:
                    opened.add((nx, ny))
    return opened


def snapshot(s):
    return (s.seed, s.width, s.height, s.mines_total, s.mines, s.adj,
            s.opened, s.flagged, s.status, s.first_done)


# ---------- M1/M2: API surface, frozen dataclass, purity

def test_api_names_exist():
    for name in ("new_game", "open_cell", "toggle_flag", "is_won", "is_lost"):
        assert callable(getattr(eng, name)), name


def test_state_is_frozen_with_pinned_fields():
    s = eng.new_game(1, 9, 9, 10)
    fields = {f.name for f in dataclasses.fields(s)}
    assert {"seed", "width", "height", "mines_total", "mines", "adj",
            "opened", "flagged", "status", "first_done"} == fields
    assert s.status == "playing" and s.first_done is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.status = "won"
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.first_done = True


def test_state_attributes_are_immutable_types():
    s = eng.new_game(1, 5, 5, 3)
    assert isinstance(s.mines, frozenset)
    assert isinstance(s.opened, frozenset) and s.opened == frozenset()
    assert isinstance(s.flagged, frozenset) and s.flagged == frozenset()
    assert isinstance(s.adj, tuple) and len(s.adj) == 5
    assert all(isinstance(row, tuple) and len(row) == 5 for row in s.adj)
    assert all(isinstance(v, int) for row in s.adj for v in row)
    assert all(isinstance(c, tuple) and len(c) == 2 for c in s.mines)


def test_operations_are_pure_and_return_new_objects():
    s = eng.new_game(3, 9, 9, 10)
    before = snapshot(s)
    flagged = eng.toggle_flag(s, 1, 1)
    opened = eng.open_cell(flagged, 2, 2)
    assert snapshot(s) == before  # input state untouched
    assert flagged is not s and opened is not s and opened is not flagged
    assert snapshot(flagged)[:7] == before[:7]  # only flagged differs
    assert flagged.flagged == frozenset({(1, 1)})
    assert snapshot(opened)[:6] == snapshot(flagged)[:6]  # mines/adj preserved


# ---------- M3: validation, determinism, field legality

@pytest.mark.parametrize("w,h,n", [
    (0, 5, 1), (5, 0, 1), (-1, 5, 1), (1, -1, 1),
    (65, 1, 1), (1, 33, 1), (64, 33, 1), (65, 32, 1),
    (5, 5, -1), (3, 3, 9), (2, 2, 4), (1, 1, 1),
])
def test_bad_new_game_raises_value_error(w, h, n):
    with pytest.raises(ValueError):
        eng.new_game(1, w, h, n)


def test_boundary_sizes_accepted():
    s = eng.new_game(1, 64, 32, 64 * 32 - 1)
    assert s.width == 64 and s.height == 32
    assert s.mines_total == 64 * 32 - 1 and len(s.mines) == 64 * 32 - 1
    s0 = eng.new_game(1, 1, 1, 0)
    assert s0.mines_total == 0 and s0.mines == frozenset()
    assert s0.adj == ((0,),) and s0.status == "playing" and s0.first_done is False


def test_same_seed_identical_different_seed_differs():
    a, b = eng.new_game(42, 16, 16, 40), eng.new_game(42, 16, 16, 40)
    assert a.mines == b.mines and a.adj == b.adj
    assert a.seed == 42 and a.mines_total == 40
    assert eng.new_game(7, 16, 16, 40).mines != eng.new_game(8, 16, 16, 40).mines


@pytest.mark.parametrize("seed,w,h,n", [
    (1, 9, 9, 10), (13, 16, 16, 40), (20, 30, 16, 99), (7, 64, 32, 500),
])
def test_mines_match_reference_placement_and_are_legal(seed, w, h, n):
    s = eng.new_game(seed, w, h, n)
    exp = ref_mines(seed, w, h, n)
    assert s.mines == exp, f"placement mismatch seed={seed}"
    assert len(s.mines) == n  # no duplicates
    assert all(1 <= x <= w and 1 <= y <= h for x, y in s.mines)
    assert s.opened == frozenset() and s.flagged == frozenset()


# ---------- M4: adjacency, hand-pinned reference fields

@pytest.mark.parametrize("seed,expected_adj", [
    # 3x3, single mine at CENTER (2,2): every other cell sees exactly it.
    (5, ((1, 1, 1), (1, 0, 1), (1, 1, 1))),
    # 3x3, single mine at CORNER (1,1).
    (2, ((0, 1, 0), (1, 1, 0), (0, 0, 0))),
    # 3x3, single mine at EDGE (2,1).
    (6, ((1, 0, 1), (1, 1, 1), (0, 0, 0))),
])
def test_adjacency_hand_pinned_fields(seed, expected_adj):
    s = eng.new_game(seed, 3, 3, 1)
    assert len(s.mines) == 1
    assert s.adj == expected_adj


def test_adjacency_matches_reference_on_random_fields():
    for seed, w, h, n in ((1, 9, 9, 10), (13, 16, 16, 40), (2, 6, 6, 4)):
        s = eng.new_game(seed, w, h, n)
        assert s.adj == ref_adj(s.mines, w, h), f"adj mismatch seed={seed}"


# ---------- M5: safe first open (corner / edge / center)

@pytest.mark.parametrize("seed,x,y", [
    (6, 1, 1),   # corner click lands on a mine
    (16, 1, 5),  # edge click lands on a mine
    (6, 5, 5),   # center click lands on a mine
])
def test_first_open_on_a_mine_relocates_it(seed, x, y):
    s = eng.new_game(seed, 9, 9, 10)
    assert (x, y) in s.mines  # fixture sanity: first click lands on a mine
    out = eng.open_cell(s, x, y)
    assert out is not None
    assert out.status != "lost"
    assert (x, y) in out.opened and (x, y) not in out.mines
    assert out.first_done is True
    moved = out.mines - (s.mines - {(x, y)})
    assert len(moved) == 1
    exp_new = next(c for c in ref_cells(9, 9)
                   if c not in (s.mines - {(x, y)}) and c != (x, y))
    assert moved == {exp_new}  # first row-major non-mine cell, not the clicked one
    assert out.adj == ref_adj(out.mines, 9, 9)  # adjacency recomputed


def test_first_open_on_safe_cell_does_not_relocate():
    s = eng.new_game(1, 9, 9, 10)
    safe = next(c for c in ref_cells(9, 9) if c not in s.mines)
    out = eng.open_cell(s, *safe)
    assert out is not None and out.mines == s.mines and out.adj == s.adj
    assert out.first_done is True and (safe) in out.opened


def test_second_open_on_a_mine_does_not_relocate():
    s = eng.new_game(1, 9, 9, 10)
    safe = next(c for c in ref_cells(9, 9) if c not in s.mines)
    first = eng.open_cell(s, *safe)
    mine = next(c for c in ref_cells(9, 9) if c in first.mines)
    out = eng.open_cell(first, *mine)
    assert out.status == "lost"
    assert out.mines == first.mines  # no relocation after the first reveal
    assert mine not in out.opened


# ---------- M6: reveal semantics

def test_open_number_reveals_only_itself():
    s = eng.new_game(1, 9, 9, 10)
    # (6,1) is a safe cell with adj==1 on this pinned field.
    assert (6, 1) not in s.mines and s.adj[0][5] == 1
    out = eng.open_cell(s, 6, 1)
    assert out is not None
    assert out.opened == frozenset({(6, 1)})
    assert out.status == "playing" and out.first_done is True


def test_open_zero_floods_region_with_numeric_border():
    # Pinned 6x6/4 field (seed 2): flood from (1,1) covers the zero region plus
    # its numeric border; (5,1), (6,2), (6,3) are safe cells that must stay closed.
    s = eng.new_game(2, 6, 6, 4)
    assert s.mines == frozenset({(4, 1), (5, 2), (6, 1), (6, 4)})
    assert s.adj[0][0] == 0
    out = eng.open_cell(s, 1, 1)
    exp = ref_reveal(s.mines, s.adj, 6, 6, (1, 1))
    assert out.opened == frozenset(exp)
    assert any(out.adj[y - 1][x - 1] > 0 for (x, y) in out.opened)  # border opened
    remaining = set(ref_cells(6, 6)) - out.opened - s.mines
    assert remaining == {(5, 1), (6, 2), (6, 3)}  # flood must NOT cover the board
    assert out.status == "playing"


def test_open_mine_loses_and_keeps_mine_out_of_opened():
    s = eng.new_game(1, 9, 9, 10)
    safe = next(c for c in ref_cells(9, 9) if c not in s.mines)
    mid = eng.open_cell(s, *safe)  # first open is safe by M5
    mine = next(iter(sorted(mid.mines)))
    out = eng.open_cell(mid, *mine)
    assert out.status == "lost"
    assert mine not in out.opened
    assert eng.is_lost(out) and not eng.is_won(out)
    assert out.first_done is True


def test_reopen_opened_cell_returns_none_state_unchanged():
    s = eng.new_game(1, 9, 9, 10)
    safe = next(c for c in ref_cells(9, 9) if c not in s.mines)
    one = eng.open_cell(s, *safe)
    before = snapshot(one)
    assert eng.open_cell(one, *safe) is None
    assert snapshot(one) == before


def test_open_on_flagged_cell_returns_none():
    s = eng.new_game(1, 9, 9, 10)
    safe = next(c for c in ref_cells(9, 9) if c not in s.mines)
    fl = eng.toggle_flag(s, *safe)
    assert eng.open_cell(fl, *safe) is None


@pytest.mark.parametrize("x,y", [(0, 1), (10, 1), (1, 10), (0, 0), (10, 10), (-3, 4)])
def test_open_out_of_field_returns_none(x, y):
    s = eng.new_game(1, 9, 9, 10)
    assert eng.open_cell(s, x, y) is None


def test_game_over_blocks_all_moves():
    s = eng.new_game(1, 9, 9, 10)
    safe = next(c for c in ref_cells(9, 9) if c not in s.mines)
    mid = eng.open_cell(s, *safe)
    mine = next(iter(sorted(mid.mines)))
    lost = eng.open_cell(mid, *mine)
    assert lost.status == "lost"
    assert eng.open_cell(lost, 2, 2) is None
    assert eng.open_cell(lost, *mine) is None  # re-open the mine itself
    assert eng.toggle_flag(lost, 3, 3) is None


# ---------- M6 win condition

def test_win_without_flags():
    # Pinned 3x3 field (seed 5): single mine at CENTER -> no zero cells, no
    # floods; every safe cell must be opened explicitly. No flags placed.
    s = eng.new_game(5, 3, 3, 1)
    cur = s
    for c in ref_cells(3, 3):
        if c in cur.mines or c in cur.opened:
            continue
        cur = eng.open_cell(cur, *c)
        assert cur is not None
        unopened = {cc for cc in ref_cells(3, 3)
                    if cc not in cur.mines and cc not in cur.opened}
        if unopened:
            assert cur.status == "playing" and not eng.is_won(cur)
    assert cur.status == "won" and eng.is_won(cur) and not eng.is_lost(cur)
    assert cur.flagged == frozenset()  # won WITHOUT any flags
    assert eng.open_cell(cur, 1, 1) is None and eng.toggle_flag(cur, 3, 1) is None


def test_win_with_zero_mines_on_first_open():
    s = eng.new_game(4, 4, 4, 0)
    out = eng.open_cell(s, 2, 2)
    assert out is not None and out.status == "won" and eng.is_won(out)
    assert out.opened == frozenset(ref_cells(4, 4))


def test_is_won_is_lost_are_predicates_on_status():
    s = eng.new_game(1, 9, 9, 10)
    assert not eng.is_won(s) and not eng.is_lost(s)
    safe = next(c for c in ref_cells(9, 9) if c not in s.mines)
    mid = eng.open_cell(s, *safe)
    assert not eng.is_won(mid) and not eng.is_lost(mid)
    lost = eng.open_cell(mid, *next(iter(sorted(mid.mines))))
    assert eng.is_lost(lost) and not eng.is_won(lost)


# ---------- M7: flags

def test_flag_toggle_on_then_off():
    s = eng.new_game(1, 9, 9, 10)
    closed = next(c for c in ref_cells(9, 9) if c not in s.mines)
    on = eng.toggle_flag(s, *closed)
    assert on is not None and closed in on.flagged
    assert on.opened == s.opened and on.mines == s.mines and on.status == "playing"
    off = eng.toggle_flag(on, *closed)
    assert off is not None and off.flagged == frozenset()
    assert snapshot(off)[:6] == snapshot(s)[:6]


def test_flag_on_mine_cell_is_allowed():
    s = eng.new_game(1, 9, 9, 10)
    mine = next(iter(sorted(s.mines)))
    on = eng.toggle_flag(s, *mine)
    assert on is not None and on.flagged == frozenset({mine})


def test_flag_on_opened_cell_returns_none():
    s = eng.new_game(1, 9, 9, 10)
    safe = next(c for c in ref_cells(9, 9) if c not in s.mines)
    opened = eng.open_cell(s, *safe)
    assert eng.toggle_flag(opened, *safe) is None


@pytest.mark.parametrize("x,y", [(0, 0), (10, 10), (0, 5), (5, 0)])
def test_flag_out_of_field_returns_none(x, y):
    s = eng.new_game(1, 9, 9, 10)
    assert eng.toggle_flag(s, x, y) is None
