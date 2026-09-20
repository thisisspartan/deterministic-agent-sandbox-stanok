'use strict';
// Terminal fire — a realistic animated flame rendered with 24-bit ANSI truecolor.
//
// Four separated concerns:
//   1. Simulation  — createFire()/tick(): a 2D heat field with seeded PRNG,
//                    upward advection, cooling, turbulence (per-column sway),
//                    a wide-base tapering shape, global flicker and rising
//                    smoke particles. All heat values normalized to [0, 1].
//   2. Palette     — heatToRGB()/heatToColor(): multi-stop gradient
//                    white-hot core -> yellow -> orange -> red -> dark red,
//                    emitting `\x1b[38;2;R;G;B m`. Zero heat -> empty cell.
//   3. Renderer    — renderFrame(): grid -> one ANSI frame string (one
//                    full-block char per cell; frame dims == grid dims).
//   4. Loop        — run(): IO only, started ONLY when run as main on a TTY.
// Zero dependencies, CommonJS.

// ---------------------------------------------------------------------------
// Seeded PRNG (mulberry32) — deterministic frames for a given seed.
// ---------------------------------------------------------------------------
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------------------------------------------------------------------------
// 1. Simulation — pure functions over a state object (no IO).
// ---------------------------------------------------------------------------

/**
 * Create a fire simulation. Pre-warmed so the flame is already burning.
 * @param {{width?: number, height?: number, seed?: number}} opts
 */
function createFire(opts = {}) {
  const w = Math.max(8, opts.width | 0 || 48);
  const h = Math.max(8, opts.height | 0 || 24);
  const seed = opts.seed === undefined ? 1337 : opts.seed >>> 0;
  const state = {
    w,
    h,
    width: w,
    height: h,
    seed,
    tick: 0,
    heat: new Float64Array(w * h), // [0, 1]
    sway: new Float64Array(w),     // per-column turbulence offsets
    smoke: [],                     // { x, y, life } faint gray particles
    rng: mulberry32(seed),
  };
  for (let i = 0; i < 30; i++) tick(state);
  return state;
}

/**
 * Advance the simulation by one tick (deterministic for a given seed).
 * Mutates the state in place.
 */
function tick(s) {
  const { w, h, rng } = s;
  const prev = s.heat;
  const next = new Float64Array(w * h);
  const cx = (w - 1) / 2;
  s.tick += 1;

  // Flicker: global intensity noise for this frame.
  const flicker = 0.75 + 0.5 * rng();

  // Turbulence: per-column random walk (sway), decaying, bounded.
  for (let x = 0; x < w; x++) {
    let sw = (s.sway[x] + (rng() - 0.5) * 0.35) * 0.94;
    if (sw > 3) sw = 3;
    if (sw < -3) sw = -3;
    s.sway[x] = sw;
  }

  // Advection upward + turbulence perturbation + lateral diffusion + cooling.
  // (Heat injected at row h-1 rises into row h-2, and so on.)
  for (let y = h - 2; y >= 1; y--) {
    const rise = (h - 1 - y) / (h - 1); // 0 at the base, 1 at the top
    for (let x = 0; x < w; x++) {
      const ox = s.sway[x] * rise * 1.5; // sways more the higher you go
      const sx = Math.min(w - 1, Math.max(0, Math.round(x - ox)));
      const v = prev[(y + 1) * w + sx] * 0.82; // cooling while rising
      const l = prev[(y + 1) * w + Math.max(0, x - 1)];
      const r = prev[(y + 1) * w + Math.min(w - 1, x + 1)];
      next[y * w + x] = v + (l + r) * 0.04; // softening diffusion
    }
  }

  // Base injection: a wide hearth whose flames lick independently per column.
  for (let x = 0; x < w; x++) {
    const dx = Math.abs(x - cx) / cx;        // 0 at center, 1 at edges
    const widthMask = Math.max(0, 1 - dx * dx);
    const lick = 0.65 + 0.35 * rng();
    const inject = flicker * widthMask * lick;
    const i = (h - 1) * w + x;
    next[i] = Math.min(1, next[i] + inject);
    const i2 = (h - 2) * w + x;
    next[i2] = Math.min(1, next[i2] + inject * 0.85);
  }

  // Flame shape: wide base tapering upward; the whole column drifts with
  // the turbulence as it rises.
  for (let y = 0; y < h; y++) {
    const rise = (h - 1 - y) / (h - 1);
    const halfW = cx * (1 - 0.8 * rise * rise);
    const center = cx + s.sway[Math.round(cx)] * rise * 2;
    for (let x = 0; x < w; x++) {
      const d = Math.abs(x - center);
      if (d > halfW) {
        const falloff = 1 - Math.min(1, (d - halfW) / (2 + halfW * 0.2));
        next[y * w + x] *= Math.max(0, falloff);
      }
    }
  }

  // Smoke: faint gray particles spawned above the flame top, drifting up.
  let topRow = -1;
  for (let y = 0; y < h && topRow < 0; y++) {
    let max = 0;
    for (let x = 0; x < w; x++) max = Math.max(max, prev[y * w + x]);
    if (max > 0.5) topRow = y;
  }
  for (const p of s.smoke) {
    p.y -= 0.6 + rng() * 0.5;
    p.x += (rng() - 0.5) * 0.4 + s.sway[Math.min(w - 1, Math.max(0, Math.round(p.x)))] * 0.15;
    p.life -= 0.015;
  }
  s.smoke = s.smoke.filter((p) => p.life > 0 && p.y > -2);
  if (topRow >= 0) {
    for (let x = 0; x < w; x++) {
      if (rng() < 0.15 && prev[topRow * w + x] > 0.5) {
        s.smoke.push({
          x: x + (rng() - 0.5),
          y: topRow - 1 - rng() * 2,
          life: 0.5 + rng() * 0.5,
        });
      }
    }
  }

  // Clamp the whole field to [0, 1].
  for (let i = 0; i < next.length; i++) {
    const v = next[i];
    next[i] = !Number.isFinite(v) || v < 0 ? 0 : v > 1 ? 1 : v;
  }
  s.heat = next;
}

