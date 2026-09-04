'use strict';

const { formatPos } = require('./utils.js');

/**
 * Возвращает prefix + "x=<X> y=<Y>" (formatPos из ./utils.js).
 * @param {string} prefix — строковый префикс
 * @param {number} x
 * @param {number} y
 * @returns {string}
 */
function formatPosPrefixed(prefix, x, y) {
  if (typeof prefix !== 'string') {
    throw new TypeError('prefix must be a string');
  }
  if (typeof x !== 'number' || Number.isNaN(x)) {
    throw new TypeError('x must be a number and not NaN');
  }
  if (typeof y !== 'number' || Number.isNaN(y)) {
    throw new TypeError('y must be a number and not NaN');
  }
  return prefix + formatPos(x, y);
}

module.exports = { formatPosPrefixed };
