"""minesweeper_cli — console entry point of the Minesweeper game (CC-308, C1..C5).

main(argv) parses the flags, then runs the ONE stdin command loop: every
accepted state command (open/flag/new/difficulty/custom) delegates the rules
to src/minesweeper_engine and prints exactly one full frame from
src/minesweeper_render; every rejected command prints exactly one
"rejected: ..." line and never mutates the field. The CLI reimplements no
game rules and writes frames in no place other than the loop.
"""

from __future__ import annotations

import argparse
import sys

try:
    from src import minesweeper_engine as engine
    from src import minesweeper_render as rendering
except ImportError:  # direct script run: python3 src/minesweeper_cli.py
    import minesweeper_engine as engine
    import minesweeper_render as rendering

# pinned verbatim (C2 banner, C3 presets and rejection strings)
BANNER = ("commands: open X Y | flag X Y | new | difficulty beginner|medium|expert"
          " | custom W H MINES | help | quit")
PRESETS = {"beginner": (9, 9, 10), "medium": (16, 16, 40), "expert": (30, 16, 99)}

REJECT_UNKNOWN = "rejected: unknown command"
REJECT_ARGS = "rejected: bad arguments"
REJECT_RANGE = "rejected: out of range"
REJECT_ALREADY_OPEN = "rejected: already open"
REJECT_IS_FLAGGED = "rejected: cell is flagged"
REJECT_IS_OPEN = "rejected: cell is open"
REJECT_GAME_OVER = "rejected: game over"
REJECT_DIFFICULTY = "rejected: unknown difficulty"
REJECT_SIZE = "rejected: invalid size"


def _ints(tokens: list[str]) -> list[int] | None:
    try:
        return [int(token) for token in tokens]
    except ValueError:
        return None


def _emit(state: engine.GameState) -> None:
    for line in rendering.render(state):
        print(line)


def _play(seed: int) -> int:
    """C2/C3/C4: the single stdin loop, until quit or EOF; rc 0 either way."""
    games_played = 0
    config = PRESETS["beginner"]
    state = engine.new_game(seed + games_played, *config)
    print(BANNER)
    _emit(state)
    for raw in sys.stdin:
        tokens = raw.split()
        if not tokens:
            continue
        command = tokens[0]
        if command == "quit":
            return 0
        if command == "help":
            print(BANNER)
        elif command == "new":
            state = engine.new_game(seed + games_played, *config)
            games_played += 1
            _emit(state)
        elif command == "difficulty":
            if len(tokens) != 2:
                print(REJECT_ARGS)
            elif tokens[1] not in PRESETS:
                print(REJECT_DIFFICULTY)
            else:
                config = PRESETS[tokens[1]]
                state = engine.new_game(seed + games_played, *config)
                games_played += 1
                _emit(state)
        elif command == "custom":
            sizes = _ints(tokens[1:]) if len(tokens) == 4 else None
            if sizes is None:
                print(REJECT_ARGS)
            else:
                try:
                    fresh = engine.new_game(seed + games_played, *sizes)
                except ValueError:
                    print(REJECT_SIZE)
                else:
                    config = sizes
                    state = fresh
                    games_played += 1
                    _emit(state)
        elif command in ("open", "flag"):
            coords = _ints(tokens[1:]) if len(tokens) == 3 else None
            if coords is None:
                print(REJECT_ARGS)
            elif state.status != "playing":
                print(REJECT_GAME_OVER)
            elif not (1 <= coords[0] <= state.width and 1 <= coords[1] <= state.height):
                print(REJECT_RANGE)
            elif command == "open":
                cell = (coords[0], coords[1])
                if cell in state.opened:
                    print(REJECT_ALREADY_OPEN)
                elif cell in state.flagged:
                    print(REJECT_IS_FLAGGED)
                else:
                    moved = engine.open_cell(state, *coords)
                    if moved is not None:  # unreachable after the guards above
                        state = moved
                        _emit(state)
            elif (coords[0], coords[1]) in state.opened:
                print(REJECT_IS_OPEN)
            else:
                moved = engine.toggle_flag(state, *coords)
                if moved is not None:  # unreachable after the guards above
                    state = moved
                    _emit(state)
        else:
            print(REJECT_UNKNOWN)
    return 0


def main(argv: list[str]) -> int:
    """C1: flags only (--seed N, default 0); a usage error exits with rc 2."""
    parser = argparse.ArgumentParser(
        prog="minesweeper",
        description="Console Minesweeper: read commands from stdin until quit or EOF.",
    )
    parser.add_argument("--seed", type=int, default=0, help="base game seed (default: 0)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as usage_error:  # argparse already wrote the usage line to stderr
        return usage_error.code if isinstance(usage_error.code, int) else 2
    return _play(args.seed)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
