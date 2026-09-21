'use strict';
/*
 * fire.js — terminal fire: heat-field simulation -> palette -> ANSI frame.
 *
 * Four separated concerns:
 *   1. Simulation  — seeded, deterministic 2D heat field (inject at base,
 *                    diffuse upward, cool, perturb with turbulence).
 *   2. Palette     — heat in [0,1] -> 24-bit truecolor ANSI (or '' for zero).
 *   3. Renderer    — heat + smoke grid -> one ANSI frame string.
 *   4. Loop (IO)   — runs only when executed as main (`require.main === module`).
 */

const ESC = '\x1b';

// ---------------------------------------------------------------------------
// Seeded PRNG (mulberry32) — deterministic frames for tests.
// ---------------------------------------------------------------------------
function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

// ---------------------------------------------------------------------------
// 1. Simulation — 2D heat field, values normalized to [0, 1].
// ---------------------------------------------------------------------------
function createSim(width, height, seed) {
  const zeroRow = () => new Array(width).fill(0);
  return {
    width,
    height,
    heat: Array.from({ length: height }, zeroRow),
    smokeField: Array.from({ length: height }, zeroRow),
    particles: [],
    rng: mulberry32(seed),
    t: 0,
    flicker: 0.9, // global per-frame intensity noise (smooth random walk)
    sway: new Array(width).fill(0), // per-column turbulence (random walk)
    colNoise: new Array(width).fill(0.7), // per-column base-noise (random walk)
  };
}

function step(sim) {
  const W = sim.width;
  const H = sim.height;
  const rng = sim.rng;
  const old = sim.heat;
  const next = Array.from({ length: H }, () => new Array(W).fill(0));
  const smoke = Array.from({ length: H }, () => new Array(W).fill(0));

  if (H < 2) {
    sim.t += 1;
    return sim;
  }

  // Flicker: global intensity noise per frame (bounded random walk).
  sim.flicker = clamp(sim.flicker + (rng() - 0.5) * 0.22, 0.72, 1.12);

  // Turbulence: per-column sway random walk — the flame sways and licks.
  for (let x = 0; x < W; x++) {
    sim.sway[x] = clamp(sim.sway[x] + (rng() - 0.5) * 0.55, -1.5, 1.5);
  }

  // Diffuse upward: heat advects one row up per tick, sampled from the cell
  // below through the turbulence shift (stronger near the top), blended
  // with lateral neighbors for soft licking edges, then cooled.
  for (let y = 0; y < H - 1; y++) {
    const rise = 1 - y / H; // 0 at base, 1 at top
    const below = old[y + 1];
    const row = next[y];
    for (let x = 0; x < W; x++) {
      const sx = clamp(x + Math.round(sim.sway[x] * 2 * rise), 0, W - 1);
      const sxl = clamp(sx - 1, 0, W - 1);
      const sxr = clamp(sx + 1, 0, W - 1);
      const v = below[sx] + (below[sxl] + below[sxr]) * 0.15 + (rng() - 0.5) * 0.04;
      row[x] = clamp(v * (0.9 + 0.07 * rng()), 0, 1);
    }
  }

  // Base injection: wide base tapering upward — per-column noise keeps it
  // organic rather than a static cone.
  const cx = (W - 1) / 2;
  const baseHalf = W * 0.2;
  for (let x = 0; x < W; x++) {
    const d = Math.abs(x - cx) / baseHalf;
    if (d >= 1) continue;
    sim.colNoise[x] = clamp(sim.colNoise[x] + (rng() - 0.5) * 0.35, 0.25, 1);
    const amt = (1 - d * d) * sim.flicker * sim.colNoise[x];
    next[H - 1][x] = Math.max(next[H - 1][x], amt);
    next[H - 2][x] = Math.max(next[H - 2][x], amt * 0.85);
  }
  sim.heat = next;

  // Smoke: faint gray particles spawn above the flame, rise, drift, fade.
  if (rng() < 0.65) {
    sim.particles.push({
      x: cx + (rng() - 0.5) * baseHalf * 1.6,
      y: H - Math.round(H * (0.45 + rng() * 0.25)),
      life: 8 + rng() * 12,
    });
  }
  sim.particles = sim.particles.filter((p) => {
    p.y -= 1;
    p.x += (rng() - 0.5) * 0.7;
    p.life -= 1;
    if (p.y < 0 || p.life <= 0) return false;
    const xi = clamp(Math.round(p.x), 0, W - 1);
    const yi = Math.round(p.y);
    const s = Math.min(1, p.life / 15) * 0.5;
    smoke[yi][xi] = Math.max(smoke[yi][xi], s);
    return true;
  });
  sim.smokeField = smoke;

  sim.t += 1;
  return sim;
}

