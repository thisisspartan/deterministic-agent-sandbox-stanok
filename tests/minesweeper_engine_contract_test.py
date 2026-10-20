"""Calibrated contract oracle for src/minesweeper_engine.py (SPEC-MINESWEEPER-CONSOLE M1..M7).

Independence policy: every expected value here is re-derived from an
independent reference implementation of the pinned rules written in this
file (own placement RNG walk, own adjacency, own flood) or hand-pinned
fixtures — never captured from the engine under test. Mutants EM1..EM8
(see specs/STATUS.md) must each turn at least one test RED; the reference
lab build must be all-GREEN. Host-authored; machine must not edit.
"""
import dataclasses
import random

import pytest

try:
    from src import minesweeper_engine as eng
except ImportError:
    import minesweeper_engine as eng


# ---------- independent reference helpers (independent of engine under test)

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


def ref_reveal(mines, adj, start):
    """M6 expected opened set from opening `start` (start assumed non-mine)."""
    h, w = len(adj), len(adj[0])
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
    for z in list(opened):  # numeric border via 8-neighborhood of any revealed zero
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = z[0] + dx, z[1] + dy
                if 1 <= nx <= w and 1 <= ny <= h and (nx, ny) not in mines:
                    opened.add((nx, ny))
    return opened


def st(seed=1, w=9, h=9, n=10):
    return eng.new_game(seed, w, h, n)


# ---------- M1/M2 API surface, frozen, purity

def test_api_names_exist():
    for name in ("new_game", "open_cell", "toggle_flag", "is_won", "is_lost"):
        assert callable(getattr(eng, name)), name


def test_state_is_frozen_with_pinned_fields():
    s = st()
    assert isinstance(s, type(eng.new_game(1, 9, 9, 10)))
    fields = {f.name for f in dataclasses.fields(s)}
    assert {"seed", "width", "height", "mines_total", "mines", "adj",
            "opened", "flagged", "status", "first_done"} <= fields
    assert s.status == "playing" and s.first_done is False
    assert isinstance(s.mines, frozenset) and isinstance(s.opened, frozenset)
    assert isinstance(s.flagged, frozenset)
    assert isinstance(s.adj, tuple) and all(isinstance(r, tuple) for r in s.adj)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.status = "won"


def test_operations_do_not_mutate_input_state():
    s = st(seed=3)
    snap = (s.mines, s.adj, s.opened, s.flagged, s.status, s.first_done)
    out = eng.toggle_flag(s, 1, 1)
    out2 = eng.open_cell(out, 2, 2)
    assert (s.mines, s.adj, s.opened, s.flagged, s.status, s.first_done) == snap
    if out2 is not None:
        assert out2 is not s and out2 is not out


# ---------- M3 placement: validation, determinism, field legality

@pytest.mark.parametrize("w,h,n", [
    (0, 5, 1), (5, 0, 1), (-1, 5, 1), (65, 1, 1), (1, 33, 1),
    (5, 5, -1), (3, 3, 9), (2, 2, 4),
])
def test_bad_new_game_raises_value_error(w, h, n):
    with pytest.raises(ValueError):
        eng.new_game(1, w, h, n)


def test_boundary_sizes_accepted():
    s = eng.new_game(1, 64, 32, 64 * 32 - 1)
    assert s.mines_total == 64 * 32 - 1
    s0 = eng.new_game(1, 1, 1, 0)
    assert s0.mines_total == 0


def test_same_seed_identical_different_seed_differs():
    a, b = st(seed=42), st(seed=42)
    assert a.mines == b.mines and a.adj == b.adj
    assert st(seed=7).mines != st(seed=8).mines


def test_mines_legal_and_match_reference_placement():
    for seed, w, h, n in ((1, 9, 9, 10), (13, 16, 16, 40), (20, 30, 16, 99)):
        s = eng.new_game(seed, w, h, n)
        exp = ref_mines(seed, w, h, n)
        assert s.mines == exp, f"placement mismatch seed={seed}"
        assert len(s.mines) == n
        assert all(1 <= x <= w and 1 <= y <= h for x, y in s.mines)
        assert s.adj == ref_adj(exp, w, h)


# ---------- M5 safe first open (corner / edge / center)

@pytest.mark.parametrize("x,y", [(1, 1), (1, 5), (5, 5)])
def test_first_open_is_always_safe(x, y):
    seed = next(sd for sd in range(1, 500)
                if (x, y) in ref_mines(sd, 9, 9, 10))
    s = eng.new_game(seed, 9, 9, 10)
    assert (x, y) in s.mines  # fixture sanity: first click lands on a mine
    out = eng.open_cell(s, x, y)
    assert out is not None and out.status != "lost"
    assert (x, y) in out.opened and (x, y) not in out.mines
    assert out.first_done is True
    moved = out.mines - (s.mines - {(x, y)})
    assert len(moved) == 1
    exp_new = next(c for c in ref_cells(out.width, out.height)
                   if c not in (s.mines - {(x, y)}) and c != (x, y))
    assert moved == {exp_new}
    assert out.adj == ref_adj(out.mines, 9, 9)


