'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');

const { createModel, step } = require('../src/fire_model.js');

test('createModel: default shape and zeroed heat', () => {
  const m = createModel();
  assert.equal(m.width, 80);
  assert.equal(m.height, 24);
  assert.ok(m.heat instanceof Float64Array);
  assert.equal(m.heat.length, 80 * 24);
  for (let i = 0; i < m.heat.length; i++) {
    assert.equal(m.heat[i], 0);
  }
  assert.equal(typeof m.prng, 'number');
});

test('determinism: same seed -> identical heat and prng after 50 steps', () => {
  const a = createModel({ seed: 1337 });
  const b = createModel({ seed: 1337 });
  let sa = a, sb = b;
  for (let i = 0; i < 50; i++) {
    sa = step(sa);
    sb = step(sb);
  }
  assert.deepEqual(sa.heat, sb.heat);
  assert.equal(sa.prng, sb.prng);
});

test('different seeds -> different heat after 10 steps', () => {
  let a = createModel({ seed: 1 });
  let b = createModel({ seed: 2 });
  for (let i = 0; i < 10; i++) {
    a = step(a);
    b = step(b);
  }
  assert.notDeepEqual(a.heat, b.heat);
});

test('purity: step does not mutate input heat or prng', () => {
  const state = createModel();
  const heatCopy = state.heat.slice();
  const prngCopy = state.prng;
  const next = step(state);
  assert.notEqual(next, state);
  assert.notEqual(next.heat, state.heat);
  for (let i = 0; i < state.heat.length; i++) {
    assert.equal(state.heat[i], heatCopy[i]);
  }
  assert.equal(state.prng, prngCopy);
});

test('bounds: 200 steps keep heat finite and within [0,1]', () => {
  let s = createModel();
  for (let i = 0; i < 200; i++) s = step(s);
  for (let i = 0; i < s.heat.length; i++) {
    const v = s.heat[i];
    assert.ok(Number.isFinite(v), `heat[${i}] not finite: ${v}`);
    assert.ok(v >= 0 && v <= 1, `heat[${i}] out of [0,1]: ${v}`);
  }
});

test('rise: after 100 steps the top row has a positive cell', () => {
  let s = createModel();
  for (let i = 0; i < 100; i++) s = step(s);
  const width = s.width;
  let maxTop = -1;
  for (let c = 0; c < width; c++) maxTop = Math.max(maxTop, s.heat[c]);
  assert.ok(maxTop > 0, `top row max was ${maxTop}`);
});