// ---------------------------------------------------------------------------
// 2. Palette — heat -> multi-stop gradient:
//    white-hot core -> yellow -> orange -> red -> dark red -> transparent.
//    Zero heat -> '' (empty cell, no escape).
// ---------------------------------------------------------------------------
const STOPS = [
  { t: 0.0, r: 12, g: 2, b: 0 }, // dark red (fades to nothing)
  { t: 0.15, r: 92, g: 12, b: 0 }, // red
  { t: 0.35, r: 210, g: 40, b: 0 }, // orange-red
  { t: 0.55, r: 255, g: 130, b: 15 }, // orange
  { t: 0.75, r: 255, g: 205, b: 70 }, // yellow
  { t: 1.0, r: 255, g: 255, b: 235 }, // white-hot core
];

function palette(heat) {
  if (heat <= 0) return '';
  const t = clamp(heat, 0, 1);
  let i = 0;
  while (i < STOPS.length - 2 && STOPS[i + 1].t <= t) i++;
  const a = STOPS[i];
  const b = STOPS[i + 1];
  const f = (t - a.t) / (b.t - a.t);
  const r = Math.round(a.r + (b.r - a.r) * f);
  const g = Math.round(a.g + (b.g - a.g) * f);
  const bl = Math.round(a.b + (b.b - a.b) * f);
  return `${ESC}[38;2;${r};${g};${bl} m`;
}

// ---------------------------------------------------------------------------
// 3. Renderer — grid -> one ANSI frame string.
//    Half-block '▀' for vertical resolution (lower half transparent glow).
//    Smoke cells render as faint gray half-blocks.
// ---------------------------------------------------------------------------
function renderFrame(sim) {
  const W = sim.width;
  const H = sim.height;
  const lines = new Array(H);
  for (let y = 0; y < H; y++) {
    let line = '';
    let colored = false;
    for (let x = 0; x < W; x++) {
      const h = sim.heat[y][x];
      if (h > 0) {
        line += palette(h) + '\u2580';
        colored = true;
      } else {
        const s = sim.smokeField[y][x];
        if (s > 0.03) {
          const c = Math.round(40 + 60 * clamp(s, 0, 1));
          line += `${ESC}[38;2;${c};${c};${c} m\u2580`;
          colored = true;
        } else {
          line += ' ';
        }
      }
    }
    if (colored) line += `${ESC}[0m`;
    lines[y] = line;
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 4. Loop (IO only) — hides the cursor, animates at ~30 FPS, centers the
//    flame, and cleans up on SIGINT (cursor restored, ANSI reset, exit 0).
//    Starts only when run as main on a real terminal (TTY); piped/CI
//    contexts (e.g. `scripts/run.sh smoke`) load the module and exit 0.
// ---------------------------------------------------------------------------
function startLoop() {
  const cols = (process.stdout.columns || 0) >= 20 ? process.stdout.columns : 80;
  const rows = (process.stdout.rows || 0) >= 8 ? process.stdout.rows : 24;
  const sim = createSim(cols, rows, 0xc0ffee);
  const frameMs = 33; // ~30 FPS

  process.stdout.write(`${ESC}[?25l`); // hide cursor
  const timer = setInterval(() => {
    step(sim);
    process.stdout.write(`${ESC}[2J${ESC}[H${renderFrame(sim)}${ESC}[0m`);
  }, frameMs);

  let stopping = false;
  process.on('SIGINT', () => {
    if (stopping) return;
    stopping = true;
    clearInterval(timer);
    process.stdout.write(`${ESC}[0m${ESC}[?25h\r\n`);
    process.exit(0);
  });

  return timer;
}

if (require.main === module && process.stdout.isTTY) {
  startLoop();
}

module.exports = { createSim, step, palette, renderFrame, startLoop, clamp };
