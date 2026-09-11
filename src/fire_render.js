'use strict';

// Fire renderer: maps a model state's heat field to a string frame.
//
// Two modes:
//   - 'ansi256' (default): each cell is an RGB escape sequence plus the block
//     glyph: '\x1b[38;2;r;g;bm' + '█'.
//   - 'symbols': each cell is a single bracket-style character (no escapes).
//
// Pure and deterministic: renderFrame only reads state.heat/width/height.

// Color stops for the heat ramp, h in [0,1].
const STOPS = [
  { h: 0.0, c: [0, 0, 0] },
  { h: 0.25, c: [128, 0, 0] },
  { h: 0.5, c: [255, 64, 0] },
  { h: 0.75, c: [255, 160, 0] },
  { h: 1.0, c: [255, 255, 255] },
];

// Piecewise-linear interpolation across STOPS. Returns [r, g, b] with each
// channel rounded to the nearest integer.
function ramp(h) {
  if (h <= STOPS[0].h) return STOPS[0].c.slice();
  const last = STOPS[STOPS.length - 1];
  if (h >= last.h) return last.c.slice();
  for (let i = 0; i < STOPS.length - 1; i++) {
    const a = STOPS[i];
    const b = STOPS[i + 1];
    if (h >= a.h && h <= b.h) {
      const t = (h - a.h) / (b.h - a.h);
      return [
        Math.round(a.c[0] + t * (b.c[0] - a.c[0])),
        Math.round(a.c[1] + t * (b.c[1] - a.c[1])),
        Math.round(a.c[2] + t * (b.c[2] - a.c[2])),
      ];
    }
  }
  return last.c.slice();
}

// Single-character bracket map (no escape sequences).
function symbolFor(h) {
  if (h <= 0) return ' ';
  if (h <= 0.25) return '░';
  if (h <= 0.5) return '▒';
  if (h <= 0.75) return '▓';
  return '█';
}

function renderFrame(state, opts) {
  const mode = (opts && opts.mode) || 'ansi256';
  const { width, height, heat } = state;
  const lines = new Array(height);
  for (let r = 0; r < height; r++) {
    const row = r * width;
    let line = '';
    for (let c = 0; c < width; c++) {
      const h = heat[row + c];
      if (mode === 'symbols') {
        line += symbolFor(h);
      } else {
        const [rr, g, b] = ramp(h);
        line += '\x1b[38;2;' + rr + ';' + g + ';' + b + 'm' + '█';
      }
    }
    lines[r] = line;
  }
  return lines.join('\n');
}

module.exports = { renderFrame, ramp };
