'use strict';
const { test } = require('node:test');
const assert = require('node:assert');

const {
  createFire,
  tick,
  heatToRGB,
  heatToColor,
  renderFrame,
} = require('../src/fire.js');

const STRIP_ANSI = /\x1b\[[0-9;]*m/g;
const SIZE = { width: 32, height: 20, seed: 42 };

test('determinism: same seed produces identical rendered frames', () => {
  const a = createFire(SIZE);
  const b = createFire(SIZE);
  for (let i = 0; i < 6; i++) {
    tick(a);
    tick(b);
  }
  assert.strictEqual(renderFrame(a), renderFrame(b));
});

test('determinism: different seeds produce different frames', () => {
  const a = createFire({ ...SIZE, seed: 42 });
  const b = createFire({ ...SIZE, seed: 777 });
  for (let i = 0; i < 6; i++) {
    tick(a);
    tick(b);
  }
  assert.notStrictEqual(renderFrame(a), renderFrame(b));
});

test('heat field: values stay in [0, 1] and the field changes between two ticks', () => {
  const s = createFire(SIZE);
  const inRange = (g) => {
    for (let i = 0; i < g.length; i++) {
      assert.ok(Number.isFinite(g[i]), `heat not finite: ${g[i]}`);
      assert.ok(g[i] >= 0 && g[i] <= 1, `heat out of range: ${g[i]}`);
    }
  };
  inRange(s.heat);
  assert.ok(s.heat.some((v) => v > 0), 'flame should already be lit after prewarm');
  const before = Array.from(s.heat);
  tick(s);
  inRange(s.heat);
  const after = Array.from(s.heat);
  assert.notDeepEqual(before, after, 'the field must change between two ticks');
});

test('palette: truecolor escapes, RGB in 0-255, hot brighter than cool, zero heat empty', () => {
  for (let h = 0; h <= 1.0001; h += 0.05) {
    const v = Math.min(1, h);
    const [r, g, b] = heatToRGB(v);
    for (const c of [r, g, b]) {
      assert.ok(Number.isInteger(c) && c >= 0 && c <= 255,
        `channel out of range: ${c} at h=${v}`);
    }
    const ans = heatToColor(v);
    if (v <= 0.02) {
      assert.strictEqual(ans, '', 'zero heat must map to an empty cell');
    } else {
      const m = ans.match(/^\x1b\[38;2;(\d+);(\d+);(\d+)m$/);
      assert.ok(m, `not a truecolor escape: ${JSON.stringify(ans)}`);
      assert.strictEqual(Number(m[1]), r);
      assert.strictEqual(Number(m[2]), g);
      assert.strictEqual(Number(m[3]), b);
    }
  }
  const sum = (c) => c[0] + c[1] + c[2];
  assert.ok(sum(heatToRGB(0.95)) > sum(heatToRGB(0.2)),
    'a hot core must map brighter than a cool edge');
});

test('renderer: frame contains ANSI escapes and its dimensions match the grid', () => {
  const s = createFire(SIZE);
  tick(s);
  const frame = renderFrame(s);
  assert.ok(frame.includes('\x1b['), 'frame must contain ANSI escape sequences');
  const lines = frame.split('\n');
  assert.strictEqual(lines.length, s.height, 'frame rows must equal grid height');
  for (const line of lines) {
    assert.strictEqual(line.replace(STRIP_ANSI, '').length, s.width,
      'frame column count must equal grid width');
  }
});

test('renderer: an empty heat field renders as plain spaces only', () => {
  const s = createFire(SIZE);
  s.heat.fill(0);
  s.smoke = [];
  const frame = renderFrame(s);
  assert.ok(!frame.includes('\x1b'), 'empty field must not emit escape sequences');
  const lines = frame.split('\n');
  assert.strictEqual(lines.length, s.height);
  for (const line of lines) {
    assert.strictEqual(line, ' '.repeat(s.width));
  }
});
