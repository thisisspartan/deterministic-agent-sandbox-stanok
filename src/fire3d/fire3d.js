'use strict';

// fire3d physics + pure ANSI renderer (ticket 041).
//
// Volumetric flame in a W×H×D voxel grid. `heat` is a flat Float32Array of
// size W*H*D with index `y*W*D + x*D + z` (y: 0 = base … H-1 = top;
// x: 0..W-1; z: 0..D-1). step() pushes heat upward from a flickering base
// layer (y=0) with per-layer decay and per-cell sparkle noise — the flame
// spreads in all three dimensions. render(state, width, angle) rotates the
// voxels around the vertical y axis by `angle` (x' = x·cos − z·sin,
// z' = x·sin + z·cos, coordinates relative to the slice center), projects
// onto the screen (col from x' scaled to `width`, row from y — y=0 is the
// bottom row) and takes the max-heat voxel per screen cell; an empty cell
// is the dark background 234, a heated cell is colored by the 256-color
// flame palette (same stops as src/fire/fire.js colorIndex). Rows are built
// as per-cell tokens and emitted with same-color runs merged. A frame is
// one string block: cursor home,
// rows, tail clear. There is no fireplace frame — the flame burns on the
// whole grid.
//
// Pure logic, no io. Determinism: the PRNG is injected (default
// mulberry32(seed)) — one seed + one step() sequence ⇒ identical frames.

// --- PRNG ---------------------------------------------------------------------

// Dependency-free 32-bit PRNG (mulberry32). Same seed => same stream.
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

// --- constants ------------------------------------------------------------------

const DEFAULT_W = 48;
const DEFAULT_H = 24;
const DEFAULT_D = 48;
const DEFAULT_SEED = 1337;
const DECAY_MIN = 0.85;
const DECAY_MAX = 0.92;
const DEFAULT_DECAY = 0.88; // per-layer attenuation on the way up
const BASE_TEMP = 1.0;      // base-layer temperature ~1.0
const FLICKER_AMP = 0.25;   // per-cell flicker at the source: ±0.125
const SPARKLE = 0.15;       // per-cell noise amplitude for upper layers (E[0])
// Source footprint: elliptical dome over the x–z plane (radii a/b in
// half-grid units). The flame body itself is volumetric — the dome only
// shapes where the heat is born, so rotation around y is visible.
const SRC_A = 0.8;
const SRC_B = 0.6;

// --- physics ------------------------------------------------------------------

// create(opts) -> state: { heat, W, H, D, angle, rng, decay, srcMask, step }.
// opts: W, H, D (grid sizes), seed (PRNG seed), rng (injected PRNG), decay.
function create(opts) {
  const options = opts || {};
  const W = options.W > 0 ? Math.floor(options.W) : DEFAULT_W;
  const H = options.H > 0 ? Math.floor(options.H) : DEFAULT_H;
  const D = options.D > 0 ? Math.floor(options.D) : DEFAULT_D;
  const rng = typeof options.rng === 'function'
    ? options.rng
    : mulberry32(options.seed !== undefined ? options.seed : DEFAULT_SEED);
  const decay = typeof options.decay === 'number'
    ? Math.min(DECAY_MAX, Math.max(DECAY_MIN, options.decay))
    : DEFAULT_DECAY;

  const heat = new Float32Array(W * H * D);
  const state = { heat, W, H, D, angle: 0, rng, decay };

  // Elliptical source dome: 1 at the center → 0 at/ beyond the rim.
  const cx = (W - 1) / 2;
  const cz = (D - 1) / 2;
  const srcMask = new Float32Array(W * D);
  for (let x = 0; x < W; x++) {
    const u = (x - cx) / (W / 2);
    const uu = (u * u) / (SRC_A * SRC_A);
    for (let z = 0; z < D; z++) {
      const v = (z - cz) / (D / 2);
      srcMask[x * D + z] = Math.max(0, 1 - uu - (v * v) / (SRC_B * SRC_B));
    }
  }
  state.srcMask = srcMask;

  state.step = () => step(state);
  return state;
}

