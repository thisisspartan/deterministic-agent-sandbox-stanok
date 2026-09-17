'use strict';

const MAX_HEAT = 255;
const LOSS = 1;

function mulberry32(seed) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function createModel(cols, rows, seed) {
  const grid = Array.from({ length: rows }, () => new Array(cols).fill(0));
  return { cols, rows, grid, rand: mulberry32(seed) };
}

function step(model) {
  const { cols, rows, grid, rand } = model;
  // 1. bottom row: random fire source
  for (let x = 0; x < cols; x++) {
    grid[rows - 1][x] = Math.floor(rand() * 256);
  }
  // 2. every other cell, top to bottom-1 (use a fresh buffer so neighbors are
  //    read from the previous frame)
  const next = Array.from({ length: rows }, () => new Array(cols));
  for (let y = 0; y < rows - 1; y++) {
    for (let x = 0; x < cols; x++) {
      const left = x > 0 ? grid[y][x - 1] : 0;
      const right = x < cols - 1 ? grid[y][x + 1] : 0;
      const below = grid[y + 1][x];
      const self = grid[y][x];
      const v = Math.max(0, Math.floor((left + right + below + self) / 4) - LOSS);
      next[y][x] = Math.min(MAX_HEAT, Math.max(0, v));
    }
  }
  // 3. bottom row already set; copy next into grid for rows 0..rows-2
  for (let y = 0; y < rows - 1; y++) {
    grid[y] = next[y];
  }
  return model;
}

// monotonic heat -> 256-color index: black(0) -> red(~196) -> orange(~208)
// -> yellow(~220) -> white(~230) -> 255
const RAMP_STOPS = [
  [0, 0],
  [48, 196],
  [96, 208],
  [144, 220],
  [192, 230],
  [255, 255],
];

function heatToColor(heat) {
  if (heat <= 0) return 0;
  if (heat >= MAX_HEAT) return 255;
  for (let i = 1; i < RAMP_STOPS.length; i++) {
    if (heat <= RAMP_STOPS[i][0]) {
      const [h0, c0] = RAMP_STOPS[i - 1];
      const [h1, c1] = RAMP_STOPS[i];
      return Math.round(c0 + ((heat - h0) * (c1 - c0)) / (h1 - h0));
    }
  }
  return 255;
}

function renderFrame(model) {
  const { cols, rows, grid } = model;
  const lines = new Array(rows);
  for (let y = 0; y < rows; y++) {
    let line = '';
    for (let x = 0; x < cols; x++) {
      line += '\x1b[38;5;' + heatToColor(grid[y][x]) + 'm\u2588';
    }
    lines[y] = line;
  }
  return lines;
}

function createApp() {
  return { main };
}

function main() {
  const cols = parseInt(process.env.COLUMNS || '80', 10);
  const rows = parseInt(process.env.LINES || '24', 10);
  const seed = parseInt(process.env.FIRE_SEED || '42', 10);
  const model = createModel(cols, rows, seed);

  if (process.stdout.isTTY) {
    process.stdout.write('\x1b[?1049h\x1b[?25l');
    const cleanup = () => {
      process.stdout.write('\x1b[?25h\x1b[?1049h');
      process.exit(0);
    };
    process.on('SIGINT', cleanup);
    const tick = () => {
      step(model);
      process.stdout.write('\x1b[H' + renderFrame(model).join('\n'));
      setTimeout(tick, 40); // ~25 FPS
    };
    tick();
  } else {
    // Headless: exactly 10 frames, one \n per frame, then exit.
    let out = '';
    for (let i = 0; i < 10; i++) {
      step(model);
      out += renderFrame(model).join('\n') + '\n';
    }
    process.stdout.write(out);
    process.exit(0);
  }
}

if (require.main === module) {
  main();
}

module.exports = { MAX_HEAT, mulberry32, createModel, step, renderFrame, heatToColor, createApp, main };
