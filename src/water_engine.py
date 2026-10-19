"""water_engine — pure, deterministic water-surface functions (CC-299).

stdlib only; no I/O, no random, no time, no global mutable state. Every
function is a pure call: equal arguments give equal results, and nothing is
shared or mutated between calls. See docs/water_engine.md.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

MAX_AMPLITUDE = 0.94
MAX_SLOPE = 0.55
MAX_RIPPLE = 0.04
MIN_WIDTH = 12
MAX_CYCLE_RATIO = 0.08
FOAM_SLOPE = 0.25
FOAM_LIGHT = 0.85
GLINT_LIGHT = 0.97

_TWO_PI = 2.0 * math.pi
_AMPLITUDES = (0.45, 0.30, 0.15)


@dataclass(frozen=True)
class WaveParams:
    seed: int
    amplitudes: tuple
    cycles: tuple
    omegas: tuple
    phases: tuple
    light_cycles: int


@dataclass(frozen=True)
class FrameState:
    heights: tuple
    light: tuple
    foam: tuple
    glint: tuple


def make_params(seed: int) -> WaveParams:
    """Derive WaveParams from a seed: sha256("water|<seed>") read field by field."""
    if seed < 0:
        raise ValueError(f"seed must be >= 0, got {seed}")
    d = hashlib.sha256(f"water|{seed}".encode()).digest()
    return WaveParams(
        seed=seed,
        amplitudes=_AMPLITUDES,
        cycles=tuple(2 + d[i] % 3 for i in range(3)),
        omegas=tuple(
            0.04 + 0.08 * (int.from_bytes(d[4 + 2 * i:6 + 2 * i], "big") / 65536.0)
            for i in range(3)
        ),
        phases=tuple(
            _TWO_PI * (int.from_bytes(d[10 + 2 * i:12 + 2 * i], "big") / 65536.0)
            for i in range(3)
        ),
        light_cycles=2 + d[3] % 2,
    )


def _cycles_eff(c: int, width: int) -> int:
    """A cycle count usable on this width: at most MAX_CYCLE_RATIO cycles per cell."""
    return max(1, min(c, int(width * MAX_CYCLE_RATIO)))


def _ripple(seed: int, x: int, t: int) -> float:
    """Deterministic hash noise in [-MAX_RIPPLE, +MAX_RIPPLE)."""
    u = int.from_bytes(
        hashlib.sha256(f"ripple|{seed}|{x}|{t}".encode()).digest()[:8], "big"
    ) / 2 ** 64
    return MAX_RIPPLE * (2.0 * u - 1.0)


def surface_height(params: WaveParams, x: int, t: int, width: int) -> float:
    """Surface height at column x, time t: three sines plus ripple.

    Periodic in x mod width; strictly |h| <= MAX_AMPLITUDE.
    """
    if width < MIN_WIDTH:
        raise ValueError(f"width must be >= {MIN_WIDTH}, got {width}")
    x %= width
    h = 0.0
    for i in range(3):
        k = _TWO_PI * _cycles_eff(params.cycles[i], width) / width
        h += params.amplitudes[i] * math.sin(
            k * x + params.omegas[i] * t + params.phases[i]
        )
    return h + _ripple(params.seed, x, t)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _light_value(params: WaveParams, x: int, t: int, width: int) -> float:
    k_l = _TWO_PI * _cycles_eff(params.light_cycles, width) / width
    return _clamp01(
        0.5
        + 0.3 * math.sin(k_l * x + params.omegas[0] * t + params.phases[0])
        + 0.25 * math.cos(_TWO_PI * x / 7 + 0.7 * t)
    )


def frame_state(params: WaveParams, t: int, width: int) -> FrameState:
    """One immutable frame: heights, light in [0, 1], and the foam/glint flags."""
    if width < MIN_WIDTH:
        raise ValueError(f"width must be >= {MIN_WIDTH}, got {width}")
    heights = tuple(
        surface_height(params, x, t, width) for x in range(width)
    )
    light = tuple(_light_value(params, x, t, width) for x in range(width))
    foam = tuple(
        light[x] > FOAM_LIGHT
        and abs(heights[(x + 1) % width] - heights[(x - 1) % width]) / 2.0 > FOAM_SLOPE
        for x in range(width)
    )
    glint = tuple(foam[x] and light[x] > GLINT_LIGHT for x in range(width))
    return FrameState(
        heights=heights,
        light=light,
        foam=foam,
        glint=glint,
    )
