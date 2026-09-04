'use strict';

// vecops — чистые утилиты над 2D-векторами (TASK-STANOK-CC-026).
// Без внешних зависимостей, без side effects.

function assertVec2(obj, name) {
  if (obj === null || typeof obj !== 'object' || Array.isArray(obj)) {
    throw new TypeError(name + ' must be an object { x, y }, got ' + obj);
  }
  const bad = [];
  if (typeof obj.x !== 'number' || Number.isNaN(obj.x)) bad.push('x');
  if (typeof obj.y !== 'number' || Number.isNaN(obj.y)) bad.push('y');
  if (bad.length > 0) {
    throw new TypeError(
      name + ' must have numeric component(s) ' + bad.join(', ') +
        ' (got x=' + obj.x + ', y=' + obj.y + ')'
    );
  }
}

function dot(a, b) {
  return a.x * b.x + a.y * b.y;
}

function scale(v, k) {
  return { x: v.x * k, y: v.y * k };
}

/**
 * Euclidean distance between two 2D vectors:
 * Math.hypot(a.x - b.x, a.y - b.y).
 * @param {{x: number, y: number}} a
 * @param {{x: number, y: number}} b
 * @returns {number}
 * @throws {TypeError} non-object or non-numeric component (name in message).
 */
function dist(a, b) {
  assertVec2(a, 'a');
  assertVec2(b, 'b');
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/**
 * Midpoint of the segment between two 2D vectors:
 * {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2}.
 * @param {{x: number, y: number}} a
 * @param {{x: number, y: number}} b
 * @returns {{x: number, y: number}}
 * @throws {TypeError} see {@link dist}.
 */
function mid(a, b) {
  assertVec2(a, 'a');
  assertVec2(b, 'b');
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

/**
 * Normalize a 2D vector to unit length:
 * {x: v.x / len, y: v.y / len}, len = Math.hypot(v.x, v.y).
 * @param {{x: number, y: number}} v
 * @returns {{x: number, y: number}}
 * @throws {TypeError} see {@link dist}.
 * @throws {RangeError} "zero vector" for the zero vector.
 */
function normalize2(v) {
  assertVec2(v, 'v');
  const len = Math.hypot(v.x, v.y);
  if (len === 0) {
    throw new RangeError('zero vector');
  }
  return { x: v.x / len, y: v.y / len };
}

/**
 * Orthogonal projection of a onto b:
 * scale(b, dot(a, b) / dot(b, b)).
 * @param {{x: number, y: number}} a
 * @param {{x: number, y: number}} b
 * @returns {{x: number, y: number}}
 * @throws {TypeError} see {@link dist}.
 * @throws {RangeError} "zero basis" when dot(b, b) === 0.
 */
function project(a, b) {
  assertVec2(a, 'a');
  assertVec2(b, 'b');
  const bb = dot(b, b);
  if (bb === 0) {
    throw new RangeError('zero basis');
  }
  return scale(b, dot(a, b) / bb);
}

module.exports = { dist, mid, normalize2, project };
