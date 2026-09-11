# main.js

Entry point for the fire app. Runs the simulation/animation loop on top of
`src/fire_model.js` (`createModel`, `step`) and `src/fire_render.js`
(`renderFrame`). Uses only built-in Node.js modules.

## How to run

```sh
node src/main.js
```

The loop starts only when the file is executed directly
(`require.main === module`), so it can be `require`d by tests without side
effects.

## Env vars

| Var               | Default | Meaning                                          |
| ----------------- | ------- | ------------------------------------------------ |
| `FIRE_SEED`       | `1337`  | PRNG seed handed to `createModel`.               |
| `FIRE_FPS`        | `25`    | Frames per second; sleep is `1000 / FIRE_FPS` ms. |
| `FIRE_FRAMES`     | `50`    | Number of frames rendered in headless mode.      |
| `STANOK_HEADLESS` | —       | `'1'` forces headless mode.                      |

## TTY vs headless

- **Headless** when `STANOK_HEADLESS === '1'` OR `!process.stdout.isTTY`
  (e.g. when stdout is a pipe).
  - Loops `FIRE_FRAMES` times: `state = step(state)`, render in `symbols`
    mode, write `frame + '\n\n'` to stdout, sleep `1000 / FIRE_FPS` ms.
  - Then `process.exit(0)`. Output contains no ANSI escape bytes.
- **TTY** otherwise.
  - Writes `enterTerminal()` to stdout, then loops forever: `state = step(state)`,
    render in `ansi256` mode, write `'\x1b[H' + frame` (home cursor + frame),
    sleep `1000 / FIRE_FPS` ms.

## Ctrl+C (and SIGTERM) behavior

`SIGINT`/`SIGTERM` handlers are registered **before** the loop starts.

- **Headless:** the process exits with code `0`.
- **TTY:** `leaveTerminal()` is written to stdout, then the process exits
  with code `0`.

## Exports

- `enterTerminal()` → `'\x1b[?1049h\x1b[?25l'` (alternate screen + hide cursor).
- `leaveTerminal()` → `'\x1b[?25h\x1b[?1049l'` (show cursor + leave alt screen).
