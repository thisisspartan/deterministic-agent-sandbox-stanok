'use strict';
/*
 * Terminal fire — an animated flame for the ANSI terminal.
 *
 * Four separated concerns:
 *   1. Simulation  — createSim()/tick(): a 2D heat field (seeds, deterministic).
 *   2. Palette     — palette(): heat value in [0,1] -> {r,g,b} or null (empty).
 *   3. Renderer    — renderFrame(): grid -> one ANSI frame string.
 *   4. Loop        — start(): IO only, runs ONLY when executed as main.
 *
 * Node built-ins only, CommonJS, zero dependencies.
 */

// ---------------------------------------------------------------- PRNG -----
// mulberry32: small seeded PRNG, deterministic across runs.
function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ------------------------------------------- deterministic 2-D value noise --
function hash2(i, j) {
  let h = Math.imul(i, 374761393) + Math.imul(j, 668265263);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

function smoothstep(t) {
  return t * t * (3 - 2 * t);
}

// Smooth value noise on a 2-D lattice, result in [0, 1]. Pure function of (x, y).
function valueNoise(x, y) {
  const xi = Math.floor(x);
  const yi = Math.floor(y);
  const xf = x - xi;
  const yf = y - yi;
  const a = hash2(xi, yi);
  const b = hash2(xi + 1, yi);
  const c = hash2(xi, yi + 1);
  const d = hash2(xi + 1, yi + 1);
  const u = smoothstep(xf);
  const v = smoothstep(yf);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}

// ------------------------------------------------------------ simulation ---
// state: { width, height, heat: Float32Array, smoke: Float32Array, rng, t }
// heat is normalized to [0, 1]; index = y * width + x.
function createSim(width, height, seed) {
  return {
    width: width | 0,
    height: height | 0,
    heat: new Float32Array((width | 0) * (height | 0)),
    smoke: new Float32Array((width | 0) * (height | 0)),
    rng: mulberry32(seed >>> 0 || 1),
    t: 0,
  };
}

const COOL = 0.95; // per-row cooling: makes the flame taper upward

function tick(state) {
  const W = state.width;
  const H = state.height;
  const heat = state.heat;
  const smoke = state.smoke;
  const rng = state.rng;
  const t = state.t + 1;

  const newHeat = new Float32Array(W * H);
  const newSmoke = new Float32Array(W * H);

  // Global flicker: whole flame breathes a little brighter/darker per frame.
  const flicker = 0.88 + 0.12 * valueNoise(t * 0.21, 5.7);

  // Base: wide gaussian at the bottom; its center sways and its width breathes.
  const centerX = W / 2 + (valueNoise(t * 0.23, 7.31) - 0.5) * W * 0.07;
  const sigma = W * 0.16 * (0.85 + 0.3 * valueNoise(t * 0.17, 2.93));

  const belowHeat = (y, x) =>
    y < 0 || y >= H || x < 0 || x >= W ? 0 : heat[y * W + x];

  // Diffuse heat upward; turbulence has two parts: value noise shifts the
  // sampling offset (sway), and a per-cell random walk (seeded rng) adds
  // fine flicker so the flame licks.
  for (let y = H - 1; y >= 0; y--) {
    for (let x = 0; x < W; x++) {
      const off = Math.round(
        (valueNoise(x * 0.19 + t * 0.31, y * 0.07 + 11.7) - 0.5) * 2.4
      );
      let v =
        (belowHeat(y + 1, x + off) +
          belowHeat(y + 1, x + off - 1) +
          belowHeat(y + 1, x + off + 1)) /
        3;
      v *= COOL;
      v += v * (rng() - 0.5) * 0.15; // random-walk turbulence (relative)
      newHeat[y * W + x] = v < 0 ? 0 : v > 1 ? 1 : v;
    }
  }

  // Inject heat in the bottom rows: wide base, tapering upward.
  for (let yb = 0; yb < 3; yb++) {
    const y = H - 1 - yb;
    const taper = 1 - yb * 0.35;
    for (let x = 0; x < W; x++) {
      const d = x - centerX;
      const p = Math.exp(-(d * d) / (2 * sigma * sigma)) * taper;
      const i = y * W + x;
      if (p * flicker > newHeat[i]) newHeat[i] = p * flicker;
    }
  }

  // Smoke: faint particles seeded just above each column's flame tip,
  // rising one row per tick and fading as they climb.
  const tip = new Int16Array(W).fill(H);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      if (newHeat[y * W + x] > 0.2 && y < tip[x]) tip[x] = y;
    }
  }
  for (let y = H - 1; y >= 0; y--) {
    for (let x = 0; x < W; x++) {
      const i = y * W + x;
      const s = y < H - 1 ? smoke[(y + 1) * W + x] * 0.9 : 0;
      newSmoke[i] = Math.min(0.09, s * flicker);
    }
  }
  for (let x = 0; x < W; x++) {
    if (tip[x] > 0 && tip[x] < H) {
      const i = (tip[x] - 1) * W + x;
      newSmoke[i] = Math.max(newSmoke[i], (0.05 + 0.04 * rng()) * flicker);
    }
  }

  state.heat = newHeat;
  state.smoke = newSmoke;
  state.t = t;
  return state;
}

