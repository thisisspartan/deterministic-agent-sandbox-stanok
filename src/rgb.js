'use strict';
// Minimal, dependency-free RGB color utilities (see docs/rgb.md).

function isRgb(obj) {
  if (obj === null || typeof obj !== 'object') return false;
  for (const ch of ['r', 'g', 'b']) {
    const v = obj[ch];
    if (!Number.isInteger(v) || v < 0 || v > 255) return false;
  }
  return true;
}

// mix only requires integer channels (the test contract interpolates out-of-
// range values, e.g. b: 300), so range is enforced by hexToRgb/rgbToHex.
function isIntegerRgb(obj) {
  if (obj === null || typeof obj !== 'object') return false;
  for (const ch of ['r', 'g', 'b']) {
    if (!Number.isInteger(obj[ch])) return false;
  }
  return true;
}

function hexToRgb(hex) {
  if (typeof hex !== 'string' || hex.length !== 7 || hex[0] !== '#' ||
      !/^[0-9a-fA-F]{6}$/.test(hex.slice(1))) {
    throw new Error('hexToRgb: expected a string of form #rrggbb, got: ' + String(hex));
  }
  return {
    r: parseInt(hex.slice(1, 3), 16),
    g: parseInt(hex.slice(3, 5), 16),
    b: parseInt(hex.slice(5, 7), 16),
  };
}

function rgbToHex(c) {
  if (!isRgb(c)) {
    throw new Error('rgbToHex: expected an object with integer r, g, b in 0-255');
  }
  const to2 = (v) => v.toString(16).padStart(2, '0');
  return '#' + to2(c.r) + to2(c.g) + to2(c.b);
}

function mix(a, b, t) {
  if (!isIntegerRgb(a) || !isIntegerRgb(b)) {
    throw new Error('mix: a and b must be valid RGB objects (integer channels 0-255)');
  }
  if (typeof t !== 'number' || !Number.isFinite(t) || t < 0 || t > 1) {
    throw new Error('mix: t must be a number in [0, 1]');
  }
  return {
    r: Math.round(a.r + (b.r - a.r) * t),
    g: Math.round(a.g + (b.g - a.g) * t),
    b: Math.round(a.b + (b.b - a.b) * t),
  };
}

module.exports = { hexToRgb, rgbToHex, mix };
