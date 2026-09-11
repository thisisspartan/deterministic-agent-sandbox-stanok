'use strict';

// Fire app entry point: `node src/main.js`.
//
// Reads configuration from the environment, then runs the fire animation in
// one of two modes:
//   - TTY: alternate-screen ANSI256 rendering, animated forever; Ctrl+C / SIGTERM
//     restores the terminal and exits 0.
//   - headless: prints FIRE_FRAMES symbol frames (one per line-block) then exits 0;
//     SIGINT / SIGTERM exits 0 early.
//
// The main loop runs ONLY when this file is the entry point
// (`require.main === module`), so tests can `require` it without side effects.

const { createModel, step } = require('./fire_model');
const { renderFrame } = require('./fire_render');

// Switch into the terminal alternate screen and hide the cursor.
function enterTerminal() {
  return '\x1b[?1049h\x1b[?25l';
}

// Restore the cursor and switch back to the primary screen.
function leaveTerminal() {
  return '\x1b[?25h\x1b[?1049l';
}

// Read a positive integer from the environment, falling back to a default.
function envInt(name, fallback) {
  const value = parseInt(process.env[name], 10);
  return Number.isFinite(value) ? value : fallback;
}

// Yield to the event loop for `ms` milliseconds (keeps signal handling alive).
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function main() {
  const seed = envInt('FIRE_SEED', 1337);
  const fps = envInt('FIRE_FPS', 25);
  const frames = envInt('FIRE_FRAMES', 50);
  const headless = process.env.STANOK_HEADLESS === '1' || !process.stdout.isTTY;

  // Register signal handlers BEFORE starting the loop.
  const onSignal = () => {
    if (!headless) {
      process.stdout.write(leaveTerminal());
    }
    process.exit(0);
  };
  process.on('SIGINT', onSignal);
  process.on('SIGTERM', onSignal);

  let state = createModel({ seed });

  if (headless) {
    (async () => {
      for (let i = 0; i < frames; i++) {
        state = step(state);
        const frame = renderFrame(state, { mode: 'symbols' });
        process.stdout.write(frame + '\n\n');
        await sleep(1000 / fps);
      }
      process.exit(0);
    })();
  } else {
    process.stdout.write(enterTerminal());
    (async () => {
      for (;;) {
        state = step(state);
        const frame = renderFrame(state, { mode: 'ansi256' });
        process.stdout.write('\x1b[H' + frame);
        await sleep(1000 / fps);
      }
    })();
  }
}

if (require.main === module) {
  main();
}

module.exports = { enterTerminal, leaveTerminal };
