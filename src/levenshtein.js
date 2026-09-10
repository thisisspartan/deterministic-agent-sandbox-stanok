'use strict';

/**
 * Levenshtein edit distance.
 *
 * The minimum number of single-character insertions, deletions, and
 * substitutions needed to transform string `a` into string `b`,
 * where each operation costs 1.
 */

/**
 * Compute the Levenshtein edit distance between two strings.
 *
 * Dynamic programming over an (a.length + 1) x (b.length + 1) table:
 *   d[0][0] = 0,
 *   d[i][0] = i (deletions), d[0][j] = j (insertions),
 *   d[i][j] = min(
 *     d[i-1][j] + 1,          // delete a[i-1]
 *     d[i][j-1] + 1,          // insert b[j-1]
 *     d[i-1][j-1] + (a[i-1] === b[j-1] ? 0 : 1)  // match or substitute
 *   ).
 *
 * Only two rows are kept, so memory is O(min(len(a), len(b))).
 *
 * @param {string} a
 * @param {string} b
 * @returns {number} non-negative integer edit distance
 * @throws {TypeError} if either argument is not a string
 */
function levenshtein(a, b) {
  if (typeof a !== 'string') {
    throw new TypeError(`a must be a string, got ${typeof a}`);
  }
  if (typeof b !== 'string') {
    throw new TypeError(`b must be a string, got ${typeof b}`);
  }

  // Iterate over the shorter string as the row axis to save memory.
  let [x, y] = a.length <= b.length ? [a, b] : [b, a];

  let prev = new Array(y.length + 1);
  for (let j = 0; j <= y.length; j++) prev[j] = j;

  for (let i = 1; i <= x.length; i++) {
    const cur = new Array(y.length + 1);
    cur[0] = i;
    for (let j = 1; j <= y.length; j++) {
      const cost = x[i - 1] === y[j - 1] ? 0 : 1;
      cur[j] = Math.min(
        prev[j] + 1, // deletion
        cur[j - 1] + 1, // insertion
        prev[j - 1] + cost // substitution / match
      );
    }
    prev = cur;
  }

  return prev[y.length];
}

module.exports = { levenshtein };
