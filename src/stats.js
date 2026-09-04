'use strict';

// stats — чистые функции статистики над массивами чисел (TASK-STANOK-CC-027).
// Без внешних зависимостей, без side effects, входные массивы не мутируются.

function assertArray(a) {
  if (!Array.isArray(a)) {
    throw new TypeError('a must be an array');
  }
}

function assertFiniteElements(a) {
  for (let i = 0; i < a.length; i++) {
    if (typeof a[i] !== 'number' || !Number.isFinite(a[i])) {
      throw new TypeError(`a[${i}] must be a finite number`);
    }
  }
}

/**
 * Сумма элементов массива чисел. Пустой массив → 0.
 * @param {number[]} a
 * @returns {number}
 * @throws {TypeError} если `a` не массив ("a" в сообщении) или элемент
 *   неконечное число/`NaN`/`Infinity` (`"a[<i>]"` в сообщении).
 */
function sum(a) {
  assertArray(a);
  assertFiniteElements(a);
  let s = 0;
  for (let i = 0; i < a.length; i++) {
    s += a[i];
  }
  return s;
}

/**
 * Среднее арифметическое: sum(a) / a.length.
 * @param {number[]} a
 * @returns {number}
 * @throws {RangeError} "empty array" — если массив пуст.
 * @throws {TypeError} см. sum().
 */
function mean(a) {
  assertArray(a);
  assertFiniteElements(a);
  if (a.length === 0) {
    throw new RangeError('empty array');
  }
  return sum(a) / a.length;
}

/**
 * Медиана: для нечётной длины — средний элемент отсортированного
 * (по возрастанию) массива; для чётной — среднее двух средних.
 * Входной массив не мутируется.
 * @param {number[]} a
 * @returns {number}
 * @throws {RangeError} "empty array" — если массив пуст.
 * @throws {TypeError} см. sum().
 */
function median(a) {
  assertArray(a);
  assertFiniteElements(a);
  if (a.length === 0) {
    throw new RangeError('empty array');
  }
  const sorted = [...a].sort((x, y) => x - y);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) {
    return sorted[mid];
  }
  return (sorted[mid - 1] + sorted[mid]) / 2;
}

/**
 * Дисперсия (популяционная): sum((x - mean)^2) / a.length.
 * @param {number[]} a
 * @returns {number}
 * @throws {RangeError} "need >= 2" — если элементов меньше двух.
 * @throws {TypeError} см. sum().
 */
function variance(a) {
  assertArray(a);
  assertFiniteElements(a);
  if (a.length < 2) {
    throw new RangeError('need >= 2');
  }
  const m = sum(a) / a.length;
  let s = 0;
  for (let i = 0; i < a.length; i++) {
    const d = a[i] - m;
    s += d * d;
  }
  return s / a.length;
}

module.exports = { sum, mean, median, variance };
