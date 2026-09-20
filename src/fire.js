'use strict';
// fire.js — a realistic burning flame rendered in the terminal.
//
// Four separated concerns:
//   1. Simulation — 2D heat-field grid, ticked by pure functions (seeded).
//   2. Palette    — heat value [0,1] -> 24-bit truecolor ANSI SGR string.
//   3. Renderer   — field -> one ANSI frame string (half-block ▀, 2 lines per row).
//   4. Loop       — IO only; runs ONLY when executed as main.
//
// Zero dependencies (node built-ins only), CommonJS.
//
//   node src/fire.js          — run the animation (Ctrl-C stops it cleanly)

// ---------------------------------------------------------------------------
// 1. Deterministic randomness: seeded PRNG + value noise
// ---------------------------------------------------------------------------

// mulberry32 — small fast seeded PRNG, returns floats in [0, 1).
function createRng(seed) {
  let a = seed >>> 0;
  return function next() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// 3D value noise: lattice of random values (from a seeded PRNG),
// smoothstep interpolation. Returns values in [0, 1].
function makeValueNoise(rng) {
  const table = new Float32Array(512);
  for (let i = 0; i < 512; i++) table[i] = rng();

  function lat(ix, iy, iz) {
    let h = (Math.imul(ix, 374761393) ^
             Math.imul(iy, 668265263) ^
             Math.imul(iz, 1440662683)) >>> 0;
    h = (h ^ (h >>> 13)) >>> 0;
    return table[h & 511];
  }
  const fade = (t) => t * t * (3 - 2 * t);
  const lerp = (a, b, t) => a + (b - a) * t;

  return function noise3(x, y, z) {
    const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z);
    const u = fade(x - xi), v = fade(y - yi), w = fade(z - zi);
    const x00 = lerp(lat(xi, yi, zi), lat(xi + 1, yi, zi), u);
    const x10 = lerp(lat(xi, yi + 1, zi), lat(xi + 1, yi + 1, zi), u);
    const x01 = lerp(lat(xi, yi, zi + 1), lat(xi + 1, yi, zi + 1), u);
    const x11 = lerp(lat(xi, yi + 1, zi + 1), lat(xi + 1, yi + 1, zi + 1), u);
    return lerp(lerp(x00, x10, v), lerp(x01, x11, v), w);
  };
}

// ---------------------------------------------------------------------------
// Simulation: 2D heat field, normalized to [0, 1]
// ---------------------------------------------------------------------------

function createField(cols, rows, seed = 1337) {
  const rng = createRng(seed >>> 0);
  return {
    cols,
    rows,
    heat: new Float32Array(cols * rows),
    smoke: new Float32Array(cols * rows),
    noise: makeValueNoise(rng),
    tickCount: 0,
  };
}

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

// Advance the field by one tick (pure w.r.t. its inputs: field + its state).
// Heat is injected at the base, diffuses upward, cools per row, and is
// perturbed by turbulence (value noise) so the flame sways and licks.
function tick(field) {
  const { cols: W, rows: H, heat, noise } = field;
  const t = field.tickCount++;
  const next = new Float32Array(W * H);
  const cx = (W - 1) / 2;

  // Flicker: slow global intensity noise, 0.85..1.0 per frame.
  const flicker = 0.85 + 0.15 * noise(t * 0.11, 7.3, 2.1);
  // Flame base: wide, width wobbles over time (not a static cone).
  const baseHalf = W * (0.16 + 0.05 * noise(t * 0.13, 4.5, 9.2));

  for (let y = 0; y < H; y++) {
    const fromBottom = H - 1 - y;
    for (let x = 0; x < W; x++) {
      let h = 0;
      const below = y + 1;
      if (below < H) {
        // Turbulence: sample the row below with a per-cell noisy offset
        // so the flame sways and licks.
        const sway = Math.round((noise(x * 0.22, t * 0.17, y * 0.05) - 0.5) * 4);
        const x0 = clamp(x + sway, 0, W - 1);
        const xL = clamp(x + sway - 1, 0, W - 1);
        const xR = clamp(x + sway + 1, 0, W - 1);
        h = (heat[below * W + x0] + heat[below * W + xL] + heat[below * W + xR]) / 3;
        // Cooling: heat decays as it rises (flame tapers upward).
        h *= 0.85;
      }
      if (y === H - 1) {
        // Base injection: hot, with a noisy ragged edge.
        const edge = baseHalf + (noise(x * 0.3, t * 0.29, 1.1) - 0.5) * 4;
        if (Math.abs(x - cx) <= edge) h = Math.max(h, 1);
      }
      next[y * W + x] = clamp(h * flicker, 0, 1);
    }
  }

  // Smoke: faint particles above the flame — only where a hot column
  // feeds the cell from below (within a few rows of flame height) and the
  // noise field invites a puff.
  const smokeNext = new Float32Array(W * H);
  for (let y = 0; y < H; y++) {
    if (H - 1 - y < H * 0.45) continue; // smoke zone: upper 45% only
    for (let x = 0; x < W; x++) {
      const h = next[y * W + x];
      if (h >= 0.12) continue;
      let belowHeat = 0;
      for (let dy = 1; dy <= 12 && y + dy < H; dy++) {
        belowHeat = Math.max(belowHeat, next[(y + dy) * W + x]);
      }
      if (belowHeat <= 0.25) continue;
      const n = noise(x * 0.35, y * 0.35, t * 0.21);
      if (n > 0.62) {
        smokeNext[y * W + x] = 0.15 + 0.5 * (n - 0.62) / 0.38;
      }
    }
  }

  field.heat = next;
  field.smoke = smokeNext;
  return field;
}

