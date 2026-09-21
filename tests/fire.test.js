'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');

const {
  createSim,
  tick,
  composite,
  palette,
  renderFrame,
} = require('../src/fire.js');

const W = 60;
const H = 40;

function stripAnsi(s) {
  return s.replace(/\x1b\[[0-9;]*m/g, '');
}

function luminance(c) {
  return 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
}

function ticked(seed, n) {
  const s = createSim(W, H, seed);
  for (let i = 0; i < n; i++) tick(s);
  return s;
}

test('determinism: same seed -> identical rendered frame', () => {
  const a = ticked(1234, 5);
  const b = ticked(1234, 5);
  assert.equal(renderFrame(composite(a), W, H), renderFrame(composite(b), W, H));
  // different seed -> different frame
  const c = ticked(98765, 5);
  assert.notEqual(renderFrame(composite(c), W, H), renderFrame(composite(a), W, H));
});

test('heat field: values in [0, 1] and the field changes between ticks', () => {
  const s = ticked(42, 1);
  for (const v of s.heat) {
    assert.ok(v >= 0 && v <= 1, `heat ${v} out of [0,1]`);
  }
  const before = Buffer.from(s.heat.buffer);
  tick(s);
  const after = Buffer.from(s.heat.buffer);
  assert.notDeepEqual(after, before, 'field must change between ticks');
  for (const v of s.heat) {
    assert.ok(v >= 0 && v <= 1, `heat ${v} out of [0,1] after tick`);
  }
});

test('palette: RGB in 0..255, hot brighter than cool, zero heat -> empty', () => {
  assert.equal(palette(0), null, 'zero heat must be an empty cell');
  for (const v of [0.02, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 0.95, 1]) {
    const c = palette(v);
    assert.ok(c, `palette(${v}) must not be empty`);
    for (const ch of [c.r, c.g, c.b]) {
      assert.ok(Number.isInteger(ch) && ch >= 0 && ch <= 255, `channel ${ch}`);
    }
  }
  assert.ok(luminance(palette(0.95)) > luminance(palette(0.2)), 'hot core brighter than cool edge');
  assert.ok(luminance(palette(1)) >= luminance(palette(0.95)));
  // smoke band renders as (near-)gray
  const sm = palette(0.05);
  assert.ok(Math.abs(sm.r - sm.g) <= 10 && Math.abs(sm.r - sm.b) <= 10);
});

test('renderer: ANSI escapes present and frame dimensions match the grid', () => {
  const s = ticked(5, 30);
  const grid = composite(s);
  assert.equal(grid.length, H);
  assert.equal(grid[0].length, W);
  const frame = renderFrame(grid, W, H);
  assert.ok(frame.includes('\x1b[38;2;'), 'frame must contain truecolor escapes');
  const lines = frame.split('\n');
  assert.equal(lines.length, Math.ceil(H / 2), 'rows = ceil(height/2)');
  for (const line of lines) {
    assert.equal(stripAnsi(line).length, W, 'columns match grid width');
  }
  // fully empty grid -> plain spaces only, no escapes
  const empty = renderFrame([[0, 0, 0, 0]], 4, 1);
  assert.equal(empty, '    ');
  assert.ok(!empty.includes('\x1b'), 'empty cells carry no escape sequences');
});

test('smoke: faint gray particles rise above the flame tip', () => {
  const s = ticked(7, 90);
  let smokeCells = 0;
  let minSmokeY = H;
  let minFlameY = H;
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const i = y * W + x;
      if (s.smoke[i] > 0.02) {
        smokeCells++;
        if (y < minSmokeY) minSmokeY = y;
      }
      if (s.heat[i] > 0.5) {
        if (y < minFlameY) minFlameY = y;
      }
    }
  }
  assert.ok(flameExists(s), 'flame core must be present');
  assert.ok(smokeCells > 5, 'smoke particles must be present');
  assert.ok(minFlameY < H, 'flame tip located');
  assert.ok(minSmokeY <= minFlameY, 'smoke rises above the flame tip');
});

function flameExists(s) {
  let n = 0;
  for (const v of s.heat) if (v > 0.5) n++;
  return n > 10;
}
