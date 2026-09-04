'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { create, render } = require('../../src/fire3d/fire3d.js');

// Mean heat of one horizontal layer y (index scheme: y*W*D + x*D + z).
function layerMean(state, y) {
  const { W, D, heat } = state;
  const off = y * W * D;
  let sum = 0;
  for (let i = 0; i < W * D; i++) sum += heat[off + i];
  return sum / (W * D);
}

test('physics: heating rises from the base — after N steps the base layer is hotter than the top', () => {
  const s = create({ seed: 7, W: 24, H: 16, D: 24 });
  for (let i = 0; i < 30; i++) s.step();
  const base = layerMean(s, 0);
  const top = layerMean(s, s.H - 1);
  assert.ok(base > 0.1, `base layer mean ${base} should be hot`);
  assert.ok(base > top, `base ${base} should be hotter than top ${top}`);
});

test('physics: heat decays with height — layer means drop monotonically upward', () => {
  const s = create({ seed: 7, W: 24, H: 16, D: 24 });
  for (let i = 0; i < 30; i++) s.step();
  const m0 = layerMean(s, 0);
  const mMid = layerMean(s, Math.floor(s.H / 2));
  const mTop = layerMean(s, s.H - 1);
  assert.ok(m0 > mMid, `mean(y=0)=${m0} > mean(mid)=${mMid}`);
  assert.ok(mMid > mTop, `mean(mid)=${mMid} > mean(top)=${mTop}`);
});

test('physics: volumetric 3D spread — at one (x, y) several z cells have heat > 0', () => {
  const s = create({ seed: 7, W: 24, H: 16, D: 24 });
  for (let i = 0; i < 30; i++) s.step();
  const x = Math.floor(s.W / 2);
  const y = 2;
  let count = 0;
  for (let z = 0; z < s.D; z++) {
    if (s.heat[y * s.W * s.D + x * s.D + z] > 0) count++;
  }
  assert.ok(count >= 3, `at least 3 z cells hot at (x=${x}, y=${y}), got ${count}`);
});

test('physics: determinism — same seed + same step sequence => identical frames', () => {
  const a = create({ seed: 42 });
  const b = create({ seed: 42 });
  for (let i = 0; i < 15; i++) {
    a.step();
    b.step();
  }
  assert.strictEqual(render(a, 60, 0), render(b, 60, 0));
});
