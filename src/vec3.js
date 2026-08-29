'use strict';

// vec3 — чистые функции 3D-векторной алгебры (TASK-STANOK-CC-013).
// Без внешних зависимостей, без side effects.
// Вектор — объект { x, y, z } с числовыми компонентами.

function assertNumber(value, name) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    throw new TypeError(`${name} must be a finite number, got ${value}`);
  }
}

function assertVec3(obj, name) {
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) {
    throw new TypeError(`${name} must be an object { x, y, z }, got ${obj}`);
  }
  assertNumber(obj.x, name + '.x');
  assertNumber(obj.y, name + '.y');
  assertNumber(obj.z, name + '.z');
}

/**
 * Покомпонентное сложение: {x: a.x + b.x, y: a.y + b.y, z: a.z + b.z}.
 * @param {{x: number, y: number, z: number}} a
 * @param {{x: number, y: number, z: number}} b
 * @returns {{x: number, y: number, z: number}}
 * @throws {TypeError} если a/b не объект или компонента не число/NaN (имя в сообщении).
 */
function add(a, b) {
  assertVec3(a, 'a');
  assertVec3(b, 'b');
  return { x: a.x + b.x, y: a.y + b.y, z: a.z + b.z };
}

/**
 * Покомпонентное вычитание: {x: a.x - b.x, y: a.y - b.y, z: a.z - b.z}.
 * @param {{x: number, y: number, z: number}} a
 * @param {{x: number, y: number, z: number}} b
 * @returns {{x: number, y: number, z: number}}
 * @throws {TypeError} если a/b не объект или компонента не число/NaN (имя в сообщении).
 */
function sub(a, b) {
  assertVec3(a, 'a');
  assertVec3(b, 'b');
  return { x: a.x - b.x, y: a.y - b.y, z: a.z - b.z };
}

/**
 * Умножение на скаляр: {x: v.x * s, y: v.y * s, z: v.z * s}.
 * @param {{x: number, y: number, z: number}} v
 * @param {number} s
 * @returns {{x: number, y: number, z: number}}
 * @throws {TypeError} если v не объект/компонента не число, s не число/NaN.
 */
function scale(v, s) {
  assertVec3(v, 'v');
  assertNumber(s, 's');
  return { x: v.x * s, y: v.y * s, z: v.z * s };
}

/**
 * Скалярное произведение: a.x*b.x + a.y*b.y + a.z*b.z.
 * @param {{x: number, y: number, z: number}} a
 * @param {{x: number, y: number, z: number}} b
 * @returns {number}
 * @throws {TypeError} если a/b не объект или компонента не число/NaN (имя в сообщении).
 */
function dot(a, b) {
  assertVec3(a, 'a');
  assertVec3(b, 'b');
  return a.x * b.x + a.y * b.y + a.z * b.z;
}

/**
 * Векторное (кросс) произведение:
 * {x: a.y*b.z - a.z*b.y, y: a.z*b.x - a.x*b.z, z: a.x*b.y - a.y*b.x}.
 * @param {{x: number, y: number, z: number}} a
 * @param {{x: number, y: number, z: number}} b
 * @returns {{x: number, y: number, z: number}}
 * @throws {TypeError} если a/b не объект или компонента не число/NaN (имя в сообщении).
 */
function cross(a, b) {
  assertVec3(a, 'a');
  assertVec3(b, 'b');
  return {
    x: a.y * b.z - a.z * b.y,
    y: a.z * b.x - a.x * b.z,
    z: a.x * b.y - a.y * b.x
  };
}

/**
 * Длина вектора: Math.sqrt(x^2 + y^2 + z^2).
 * @param {{x: number, y: number, z: number}} v
 * @returns {number}
 * @throws {TypeError} если v не объект или компонента не число/NaN (имя в сообщении).
 */
function length(v) {
  assertVec3(v, 'v');
  return Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
}

/**
 * Приведение к единичной длине: scale(v, 1 / length(v)).
 * @param {{x: number, y: number, z: number}} v
 * @returns {{x: number, y: number, z: number}}
 * @throws {RangeError} "zero vector" для нулевого вектора.
 * @throws {TypeError} если v не объект или компонента не число/NaN (имя в сообщении).
 */
function normalize(v) {
  assertVec3(v, 'v');
  const L = Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
  if (L === 0) {
    throw new RangeError('zero vector');
  }
  return scale(v, 1 / L);
}

module.exports = { add, sub, scale, dot, cross, length, normalize };
