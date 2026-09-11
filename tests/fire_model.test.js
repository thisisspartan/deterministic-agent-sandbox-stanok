'use strict';

// Reference tests for the fire model (heat simulation).
const test = require('node:test');
const assert = require('node:assert/strict');

const { createModel, step } = require('../src/fire_model.js');

function deepHeat(h) {
  return Array.from(h);
}

test('shape: default model dimensions and zero heat', () => {
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
  assert.deepEqual(deepHeat(sa.heat), deepHeat(sb.heat));
  assert.equal(sa.prng, sb.prng);
});

test('different seeds differ after 10 steps', () => {
  let a = createModel({ seed: 1 });
  let b = createModel({ seed: 2 });
  for (let i = 0; i < 10; i++) {
    a = step(a);
    b = step(b);
  }
  assert.notDeepEqual(deepHeat(a.heat), deepHeat(b.heat));
});

test('purity: step does not mutate input state', () => {
  const state = createModel();
  const heatCopy = Array.from(state.heat);
  const prngCopy = state.prng;
  const next = step(state);
  assert.notStrictEqual(next, state);
  assert.deepEqual(deepHeat(state.heat), heatCopy);
  assert.equal(state.prng, prngCopy);
});

test('bounds: 200 steps stay finite and within [0,1]', () => {
  let s = createModel();
  for (let i = 0; i < 200; i++) {
    s = step(s);
  }
  for (let i = 0; i < s.heat.length; i++) {
    const v = s.heat[i];
    assert.ok(Number.isFinite(v), `heat not finite at ${i}: ${v}`);
    assert.ok(v >= 0 && v <= 1, `heat out of range at ${i}: ${v}`);
  }
});

test('rise: top row has a cell > 0 after 100 steps', () => {
  let s = createModel();
  for (let i = 0; i < 100; i++) {
    s = step(s);
  }
  const width = s.width;
  let anyPositive = false;
  for (let c = 0; c < width; c++) {
    if (s.heat[c] > 0) {
      anyPositive = true;
      break;
    }
  }
  assert.ok(anyPositive, 'expected at least one positive cell in top row');
});
