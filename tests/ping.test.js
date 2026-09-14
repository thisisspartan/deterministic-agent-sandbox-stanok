"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");

test("ping() returns 'pong'", () => {
  const { ping } = require("../src/ping.js");
  assert.strictEqual(ping(), "pong");
});
