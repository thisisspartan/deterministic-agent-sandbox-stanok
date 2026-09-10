'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { renderFrame, PALETTE } = require('../src/fire_render.js');

/** Strip ANSI escape sequences (color codes) so only visible characters remain. */
function visible(s) {
  return s.replace(/\u001b\[[0-9;]*m/g, '');
}

/** Build a grid of w columns and h rows filled with a single value. */
function solid(w, h, v) {
  const grid = [];
  for (let y = 0; y < h; y++) {
    const row = new Array(w);
    for (let x = 0; x < w; x++) row[x] = v;
    grid.push(row);
  }
  return grid;
}

/** Extract every 256-color index of the form \033[38;5;<n>m from a string. */
function ansiIndices(s) {
  const re = /\u001b\[38;5;(\d+)m/g;
  return [...s.matchAll(re)].map((m) => Number(m[1]));
}

test('cold frame: 10x5 all zeros -> 5 rows of 10 visible chars, no non-space glyphs', () => {
  const frame = renderFrame(solid(10, 5, 0));
  assert.equal(frame.length, 5, 'should have 5 rows');
  for (let y = 0; y < 5; y++) {
    assert.equal(visible(frame[y]).length, 10, `row ${y} should have 10 visible chars`);
    assert.equal(visible(frame[y]), ' '.repeat(10), `row ${y} should be all spaces`);
    assert.ok(!/\S/.test(visible(frame[y])), `row ${y} has a non-space visible char`);
  }
});

test('hot frame (ansi256): 10x5 all maxHeat -> every cell is a 256-color block at the hottest index', () => {
  const maxHeat = 255;
  const frame = renderFrame(solid(10, 5, maxHeat), { maxHeat });
  assert.equal(frame.length, 5);
  const hottest = PALETTE[255];
  for (let y = 0; y < 5; y++) {
    const v = visible(frame[y]);
    assert.equal(v.length, 10, `row ${y} should have 10 visible chars`);
    assert.equal(v, '█'.repeat(10), `row ${y} should be all blocks`);
    assert.ok(frame[y].includes('\u001b['), `row ${y} should contain an ANSI escape`);
    const idx = ansiIndices(frame[y]);
    assert.equal(idx.length, 10, `row ${y} should contain 10 color escapes (one per cell)`);
    for (const n of idx) {
      assert.equal(n, hottest, `cell index ${n} should equal hottest palette index ${hottest}`);
    }
  }
});

test('PALETTE is a 256-entry monotonically non-decreasing ramp: coldest darkest, hottest brightest', () => {
  assert.ok(Array.isArray(PALETTE), 'PALETTE should be an array');
  assert.equal(PALETTE.length, 256, 'PALETTE should have 256 entries');
  for (let i = 0; i < 256; i++) {
    assert.equal(typeof PALETTE[i], 'number', `PALETTE[${i}] should be a number`);
    assert.ok(Number.isInteger(PALETTE[i]) && PALETTE[i] >= 0 && PALETTE[i] <= 255,
      `PALETTE[${i}] = ${PALETTE[i]} out of ANSI-256 range`);
    if (i > 0) {
      assert.ok(PALETTE[i] >= PALETTE[i - 1],
        `PALETTE must be non-decreasing, but PALETTE[${i}]=${PALETTE[i]} < PALETTE[${i - 1}]=${PALETTE[i - 1]}`);
    }
  }
  // Far-apart temperatures must map to strictly increasing indices.
  assert.ok(PALETTE[200] > PALETTE[50], 'index for a much hotter temp must be strictly greater');
  assert.ok(PALETTE[255] > PALETTE[0], 'hottest index must exceed coldest index');
});

test('monotonicity (rendered): hotter cell carries a strictly greater ANSI index than a much colder cell', () => {
  const maxHeat = 255;
  // 2 rows x 1 col: top row is colder (t1), bottom row is hotter (t2).
  const grid = [[maxHeat * 0.3], [maxHeat * 0.8]];
  const frame = renderFrame(grid, { maxHeat });
  assert.equal(frame.length, 2);
  const [i1] = ansiIndices(frame[0]);
  const [i2] = ansiIndices(frame[1]);
  assert.ok(Number.isInteger(i1) && Number.isInteger(i2), 'each hot row must contain one color escape');
  assert.ok(i2 > i1, `hotter cell index ${i2} should be > colder cell index ${i1}`);
});

test('symbols mode: only chars from " ░▒▓█", no ANSI, cold=space, hottest=█', () => {
  const maxHeat = 255;
  // Mix cold and hot cells in a 6x3 grid.
  const grid = [
    [0, 0, 0, 0, 0, 0],
    [0, 64, 128, 192, 255, 0],
    [255, 255, 255, 255, 255, 255],
  ];
  const frame = renderFrame(grid, { maxHeat, palette: 'symbols' });
  assert.equal(frame.length, 3);
  const allowed = /^[ ░▒▓█]*$/;
  for (let y = 0; y < 3; y++) {
    assert.ok(!frame[y].includes('\u001b'), `row ${y} must contain no ANSI escapes`);
    assert.ok(allowed.test(frame[y]), `row ${y} contains a character outside " ░▒▓█"`);
    assert.equal(frame[y].length, 6, `row ${y} should have 6 visible chars`);
  }
  // Cold cells are spaces.
  assert.equal(frame[0], ' '.repeat(6), 'all-cold row should be spaces');
  // Hottest cells are █.
  assert.equal(frame[2], '█'.repeat(6), 'all-hot row should be blocks');
  // Cold corner stays a space while a hot corner is a block.
  assert.equal(frame[1][0], ' ', 'cold cell should be a space');
  assert.equal(frame[1][4], '█', 'hottest cell should be █');
});

test('dimensions: 200x60 grid -> exactly 60 rows, each exactly 200 visible chars (ANSI stripped)', () => {
  const frame = renderFrame(solid(200, 60, 128));
  assert.equal(frame.length, 60, 'should have 60 rows');
  for (let y = 0; y < 60; y++) {
    assert.equal(visible(frame[y]).length, 200, `row ${y} should have 200 visible chars`);
  }
});

test('throws TypeError when grid is not an array of arrays of numbers', () => {
  const bad = [null, undefined, 'abc', 42, {}, [[1, 'x']], [[1, 2], ['y']], [1, 2], [null]];
  for (const g of bad) {
    assert.throws(
      () => renderFrame(g),
      TypeError,
      `renderFrame(${String(g)}) should throw TypeError`
    );
  }
});

// --- density (opt-in glyph-density soft edges; ansi256 only, default off) ---
test('density=true (ansi256) maps heat to glyph density: cold cell ░, hot cell █, one color escape each', () => {
  const maxHeat = 255;
  // 2 rows x 1 col: cold cell (t=10), hot cell (t=250).
  const grid = [[10], [250]];
  const frame = renderFrame(grid, { maxHeat, palette: 'ansi256', density: true });
  assert.equal(frame.length, 2);
  // Cold hot-cell renders as level 0 (░), hot cell as level 3 (█).
  assert.equal(visible(frame[0]), '░', 'cold cell should be a dim ░ glyph');
  assert.equal(visible(frame[1]), '█', 'hot cell should be a bright █ glyph');
  // Each row still carries exactly one 256-color escape.
  assert.equal(ansiIndices(frame[0]).length, 1, 'cold row should contain one color escape');
  assert.equal(ansiIndices(frame[1]).length, 1, 'hot row should contain one color escape');
  // ...and each color index is a valid ANSI-256 value.
  assert.ok(ansiIndices(frame[0])[0] >= 0 && ansiIndices(frame[0])[0] <= 255, 'cold index in ANSI-256 range');
  assert.ok(ansiIndices(frame[1])[0] >= 0 && ansiIndices(frame[1])[0] <= 255, 'hot index in ANSI-256 range');
});

test('density=true (ansi256) keeps color monotonic: hotter cell has a strictly greater ANSI index', () => {
  const maxHeat = 255;
  const grid = [[maxHeat * 0.3], [maxHeat * 0.8]];
  const frame = renderFrame(grid, { maxHeat, palette: 'ansi256', density: true });
  assert.equal(frame.length, 2);
  const [i1] = ansiIndices(frame[0]);
  const [i2] = ansiIndices(frame[1]);
  assert.ok(Number.isInteger(i1) && Number.isInteger(i2), 'each hot row must contain one color escape');
  assert.ok(i2 > i1, `hotter cell index ${i2} should be > colder cell index ${i1}`);
});

test('density=false (default) ansi256 uses █ for every hot cell (legacy behavior pinned)', () => {
  const maxHeat = 255;
  const grid = [[0, 5, 128, 250]];
  const frame = renderFrame(grid, { maxHeat });
  assert.equal(frame.length, 1);
  const v = visible(frame[0]);
  assert.equal(v.length, 4, 'row should have 4 visible chars');
  for (let x = 0; x < grid[0].length; x++) {
    if (grid[0][x] <= 0) {
      assert.equal(v[x], ' ', 'cold cell should be a space');
    } else {
      assert.equal(v[x], '█', 'every hot cell should be a solid █ regardless of heat');
    }
  }
});

test('density=true: row length is still w visible chars (ANSI stripped) for a non-trivial grid', () => {
  const maxHeat = 255;
  const grid = [
    [10, 60, 120, 200, 255],
    [0, 40, 90, 180, 250],
    [255, 255, 128, 64, 32],
  ];
  const frame = renderFrame(grid, { maxHeat, palette: 'ansi256', density: true });
  assert.equal(frame.length, 3);
  for (let y = 0; y < 3; y++) {
    assert.equal(visible(frame[y]).length, 5, `row ${y} should have 5 visible chars`);
  }
});

test('density=true with palette symbols is unchanged: no ANSI, glyphs only from " ░▒▓█"', () => {
  const maxHeat = 255;
  const grid = [
    [10, 60, 120, 200, 255],
    [0, 40, 90, 180, 250],
    [255, 255, 128, 64, 32],
  ];
  const frame = renderFrame(grid, { maxHeat, palette: 'symbols', density: true });
  assert.equal(frame.length, 3);
  const allowed = /^[ ░▒▓█]*$/;
  for (let y = 0; y < 3; y++) {
    assert.ok(!frame[y].includes('\u001b'), `row ${y} must contain no ANSI escapes`);
    assert.ok(allowed.test(frame[y]), `row ${y} contains a character outside " ░▒▓█"`);
    assert.equal(frame[y].length, 5, `row ${y} should have 5 visible chars`);
  }
});

test('invalid density throws TypeError (1, "true", null)', () => {
  const grid = [[10], [250]];
  for (const d of [1, 'true', null]) {
    assert.throws(
      () => renderFrame(grid, { maxHeat: 255, palette: 'ansi256', density: d }),
      TypeError,
      `density=${String(d)} should throw TypeError`
    );
  }
});
