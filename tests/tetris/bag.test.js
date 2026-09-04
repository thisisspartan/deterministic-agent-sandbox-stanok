'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const { newBag } = require('../../src/tetris/bag.js');

const NAMES = ['I', 'O', 'T', 'S', 'Z', 'J', 'L'];

// --- golden-14 for seed=1 ---
// Pinned constant from the ticket: the first 14 next() (two 7-bags) of newBag(1).
const GOLDEN14 = [
  'Z', 'I', 'T', 'S', 'L', 'J', 'O',
  'Z', 'L', 'T', 'S', 'O', 'I', 'J',
];

test('golden-14 for seed=1 matches the ticket-computed sequence', () => {
  const bag = newBag(1);
  const got = Array.from({ length: 14 }, () => bag.next());
  assert.deepStrictEqual(got, GOLDEN14);
});

test('bag property: first 7 next() is a permutation of the 7 pieces; second 7 likewise', () => {
  const bag = newBag(1);
  const first = Array.from({ length: 7 }, () => bag.next()).sort();
  const second = Array.from({ length: 7 }, () => bag.next()).sort();
  assert.deepStrictEqual(first, [...NAMES].sort());
  assert.deepStrictEqual(second, [...NAMES].sort());
});

test('peek() does not consume; first peek() === first next(), second next() same piece', () => {
  const bag = newBag(1);
  const p = bag.peek();
  const n1 = bag.next();
  assert.strictEqual(p, n1);
  // Peek left the bag untouched, so next() keeps yielding the pinned sequence.
  assert.strictEqual(n1, GOLDEN14[0]);
  const n2 = bag.next();
  assert.strictEqual(n2, GOLDEN14[1]);
});

test('reset(seed) reproduces the same sequence as newBag(seed)', () => {
  const a = newBag(1);
  const b = newBag(99);
  const seqA = Array.from({ length: 14 }, () => a.next());
  b.reset(1);
  const seqB = Array.from({ length: 14 }, () => b.next());
  assert.deepStrictEqual(seqA, seqB);
  assert.deepStrictEqual(seqA, GOLDEN14);
});

test('determinism: two newBag(42) instances give identical first 21 next()', () => {
  const a = newBag(42);
  const b = newBag(42);
  for (let i = 0; i < 21; i++) {
    assert.strictEqual(a.next(), b.next());
  }
});

test('every value is in the 7-piece set', () => {
  const bag = newBag(7);
  for (let i = 0; i < 100; i++) {
    const v = bag.next();
    assert.ok(NAMES.includes(v), `unexpected piece ${v}`);
  }
});

test('module is pure: no forbidden identifiers in source', () => {
  const src = fs.readFileSync(
    path.join(__dirname, '..', '..', 'src', 'tetris', 'bag.js'),
    'utf8',
  );
  // Strip comments so identifiers inside comments do not trip the check.
  const stripped = src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1');
  for (const bad of ['process', 'readline', 'setInterval', 'Date']) {
    assert.ok(!new RegExp('\\b' + bad + '\\b').test(stripped),
      `source must not contain identifier "${bad}"`);
  }
});
