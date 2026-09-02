'use strict';

// Fire physics + palette + pure ANSI renderer (ticket 030).
//
// Pure logic, no io: createFire(opts) builds a W×H temperature grid with a
// flickering base row and spark particles; step() pushes heat upward with
// decay; render() composes one frame as a single string block (cursor home,
// rows, tail clear). Determinism: the PRNG is injected (default
// mulberry32(seed)) — same seed ⇒ identical frames.

// --- PRNG ---------------------------------------------------------------------

// Small dependency-free 32-bit PRNG (Stewart Olin Pearson's mulberry32).
// Returns values in [0,1). Same seed => same stream.
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function clamp01(v) {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

function clamp(v, lo, hi) {
  return v < lo ? lo : v > hi ? hi : v;
}

// --- physics ------------------------------------------------------------------

const DEFAULT_W = 80;
const DEFAULT_H = 24;
const DEFAULT_DECAY = 0.88;   // per-step attenuation, in [0.85..0.92]
const DEFAULT_SPARKS = 16;
const BASE_FLOOR = 0.9;       // base row temperature floor (~1.0 with flicker)
const SPARKLE = 0.12;         // per-cell noise amplitude (centered, E[0])
const SPARK_LIFE_MIN = 0.4;
const SPARK_LIFE_MAX = 0.9;

function createFire(opts) {
  const options = opts || {};
  const W = options.W > 0 ? Math.floor(options.W) : DEFAULT_W;
  const H = options.H > 0 ? Math.floor(options.H) : DEFAULT_H;
  const decay = typeof options.decay === 'number'
    ? clamp(options.decay, 0.85, 0.92) : DEFAULT_DECAY;
  const rng = typeof options.rng === 'function'
    ? options.rng
    : mulberry32(options.seed !== undefined ? options.seed : 1);
  const sparkCount = Math.max(0, Math.floor(options.sparks !== undefined ? options.sparks : DEFAULT_SPARKS));

  const heat = Array.from({ length: H }, () => new Array(W).fill(0));
  const base = H - 1;

  // Sparks live at float coordinates so they drift smoothly; life counts down
  // to 0 then the spark respawns at the base (resurrection per ticket).
  const sparks = [];
  for (let i = 0; i < sparkCount; i++) {
    const s = { x: 0, y: base, vy: -0.1, life: 0 };
    respawn(s);
    sparks.push(s);
  }

  function respawn(s) {
    s.x = 1 + rng() * (Math.max(1, W - 2));
    s.y = base - rng() * 0.5;
    s.vy = -(0.15 + rng() * 0.1);
    s.life = SPARK_LIFE_MIN + rng() * (SPARK_LIFE_MAX - SPARK_LIFE_MIN);
  }

  function step() {
    // Ticket formula: heat[y][x] = avg(heat[y+1][x-1..x+1]) * decay +
    // noise*sparkle. The noise is CENTERED ((rng()-0.5)*SPARKLE, E[0]), so the
    // expected field decays geometrically upward (0.88^rows above the base) —
    // the flame cools with height while the jitter makes it flicker.
    const next = Array.from({ length: H }, () => new Array(W).fill(0));
    for (let y = 0; y < H; y++) {
      const below = heat[y + 1]; // undefined above the top row => row stays 0
      if (!below) continue;
      const row = next[y];
      for (let x = 0; x < W; x++) {
        const l = x > 0 ? below[x - 1] : 0;
        const r = x < W - 1 ? below[x + 1] : 0;
        const v = ((l + below[x] + r) / 3) * decay + (rng() - 0.5) * SPARKLE;
        row[x] = clamp01(v);
      }
    }
    // Heat source: base row ~1.0 with flicker (noise).
    const b = next[base];
    for (let x = 0; x < W; x++) {
      b[x] = clamp01(BASE_FLOOR + 0.1 * rng());
    }
    for (let y = 0; y < H; y++) heat[y] = next[y];

    // Sparks: rise, fade, respawn at the base (life or leaving the top).
    const dt = 1;
    for (const s of sparks) {
      s.y += s.vy * dt;
      s.x += (rng() - 0.5) * 0.2 * dt; // lateral drift
      if (s.x < 0) s.x = 0;
      else if (s.x >= W) s.x = W - 1; // keep x within [0, W)
      s.life -= 0.004 * dt;
      if (s.life <= 0 || s.y < 0) respawn(s);
    }
    return heat;
  }

  return { step, heat, sparks, W, H };
}

// --- palette ------------------------------------------------------------------

// Temperature [0..1] -> 256-color index: 0 => null (empty), then dark red ->
// red -> orange -> yellow -> white hot core. Piecewise-linear over xterm-256
// color indices: 160 dark red, 196 red, 202/214 orange, 226 yellow, 231 white.
const STOPS = [
  [0.0, 0],
  [0.05, 160],
  [0.3, 196],
  [0.5, 202],
  [0.7, 214],
  [0.9, 226],
  [1.0, 231],
];

function colorIndex(t) {
  if (!(t > 0)) return null;
  if (t >= STOPS[STOPS.length - 1][0]) return STOPS[STOPS.length - 1][1];
  for (let i = 1; i < STOPS.length; i++) {
    if (t <= STOPS[i][0]) {
      const [t0, c0] = STOPS[i - 1];
      const [t1, c1] = STOPS[i];
      return Math.round(c0 + (c1 - c0) * ((t - t0) / (t1 - t0)));
    }
  }
  return null;
}

// --- render -------------------------------------------------------------------

const ESC = '\u001b';
const CURSOR_HOME = ESC + '[H';
const CLEAR_TAIL = ESC + '[' + 'J';
const SPARK_GLYPH = '\u2726'; // ✦ bright pixel over the flame

// Pure: one frame as a single string block. `width` clamps rendered columns on
// narrow terminals; never touches process/io.
//
// Rows are built as per-CELL token arrays ({c: colorCode|null, spark: bool})
// and emitted at the end — the spark overlay replaces the CELL at (sx, sy),
// never a raw string offset, so ANSI escape sequences can never be split.
function render(state, width) {
  const H = state.H;
  const cols = typeof width === 'number' && width > 0 ? Math.min(state.W, width) : state.W;
  const cells = Array.from({ length: H }, () => Array.from({ length: cols }, () => ({ c: null })));
  for (let y = 0; y < H; y++) {
    const row = state.heat[y];
    const line = cells[y];
    for (let x = 0; x < cols; x++) {
      const idx = colorIndex(row[x]);
      line[x] = { c: idx === null ? null : ESC + '[38;5;' + idx + 'm' };
    }
  }
  // Sparks overlay the flame as bright pixels (cell-level replace).
  for (const s of state.sparks) {
    const sy = Math.max(0, Math.min(H - 1, Math.floor(s.y)));
    const sx = Math.max(0, Math.min(cols - 1, Math.floor(s.x)));
    cells[sy][sx].spark = true;
  }
  const lines = cells.map((line, y) => {
    const parts = [];
    let open = null; // current color code, or null (empty/space)
    for (let x = 0; x < line.length; x++) {
      const cell = line[x];
      if (cell.c !== open) {
        if (open !== null) parts.push(ESC + '[0m');
        open = cell.c;
        if (open !== null) parts.push(open);
      }
      parts.push(cell.spark ? SPARK_GLYPH : ' ');
    }
    if (open !== null) parts.push(ESC + '[0m');
    return parts.join('');
  });
  return CURSOR_HOME + lines.join('\n') + '\n' + CLEAR_TAIL;
}

module.exports = { createFire, render, colorIndex, mulberry32 };
