'use strict';

const { createModel, step } = require('./fire_model.js');
const { renderFrame } = require('./fire_render.js');

// Alternate-screen / cursor hide on enter, show-restore on leave.
function enterTerminal() {
  return '\x1b[?1049h\x1b[?25l';
}

function leaveTerminal() {
  return '\x1b[?25h\x1b[?1049l';
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Read an integer env var, falling back to `def` when unset/blank/invalid.
function envInt(name, def) {
  const raw = process.env[name];
  if (raw === undefined || raw === '') return def;
  const n = Number(raw);
  return Number.isFinite(n) ? n : def;
}

async function run() {
  const seed = envInt('FIRE_SEED', 1337);
  const fps = envInt('FIRE_FPS', 25);
  const frames = envInt('FIRE_FRAMES', 50);
  const headless = process.env.STANOK_HEADLESS === '1' || !process.stdout.isTTY;

  let state = createModel({ seed });

  let stopped = false;
  const onSignal = () => {
    if (stopped) return;
    stopped = true;
    if (!headless) {
      process.stdout.write(leaveTerminal());
    }
    process.exit(0);
  };
  // Register signal handlers BEFORE starting the loop.
  process.on('SIGINT', onSignal);
  process.on('SIGTERM', onSignal);

  const delay = 1000 / fps;

  if (headless) {
    for (let i = 0; i < frames; i++) {
      state = step(state);
      const frame = renderFrame(state, { mode: 'symbols' });
      process.stdout.write(frame + '\n\n');
      await sleep(delay);
    }
    process.exit(0);
  }

  // TTY mode: run forever until interrupted.
  process.stdout.write(enterTerminal());
  for (;;) {
    state = step(state);
    const frame = renderFrame(state, { mode: 'ansi256' });
    process.stdout.write('\x1b[H' + frame);
    await sleep(delay);
  }
}

if (require.main === module) {
  run();
}

module.exports = { enterTerminal, leaveTerminal };
