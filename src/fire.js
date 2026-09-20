'use strict';
/*
 * src/fire.js — a realistic terminal fire, zero dependencies.
 *
 * Four separated concerns:
 *   1. Simulation — pure heat-field step (seeded PRNG, deterministic)
 *   2. Palette    — heat value -> 24-bit truecolor (or null for empty)
 *   3. Renderer   — grid -> one ANSI frame string (half-block ▀, 2x vertical)
 *   4. Loop       — IO only, starts only when run as main on a TTY
 *
 * Run:  node src/fire.js          Stop: Ctrl-C (cursor restored, ANSI reset, exit 0)
 */

// ---------- seeded PRNG (mulberry32) ----------
function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------- 1D value noise (smooth, deterministic) ----------
function makeNoise1D(seed) {
  const rng = mulberry32((seed ^ 0x9e3779b9) >>> 0);
  const TABLE = 1024;
  const table = new Float64Array(TABLE);
  for (let i = 0; i < TABLE; i++) table[i] = rng();
  return function noise(t) {
    const i0 = Math.floor(t);
    const f = t - i0;
    const a = table[((i0 % TABLE) + TABLE) % TABLE];
    const b = table[(((i0 + 1) % TABLE) + TABLE) % TABLE];
    const u = f * f * (3 - 2 * f); // smoothstep
    return a + (b - a) * u;
  };
}

// ---------- 1. Simulation ----------

// Create a heat-field grid. `rows` is the number of HEAT rows (the renderer
// draws rows/2 terminal lines with half-blocks). Rows are forced even.
function createFire(cols, rows, seed) {
  const width = Math.max(4, cols);
  const height = Math.max(2, (rows % 2 === 0 ? rows : rows + 1));
  const s = (seed === undefined || seed === null) ? 1 : seed >>> 0;
  return {
    cols: width,
    rows: height,
    heat: new Float64Array(width * height),
    smoke: new Float64Array(width * height),
    time: 0,
    rng: mulberry32(s),
    noise: makeNoise1D(s),
  };
}

// One tick: diffuse upward, cool, sway with turbulence, inject at the base,
// spawn and advect smoke. All values clamped to [0, 1]. Deterministic.
function step(fire) {
  const cols = fire.cols;
  const rows = fire.rows;
  const heat = fire.heat;
  const smoke = fire.smoke;
  const { rng, noise } = fire;
  fire.time += 1;
  const t = fire.time;

  const next = new Float64Array(cols * rows);
  const nextSmoke = new Float64Array(cols * rows);

  // Flicker: global per-frame intensity noise.
  const flicker = 0.75 + 0.5 * noise(t * 0.23 + 7.7); // ~[0.75, 1.25]

  // Turbulence: per-row horizontal sway so the flame licks and sways.
  const sway = (y) => Math.round((noise(t * 0.11 + y * 0.19) - 0.5) * 3);

  // 1) Heat rises with turbulent perturbation and cools.
  for (let y = 0; y < rows; y++) {
    const dx = sway(y);
    for (let x = 0; x < cols; x++) {
      const v = heat[y * cols + x];
      if (v <= 0.001) continue;
      const cooled = v * 0.95;
      // Occasional extra kick makes the flame lick sideways.
      const kick = rng() < 0.18 ? (rng() < 0.5 ? -1 : 1) : 0;
      const nx = Math.max(0, Math.min(cols - 1, x + dx + kick));
      if (y > 0) next[(y - 1) * cols + nx] += cooled * 0.9;
      next[y * cols + x] += cooled * 0.1;
    }
  }

  // 2) Inject at the base: wide base tapering upward, flickering width.
  const cx = (cols - 1) / 2;
  const half = Math.max(2, Math.round(cols * 0.22 * flicker));
  for (let y = rows - 3; y < rows; y++) {
    const rowFade = (y - (rows - 3)) / 2; // 0.5..1, strongest at the bottom
    const w = Math.max(1, Math.round(half * (0.4 + 0.6 * rowFade)));
    const x0 = Math.max(0, Math.round(cx - w));
    const x1 = Math.min(cols - 1, Math.round(cx + w));
    for (let x = x0; x <= x1; x++) {
      const d = Math.abs(x - cx) / w;
      if (d > 1) continue;
      const j = (1 - d * d) * (0.55 + 0.45 * noise(t * 0.31 + x * 0.17)) * flicker * rowFade;
      next[y * cols + x] += j;
    }
  }

  // 3) Smoke: spawn faint particles just above the hot tip, rise, decay.
  for (let y = 0; y < rows; y++) {
    for (let x = 0; x < cols; x++) {
      const s = smoke[y * cols + x];
      if (s > 0.01) {
        if (y > 0) nextSmoke[(y - 1) * cols + x] += s * 0.9;
        nextSmoke[y * cols + x] += s * 0.4;
      }
      if (y > 2 && heat[y * cols + x] > 0.25 &&
          heat[(y - 1) * cols + x] < 0.08 && rng() < 0.3) {
        nextSmoke[(y - 1) * cols + x] += 0.08 + 0.12 * rng();
      }
    }
  }

  // 4) Clamp to [0, 1].
  for (let i = 0; i < next.length; i++) {
    next[i] = next[i] > 1 ? 1 : next[i] < 0 ? 0 : next[i];
    nextSmoke[i] = nextSmoke[i] > 1 ? 1 : nextSmoke[i] < 0 ? 0 : nextSmoke[i];
  }
  fire.heat = next;
  fire.smoke = nextSmoke;
  return fire;
}

