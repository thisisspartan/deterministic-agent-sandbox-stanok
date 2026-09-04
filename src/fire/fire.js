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

// --- ticket 035: fire life cycle (BURN -> DIE -> EMBER -> REKINDLE) -----------
// The cycle is driven by a step counter (30 FPS), fully deterministic: same
// seed => identical phase sequence. BURN keeps the classic steady flame; DIE
// fades the source multiplier 1.0 -> DIE_MIN linearly; EMBER kills the source
// and lets a few embers glow in the window base; REKINDLE ramps the multiplier
// 0 -> 1.0. Phase transitions are counted by steps, not wall-clock time.
const PHASE_BURN = 0;
const PHASE_DIE = 1;
const PHASE_EMBER = 2;
const PHASE_REKINDLE = 3;
const BURN_STEPS = 5400;       // ~3 min at 30 FPS
const DIE_STEPS = 360;         // ~12 s
const DIE_MIN = 0.15;          // source multiplier at the end of DIE
const EMBER_STEPS = 240;       // ~8 s
const REKINDLE_STEPS = 240;    // ~8 s
const PHASE_STEPS = [BURN_STEPS, DIE_STEPS, EMBER_STEPS, REKINDLE_STEPS];
const EMBER_ROWS = 2;          // ember rows: base-2, base-3 (window base)
const EMBER_COUNT = 6;         // how many ember cells smoulder
const EMBER_FLICK_PERIOD = 8;  // ember flicker period (longer than flame flicker)
const EMBER_FLICK_AMP = 0.05;  // small flicker amplitude
const EMBER_BASE_MIN = 0.12;   // ember core heat base in [0.12 .. 0.24]
const EMBER_BASE_SPAN = 0.12;
const SPARK_SOURCE_MIN = 0.3;  // sparks re-ignite only above this source strength

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

  // --- ticket 035: life cycle (step-counted, deterministic) --------------------
  let phase = PHASE_BURN;
  let phaseStep = 0;   // steps elapsed inside the current phase
  let embers = [];    // [{y, x, base, off}] smouldering cells of the window base

  // Source strength multiplier for the current phase (BURN => 1, DIE fades to
  // DIE_MIN, EMBER => 0, REKINDLE ramps 0 -> 1 with a smoothstep flare).
  function sourceMult() {
    switch (phase) {
      case PHASE_DIE:
        return 1 - (1 - DIE_MIN) * (phaseStep / DIE_STEPS);
      case PHASE_EMBER:
        return 0;
      case PHASE_REKINDLE: {
        const t = phaseStep / REKINDLE_STEPS;
        return t * t * (3 - 2 * t); // slow ignition, fast flare-up at the end
      }
      default:
        return 1; // BURN
    }
  }

  // Entering EMBER: pick a fixed PRNG subset of the source-zone cells in the
  // window base (1-2 rows above the plinth) — those will smoulder as embers.
  function enterEmbers() {
    embers = [];
    const rows = [base - 2, base - 3];
    for (let i = 0; i < EMBER_COUNT; i++) {
      embers.push({
        y: rows[i % rows.length],
        x: srcL + 1 + Math.floor(rng() * Math.max(1, srcHalf - 2)),
        base: EMBER_BASE_MIN + rng() * EMBER_BASE_SPAN,
        off: Math.floor(rng() * EMBER_FLICK_PERIOD),
      });
    }
  }

  function step() {
    // Advance the phase machine first: transitions fire on step counts, so the
    // source of THIS frame already reflects the new phase (BURN->DIE is
    // continuous at mult=1, EMBER->REKINDLE at mult=0).
    phaseStep++;
    if (phaseStep >= PHASE_STEPS[phase]) {
      phaseStep = 0;
      phase = (phase + 1) % PHASE_STEPS.length;
      if (phase === PHASE_EMBER) enterEmbers();
    }

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
    // Ticket 035: multiplied by the phase source multiplier (BURN=1, DIE fades
    // to DIE_MIN, EMBER=0, REKINDLE ramps 0->1).
    const mult = sourceMult();
    for (let x = 0; x < W; x++) {
      const m = srcMask[x];
      if (m === 0) { b[x] = 0; continue; }
      const fl = FLICKER_LOW + FLICKER_HIGH * rng();
      b[x] = clamp01(m * (BASE_FLOOR + fl) * breath * mult);
    }
    // Ticket 035 EMBER: the source is out, but a PRNG-chosen subset of the
    // window-base cells smoulders as embers — a slow sine (period
    // EMBER_FLICK_PERIOD, longer than flame flicker) plus a small per-frame
    // jitter. They live in rows 1-2 above the plinth, inside the source zone.
    if (phase === PHASE_EMBER) {
      for (const e of embers) {
        if (e.y < 0 || e.y >= H) continue;
        const sway = Math.sin(2 * Math.PI * (frame + e.off) / EMBER_FLICK_PERIOD);
        next[e.y][e.x] = clamp01(e.base + EMBER_FLICK_AMP * sway + (rng() - 0.5) * 0.04);
      }
    }
    for (let y = 0; y < H; y++) heat[y] = next[y];
    frame++;

    // Sparks: rise, fade, respawn inside the source zone (life or top exit).
    // Ticket 035: a spark can re-ignite only above a minimum source strength
    // — in EMBER/late-DIE they park at the plinth base (a frame row, where
    // render() skips them) until the fire is strong enough again. No
    // hardcoding by phase name: it follows the physical source multiplier.
    const dt = 1;
    for (const s of sparks) {
      if (s.dead) {
        if (mult >= SPARK_SOURCE_MIN) { s.dead = false; respawn(s); }
        continue;
      }
      s.y += s.vy * dt;
      s.x += (rng() - 0.5) * 0.2 * dt; // lateral drift
      // Keep sparks inside the flame column (F4).
      if (s.x < srcL + 0.5) s.x = srcL + 0.5;
      else if (s.x >= srcR - 0.5) s.x = srcR - 0.5;
      s.life -= 0.004 * dt;
      if (s.life <= 0 || s.y < 0) {
        if (mult >= SPARK_SOURCE_MIN) {
          respawn(s);
        } else {
          s.dead = true; // park at the base (plinth row, invisible)
          s.y = base;
          s.life = 0.5;
        }
      }
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
//
// Ticket 040: the fireplace frame is gone — the flame burns on the whole
// W×H grid: every cell is a window cell (dark background 234 at heat <= 0,
// density glyph otherwise). Parked (dead) sparks are not drawn.

const ESC = '\u001b';
const CURSOR_HOME = ESC + '[H';
const CLEAR_TAIL = ESC + '[' + 'J';
const SPARK_GLYPH = '\u2726'; // ✦ bright pixel over the flame
const DARK_BG = 234;          // empty-cell background, heat <= 0 (233–235 range)

// --- flame density glyphs (ticket 034 R1) -------------------------------------
//
// Ramp from sparse (index 0 = space) to dense. Must avoid brick glyphs
// (▓█▒ — the frame of ticket 032 has been removed), spark glyph (✦), and
// the log glyphs (=, #, -) that R3 test forbids anywhere in the frame.
// Index 0 is a space so cells with heat <= FLAME_MIN look identical to the
// previous "invisible flame" behavior (background). The last glyph "@" is
// the heaviest visually.
const FLAME_GLYPHS = ' .,;:~*oO@';
const FLAME_MIN = 0.08;

// Ticket 036: map heat to a ramp index with NO gap. heat <= FLAME_MIN -> 0
// (space); heat in (FLAME_MIN, 1] -> index in [1, len-1], monotone in heat and
// continuous from the left at FLAME_MIN (the old floor(heat*(len-1)) left
// (FLAME_MIN, 1/(len-1)) rendering as a space — embers were invisible). Max
// heat maps to the heaviest glyph (len-1).
function flameGlyphIndex(heat) {
  if (heat <= FLAME_MIN) return 0;
  const n = FLAME_GLYPHS.length - 1;
  const u = (heat - FLAME_MIN) / (1 - FLAME_MIN); // 0..1 across the visible range
  const i = Math.round(u * n);
  return i < 1 ? 1 : i > n ? n : i;
}

// Pure: one frame as a single string block. `width` clamps rendered columns on
// narrow terminals; never touches process/io.
//
// Ticket 040: no fireplace frame — every grid cell is rendered: dark
// background (234) at heat <= 0, density glyph otherwise. Parked (dead)
// sparks are invisible.
//
// Rows are built as per-CELL token arrays ({c: colorCode|null, spark: bool})
// and emitted at the end — the spark overlay replaces the CELL at (sx, sy),
// never a raw string offset, so ANSI escape sequences can never be split.
function render(state, width) {
  const H = state.H;
  const W = state.W;
  const cols = typeof width === 'number' && width > 0 ? Math.min(W, width) : W;

  const cells = Array.from({ length: H }, () => Array.from({ length: cols }, () => ({ c: null })));
  for (let y = 0; y < H; y++) {
    const row = state.heat[y];
    const line = cells[y];
    for (let x = 0; x < cols; x++) {
      const h = row[x];
      const idx = h > 0 ? colorIndex(h) : DARK_BG; // dark bg for empty cells
      // Cell with heat > FLAME_MIN carries a density glyph from FLAME_GLYPHS;
      // color code is left untouched.
      const g = FLAME_GLYPHS[flameGlyphIndex(h)];
      line[x] = { c: ESC + '[38;5;' + idx + 'm', glyph: g };
    }
  }
  // Sparks overlay the flame as bright pixels (cell-level replace); parked
  // (dead) sparks are not drawn (ticket 040).
  for (const s of state.sparks) {
    if (s.dead) continue;
    const sy = Math.max(0, Math.min(H - 1, Math.floor(s.y)));
    const sx = Math.max(0, Math.min(cols - 1, Math.floor(s.x)));
    cells[sy][sx].spark = true;
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

module.exports = {
  createFire, render, colorIndex, mulberry32,
  // Ticket 036: deterministic phase access + glyph mapping for tests.
  flameGlyphIndex, FLAME_GLYPHS, FLAME_MIN,
  PHASE_BURN, PHASE_DIE, PHASE_EMBER, PHASE_REKINDLE,
  BURN_STEPS, DIE_STEPS, EMBER_STEPS, REKINDLE_STEPS,
};
