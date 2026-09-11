# main — Fire app entry point

Run with:

```sh
node src/main.js
```

The main loop runs only when `main.js` is the entry point (`require.main ===
module`), so it can be `require`d by tests without side effects.

## Environment variables

| Variable          | Default | Meaning                                            |
|-------------------|---------|----------------------------------------------------|
| `FIRE_SEED`       | `1337`  | PRNG seed → deterministic fire.                    |
| `FIRE_FPS`        | `25`    | Frame rate; sleep per frame is `1000 / FIRE_FPS` ms. |
| `FIRE_FRAMES`     | `50`    | Number of frames to render in headless mode.       |
| `STANOK_HEADLESS` | —       | `'1'` forces headless mode.                        |

## TTY vs headless

Headless is active when `STANOK_HEADLESS === '1'` **or** `process.stdout.isTTY`
is falsy (e.g. when stdout is a pipe, as under the test runner).

- **TTY mode** — writes `enterTerminal()` to stdout once, then loops forever:
  `state = step(state)`; render `renderFrame(state, { mode: 'ansi256' })`;
  write `'\x1b[H' + frame` (cursor home + overwrite); sleep `1000 / FIRE_FPS` ms.
- **Headless mode** — loops `FIRE_FRAMES` times: `state = step(state)`;
  render `renderFrame(state, { mode: 'symbols' })`; write `frame + '\n\n'`;
  sleep `1000 / FIRE_FPS` ms. After the loop it exits `0`.

## Ctrl+C / signals

`SIGINT` and `SIGTERM` handlers are registered **before** the loop starts.

- **TTY mode** — on signal, writes `leaveTerminal()` to stdout, then
  `process.exit(0)`.
- **Headless mode** — on signal, `process.exit(0)` immediately (early stop).

Both signal paths always exit with code `0`.

## Exports

- `enterTerminal()` → `'\x1b[?1049h\x1b[?25l'`
- `leaveTerminal()` → `'\x1b[?25h\x1b[?1049l'`