// ---------- 2. Palette ----------

// Gradient stops: white-hot core -> yellow -> orange -> red -> dark red.
const STOPS = [
  [0.0, 10, 5, 5],       // near-black (interpolation base)
  [0.1, 70, 12, 0],      // dark red
  [0.35, 170, 30, 8],    // red
  [0.6, 255, 120, 25],   // orange
  [0.85, 255, 210, 90],  // yellow
  [1.0, 255, 255, 235],  // white-hot core
];

// heat value in [0,1] -> {r,g,b} in 0..255, or null for an empty cell.
function palette(t) {
  if (t <= 0) return null;
  if (t >= 1) t = 1;
  for (let i = 1; i < STOPS.length; i++) {
    if (t <= STOPS[i][0]) {
      const [t0, r0, g0, b0] = STOPS[i - 1];
      const [t1, r1, g1, b1] = STOPS[i];
      const u = (t - t0) / (t1 - t0);
      return {
        r: Math.round(r0 + (r1 - r0) * u),
        g: Math.round(g0 + (g1 - g0) * u),
        b: Math.round(b0 + (b1 - b0) * u),
      };
    }
  }
  const last = STOPS[STOPS.length - 1];
  return { r: last[1], g: last[2], b: last[3] };
}

// Faint warm gray for smoke.
function smokeColor(v) {
  const g = Math.min(150, Math.round(50 + 100 * v));
  return { r: g - 10, g: g, b: g + 5 };
}

// ---------- 3. Renderer ----------

const ESC = (c) => `\x1b[38;2;${c.r};${c.g};${c.b}m`;

// grid -> one ANSI frame string. rows/2 terminal lines; each cell is two
// half-block chars: colored '▀' (top heat half) + colored ' ' (bottom half).
// Zero heat -> plain space, no escape.
function render(fire) {
  const cols = fire.cols;
  const rows = fire.rows;
  const heat = fire.heat;
  const smoke = fire.smoke || null;
  const lines = Math.floor(rows / 2);
  const out = [];
  for (let r = 0; r < lines; r++) {
    let line = '';
    for (let x = 0; x < cols; x++) {
      const top = heat[r * 2 * cols + x];
      const bot = heat[(r * 2 + 1) * cols + x];
      const st = smoke ? smoke[r * 2 * cols + x] : 0;
      const sb = smoke ? smoke[(r * 2 + 1) * cols + x] : 0;
      const ct = palette(top);
      const cb = palette(bot);
      line += ct ? ESC(ct) + '▀' : (st > 0.02 ? ESC(smokeColor(st)) + '▀' : ' ');
      line += cb ? ESC(cb) + ' ' : (sb > 0.02 ? ESC(smokeColor(sb)) + ' ' : ' ');
    }
    out.push(line);
  }
  return out.join('\n');
}

// ---------- 4. Loop (IO only) ----------

function start() {
  const cols = (process.stdout.columns && process.stdout.columns > 10)
    ? process.stdout.columns : 80;
  const rows = (process.stdout.rows && process.stdout.rows > 8)
    ? process.stdout.rows : 24;
  // Heat grid is twice the terminal height; flame is centered by the
  // base-injection profile (cx = cols/2).
  const fire = createFire(cols, rows * 2, 1337);

  let timer = null;
  const quit = () => {
    if (timer) clearInterval(timer);
    timer = null;
    process.stdout.write('\x1b[0m\x1b[?25h\n'); // reset ANSI, restore cursor
    process.exit(0);
  };
  process.on('SIGINT', quit);

  process.stdout.write('\x1b[?25l'); // hide cursor
  timer = setInterval(() => {
    step(fire);
    process.stdout.write('\x1b[2J\x1b[H' + render(fire));
  }, 33); // ~30 FPS
}

// Animate only when executed directly in an interactive terminal; as a module
// (require) or with piped stdout (smoke/test) this stays inert.
if (require.main === module && process.stdout.isTTY) {
  start();
}

module.exports = {
  mulberry32,
  makeNoise1D,
  createFire,
  step,
  palette,
  smokeColor,
  render,
};
