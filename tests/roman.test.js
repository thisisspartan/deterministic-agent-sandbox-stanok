'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { toRoman, fromRoman } = require('../src/roman.js');

test('toRoman: canonical values', () => {
  const cases = [
    [1, 'I'],
    [4, 'IV'],
    [9, 'IX'],
    [14, 'XIV'],
    [49, 'XLIX'],
    [99, 'XCIX'],
    [400, 'CD'],
    [900, 'CM'],
    [1994, 'MCMXCIV'],
    [3999, 'MMMCMXCIX'],
  ];
  for (const [n, expected] of cases) {
    assert.equal(toRoman(n), expected, `toRoman(${n})`);
  }
});

test('toRoman: throws RangeError outside 1..3999', () => {
  for (const n of [0, -5, 4000]) {
    assert.throws(() => toRoman(n), RangeError, `toRoman(${n})`);
  }
});

test('toRoman: throws TypeError for non-integers', () => {
  for (const value of [3.5, '5', null, undefined, true, [1]]) {
    assert.throws(
      () => toRoman(value),
      TypeError,
      `toRoman(${String(value)})`
    );
  }
});

test('fromRoman: canonical values', () => {
  assert.equal(fromRoman('I'), 1);
  assert.equal(fromRoman('IV'), 4);
  assert.equal(fromRoman('MCMXCIV'), 1994);
  assert.equal(fromRoman('MMMCMXCIX'), 3999);
});

test('fromRoman: round-trips every n in 1..3999', () => {
  for (let n = 1; n <= 3999; n++) {
    assert.equal(fromRoman(toRoman(n)), n, `round-trip ${n}`);
  }
});

test('fromRoman: throws RangeError for invalid canonical numerals', () => {
  const invalid = ['', 'IIII', 'MMMM', 'LC', 'XM', 'ix', 'IVX', 'IIV', 'VIV'];
  for (const s of invalid) {
    assert.throws(() => fromRoman(s), RangeError, `fromRoman("${s}")`);
  }
});

test('fromRoman: throws TypeError for non-strings', () => {
  for (const value of [123, null, undefined, ['IV'], { s: 'IV' }]) {
    assert.throws(
      () => fromRoman(value),
      TypeError,
      `fromRoman(${String(value)})`
    );
  }
});
