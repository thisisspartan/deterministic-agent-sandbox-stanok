'use strict';

/**
 * Roman numeral conversion (1..3999), canonical form only.
 *
 * Canonical rules:
 *  - only uppercase I, V, X, L, C, D, M;
 *  - subtractive pairs only IV, IX, XL, XC, CD, CM;
 *  - no symbol appears more than 3 times in a row;
 *  - values never increase left to right, except inside a subtractive pair;
 *  - empty string is invalid.
 */

const SYMBOLS = [
  [1000, 'M'],
  [900, 'CM'],
  [500, 'D'],
  [400, 'CD'],
  [100, 'C'],
  [90, 'XC'],
  [50, 'L'],
  [40, 'XL'],
  [10, 'X'],
  [9, 'IX'],
  [5, 'V'],
  [4, 'IV'],
  [1, 'I'],
];

const VALUES = { I: 1, V: 5, X: 10, L: 50, C: 100, D: 500, M: 1000 };

// Grammar of canonical Roman numerals: thousands, hundreds, tens, units.
const CANONICAL = /^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$/;

/**
 * Convert an integer 1..3999 to its canonical Roman numeral.
 *
 * @param {number} n integer in 1..3999
 * @returns {string} uppercase Roman numeral
 * @throws {TypeError} if n is not an integer
 * @throws {RangeError} if n < 1 or n > 3999
 */
function toRoman(n) {
  if (!Number.isInteger(n)) {
    throw new TypeError(`n must be an integer, got ${typeof n}`);
  }
  if (n < 1 || n > 3999) {
    throw new RangeError(`n must be in 1..3999, got ${n}`);
  }
  let rest = n;
  let out = '';
  for (const [value, symbol] of SYMBOLS) {
    while (rest >= value) {
      out += symbol;
      rest -= value;
    }
  }
  return out;
}

/**
 * Convert a canonical Roman numeral to its integer value.
 *
 * @param {string} s canonical uppercase Roman numeral
 * @returns {number} integer value (1..3999)
 * @throws {TypeError} if s is not a string
 * @throws {RangeError} if s is not a valid canonical Roman numeral
 */
function fromRoman(s) {
  if (typeof s !== 'string') {
    throw new TypeError(`s must be a string, got ${typeof s}`);
  }
  if (s.length === 0 || !CANONICAL.test(s)) {
    throw new RangeError(`not a valid canonical Roman numeral: "${s}"`);
  }
  let total = 0;
  for (let i = 0; i < s.length; i++) {
    const value = VALUES[s[i]];
    const next = i + 1 < s.length ? VALUES[s[i + 1]] : 0;
    total += value < next ? -value : value;
  }
  return total;
}

module.exports = { toRoman, fromRoman };
