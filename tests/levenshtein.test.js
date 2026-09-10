'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { levenshtein } = require('../src/levenshtein.js');

test('levenshtein: basics', () => {
  assert.equal(levenshtein('', ''), 0);
  assert.equal(levenshtein('abc', 'abc'), 0);
  assert.equal(levenshtein('', 'abc'), 3);
  assert.equal(levenshtein('abc', ''), 3);
});

test('levenshtein: classic pairs', () => {
  assert.equal(levenshtein('kitten', 'sitting'), 3);
  assert.equal(levenshtein('flaw', 'lawn'), 2);
  assert.equal(levenshtein('sunday', 'saturday'), 3);
});

test('levenshtein: single operations', () => {
  assert.equal(levenshtein('a', ''), 1);
  assert.equal(levenshtein('ab', 'a'), 1);
  assert.equal(levenshtein('a', 'b'), 1);
  assert.equal(levenshtein('ab', 'ba'), 2);
});

test('levenshtein: symmetry', () => {
  const pairs = [
    ['', 'abc'],
    ['kitten', 'sitting'],
    ['flaw', 'lawn'],
    ['sunday', 'saturday'],
    ['a', 'b'],
    ['ab', 'ba'],
  ];
  for (const [a, b] of pairs) {
    assert.equal(
      levenshtein(a, b),
      levenshtein(b, a),
      `symmetry for (${JSON.stringify(a)}, ${JSON.stringify(b)})`
    );
  }
});

test('levenshtein: throws TypeError for non-string arguments', () => {
  const bad = [
    [123, 'x'],
    ['x', null],
    [undefined, 'x'],
    [[], 'x'],
    [true, 'x'],
  ];
  for (const [a, b] of bad) {
    assert.throws(
      () => levenshtein(a, b),
      TypeError,
      `levenshtein(${String(a)}, ${String(b)})`
    );
  }
});
