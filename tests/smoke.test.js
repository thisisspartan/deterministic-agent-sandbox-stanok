// Reference tests for src/smoke.js (node:test + node:assert/strict).
// Contract: add(a, b) -> the numeric sum of a and b.
import test from "node:test";
import assert from "node:assert/strict";
import { add } from "../src/smoke.js";

test("add(2, 3) === 5", () => {
  assert.equal(add(2, 3), 5);
});

test("add(-1, 1) === 0", () => {
  assert.equal(add(-1, 1), 0);
});

test("add(0, 0) === 0", () => {
  assert.equal(add(0, 0), 0);
});