// ---------------------------------------------------------------------------
// 2. Palette — heat value -> 24-bit truecolor.
// ---------------------------------------------------------------------------

// Multi-stop gradient: dark red -> red -> orange -> yellow -> white-hot.
const STOPS = [
  [0.0, 0, 0, 0],
  [0.08, 70, 10, 5],
  [0.3, 160, 40, 10],
  [0.55, 235, 95, 20],
  [0.75, 255, 155, 40],
  [0.88, 255, 210, 90],
  [0.96, 255, 245, 210],
  [1.0, 255, 255, 255],
];

/** Heat in [0,1] -> [r, g, b], each an integer in 0..255. */
function heatToRGB(h) {
  h = Math.max(0, Math.min(1, h));
  for (let i = 1; i < STOPS.length; i++) {
    if (h <= STOPS[i][0]) {
      const [h0, r0, g0, b0] = STOPS[i - 1];
      const [h1, r1, g1, b1] = STOPS[i];
      const f = h1 === h0 ? 0 : (h - h0) / (h1 - h0);
      return [
        Math.round(r0 + (r1 - r0) * f),
        Math.round(g0 + (g1 - g0) * f),
        Math.round(b0 + (b1 - b0) * f),
      ];
    }
  }
  const last = STOPS[STOPS.length - 1];
  return [last[1], last[2], last[3]];
}

/** Heat below this renders as an empty (plain space) cell. */
const EMPTY_THRESHOLD = 0.02;

/** Heat value -> truecolor ANSI SGR string, or '' for a dead cell. */
function heatToColor(h) {
  if (h <= EMPTY_THRESHOLD) return '';
  const [r, g, b] = heatToRGB(h);
  return `\x1b[38;2;${r};${g};${b}m`;
}

// ---------------------------------------------------------------------------
// 3. Renderer — grid -> one ANSI frame string (pure, no IO).
// One full-block char per grid cell; frame dimensions == grid dimensions.
// ---------------------------------------------------------------------------
function renderFrame(s) {
  const { w, h } = s;
  // One [color, char] pair per grid cell (built cell-by-cell so overlays
  // can never slice into an ANSI escape sequence).
  const cells = new Array(w * h);
  for (let i = 0; i < w * h; i++) {
    const c = heatToColor(s.heat[i]);
    cells[i] = c ? [c, '█'] : ['', ' '];
  }
  // Smoke overlay: faint gray particles rising above the flame.
  for (const p of s.smoke) {
    const px = Math.round(p.x);
    const py = Math.round(p.y);
    if (px < 0 || px >= w || py < 0 || py >= h) continue;
    const i = py * w + px;
    if (s.heat[i] > EMPTY_THRESHOLD) continue;
    const a = Math.max(0, Math.min(1, p.life));
    const g = Math.round(90 * a);
    cells[i] = [`\x1b[38;2;${g};${g};${g}m`, '░'];
  }
  const lines = new Array(h);
  for (let y = 0; y < h; y++) {
    let row = '';
    for (let x = 0; x < w; x++) {
      const [c, ch] = cells[y * w + x];
      row += c ? c + ch + '\x1b[0m' : ch;
    }
    lines[y] = row;
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 4. Loop — IO only. Started ONLY when this file is run as the main module
//    on a TTY. Ctrl-C (SIGINT) stops the interval, restores the cursor,
//    resets ANSI state and exits 0.
// ---------------------------------------------------------------------------
function run(opts = {}) {
  const cols = process.stdout.columns > 0 ? process.stdout.columns : 80;
  const rows = process.stdout.rows > 0 ? process.stdout.rows : 24;
  const w = Math.min(64, Math.max(12, cols - 8));
  const h = Math.min(30, Math.max(8, rows - 4));
  const fps = opts.fps || 30;
  const fire = createFire({ width: w, height: h, seed: opts.seed });

  const padL = Math.max(0, Math.floor((cols - w) / 2)); // centered flame
  const padT = Math.max(0, Math.floor((rows - h) / 2));
  const pad = ' '.repeat(padL);
  const blank = ' '.repeat(cols);

  let stopped = false;
  let timer;
  const stop = () => {
    if (stopped) return;
    stopped = true;
    clearInterval(timer);
    process.stdout.write('\x1b[0m\x1b[?25h\n'); // reset ANSI, restore cursor
    process.exit(0);
  };

  const draw = () => {
    tick(fire);
    const lines = renderFrame(fire).split('\n');
    const out = ['\x1b[2J\x1b[H']; // clear screen, cursor home
    for (let i = 0; i < padT; i++) out.push(blank);
    for (const l of lines) out.push(pad + l);
    process.stdout.write(out.join('\n'));
  };

  process.stdout.write('\x1b[?25l'); // hide cursor (first output)
  draw();
  timer = setInterval(draw, Math.round(1000 / fps));
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
}

module.exports = {
  mulberry32,
  createFire,
  tick,
  heatToRGB,
  heatToColor,
  renderFrame,
  run,
  EMPTY_THRESHOLD,
};

if (require.main === module && process.stdout.isTTY) {
  run();
}
