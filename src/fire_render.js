'use strict';

// Color stops for the heat->RGB ramp: [h, r, g, b].
const STOPS = [
  [0.0, 0, 0, 0],
  [0.25, 128, 0, 0],
  [0.5, 255, 64, 0],
  [0.75, 255, 160, 0],
  [1.0, 255, 255, 255],
];

function clamp(v, lo, hi) {
  return v < lo ? lo : v > hi ? hi : v;
}

// Piecewise-linear interpolation over the stops; each channel rounded to the
// nearest integer. Pure function of h in [0,1].
function ramp(h) {
  h = clamp(h, 0, 1);
  let i = 0;
  while (i < STOPS.length - 1 && h > STOPS[i + 1][0]) i++;
  const [t0, r0, g0, b0] = STOPS[i];
  const [t1, r1, g1, b1] = STOPS[i + 1];
  const f = (h - t0) / (t1 - t0);
  return [
    Math.round(r0 + (r1 - r0) * f),
    Math.round(g0 + (g1 - g0) * f),
    Math.round(b0 + (b1 - b0) * f),
  ];
}

// Symbol map: 0 -> ' ', (0,0.25] -> '░', (0.25,0.5] -> '▒', (0.5,0.75] -> '▓', (0.75,1] -> '█'.
function symbolFor(h) {
  h = clamp(h, 0, 1);
  if (h === 0) return ' ';
  if (h <= 0.25) return '░';
  if (h <= 0.5) return '▒';
  if (h <= 0.75) return '▓';
  return '█';
}

// Render a model state ({width, height, heat} row-major, row 0 = top) into a
// string of `height` lines joined by '\n' (no trailing newline). Read-only:
// never mutates the state.
function renderFrame(state, { mode = 'ansi256' } = {}) {
  const { width, height, heat } = state;
  const lines = new Array(height);

  if (mode === 'symbols') {
    for (let r = 0; r < height; r++) {
      const row = r * width;
      let line = '';
      for (let c = 0; c < width; c++) {
        line += symbolFor(heat[row + c]);
      }
      lines[r] = line;
    }
  } else {
    for (let r = 0; r < height; r++) {
      const row = r * width;
      let line = '';
      for (let c = 0; c < width; c++) {
        const [rr, gg, bb] = ramp(heat[row + c]);
        line += '\x1b[38;2;' + rr + ';' + gg + ';' + bb + 'm█';
      }
      lines[r] = line;
    }
  }

  return lines.join('\n');
}

module.exports = { renderFrame, ramp };
