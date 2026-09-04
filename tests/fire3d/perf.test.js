'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { create, render } = require('../../src/fire3d/fire3d.js');

test('perf: 100 iterations of step() + render() < 2000 ms (default 48x24x48 grid)', () => {
  const s = create({ seed: 1337 });
  assert.strictEqual(s.W * s.H * s.D, 48 * 24 * 48, 'default grid size');
  const t0 = Date.now();
  for (let i = 0; i < 100; i++) {
    s.step();
    render(s, 80, 0);
  }
  const dt = Date.now() - t0;
  assert.ok(dt < 2000, `100 step+render iterations took ${dt} ms (limit 2000 ms)`);
});
