# fire

Infinite terminal fire animation (classic Doom-fire effect). Heat rises from a
randomized bottom row, decays as it spreads upward, and is rendered as
ANSI-256-colored `█` cells on the alternate screen at ~25 FPS. Run it with
`node src/fire.js` in a real terminal; press Ctrl-C to stop and restore the
screen. Configuration via environment variables: `COLUMNS` (default 80),
`LINES` (default 24), `FIRE_SEED` (default 42). When stdout is not a TTY the
app renders exactly 10 frames and exits.