// One physics tick. Bottom layer y=0: base temperature ~1.0 with per-cell
// flicker over the source dome. Every layer above: 3×3 average of the layer
// below × decay + centered sparkle noise, clamped to [0..1]. The flame
// spreads in x, y AND z (volumetric). Fully deterministic per seed.
function step(state) {
  const W = state.W, H = state.H, D = state.D;
  const prev = state.heat;
  const next = new Float32Array(W * H * D);
  const rng = state.rng;
  const decay = state.decay;
  const mask = state.srcMask;

  // y = 0: source layer.
  for (let x = 0; x < W; x++) {
    const off = x * D;
    for (let z = 0; z < D; z++) {
      const m = mask[off + z];
      if (m <= 0) continue; // outside the source dome stays cold
      next[off + z] = clamp01(m * (BASE_TEMP + (rng() - 0.5) * FLICKER_AMP));
    }
  }
  // y >= 1: 3D average of the 3×3 neighborhood in the layer below.
  for (let y = 1; y < H; y++) {
    const belowOff = (y - 1) * W * D;
    const off = y * W * D;
    for (let x = 0; x < W; x++) {
      const cur = off + x * D;
      for (let z = 0; z < D; z++) {
        let sum = 0;
        let n = 0;
        for (let dx = -1; dx <= 1; dx++) {
          const xx = x + dx;
          if (xx < 0 || xx >= W) continue;
          const b = belowOff + xx * D;
          for (let dz = -1; dz <= 1; dz++) {
            const zz = z + dz;
            if (zz < 0 || zz >= D) continue;
            sum += prev[b + zz];
            n++;
          }
        }
        next[cur + z] = clamp01((sum / n) * decay + (rng() - 0.5) * SPARKLE);
      }
    }
  }
  state.heat = next;
  return next;
}

// --- render ---------------------------------------------------------------------

const ESC = '\u001b';
const CURSOR_HOME = ESC + '[H';
const CLEAR_TAIL = ESC + '[J';
const DARK_BG = 234;           // dark background color for empty/cool cells
const RESET = ESC + '[0m';

// --- palette (ticket 042, mirrors src/fire/fire.js colorIndex) --------------

// Heat [0..1] -> xterm-256 color index: null for empty (heat <= 0), then
// dark red -> red -> orange -> yellow -> white hot core. Same stops as the
// 2D fire: 160 dark red, 196 red, 202/214 orange, 226 yellow, 231 white.
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

// Pure SGR color code for one cell (ticket 044). `color256 === true` (default):
// the 256-color palette via colorIndex (dark bg 234 for h <= 0). `color256
// === false`: 16-color fallback WITHOUT interpolation — nearest stop from
// below: 90 (bright black, bg) / 31 (red) / 91 (bright red) / 33 (yellow) /
// 97 (white). Terminals without 256-color support may mishandle ESC[38;5;Nm,
// which is why the fallback exists.
function colorCode(h, color256) {
  if (color256 === false) {
    if (h <= 0) return ESC + '[90m';
    if (h < 0.3) return ESC + '[31m';
    if (h < 0.5) return ESC + '[91m';
    if (h < 0.8) return ESC + '[33m';
    return ESC + '[97m';
  }
  const n = h > 0 ? colorIndex(h) : DARK_BG;
  return ESC + '[38;5;' + n + 'm';
}

// Flame density glyphs: ramp from sparse (index 0 = space) to dense.
// No brick glyphs (▓█▒) — the flame burns on the whole grid, no frame.
const FLAME_GLYPHS = ' .,;:~*oO@';
const FLAME_MIN = 0.08;

function flameGlyphIndex(h) {
  if (h <= FLAME_MIN) return 0;
  const n = FLAME_GLYPHS.length - 1;
  const u = (h - FLAME_MIN) / (1 - FLAME_MIN); // 0..1 across the visible range
  const i = Math.round(u * n);
  return i < 1 ? 1 : i > n ? n : i;
}

