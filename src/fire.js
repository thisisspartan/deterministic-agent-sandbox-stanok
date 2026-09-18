'use strict';
// src/fire.js — realistic terminal fire (TASK-STANOK-CC-078).
// Zero external dependencies; node built-ins only.
//
// Four separated concerns:
//   1. Simulation  — createFireSim(): 2D heat field + smoke particles,
//                    seeded PRNG, deterministic per seed.
//   2. Palette     — palette() / paletteRGB(): heat [0,1] → truecolor SGR.
//   3. Renderer    — render(): grid + smoke → one ANSI frame string (half-blocks).
//   4. Loop        — main guard: animated TTY demo only when run directly.

// ---------------------------------------------------------------------------
// Deterministic PRNG (mulberry32) and value noise
// ---------------------------------------------------------------------------

function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296; // [0, 1)
  };
}

// 2D value noise on an integer lattice, bilinearly interpolated with
// smoothstep. Deterministic for a given seed; output in [0, 1].
function makeValueNoise(seed) {
  function lattice(x, y) {
    let h = (Math.imul(x, 374761393) + Math.imul(y, 668265263) + (seed | 0)) | 0;
    h = (Math.imul(h, 668265263) ^ (h >>> 13)) | 0;
    h = (Math.imul(h, 2246822519) ^ (h >>> 16)) | 0;
    return (h >>> 0) / 4294967296;
  }
  return function noise(x, y) {
    const x0 = Math.floor(x);
    const y0 = Math.floor(y);
    const fx = x - x0;
    const fy = y - y0;
    const sx = fx * fx * (3 - 2 * fx);
    const sy = fy * fy * (3 - 2 * fy);
    const a = lattice(x0, y0);
    const b = lattice(x0 + 1, y0);
    const c = lattice(x0, y0 + 1);
    const d = lattice(x0 + 1, y0 + 1);
    return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy;
  };
}

// ---------------------------------------------------------------------------
// 1. Simulation — heat field + smoke particles
// ---------------------------------------------------------------------------

function makeGrid(width, height) {
  const rows = [];
  for (let y = 0; y < height; y++) rows.push(new Float64Array(width));
  return rows;
}

// Row y=0 is the TOP of the screen; the flame base sits at y = height-1.
function createFireSim(width, height, seed) {
  const W = width;
  const H = height;
  const cx = (W - 1) / 2;
  const baseHalf = Math.max(3, Math.floor(W * 0.22)); // half-width of the base
  const rand = mulberry32(seed >>> 0);
  const noise = makeValueNoise((seed ^ 0x51ed270b) >>> 0);

  let grid = makeGrid(W, H);
  let smoke = makeGrid(W, H);
  let t = 0;
  const particles = [];

  // Wide base tapering upward: allowed half-width shrinks toward the top.
  function halfWidthAt(y) {
    const f = (H - 1 - y) / H;
    return baseHalf * Math.pow(f, 1.1) + 1.2;
  }

  function tick() {
    t += 1;
    // Global flicker: whole-frame intensity noise.
    const flicker = 0.82 + 0.18 * noise(t * 0.11, 7.31);
    const next = makeGrid(W, H);

    // Diffuse upward + per-cell turbulence (sway/lick).
    for (let y = H - 2; y >= 0; y--) {
      const src = grid[y + 1];
      const dst = next[y];
      for (let x = 0; x < W; x++) {
        const n = noise(x * 0.13, y * 0.13 + t * 0.11);
        const ox = Math.round((n - 0.5) * 3.2); // -2..2 horizontal drift
        let sx = x - ox;
        if (sx < 0) sx = 0;
        else if (sx >= W) sx = W - 1;
        const l = sx > 0 ? src[sx - 1] : 0;
        const r = sx < W - 1 ? src[sx + 1] : 0;
        dst[x] = (src[sx] * 0.6 + (l + r) * 0.2) * 0.985; // 1.5% cooling per row
      }
    }
    // Top of the screen: hard fade so the flame does not pin to the ceiling.
    for (let x = 0; x < W; x++) next[H - 1][x] = grid[H - 1][x] * 0.45;

    // Taper mask: damp everything outside the flame silhouette.
    for (let y = 0; y < H; y++) {
      const hw = halfWidthAt(y);
      const dst = next[y];
      for (let x = 0; x < W; x++) {
        const d = Math.abs(x - cx);
        if (d > hw) {
          const k = 1 - (d - hw) * 0.4;
          dst[x] *= k > 0 ? k : 0;
        }
      }
    }

    // Heat injection at the base: wide, uneven (per-column noise), flickering.
    const inject = (y, mul) => {
      const dst = next[y];
      for (let x = 0; x < W; x++) {
        const d = Math.abs(x - cx);
        const shape = 1 - d / (baseHalf + 0.5);
        if (shape <= 0) continue;
        const v = shape * flicker * mul * (0.85 + 0.3 * noise(x * 0.31, t * 0.13));
        if (v > dst[x]) dst[x] = Math.min(1, v);
      }
    };
    inject(H - 1, 1);
    inject(H - 2, 0.85);

    // Clamp to [0, 1].
    for (let y = 0; y < H; y++) {
      const dst = next[y];
      for (let x = 0; x < W; x++) {
        let v = dst[x];
        if (v < 0) v = 0;
        else if (v > 1) v = 1;
        dst[x] = v;
      }
    }
    grid = next;

    // Smoke: faint gray particles spawning above the flame tip, rising with
    // turbulent drift, fading out.
    const tipY = Math.max(2, Math.round(H * 0.35));
    if (rand() < 0.75) {
      particles.push({
        x: cx + (rand() - 0.5) * baseHalf * 1.1,
        y: tipY + (rand() - 0.5) * 4,
        life: 0.75 + rand() * 0.35,
      });
    }
    while (particles.length > 70) particles.shift();

    const nsmoke = makeGrid(W, H);
    const put = (xx, yy, v) => {
      if (xx >= 0 && xx < W && yy >= 0 && yy < H && v > nsmoke[yy][xx]) {
        nsmoke[yy][xx] = v;
      }
    };
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.y -= 0.7 + rand() * 0.9;
      p.x += (noise(p.x * 0.21, p.y * 0.21 + t * 0.07) - 0.5) * 1.8;
      p.life -= 0.022;
      if (p.life <= 0 || p.y < 0) {
        particles.splice(i, 1);
        continue;
      }
      const px = Math.round(p.x);
      const py = Math.floor(p.y);
      const s = p.life * 0.5; // faint: smoke never exceeds 0.5
      put(px, py, s);
      put(px - 1, py, s * 0.4);
      put(px + 1, py, s * 0.4);
    }
    smoke = nsmoke;
  }

  return {
    width: W,
    height: H,
    tick,
    get grid() { return grid; },
    get smoke() { return smoke; },
  };
}

