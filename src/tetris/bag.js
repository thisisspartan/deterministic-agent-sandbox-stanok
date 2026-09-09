'use strict';

// Tetris 7-bag randomizer: mulberry32 PRNG + classic Fisher-Yates shuffle.
// Pure module (no process/readline/setInterval/Date). Seed is an explicit number.

const PIECES = ['I', 'O', 'T', 'S', 'Z', 'J', 'L'];

// Fixed mulberry32 PRNG (ticket-specified algorithm).
function mulberry32(a) {
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Classic Fisher-Yates, from the end toward the start.
function fisherYates(arr, rng) {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    const tmp = arr[i];
    arr[i] = arr[j];
    arr[j] = tmp;
  }
  return arr;
}

// A 7-bag randomizer. Draws in shuffled 7-piece bags: when the bag is
// exhausted a fresh one is generated and shuffled.
function newBag(seed) {
  let rng = mulberry32(seed);
  let bag = [];

  function refill() {
    bag = fisherYates([...PIECES], rng);
  }

  function next() {
    if (bag.length === 0) refill();
    return bag.pop();
  }

  function peek() {
    if (bag.length === 0) refill();
    return bag[bag.length - 1];
  }

  function reset(newSeed) {
    rng = mulberry32(newSeed);
    bag = [];
  }

  return { next, peek, reset };
}

module.exports = { newBag, mulberry32, fisherYates, PIECES };
