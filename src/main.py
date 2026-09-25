#!/usr/bin/env python3
"""Launch script for the terminal fire (TASK-FIRE-05).

Usage:
    python3 src/main.py [--fps N] [--palette fire|blue] [--wind N|auto]

Renders the TrueColor fire in the terminal (raw ANSI, no third-party
libraries). Press ``q`` or ``Ctrl+C`` to quit; the terminal is restored
(normal screen, visible cursor, default colors) on exit.
"""

import sys

from fire.cli import FireApp, parse_args


def main(argv=None) -> int:
    """Parse the CLI, run the fire animation, return the exit code.

    Without a terminal attached (stdout is not a TTY) there is nothing to
    render: a note is written to stderr and the program exits cleanly
    (``--help`` is handled by argparse before this check).
    """
    args = parse_args(argv)
    if not sys.stdout.isatty():
        print("fire: stdout is not a terminal; nothing rendered", file=sys.stderr)
        return 0
    app = FireApp(fps=args.fps, palette_name=args.palette, wind=args.wind)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