def test_second_open_does_not_relocate():
    s = st(seed=1)
    safe = next(c for c in ref_cells(9, 9) if c not in s.mines)
    first = eng.open_cell(s, *safe)
    mine_cell = next(c for c in ref_cells(9, 9) if c in first.mines
                     and c not in first.opened)
    out = eng.open_cell(first, *mine_cell)
    assert out.status == "lost"
    assert out.mines == first.mines  # no relocation after the first reveal


# ---------- M6 reveal semantics

def test_open_number_reveals_only_itself():
    s = st(seed=1)
    safe = next(c for c in ref_cells(9, 9)
                if c not in s.mines
                and s.adj[c[1] - 1][c[0] - 1] > 0
                and c not in s.mines)
    out = eng.open_cell(s, *safe)
    exp = ref_reveal(s.mines, s.adj, safe)
    assert out.opened == frozenset(exp)
    assert out.status == "playing"
    assert out.opened == frozenset({safe})


def test_open_zero_floods_region_with_numeric_border():
    # 6x6/4 mines: first row-major zero cell whose flood is partial (some safe
    # cells stay closed). Expected opened set re-derived independently.
    seed = None
    for sd in range(1, 5000):
        m = ref_mines(sd, 6, 6, 4)
        a = ref_adj(m, 6, 6)
        if (1, 1) in m or a[0][0] != 0:
            continue
        safe = {(x, y) for x in range(1, 7) for y in range(1, 7)} - m
        exp = ref_reveal(m, a, (1, 1))
        if exp < safe and any(a[y - 1][x - 1] > 0 for (x, y) in exp):
            seed = sd
            break
    assert seed is not None
    s = eng.new_game(seed, 6, 6, 4)
    out = eng.open_cell(s, 1, 1)
    exp = ref_reveal(s.mines, s.adj, (1, 1))
    assert out.opened == frozenset(exp)
    assert any(out.adj[y - 1][x - 1] > 0 for (x, y) in out.opened)  # numeric border
    remaining = {(x, y) for x in range(1, 7) for y in range(1, 7)} \
        - set(out.opened) - s.mines
    assert remaining  # flood must NOT cover the whole board
    assert out.status == "playing"


def test_open_mine_loses_and_keeps_mine_out_of_opened():
    s = st(seed=1)
    # safe first open first (M5 makes the very first open safe by design),
    # THEN step onto a mine.
    safe = next(c for c in ref_cells(9, 9) if c not in s.mines)
    mid = eng.open_cell(s, *safe)
    mine = next(iter(sorted(mid.mines)))
    out = eng.open_cell(mid, *mine)
    assert out.status == "lost"
    assert mine not in out.opened
    assert eng.is_lost(out) and not eng.is_won(out)
    assert eng.open_cell(out, 2, 2) is None
    assert eng.toggle_flag(out, 3, 3) is None
    # re-open the same mine: already terminated
    assert eng.open_cell(out, *mine) is None


def test_invalid_opens_return_none_without_state_change():
    s = st(seed=1)
    assert eng.open_cell(s, 0, 1) is None
    assert eng.open_cell(s, 10, 1) is None
    assert eng.open_cell(s, 1, 10) is None
    safe = next(c for c in ref_cells(9, 9) if c not in s.mines)
    one = eng.open_cell(s, *safe)
    assert eng.open_cell(one, *safe) is None  # already opened -> None, no change
    fl = eng.toggle_flag(one, *next(c for c in ref_cells(9, 9)
                                   if c not in one.opened and c not in one.mines))
    assert eng.open_cell(fl, *next(iter(sorted(fl.flagged)))) is None


# ---------- M7 flags

def test_flag_toggle_on_off_and_negatives():
    s = st(seed=1)
    closed = next(c for c in ref_cells(9, 9) if c not in s.mines)
    on = eng.toggle_flag(s, *closed)
    assert closed in on.flagged and on.opened == s.opened
    off = eng.toggle_flag(on, *closed)
    assert off.flagged == frozenset()
    safe_open = eng.open_cell(s, *closed)
    assert eng.toggle_flag(safe_open, *closed) is None  # flag an open cell
    assert eng.toggle_flag(s, 0, 0) is None
    assert eng.toggle_flag(s, 10, 10) is None


# ---------- win condition

def test_win_without_flags():
    # fixture: 3x3 with the single mine in the CENTER -> no zero cells, no
    # floods; every safe cell must be opened explicitly. No flags placed.
    seed = next(sd for sd in range(1, 10000) if ref_mines(sd, 3, 3, 1) == {(2, 2)})
    s = eng.new_game(seed, 3, 3, 1)
    cur = s
    for c in ref_cells(3, 3):
        if c in cur.mines or c in cur.opened:
            continue
        cur = eng.open_cell(cur, *c)
        assert cur is not None
        unopened = {cc for cc in ref_cells(3, 3)
                    if cc not in cur.mines and cc not in cur.opened}
        if unopened:
            assert cur.status == "playing"
    assert cur.status == "won" and eng.is_won(cur) and not eng.is_lost(cur)
    assert cur.flagged == frozenset()  # won WITHOUT any flags
    assert eng.open_cell(cur, 1, 1) is None and eng.toggle_flag(cur, 3, 1) is None


def test_win_with_zero_mines_on_first_open():
    s = eng.new_game(4, 4, 4, 0)
    out = eng.open_cell(s, 2, 2)
    assert out is not None and out.status == "won"
    assert out.opened == frozenset(ref_cells(4, 4))
