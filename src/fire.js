'use strict';

/**
 * src/fire.js — a realistic, animated fire for the terminal.
 *
 * Four separated concerns:
 *   1. Simulation  — createSimulation(): a 2D heat field, SEEDED (deterministic).
 *   2. Palette     — palette() / paletteRGB(): heat in [0,1] → truecolor ANSI.
 *   3. Renderer    — renderFrame(): grid → one ANSI frame string (half-blocks).
 *   4. Loop (IO)   — starts ONLY when run as main (`require.main === module`)
 *                    and attached to a TTY: `node src/fire.js`.
 *
 * Zero external dependencies (Node built-ins only).
 */

const ESC = '\x1b';

/* ------------------------------------------------------------------ *
 * Deterministic PRNG (mulberry32): same seed → same frame sequence.  *
 * ------------------------------------------------------------------ */
function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
const clampI = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);

/* ------------------------------------------------------------------ *
 * 1. Simulation — 2D heat field: inject at the wide base, diffuse    *
 *    upward, cool per step, perturb by per-column turbulence walks.  *
 *    Also carries a faint smoke field that rises above the flame.    *
 * ------------------------------------------------------------------ */
function createSimulation({ width, height, seed = 0xc0ffee }) {
  if (!Number.isInteger(width) || width < 4) {
    throw new TypeError('width must be an integer >= 4');
  }
  if (!Number.isInteger(height) || height < 4) {
    throw new TypeError('height must be an integer >= 4');
  }

  const rng = mulberry32(seed);
  const empty = () => Array.from({ length: height }, () => new Array(width).fill(0));
  let heat = empty();
  let smoke = empty();

  // Per-column turbulence random walk: makes the flame sway and lick.
  const walk = new Array(width).fill(0);

  const baseRow = height - 1; // bottom row is the fuel bed
  const cx = (width - 1) / 2;
  const halfBase = Math.max(2, Math.round(width * 0.18)); // WIDE base
  const COOL = 0.982; // cooling per upward step

  function tick() {
    // Flicker: global intensity noise per frame.
    const flicker = 0.82 + 0.28 * rng();

    for (let x = 0; x < width; x++) {
      walk[x] += (rng() - 0.5) * 0.7;
      if (walk[x] > 1.2) walk[x] = 1.2;
      else if (walk[x] < -1.2) walk[x] = -1.2;
    }

    const next = empty();

    // Base: wide, brighter in the middle, per-cell noise on top of flicker.
    for (let x = 0; x < width; x++) {
      const d = Math.abs(x - cx) / halfBase;
      if (d <= 1) {
        const env = 1 - d * d;
        next[baseRow][x] = clamp01(
          (0.55 + 0.45 * env) * flicker * (0.85 + 0.15 * rng())
        );
      }
    }

    // Diffuse upward: each cell samples the row below, offset by
    // turbulence (amplitude grows with height → the tip wanders most).
    for (let y = baseRow - 1; y >= 0; y--) {
      const rise = (baseRow - y) / baseRow;
      const below = heat[y + 1];
      for (let x = 0; x < width; x++) {
        const off = Math.round(walk[x] * rise * 1.6);
        const i1 = clampI(x + off, 0, width - 1);
        const i2 = clampI(x + off - 1, 0, width - 1);
        const i3 = clampI(x + off + 1, 0, width - 1);
        next[y][x] = clamp01(
          (0.6 * below[i1] + 0.2 * below[i2] + 0.2 * below[i3]) * COOL
        );
      }
    }
    heat = next;

    // Smoke: seeded above the hottest base cells, drifting upward.
    const smokeNext = empty();
    for (let y = baseRow - 1; y >= 0; y--) {
      const rise = (baseRow - y) / baseRow;
      const below = smoke[y + 1];
      for (let x = 0; x < width; x++) {
        const off = Math.round(walk[x] * rise * 2.2);
        smokeNext[y][x] = clamp01(
          below[clampI(x + off, 0, width - 1)] * 0.985
        );
      }
    }
    for (let x = 0; x < width; x++) {
      if (heat[1][x] > 0.55 && rng() < 0.35) {
        smokeNext[2][x] = Math.max(smokeNext[2][x], 0.25 + 0.4 * rng());
      }
    }
    smoke = smokeNext;

    return { heat, smoke };
  }

  return { width, height, tick };
}

/* ------------------------------------------------------------------ *
 * 2. Palette — multi-stop gradient: white-hot core → yellow → orange *
 *    → red → dark red → transparent. Truecolor ANSI output.           *
 * ------------------------------------------------------------------ */
