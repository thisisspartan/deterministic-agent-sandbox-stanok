'use strict';
// Test contract for src/rgb.js (see docs/rgb.md).
const test = require('node:test');
const assert = require('node:assert/strict');

const { hexToRgb, rgbToHex, mix } = require('../src/rgb.js');

test('hexToRgb: valid 7-char hex strings', () => {
  assert.deepEqual(hexToRgb('#ff8000'), { r: 255, g: 128, b: 0 });
  assert.deepEqual(hexToRgb('#000000'), { r: 0, g: 0, b: 0 });
  assert.deepEqual(hexToRgb('#FFFFFF'), { r: 255, g: 255, b: 255 });
});

test('hexToRgb: invalid inputs throw Error', () => {
  assert.throws(() => hexToRgb('ff8000'), Error, 'missing # must throw');
  assert.throws(() => hexToRgb('#ff800'), Error, 'wrong length must throw');
  assert.throws(() => hexToRgb('#ff80001'), Error, 'wrong length must throw');
  assert.throws(() => hexToRgb('#gg0000'), Error, 'non-hex character must throw');
  assert.throws(() => hexToRgb(123), Error, 'non-string must throw');
  assert.throws(() => hexToRgb('#FF 800'), Error, 'non-hex character must throw');
  assert.throws(() => hexToRgb(null), Error, 'non-string must throw');
});

test('rgbToHex: valid objects -> lowercase zero-padded hex', () => {
  assert.equal(rgbToHex({ r: 255, g: 128, b: 0 }), '#ff8000');
  assert.equal(rgbToHex({ r: 0, g: 5, b: 16 }), '#000510');
  assert.equal(rgbToHex({ r: 0, g: 0, b: 0 }), '#000000');
  assert.equal(rgbToHex({ r: 255, g: 255, b: 255 }), '#ffffff');
});

test('rgbToHex: invalid objects throw Error', () => {
  assert.throws(() => rgbToHex({ r: 256, g: 0, b: 0 }), Error, 'out of range must throw');
  assert.throws(() => rgbToHex({ r: -1, g: 0, b: 0 }), Error, 'negative must throw');
  assert.throws(() => rgbToHex({ r: 1.5, g: 0, b: 0 }), Error, 'non-integer must throw');
  assert.throws(() => rgbToHex({ r: 0, b: 0 }), Error, 'missing channel must throw');
  assert.throws(() => rgbToHex('ff8000'), Error, 'non-object must throw');
  assert.throws(() => rgbToHex(null), Error, 'non-object must throw');
});

test('mix: linear interpolation', () => {
  assert.deepEqual(mix({ r: 0, g: 0, b: 0 }, { r: 100, g: 200, b: 300 }, 0.5),
    { r: 50, g: 100, b: 150 });

  const a = { r: 10, g: 20, b: 30 };
  const b = { r: 110, g: 220, b: 310 };
  assert.deepEqual(mix(a, b, 0), a, 't=0 must equal a');
  assert.deepEqual(mix(a, b, 1), b, 't=1 must equal b');

  // result is a NEW object: mutating inputs after mixing must not affect it
  const c = mix(a, b, 0.5);
  a.r = 999;
  b.g = 999;
  assert.deepEqual(c, { r: 60, g: 120, b: 170 });
});

test('mix: invalid t throws Error', () => {
  const a = { r: 0, g: 0, b: 0 };
  const b = { r: 1, g: 1, b: 1 };
  assert.throws(() => mix(a, b, 1.2), Error, 't > 1 must throw');
  assert.throws(() => mix(a, b, -0.1), Error, 't < 0 must throw');
  assert.throws(() => mix(a, b, '0.5'), Error, 'non-number t must throw');
});

test('round-trip: hexToRgb(rgbToHex(c)) deep-equals c', () => {
  const c = { r: 1, g: 254, b: 128 };
  assert.deepEqual(hexToRgb(rgbToHex(c)), c);
});
