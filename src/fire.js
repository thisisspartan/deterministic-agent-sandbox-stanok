'use strict';
// Terminal fire — a burning flame rendered in the terminal.
//
// Architecture (four separated concerns):
//   1. Simulation  — pure 2D heat-field grid, seeded PRNG, deterministic ticks.
//   2. Palette     — pure heat [0,1] -> [r,g,b] multi-stop gradient (or null).
//   3. Renderer    — pure grid -> one ANSI frame string (half-block ▀).
//   4. Loop        — IO only; starts ONLY when run as main on a TTY.
// Zero external dependencies. CommonJS.

const ESC = '\x1b';
const HALF_BLOCK = '▀';

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);

/* ---------------- 0. Seeded PRNG (mulberry32) ---------------- */

function createPRNG(seed) {
  let a = seed >>> 0;
  return function next() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* ---------------- 1. Simulation (pure) ----------------
 * Grid is row-major, row 0 = top of the screen. Each tick:
 *  - flicker: global intensity noise,
 *  - base injection: wide base tapering upward, swaying with a random walk,
 *    with per-column random-walk turbulence ("licking"),
 *  - upward diffusion with per-cell turbulence + height-dependent cooling,
 *  - smoke: faint gray particles spawned above the flame tip, rising and fading.
 */

function createSim(opts = {}) {
  const width = opts.width | 0;
  const height = opts.height | 0;
  if (width < 2 || height < 2) {
    throw new Error('createSim: width/height must be >= 2');
  }
  return {
    width,
    height,
    seed: opts.seed >>> 0,
    heat: Array.from({ length: height }, () => new Float64Array(width)),
    smoke: Array.from({ length: height }, () => new Float64Array(width)),
    rng: createPRNG(opts.seed >>> 0),
    tickCount: 0,
    sway: 0, // global sway random walk, in [-1, 1]
    colPhase: new Float64Array(width), // per-column turbulence random walk
    particles: [], // smoke particles {x, y, life}
  };
}

function tick(sim) {
  const W = sim.width;
  const H = sim.height;
  const r = sim.rng;
  const heat = sim.heat;

  // Flicker: global intensity noise per frame.
  const flicker = 0.8 + 0.35 * r();

  // Global sway random walk (flame leans side to side).
  sim.sway =
    clamp01(0.5 + (sim.sway - 0.5) * 0.92 + (r() - 0.5) * 0.12) * 2 - 1;

  // Per-column turbulence random walk (flame licks).
  for (let x = 0; x < W; x++) {
    sim.colPhase[x] = clamp01(0.5 + sim.colPhase[x] * 0.9 + (r() - 0.5) * 0.25);
  }

  // Base injection: wide base, centered with sway, per-column modulation.
  const baseRow = H - 1;
  const center = W / 2 + sim.sway * W * 0.15;
  const half = W * 0.28;
  for (let x = 0; x < W; x++) {
    const d = Math.abs(x - center) / half;
    let p = d >= 1 ? 0 : (1 - d) * (1 - d); // smooth taper from the base
    p *= 0.75 + 0.5 * sim.colPhase[x]; // per-column licking
    p *= flicker;
    heat[baseRow][x] = clamp01(Math.max(heat[baseRow][x] * 0.4, p));
  }

  // Upward diffusion + cooling + per-cell turbulence perturbation.
  const next = Array.from({ length: H }, () => new Float64Array(W));
  for (let y = H - 2; y >= 0; y--) {
    const cool = 0.95 - 0.12 * (y / H); // cools faster higher up
    for (let x = 0; x < W; x++) {
      const drift = Math.round((r() - 0.5) * 2); // horizontal turbulence drift
      let s = 0;
      for (let dx = -1; dx <= 1; dx++) {
        const sx = x + drift + dx;
        if (sx < 0 || sx >= W) continue;
        s += heat[y + 1][sx] * (dx === 0 ? 0.5 : 0.25);
      }
      const turb = 1 + (r() - 0.5) * 0.15; // per-cell perturbation
      next[y][x] = clamp01(Math.max(s * cool * turb, heat[y][x] * 0.25));
    }
  }
  next[baseRow] = heat[baseRow];
  sim.heat = next;

  // Smoke: spawn faint particles just above the flame tip, rise, drift, fade.
  const newSmoke = Array.from({ length: H }, () => new Float64Array(W));
  for (let x = 0; x < W; x++) {
    let tip = -1;
    for (let y = 0; y < H; y++) {
      if (heat[y][x] > 0.35) {
        tip = y;
        break;
      }
    }
    if (tip > 1 && r() < 0.22) {
      sim.particles.push({
        x: x + (r() - 0.5) * 2,
        y: tip - 2,
        life: 0.5 + r() * 0.5,
      });
    }
  }
  const alive = [];
  for (const p of sim.particles) {
    p.y -= 1;
    p.x += (r() - 0.5) * 1.6;
    p.life -= 0.02;
    if (p.life <= 0 || p.y < 0) continue;
    alive.push(p);
    const xi = Math.round(p.x);
    const yi = Math.round(p.y);
    if (xi >= 0 && xi < W && yi >= 0 && yi < H) {
      newSmoke[yi][xi] = Math.min(1, newSmoke[yi][xi] + p.life * 0.35);
    }
  }
  sim.particles = alive;
  sim.smoke = newSmoke;
  sim.tickCount += 1;
  return sim;
}

/* ---------------- 2. Palette (pure) ----------------
 * Multi-stop gradient: transparent -> dark red -> red -> orange ->
 * yellow -> white-hot. heat <= 0 => null (empty cell, no escape).
 */

const STOPS = [
  [0.0, 0, 0, 0],
  [0.1, 90, 8, 0],
  [0.25, 200, 40, 5],
  [0.45, 255, 120, 20],
  [0.65, 255, 200, 70],
  [0.85, 255, 240, 170],
  [1.0, 255, 255, 255],
];

function palette(t) {
  t = clamp01(Number(t) || 0);
  if (t <= 0) return null;
  let i = 0;
  while (i < STOPS.length - 2 && t > STOPS[i + 1][0]) i++;
  const [t0, r0, g0, b0] = STOPS[i];
  const [t1, r1, g1, b1] = STOPS[i + 1];
  const f = t1 === t0 ? 0 : (t - t0) / (t1 - t0);
  return [
    Math.round(r0 + (r1 - r0) * f),
    Math.round(g0 + (g1 - g0) * f),
    Math.round(b0 + (b1 - b0) * f),
  ];
}

/* ---------------- 3. Renderer (pure) ----------------
 * Grid -> one ANSI frame string. Each half-block (▀) draws two
 * vertical heat samples; the colored half takes the hotter sample.
 * Faint smoke renders as gray. Frame is ceil(height/2) rows x width.
 */

function renderFrame(sim) {
  const W = sim.width;
  const H = sim.height;
  const heat = sim.heat;
  const smoke = sim.smoke;
  const rows = Math.ceil(H / 2);
  const lines = [];
  for (let p = 0; p < rows; p++) {
    const yt = 2 * p; // top grid row of this pair
    const yb = yt + 1; // bottom grid row
    let line = '';
    for (let x = 0; x < W; x++) {
      const ht = heat[yt][x];
      const hb = yb < H ? heat[yb][x] : 0;
      let c = null;
      const h = ht >= hb ? ht : hb;
      if (h > 0.05) c = palette(h); // sub-threshold heat: invisible embers
      if (!c) {
        const hs = smoke[yt][x] + (yb < H ? smoke[yb][x] : 0);
        if (hs > 0.02) {
          const g = Math.min(255, Math.round(40 + hs * 120));
          c = [g, g, g];
        }
      }
      line += c
        ? `${ESC}[38;2;${c[0]};${c[1]};${c[2]}m${HALF_BLOCK}`
        : ' ';
    }
    lines.push(line);
  }
  return lines.join('\n');
}

/* ---------------- 4. Loop (IO only) ----------------
 * Starts only when run as main on an interactive TTY. ~30 FPS,
 * clears the screen each frame, flame centered in cols x rows.
 * SIGINT: stop the interval, restore the cursor, reset ANSI, exit 0.
 */

function run() {
  const W = Math.max(2, process.stdout.columns || 80);
  const H = Math.max(4, Math.floor((process.stdout.rows || 24) / 2) * 2);
  const sim = createSim({ width: W, height: H, seed: Date.now() & 0xffffffff });
  process.stdout.write(`${ESC}[?25l${ESC}[2J${ESC}[H`); // hide cursor, clear
  const iv = setInterval(() => {
    tick(sim);
    process.stdout.write(`${ESC}[2J${ESC}[H` + renderFrame(sim));
  }, 1000 / 30);
  process.on('SIGINT', () => {
    clearInterval(iv);
    process.stdout.write(`${ESC}[0m${ESC}[?25h\n`); // reset ANSI, show cursor
    process.exit(0);
  });
}

// Main guard: run directly on a TTY only. Requiring the module (tests,
// smoke via scripts/run.sh) never starts the animation.
if (require.main === module && process.stdin.isTTY && process.stdout.isTTY) {
  run();
}

module.exports = { createPRNG, createSim, tick, palette, renderFrame, run };