// Grid of displayed values [0, 1] (heat where it matters, smoke where faint).
function composite(state) {
  const W = state.width;
  const H = state.height;
  const heat = state.heat;
  const smoke = state.smoke;
  const grid = new Array(H);
  for (let y = 0; y < H; y++) {
    const row = new Array(W);
    for (let x = 0; x < W; x++) {
      const i = y * W + x;
      row[x] = Math.min(1, Math.max(heat[i], smoke[i]));
    }
    grid[y] = row;
  }
  return grid;
}

// --------------------------------------------------------------- palette ---
// Multi-stop gradient. v in (0, 0.1) is the faint-smoke band (gray).
// The fire ramp itself: white-hot core -> yellow -> orange -> red -> dark red.
const SMOKE_MAX = 0.1;

const FIRE_STOPS = [
  // [t, r, g, b]
  [0.0, 70, 12, 2], // dark red (cool edge)
  [0.28, 190, 44, 8], // red
  [0.5, 255, 120, 22], // orange
  [0.72, 255, 186, 48], // amber/yellow
  [0.88, 255, 238, 160], // pale yellow
  [1.0, 255, 255, 248], // white-hot core
];

// heat value -> {r,g,b} (all integers 0..255) or null for an empty cell.
function palette(v) {
  if (typeof v !== 'number' || !Number.isFinite(v) || v <= 0) return null;
  if (v < SMOKE_MAX) {
    // Faint gray smoke.
    const g = Math.round(30 + (v / SMOKE_MAX) * 70); // 30..100
    return { r: g, g: g, b: Math.min(255, g + 6) };
  }
  const t = Math.min(1, (v - SMOKE_MAX) / (1 - SMOKE_MAX));
  let lo = FIRE_STOPS[0];
  let hi = FIRE_STOPS[FIRE_STOPS.length - 1];
  for (let i = 0; i < FIRE_STOPS.length - 1; i++) {
    const a = FIRE_STOPS[i];
    const b = FIRE_STOPS[i + 1];
    if (t >= a[0] && t <= b[0]) {
      lo = a;
      hi = b;
      break;
    }
  }
  const f = hi[0] === lo[0] ? 0 : (t - lo[0]) / (hi[0] - lo[0]);
  return {
    r: Math.round(lo[1] + (hi[1] - lo[1]) * f),
    g: Math.round(lo[2] + (hi[2] - lo[2]) * f),
    b: Math.round(lo[3] + (hi[3] - lo[3]) * f),
  };
}

// ------------------------------------------------------------- renderer -----
// grid: 2-D array [height][width] of values in [0, 1].
// One terminal row shows two grid rows: top half '▀', bottom half '▄',
// combined into one block character per grid column. Returns the frame as a
// single string: ceil(height/2) lines of exactly `width` visible columns.
function renderFrame(grid, width, height) {
  const rows = Math.ceil(height / 2);
  const lines = [];
  for (let r = 0; r < rows; r++) {
    let out = '';
    let cur = null; // current [r,g,b], or null (no active SGR)
    const colorCell = (ch, v) => {
      const c = palette(v);
      if (!c) return;
      if (!cur || cur[0] !== c.r || cur[1] !== c.g || cur[2] !== c.b) {
        out += '\x1b[38;2;' + c.r + ';' + c.g + ';' + c.b + 'm';
        cur = [c.r, c.g, c.b];
      }
      out += ch;
    };
    for (let x = 0; x < width; x++) {
      const top = grid[r * 2] ? grid[r * 2][x] || 0 : 0;
      const bot = r * 2 + 1 < height && grid[r * 2 + 1] ? grid[r * 2 + 1][x] || 0 : 0;
      const before = cur;
      if (top > 0 && bot > 0) {
        colorCell('\u2588', Math.max(top, bot)); // █ both halves hot
      } else if (top > 0) {
        colorCell('\u2580', top); // ▀ top half only
      } else if (bot > 0) {
        colorCell('\u2584', bot); // ▄ bottom half only
      }
      if (cur === before) {
        if (before !== null) {
          out += '\x1b[0m'; // transition back to plain
          cur = null;
        } else {
          out += ' '; // empty cell: plain space, no escape
        }
      }
    }
    lines.push(out);
  }
  return lines.join('\n');
}

// ------------------------------------------------------------------ loop ----
// IO only. Runs ONLY when this file is the main module.
function start() {
  const cols = process.stdout.columns || 80;
  const rows = process.stdout.rows || 24;
  const width = cols;
  const height = rows * 2; // half-block: two grid rows per terminal row

  const state = createSim(width, height, (Date.now() ^ (process.pid << 8)) >>> 0);

  process.stdout.write('\x1b[?25l\x1b[2J\x1b[H'); // hide cursor, clear, home

  const timer = setInterval(() => {
    tick(state);
    const frame = renderFrame(composite(state), width, height);
    process.stdout.write('\x1b[2J\x1b[H' + frame + '\x1b[0m'); // clear + draw
  }, 33); // ~30 FPS

  process.on('SIGINT', () => {
    clearInterval(timer);
    process.stdout.write('\x1b[0m\x1b[?25h\r\n'); // reset ANSI, show cursor
    process.exit(0);
  });
}

if (require.main === module) {
  start();
}

module.exports = {
  createSim,
  tick,
  composite,
  palette,
  renderFrame,
  valueNoise,
  mulberry32,
};
