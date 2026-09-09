'use strict';

const test = require('node:test');
const assert = require('node:assert');

const { slugify } = require('../src/slug.js');

test('slugify("Hello World") -> "hello-world"', () => {
  assert.strictEqual(slugify('Hello World'), 'hello-world');
});

test('slugify("  Trim   Me  ") -> "trim-me" (обрезка краёв)', () => {
  assert.strictEqual(slugify('  Trim   Me  '), 'trim-me');
});

test('slugify("a--b  c") -> "a-b-c" (хлопание повторов)', () => {
  assert.strictEqual(slugify('a--b  c'), 'a-b-c');
});

test('slugify("Привет Мир") -> "" (кириллица удаляется)', () => {
  assert.strictEqual(slugify('Привет Мир'), '');
});

test('slugify("Café au lait") -> "caf-au-lait" (акцент é удаляется)', () => {
  assert.strictEqual(slugify('Café au lait'), 'caf-au-lait');
});

test('пустая/только-мусорная строка -> ""', () => {
  assert.strictEqual(slugify('---'), '');
  assert.strictEqual(slugify(''), '');
  assert.strictEqual(slugify('!!!'), '');
});

test('slugify("a_b.c:d", "_") -> "a_b_c_d" (кастомный sep, "." и ":" удаляются)', () => {
  assert.strictEqual(slugify('a_b.c:d', '_'), 'a_b_c_d');
});

test('slugify(null) -> TypeError; slugify(42) -> TypeError', () => {
  assert.throws(() => slugify(null), TypeError);
  assert.throws(() => slugify(42), TypeError);
});

test('slugify("a b", "x") -> "axb" (sep используется как разделитель пробелов)', () => {
  assert.strictEqual(slugify('a b', 'x'), 'axb');
});

test('slugify("A1 B2") -> "a1-b2" (цифры сохраняются)', () => {
  assert.strictEqual(slugify('A1 B2'), 'a1-b2');
});