const STOPS = [
  [0.0, 0, 0, 0],         // transparent
  [0.08, 130, 25, 10],    // dark red
  [0.25, 255, 60, 0],     // red
  [0.45, 255, 140, 0],    // orange
  [0.7, 255, 215, 80],    // yellow
  [0.88, 255, 250, 200],  // near white
  [1.0, 255, 255, 255],   // white-hot core
];

function paletteRGB(h) {
  if (h <= 0) return [0, 0, 0];
  if (h >= 1) return [255, 255, 255];
  let i = 1;
  while (i < STOPS.length - 1 && STOPS[i][0] < h) i++;
  const [t0, r0, g0, b0] = STOPS[i - 1];
  const [t1, r1, g1, b1] = STOPS[i];
  const f = (h - t0) / (t1 - t0);
  return [
    Math.round(r0 + (r1 - r0) * f),
    Math.round(g0 + (g1 - g0) * f),
    Math.round(b0 + (b1 - b0) * f),
  ];
}

// heat in [0,1] → 24-bit truecolor ANSI SGR; zero heat → empty string
// (the renderer then prints a plain space, no escape).
function palette(h) {
  if (h <= 0) return '';
  const [r, g, b] = paletteRGB(h);
  return `${ESC}[38;2;${r};${g};${b} m`;
}

/* ------------------------------------------------------------------ *
 * 3. Renderer — grid → one ANSI frame string using half-block glyphs *
 *    (▀ ▄ █) for 2× vertical resolution. Contract: cols === grid     *
 *    width, rows === grid height / 2, each row exactly `cols`         *
 *    display characters.                                             *
 * ------------------------------------------------------------------ */
function renderFrame({ heat, smoke }) {
  const height = heat.length;
  const width = heat[0].length;
  const rows = Math.floor(height / 2);
  const lines = new Array(rows);

  for (let i = 0; i < rows; i++) {
    const top = heat[2 * i];
    const bot = heat[2 * i + 1];
    const topSmoke = smoke ? smoke[2 * i] : null;
    const botSmoke = smoke ? smoke[2 * i + 1] : null;
    let line = '';
    for (let x = 0; x < width; x++) {
      const ht = top[x];
      const hb = bot[x];
      if (ht > 0 && hb > 0) {
        line += palette(Math.max(ht, hb)) + '█';
      } else if (ht > 0) {
        line += palette(ht) + '▀';
      } else if (hb > 0) {
        line += palette(hb) + '▄';
      } else {
        const s = Math.max(
          topSmoke ? topSmoke[x] : 0,
          botSmoke ? botSmoke[x] : 0
        );
        if (s > 0.08) {
          // Faint gray smoke.
          const g = Math.round(60 + 90 * Math.min(1, s));
          line += `${ESC}[38;2;${g};${g};${g} m▀`;
        } else {
          line += ' '; // empty cell: plain space, no escape
        }
      }
    }
    lines[i] = line;
  }

  return { frame: lines.join('\n'), cols: width, rows };
}

/* ------------------------------------------------------------------ *
 * 4. Loop (IO only) — animation at ~30 FPS, flame centered in the     *
 *    terminal. Starts ONLY when run as main AND stdout is a TTY;     *
 *    Ctrl-C (SIGINT) stops cleanly: interval cleared, cursor restored,
 *    ANSI state reset, exit 0.                                       *
 * ------------------------------------------------------------------ */
const FRAME_MS = Math.round(1000 / 30); // 30 FPS

function run() {
  const cols = process.stdout.columns > 0 ? process.stdout.columns : 80;
  const rows = process.stdout.rows > 0 ? process.stdout.rows : 24;
  const sim = createSimulation({ width: cols, height: rows * 2, seed: 0xc0ffee });

  let stopped = false;
  let timer;
  const stop = () => {
    if (stopped) return;
    stopped = true;
    if (timer) clearInterval(timer);
    process.stdout.write(`${ESC}[?25h${ESC}[0m\n`); // cursor on, reset ANSI
    process.exit(0);
  };
  process.on('SIGINT', stop);

  process.stdout.write(`${ESC}[?25l${ESC}[2J`); // hide cursor, clear screen

  const draw = () => {
    const { frame } = renderFrame(sim.tick());
    process.stdout.write(`${ESC}[H${frame}\n`);
  };

  draw(); // first frame immediately, then at ~30 FPS
  timer = setInterval(draw, FRAME_MS);
}

if (require.main === module && process.stdout.isTTY) {
  run();
}

module.exports = { mulberry32, createSimulation, palette, paletteRGB, renderFrame, FRAME_MS };
