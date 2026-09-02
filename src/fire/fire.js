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
const DEFAULT_DECAY = 0.96;   // per-step attenuation, in [0.85..0.96] (ticket 033 F3)
const DEFAULT_SPARKS = 16;
const SOURCE_HALF = 0.25;     // base source spans W*(1/2..3/4): central 50% (ticket 031 F1)
const BASE_FLOOR = 0.9;       // base row temperature floor (~1.0 with flicker)
const SPARKLE = 0.12;         // per-cell noise amplitude (centered, E[0])
const FLICKER_LOW = -0.25;    // per-cell flicker offset (ticket 033 F2)
const FLICKER_HIGH = 0.5;     // per-cell flicker scale: flicker = LOW + HIGH*rng()
const BREATH_PERIOD = 60;     // frames; 2 s at 30 FPS (ticket 031 F3)
const BREATH_AMP = 0.15;      // ±15% intensity modulation
const TAPER_K = 2;            // vertical taper exponent (ticket 031 F2)
const TAPER_MAX = 0.6;        // top-row rows down to 1 - TAPER_MAX of base intensity
const SPARK_LIFE_MIN = 0.4;
const SPARK_LIFE_MAX = 0.9;

function createFire(opts) {
  const options = opts || {};
  const W = options.W > 0 ? Math.floor(options.W) : DEFAULT_W;
  const H = options.H > 0 ? Math.floor(options.H) : DEFAULT_H;
  const decay = typeof options.decay === 'number'
    ? clamp(options.decay, 0.85, 0.96) : DEFAULT_DECAY;
  const rng = typeof options.rng === 'function'
    ? options.rng
    : mulberry32(options.seed !== undefined ? options.seed : 1);
  const sparkCount = Math.max(0, Math.floor(options.sparks !== undefined ? options.sparks : DEFAULT_SPARKS));

  const heat = Array.from({ length: H }, () => new Array(W).fill(0));
  const base = H - 1;

  // --- ticket 031 geometry ---------------------------------------------------
  // Central source zone: middle 50% of the width, smooth cosine profile by X
  // (F1). sparkL/sparkR are the integer column bounds used for spark respawn
  // and clamping (F4: sparks live only inside the source zone).
  const srcL = Math.floor(W * (0.5 - SOURCE_HALF));      // W/4
  const srcR = Math.ceil(W * (0.5 + SOURCE_HALF));       // 3W/4 (exclusive)
  const srcHalf = Math.max(1, srcR - srcL);
  const srcMask = new Array(W).fill(0);
  for (let x = srcL; x < srcR; x++) {
    const u = (x - srcL) / srcHalf;          // 0..1 across the zone
    srcMask[x] = 0.5 * (1 + Math.cos(Math.PI * (u * 2 - 1))); // 1 at center, 0 at edges
  }
  // Vertical taper (F2): row strength decreases from the base upward so the
  // flame becomes a tongue, wide at the bottom and thin at the top.
  const taper = new Array(H);
  for (let y = 0; y < H; y++) {
    const fromBase = (base - y) / H;
    taper[y] = 1 - Math.pow(fromBase, TAPER_K) * TAPER_MAX;
  }

  // Sparks live at float coordinates so they drift smoothly; life counts down
  // to 0 then the spark respawns at the base (resurrection per ticket).
  const sparks = [];
  for (let i = 0; i < sparkCount; i++) {
    const s = { x: 0, y: base, vy: -0.1, life: 0 };
    respawn(s);
    sparks.push(s);
  }

  function respawn(s) {
    // F4: sparks are born only inside the central source zone.
    s.x = srcL + 0.5 + rng() * (srcHalf - 1);
    s.y = base - rng() * 0.5;
    s.vy = -(0.15 + rng() * 0.1);
    s.life = SPARK_LIFE_MIN + rng() * (SPARK_LIFE_MAX - SPARK_LIFE_MIN);
  }

  let frame = 0;

  function step() {
    // Ticket formula: heat[y][x] = vertical_diffusion(heat[y+1..y+2]) * decay
    // * taper(y) + noise*sparkle. The noise is CENTERED ((rng()-0.5)*SPARKLE,
    // E[0]); the expected field decays geometrically upward (decay^rows above
    // the base) while taper() squeezes the upper rows — the flame cools and
    // narrows with height while the per-cell flicker at the source (F2) and
    // the SPARKLE jitter make it flicker.
    const next = Array.from({ length: H }, () => new Array(W).fill(0));
    for (let y = 0; y < H; y++) {
      const below = heat[y + 1]; // undefined above the top row => row stays 0
      if (!below) continue;
      const up = (y + 2 < H) ? heat[y + 2] : null; // row two below (vertical diffusion)
      const row = next[y];
      const t = taper[y];
      for (let x = 0; x < W; x++) {
        const l = x > 0 ? below[x - 1] : 0;
        const r = x < W - 1 ? below[x + 1] : 0;
        let v;
        if (up) {
          const ul = x > 0 ? up[x - 1] : 0;
          const ur = x < W - 1 ? up[x + 1] : 0;
          // Ticket 033 F3: 3x3 + 3x1 vertical diffusion (rows y+1 and y+2).
          // Pulls heat from two rows below so the flame tongue extends upward
          // while the taper still squeezes the top.
          v = ((l + 2 * below[x] + r + ul + 2 * up[x] + ur) / 8) * decay * t
            + (rng() - 0.5) * SPARKLE;
        } else {
          v = ((l + below[x] + r) / 3) * decay * t + (rng() - 0.5) * SPARKLE;
        }
        row[x] = clamp01(v);
      }
    }
    // F3: slow breathing — a low-frequency sine (period 60 frames = 2 s at
    // 30 FPS, ±15%) modulates the SOURCE intensity, so the whole flame
    // "breathes" as the wave propagates up through transport (it must not
    // multiply each row: that would compound with height). Deterministic via
    // the frame counter: one seed => identical frames.
    const breath = 1 - BREATH_AMP * (0.5 + 0.5 * Math.sin(2 * Math.PI * frame / BREATH_PERIOD));
    // Heat source (F1): central zone only, cosine profile by X, flicker
    // (per-cell noise) preserved.
    const b = next[base];
    // Ticket 033 F2: per-cell flicker. Each cell of the base row receives its
    // own noise `fl = FLICKER_LOW + FLICKER_HIGH * rng()` in [-0.25, 0.25),
    // so adjacent cells differ sharply (not a smooth cosine wave). Amplitude
    // picked so the row's max-min stays well above the 0.3 threshold.
    for (let x = 0; x < W; x++) {
      const m = srcMask[x];
      if (m === 0) { b[x] = 0; continue; }
      const fl = FLICKER_LOW + FLICKER_HIGH * rng();
      b[x] = clamp01(m * (BASE_FLOOR + fl) * breath);
    }
    for (let y = 0; y < H; y++) heat[y] = next[y];
    frame++;

    // Sparks: rise, fade, respawn inside the source zone (life or top exit).
    const dt = 1;
    for (const s of sparks) {
      s.y += s.vy * dt;
      s.x += (rng() - 0.5) * 0.2 * dt; // lateral drift
      // Keep sparks inside the flame column (F4).
      if (s.x < srcL + 0.5) s.x = srcL + 0.5;
      else if (s.x >= srcR - 0.5) s.x = srcR - 0.5;
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

// --- fireplace frame (ticket 032 R1/R2) --------------------------------------
//
// Static 2D frame, no logs: brick/stone glyphs ▓ █ ▒ in dark palette colors,
// drawn around a dark window where the flame burns. Frame is state-independent
// (same for any `state`), so the flame never flickers the bricks.

const BRICKS = ['\u2593', '\u2588', '\u2592']; // ▓ █ ▒
const BRICK_COLORS = [24, 25, 26, 27, 58];     // dark brick palette (ticket 033 F1)
const DARK_BG = 234;                            // window background, heat≈0 (233–235 range)
const BG_CODE = ESC + '[38;5;' + DARK_BG + 'm';

// --- flame density glyphs (ticket 034 R1) -------------------------------------
//
// Ramp from sparse (index 0 = space) to dense. Must avoid brick glyphs
// (▓█▒), spark glyph (✦), and the log glyphs (=, #, -) that R3 test forbids
// anywhere in the frame. Index 0 is a space so cells with heat <= FLAME_MIN
// look identical to the previous "invisible flame" behavior (background).
// The last glyph "@" is the heaviest visually.
const FLAME_GLYPHS = ' .,;:~*oO@';
const FLAME_MIN = 0.08;

// Map a heat value to a ramp index in [1..len-1]; 0 (heat <= FLAME_MIN) -> 0.
function flameGlyphIndex(heat) {
  if (heat <= FLAME_MIN) return 0;
  const n = FLAME_GLYPHS.length - 1;
  const i = Math.floor(heat * n);
  return i >= n ? n : i;
}

// Deterministic pseudo-random brick pattern (fixed seed — static frame).
// Ticket 033 F1: 5-color dark brick palette {24,25,26,27,58}.
function brickAt(row, col) {
  // row: frame row (0..H-1), col: frame column (0..cols-1)
  const n = (row * 7919 + col * 104729 + 12345) % BRICKS.length;
  return { glyph: BRICKS[n], code: BRICK_COLORS[(row * 5 + col * 11 + 3) % BRICK_COLORS.length] };
}

// Pure: one frame as a single string block. `width` clamps rendered columns on
// narrow terminals; never touches process/io.
//
// Rows are built as per-CELL token arrays ({c: colorCode|null, spark: bool,
// brick: glyph|null}) and emitted at the end — the spark overlay replaces the
// CELL at (sx, sy), never a raw string offset, so ANSI escape sequences can
// never be split.
function render(state, width) {
  const H = state.H;
  const W = state.W;
  const cols = typeof width === 'number' && width > 0 ? Math.min(W, width) : W;
  const plinth = H > 4 ? 2 : 1;
  const lintel = H > 4 ? 2 : 1;
  const pillar = W > 8 ? 2 : 1;
  const frame = (y, x) =>
    y >= H - plinth || y < lintel || x < pillar || x >= cols - pillar;

  const cells = Array.from({ length: H }, () => Array.from({ length: cols }, () => ({ c: null })));
  for (let y = 0; y < H; y++) {
    const row = state.heat[y];
    const line = cells[y];
    for (let x = 0; x < cols; x++) {
      if (frame(y, x)) continue; // filled after the flame pass
      const h = row[x];
      const idx = h > 0 ? colorIndex(h) : DARK_BG; // R2: dark window bg
      // Ticket 034 R1: window cell with heat > FLAME_MIN carries a density
      // glyph from FLAME_GLYPHS; color code is left untouched.
      const g = FLAME_GLYPHS[flameGlyphIndex(h)];
      line[x] = { c: ESC + '[38;5;' + idx + 'm', glyph: g };
    }
  }
  // Static frame (R1): bricks in dark palette, state-independent.
  for (let y = 0; y < H; y++) {
    const line = cells[y];
    for (let x = 0; x < cols; x++) {
      if (!frame(y, x)) continue;
      const b = brickAt(y, x);
      line[x] = { c: ESC + '[38;5;' + b.code + 'm', glyph: b.glyph };
    }
  }
  // Sparks overlay the flame as bright pixels (cell-level replace).
  for (const s of state.sparks) {
    const sy = Math.max(0, Math.min(H - 1, Math.floor(s.y)));
    const sx = Math.max(0, Math.min(cols - 1, Math.floor(s.x)));
    if (!frame(sy, sx)) cells[sy][sx].spark = true;
  }
  const lines = cells.map((line) => {
    const parts = [];
    let open = null; // current color code, or null (empty/space)
    for (let x = 0; x < line.length; x++) {
      const cell = line[x];
      if (cell.c !== open) {
        if (open !== null) parts.push(ESC + '[0m');
        open = cell.c;
        if (open !== null) parts.push(open);
      }
      parts.push(cell.spark ? SPARK_GLYPH : (cell.glyph || ' '));
    }
    if (open !== null) parts.push(ESC + '[0m');
    return parts.join('');
  });
  return CURSOR_HOME + lines.join('\n') + '\n' + CLEAR_TAIL;
}

module.exports = { createFire, render, colorIndex, mulberry32 };
