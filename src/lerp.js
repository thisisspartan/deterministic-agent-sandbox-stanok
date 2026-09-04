'use strict';

// lerp — чистые функции линейной интерполяции и clamp (TASK-STANOK-CC-012).
// Без внешних зависимостей, без side effects.

function assertNumber(value, name) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    throw new TypeError(`${name} must be a number, got ${value}`);
  }
}

/**
 * Ограничивает v диапазоном [lo, hi].
 * @param {number} v
 * @param {number} lo
 * @param {number} hi
 * @returns {number}
 * @throws {RangeError} "lo > hi" — если lo > hi.
 * @throws {TypeError} если v/lo/hi не число/NaN (имя аргумента в сообщении).
 */
function clamp(v, lo, hi) {
  assertNumber(v, 'v');
  assertNumber(lo, 'lo');
  assertNumber(hi, 'hi');
  if (lo > hi) {
    throw new RangeError('lo > hi');
  }
  return Math.min(Math.max(v, lo), hi);
}

/**
 * Линейная интерполяция: a + (b - a) * t.
 * t вне [0, 1] допустимо (экстраполяция), ошибкой не является.
 * @param {number} a
 * @param {number} b
 * @param {number} t
 * @returns {number}
 * @throws {TypeError} если a/b/t не число/NaN (имя аргумента в сообщении).
 */
function lerp(a, b, t) {
  assertNumber(a, 'a');
  assertNumber(b, 'b');
  assertNumber(t, 't');
  return a + (b - a) * t;
}

/**
 * Обратная интерполяция: (v - a) / (b - a).
 * @param {number} a
 * @param {number} b
 * @param {number} v
 * @returns {number}
 * @throws {RangeError} "a === b" — деление на ноль.
 * @throws {TypeError} если a/b/v не число/NaN (имя аргумента в сообщении).
 */
function invLerp(a, b, v) {
  assertNumber(a, 'a');
  assertNumber(b, 'b');
  assertNumber(v, 'v');
  if (a === b) {
    throw new RangeError('a === b');
  }
  return (v - a) / (b - a);
}

module.exports = { clamp, lerp, invLerp };