// ---------------------------------------------------------------------------
// 2. Palette: heat [0,1] -> 24-bit truecolor ANSI SGR (or ' ' for zero)
// ---------------------------------------------------------------------------

// Multi-stop gradient, hot -> cool:
//   white-hot core -> yellow -> orange -> red -> dark red -> (zero: empty)
const STOPS = [
  { h: 1.0,  c: [255, 255, 255] }, // white-hot core
  { h: 0.75, c: [255, 214, 80]  }, // yellow
  { h: 0.5,  c: [255, 120, 20]  }, // orange
  { h: 0.3,  c: [215, 45, 10]   }, // red
  { h: 0.15, c: [120, 12, 5]    }, // dark red
  { h: 0.05, c: [45, 4, 2]      }, // embers
  { h: 0.0,  c: [0, 0, 0]       },
];

function palette(h) {
  if (h <= 0) return ' ';
  if (h >= 1) h = 1;
  let i = 0;
  while (i < STOPS.length - 1 && STOPS[i + 1].h >= h) i++;
  const top = STOPS[i];
  const bot = STOPS[i + 1] || top;
  const span = top.h - bot.h || 1;
  const f = (top.h - h) / span;
  const r = Math.round(top.c[0] + (bot.c[0] - top.c[0]) * f);
  const g = Math.round(top.c[1] + (bot.c[1] - top.c[1]) * f);
  const b = Math.round(top.c[2] + (bot.c[2] - top.c[2]) * f);
  return `\x1b[38;2;${r};${g};${b} m`;
}

// Faint gray smoke color, intensity in [0, 1].
function smokeColor(s) {
  const v = Math.round(30 + 70 * clamp(s, 0, 1));
  return `\x1b[38;2;${v};${v};${v} m`;
}

// ---------------------------------------------------------------------------
// 3. Renderer: field -> one ANSI frame string
// ---------------------------------------------------------------------------

// Half-block (▀) rendering: each grid row becomes 2 terminal rows, so the
// frame is rows*2 lines, each line exactly `cols` characters long.
function renderFrame(field) {
  const { cols: W, rows: H, heat, smoke } = field;
  const lines = new Array(2 * H);
  for (let y = 0; y < H; y++) {
    const top = new Array(W);
    const bot = new Array(W);
    for (let x = 0; x < W; x++) {
      const h = heat[y * W + x];
      const s = smoke[y * W + x];
      const cell = h > 0 ? '▀' : s > 0 ? '▀' : ' ';
      const color = h > 0 ? palette(h) : s > 0 ? smokeColor(s) : ' ';
      top[x] = cell === ' ' ? ' ' : color + '▀';
      bot[x] = top[x];
    }
    lines[2 * y] = top.join('');
    lines[2 * y + 1] = bot.join('');
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 4. Loop: IO only — runs only when executed as main
// ---------------------------------------------------------------------------

function run() {
  // Headless (piped stdout, e.g. `run.sh smoke`) never animates.
  if (!process.stdout.isTTY) return;
  const termW = (process.stdout.columns && process.stdout.columns > 0) ? process.stdout.columns : 80;
  const termH = (process.stdout.rows && process.stdout.rows > 0) ? process.stdout.rows : 24;
  const cols = Math.max(10, termW - 4);
  const rows = Math.max(5, Math.floor((termH - 2) / 2));

  const field = createField(cols, rows);
  for (let i = 0; i < 12; i++) tick(field); // pre-warm so the flame is already lit

  const padLeft = Math.max(0, Math.floor((termW - cols) / 2));
  const frameLines = 2 * rows;
  const padTop = Math.max(0, Math.floor((termH - frameLines) / 2));
  const prefix = '\x1b[2J\x1b[H' +
    Array(padTop).fill(' '.repeat(padLeft) + ' '.repeat(cols)).join('\n') + '\n';
  const pad = ' '.repeat(padLeft);

  process.stdout.write('\x1b[?25l'); // hide cursor

  const timer = setInterval(() => {
    tick(field);
    const body = renderFrame(field)
      .split('\n')
      .map((l) => pad + l)
      .join('\n');
    process.stdout.write(prefix + body);
  }, 33); // ~30 FPS

  process.on('SIGINT', () => {
    clearInterval(timer);
    process.stdout.write('\x1b[?25h\x1b[0m\n'); // restore cursor, reset ANSI
    process.exit(0);
  });
}

if (require.main === module) run();

module.exports = { createRng, makeValueNoise, createField, tick, palette, smokeColor, renderFrame, run };