// Pure: one frame as a single string block. `angle` may be passed explicitly;
// otherwise state.angle is used. Rotate voxels around the vertical y axis,
// project (col from x' scaled to width, row from y with y=0 at the bottom),
// max heat per screen cell, dark bg 234 for empty cells. Never touches io.
//
// `opts` (may be undefined, ticket 044):
//   - rows: terminal row count. rows_screen = min(H, max(2, rows-1)); the
//     BOTTOM rows_screen rows are drawn (base y=0 always visible). Non-number
//     / undefined rows => H (old behavior). When rows_screen == rows-1 the
//     frame omits the trailing '\n' and the ESC[J tail clear (no scroll).
//   - color256: false switches every cell to a plain 16-color SGR code
//     (colorCode) for terminals without 256-color support; default true.
function render(state, width, angle, opts) {
  const W = state.W, H = state.H, D = state.D;
  const heat = state.heat;
  const options = opts || {};
  const color256 = options.color256 !== false;
  const a = typeof angle === 'number' && Number.isFinite(angle) ? angle : state.angle;
  const cos = Math.cos(a);
  const sin = Math.sin(a);
  const cols = typeof width === 'number' && width > 0 ? Math.min(W, Math.floor(width)) : W;
  const cx = (W - 1) / 2;
  const cz = (D - 1) / 2;
  const extent = Math.max(W, D) - 1;
  const scale = cols > 1 ? (cols - 1) / extent : 0;

  // Terminal-height adaptation (ticket 044): when opts.rows is a valid
  // number, draw only the BOTTOM rows_screen rows (y = rows_screen-1 … 0 —
  // the flame base y=0 is always visible, the top is clipped). Undefined or
  // non-number rows => rows_screen = H (current behavior).
  const rowsOpt = typeof options.rows === 'number' && Number.isFinite(options.rows)
    ? Math.floor(options.rows)
    : null;
  const rowsScreen = rowsOpt !== null ? Math.min(H, Math.max(2, rowsOpt - 1)) : H;

  const maxH = new Float32Array(rowsScreen * cols);
  for (let y = 0; y < rowsScreen; y++) {
    const off = y * W * D;
    const rowBase = y * cols;
    for (let x = 0; x < W; x++) {
      const dx = x - cx;
      for (let z = 0; z < D; z++) {
        const h = heat[off + x * D + z];
        if (h <= 0) continue;
        const dz = z - cz;
        const xp = dx * cos - dz * sin; // rotated x relative to the slice center
        let col = Math.round((cx + xp) * scale);
        if (col < 0) col = 0;
        else if (col >= cols) col = cols - 1;
        const cell = rowBase + col;
        if (h > maxH[cell]) maxH[cell] = h;
      }
    }
  }
  // Screen row: y=0 (base) is the bottom row, so emit y = rowsScreen-1 … 0.
  // Per-cell tokens (color by heat, glyph by density) are merged into runs:
  // one escape code per run of consecutive same-color cells (ticket 042).
  const lines = [];
  for (let y = rowsScreen - 1; y >= 0; y--) {
    const rowBase = y * cols;
    const parts = [];
    let open = null; // current color code, or null (no run open)
    for (let c = 0; c < cols; c++) {
      const h = maxH[rowBase + c];
      const code = colorCode(h, color256);
      if (code !== open) {
        if (open !== null) parts.push(RESET);
        open = code;
        parts.push(open);
      }
      parts.push(FLAME_GLYPHS[flameGlyphIndex(h)]);
    }
    if (open !== null) parts.push(RESET);
    lines.push(parts.join(''));
  }
  // When the frame fills the last screen row (rows_screen == rows - 1), a
  // trailing '\n' would push the cursor past the bottom edge and scroll the
  // screen EVERY frame — the "running picture" black-screen bug (ticket 044).
  // In that case emit cursor home + lines only: the last row is fully covered
  // by per-cell glyphs, no tail clear needed.
  const fillsLastRow = rowsOpt !== null && rowsScreen === rowsOpt - 1;
  return fillsLastRow
    ? CURSOR_HOME + lines.join('\n')
    : CURSOR_HOME + lines.join('\n') + '\n' + CLEAR_TAIL;
}

module.exports = {
  create, step, render, colorIndex, colorCode,
  mulberry32, flameGlyphIndex, FLAME_GLYPHS, FLAME_MIN, DARK_BG,
  DEFAULT_W, DEFAULT_H, DEFAULT_D, DEFAULT_SEED, DECAY_MIN, DECAY_MAX,
};
