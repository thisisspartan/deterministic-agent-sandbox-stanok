'use strict';
// rng — детерминированный сид-PRNG (mulberry32) + хелперы randInt/pick/shuffle.
// Чистый Node.js, без внешних зависимостей, без Math.random.

/**
 * Создаёт детерминированный генератор случайных чисел по алгоритму mulberry32.
 * @param {number} seed — любое целое; нормализуется к uint32 (seed >>> 0).
 * @returns {() => number} функция rng(), возвращающая float в [0, 1).
 */
function mulberry32(seed) {
  let a = seed >>> 0;
  return function rng() {
    a |= 0;
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Равномерное целое в [min, max] ВКЛЮЧИТЕЛЬНО.
 * @param {() => number} rng — генератор вида () => [0,1).
 * @param {number} min
 * @param {number} max
 * @returns {number}
 * @throws {RangeError} если min > max.
 */
function randInt(rng, min, max) {
  if (!Number.isInteger(min) || !Number.isInteger(max)) {
    throw new RangeError('min and max must be integers');
  }
  if (min > max) {
    throw new RangeError(`min (${min}) must be <= max (${max})`);
  }
  const range = max - min + 1;
  return min + Math.floor(rng() * range);
}

/**
 * Равномерно случайный элемент массива.
 * @param {() => number} rng
 * @param {Array} arr
 * @returns {*} один из элементов arr.
 * @throws {RangeError} если arr.length === 0.
 */
function pick(rng, arr) {
  if (!Array.isArray(arr) || arr.length === 0) {
    throw new RangeError('pick: array must be non-empty');
  }
  return arr[randInt(rng, 0, arr.length - 1)];
}

/**
 * Fisher-Yates in-place перемешивание; возвращает тот же объект-массив.
 * @param {() => number} rng
 * @param {Array} arr
 * @returns {Array} тот же arr, перемешанный на месте.
 */
function shuffle(rng, arr) {
  if (!Array.isArray(arr)) {
    throw new TypeError('shuffle: expected an array');
  }
  for (let i = arr.length - 1; i > 0; i--) {
    const j = randInt(rng, 0, i);
    const tmp = arr[i];
    arr[i] = arr[j];
    arr[j] = tmp;
  }
  return arr;
}

module.exports = { mulberry32, randInt, pick, shuffle };
