'use strict';

/**
 * Doom Fire renderer — a pure mapping from a temperature matrix to an ANSI
 * frame buffer. No I/O, no terminal calls, no side effects.
 *
 * The heat model (src/fire_model.js) produces grid[y][x] in [0, maxHeat] where
 * y = 0 is the TOP row. This module turns such a grid into strings ready to be
 * written to a terminal.
 */

const SYMBOLS = ['░', '▒', '▓', '█']; // cold -> hot gradient
const RESET = '\u001b[0m';

/**
 * Build the temperature->ANSI-256-index ramp.
 *
 * PALETTE is a 256-entry array (indexed by normalized position 0..255). It is
 * monotonically non-decreasing: PALETTE[0] is the darkest (black) and
 * PALETTE[255] is the hottest (bright, near-white / red-hot end). The control
 * points trace a black -> red -> orange -> yellow -> white fire gradient using
 * ANSI-256 color indices whose numeric values strictly increase.
 */
function buildPalette() {
  // [position 0..255, ANSI-256 index] control points (index values increasing).
  const pts = [
    [0, 16],   // black
    [51, 52],  // dark red
    [102, 88], // red
    [153, 124],// bright red
    [191, 196],// pure red
    [212, 202],// dark orange
    [224, 208],// orange
    [236, 214],// amber
    [244, 220],// orange-yellow
    [252, 226],// yellow
    [255, 255],// near-white / red-hot
  ];
  const pal = new Array(256);
  for (let i = 0; i < 256; i++) {
    let j = 0;
    while (j < pts.length - 1 && i > pts[j][0]) j++;
    const p0 = pts[j][0];
    const v0 = pts[j][1];
    const p1 = pts[Math.min(j + 1, pts.length - 1)][0];
    const v1 = pts[Math.min(j + 1, pts.length - 1)][1];
    const t = p1 === p0 ? 0 : (i - p0) / (p1 - p0);
    pal[i] = Math.round(v0 + (v1 - v0) * t);
  }
  // Safety: enforce strict non-decreasing (rounding already keeps it monotonic).
  for (let i = 1; i < 256; i++) {
    if (pal[i] < pal[i - 1]) pal[i] = pal[i - 1];
  }
  return pal;
}

/** The exported temperature->color mapping (256 ANSI-256 indices). */
const PALETTE = buildPalette();

function assertGrid(grid) {
  if (!Array.isArray(grid)) {
    throw new TypeError('grid must be an array of arrays of numbers');
  }
  for (let y = 0; y < grid.length; y++) {
    const row = grid[y];
    if (!Array.isArray(row)) {
      throw new TypeError('grid rows must be arrays of numbers');
    }
    for (let x = 0; x < row.length; x++) {
      const v = row[x];
      if (typeof v !== 'number' || !Number.isFinite(v)) {
        throw new TypeError('grid cells must be finite numbers');
      }
    }
  }
}

/** Map a temperature in [0, maxHeat] to a normalized palette position 0..255. */
function tempToPos(t, maxHeat) {
  let p = Math.round((t / maxHeat) * 255);
  if (p < 0) p = 0;
  else if (p > 255) p = 255;
  return p;
}

/**
 * Render a temperature grid into a frame buffer.
 *
 * @param {number[][]} grid  grid[y][x], y = 0 is the TOP row, values in [0, maxHeat].
 * @param {object} [opts]
 * @param {number} [opts.maxHeat=255]   positive number, the scale maximum.
 * @param {'ansi256'|'symbols'} [opts.palette='ansi256']
 * @returns {string[]}  h strings (one per row, top first); each row has exactly w
 *                      visible characters (ANSI escapes are not visible characters).
 */
function renderFrame(grid, opts) {
  assertGrid(grid);

  if (opts === undefined) opts = {};
  if (opts === null || typeof opts !== 'object' || Array.isArray(opts)) {
    throw new TypeError('opts must be an object');
  }

  const maxHeat = opts.maxHeat === undefined ? 255 : opts.maxHeat;
  if (typeof maxHeat !== 'number' || !Number.isFinite(maxHeat) || maxHeat <= 0) {
    throw new TypeError('maxHeat must be a positive number');
  }

  const palette = opts.palette === undefined ? 'ansi256' : opts.palette;
  if (palette !== 'ansi256' && palette !== 'symbols') {
    throw new TypeError('palette must be "ansi256" or "symbols"');
  }

  const rows = [];
  for (let y = 0; y < grid.length; y++) {
    const row = grid[y];
    let line = '';
    for (let x = 0; x < row.length; x++) {
      const t = row[x];
      if (t <= 0) {
        line += ' ';
      } else if (palette === 'ansi256') {
        const n = PALETTE[tempToPos(t, maxHeat)];
        line += '\u001b[38;5;' + n + 'm' + '█' + RESET;
      } else {
        const pos = tempToPos(t, maxHeat);
        let level = Math.floor((pos / 255) * 4);
        if (level > 3) level = 3;
        line += SYMBOLS[level];
      }
    }
    rows.push(line);
  }
  return rows;
}

module.exports = { renderFrame, PALETTE, SYMBOLS };