// ---------------------------------------------------------------------------
// 2. Palette — heat [0,1] → multi-stop truecolor gradient
// ---------------------------------------------------------------------------

// white-hot core → yellow → orange → red → dark red → transparent
const STOPS = [
  [0.0, 0, 0, 0],
  [0.12, 60, 6, 0],
  [0.3, 150, 32, 2],
  [0.5, 226, 88, 8],
  [0.7, 255, 158, 28],
  [0.85, 255, 214, 90],
  [1.0, 255, 255, 235],
];

function paletteRGB(heat) {
  const h = Math.min(1, Math.max(0, heat));
  if (h <= 0.01) return null; // zero heat → no cell
  let i = 1;
  while (i < STOPS.length - 1 && h > STOPS[i][0]) i++;
  const [h0, r0, g0, b0] = STOPS[i - 1];
  const [h1, r1, g1, b1] = STOPS[i];
  const f = (h - h0) / (h1 - h0);
  return [
    Math.round(r0 + (r1 - r0) * f),
    Math.round(g0 + (g1 - g0) * f),
    Math.round(b0 + (b1 - b0) * f),
  ];
}

// Heat → truecolor ANSI SGR string, or '' for zero heat (empty cell).
function palette(heat) {
  const rgb = paletteRGB(heat);
  if (!rgb) return '';
  return '\x1b[38;2;' + rgb[0] + ';' + rgb[1] + ';' + rgb[2] + ' m';
}

// ---------------------------------------------------------------------------
// 3. Renderer — grid + smoke → one ANSI frame string
// ---------------------------------------------------------------------------
//
// Half-block (U+2580 ▀): the TOP half of the character takes the foreground
// color, the BOTTOM half takes the background color, giving 2x vertical
// resolution: grid row 2r → fg, grid row 2r+1 → bg of character row r.
// A grid of width W x height H (H even) renders to H/2 lines of W columns.

const FG = '\x1b[38;2;';
const BG = '\x1b[48;2;';

function sgr(prefix, rgb) {
  return prefix + rgb[0] + ';' + rgb[1] + ';' + rgb[2] + ' m';
}

function render(grid, smoke, width, height) {
  const W = width;
  const lines = [];
  for (let r = 0; r * 2 < height; r++) {
    const top = grid[r * 2];
    const bot = grid[r * 2 + 1];
    const st = smoke ? smoke[r * 2] : null;
    const sb = smoke ? smoke[r * 2 + 1] : null;
    let line = '';
    for (let x = 0; x < W; x++) {
      const ht = top[x];
      const hb = bot[x];
      if (ht < 0.02 && hb < 0.02) {
        const s = Math.max(st ? st[x] : 0, sb ? sb[x] : 0);
        if (s > 0.12) {
          const g = Math.min(255, Math.round(80 + s * 150)); // faint gray
          line += sgr(FG, [g, g, g]) + sgr(BG, [0, 0, 0]) + '░';
        } else {
          line += ' ';
        }
      } else {
        const fg = paletteRGB(ht) || [0, 0, 0];
        const bg = paletteRGB(hb) || [0, 0, 0];
        line += sgr(FG, fg) + sgr(BG, bg) + '▀';
      }
    }
    lines.push(line);
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 4. Loop — IO only; starts ONLY when run as main on a TTY
// ---------------------------------------------------------------------------

const FPS = 30;
const HIDE_CURSOR = '\x1b[?25l';
const SHOW_CURSOR = '\x1b[?25h';
const RESET_ANSI = '\x1b[0m';
const CURSOR_HOME = '\x1b[H';

function start() {
  const W = process.stdout.columns || 80;
  const R = process.stdout.rows || 24;
  const H = R * 2; // half-block: two grid rows per character row
  const sim = createFireSim(W, H, (Date.now() ^ 0x2545f491) >>> 0);
  const out = process.stdout;
  let stopped = false;

  const stop = () => {
    if (stopped) return;
    stopped = true;
    clearInterval(timer);
    out.write(RESET_ANSI);
    out.write(SHOW_CURSOR);
    process.exit(0);
  };

  out.write(HIDE_CURSOR);
  process.on('SIGINT', stop);

  const timer = setInterval(() => {
    sim.tick();
    out.write(CURSOR_HOME);
    out.write(render(sim.grid, sim.smoke, W, H));
  }, 1000 / FPS);
}

if (require.main === module && process.stdout.isTTY) {
  start();
}

module.exports = {
  mulberry32,
  makeValueNoise,
  createFireSim,
  palette,
  paletteRGB,
  render,
  FPS,
};
