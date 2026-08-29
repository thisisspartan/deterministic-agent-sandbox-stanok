'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { add } = require('../src/vec3.js');

test('diag add(null)', () => {
  try {
    add(null, { x: 1, y: 2, z: 3 });
    console.log('DIAG: no throw!');
  } catch (e) {
    console.log('DIAG add(null) threw:', e.constructor.name, JSON.stringify(e.message), /a/.test(e.message));
  }
  assert.ok(true);
});

test('diag add(5)', () => {
  try {
    add(5, { x: 1, y: 2, z: 3 });
    console.log('DIAG: no throw!');
  } catch (e) {
    console.log('DIAG add(5) threw:', e.constructor.name, JSON.stringify(e.message), /a/.test(e.message));
  }
  assert.ok(true);
});

test('diag add(5,5)', () => {
  try {
    add(5, 5);
    console.log('DIAG: no throw!');
  } catch (e) {
    console.log('DIAG add(5,5) threw:', e.constructor.name, JSON.stringify(e.message), /a/.test(e.message));
  }
  assert.ok(true);
});

test('diag add(NaN)', () => {
  try {
    add(NaN, { x: 1, y: 2, z: 3 });
    console.log('DIAG: no throw!');
  } catch (e) {
    console.log('DIAG add(NaN) threw:', e.constructor.name, JSON.stringify(e.message), /a/.test(e.message));
  }
  assert.ok(true);
});
