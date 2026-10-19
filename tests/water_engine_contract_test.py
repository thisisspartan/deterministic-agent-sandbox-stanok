"""Calibrated contract oracle for src/water_engine.py (SPEC-WATER-CONSOLE E1..E6).

Independence policy: every expected value is an in-test transcription of the
SPEC-pinned formulas/constants; the production module is never used to derive
an expectation. Hand-built WaveParams carriers hold hand-chosen values.
Equivalence properties (frame heights == surface_height) are claims of the
contract itself.

Calibration: lab /tmp/oracle-lab-water, mutants M1..M10 — see specs/STATUS.md
tables. GREEN on reference, RED on targeted mutants.
"""
import dataclasses
import hashlib
import math

import pytest

import water_engine as g

TWO_PI = 2.0 * math.pi
AMP = (0.45, 0.30, 0.15)
FOAM_LIGHT = 0.85
FOAM_SLOPE = 0.25
GLINT_LIGHT = 0.97
MAX_AMPLITUDE = 0.94
MAX_SLOPE = 0.55
MAX_RIPPLE = 0.04
MIN_WIDTH = 12
MAX_CYCLE_RATIO = 0.08
ABS_TOL = 1e-9
FLAG_MARGIN = 1e-7


def _derive(seed):
    """Transcription of E1 make_params for seed >= 0."""
    d = hashlib.sha256(f"water|{seed}".encode()).digest()
    return g.WaveParams(
        seed=seed,
        amplitudes=AMP,
        cycles=tuple(2 + d[i] % 3 for i in range(3)),
        omegas=tuple(
            0.04 + 0.08 * (int.from_bytes(d[4 + 2 * i:6 + 2 * i], "big") / 65536.0)
            for i in range(3)
        ),
        phases=tuple(
            TWO_PI * (int.from_bytes(d[10 + 2 * i:12 + 2 * i], "big") / 65536.0)
            for i in range(3)
        ),
        light_cycles=2 + d[3] % 2,
    )


def _hand(seed=3, cycles=(4, 3, 2), light_cycles=3, omegas=(0.10, 0.07, 0.05),
          phases=(0.3, 2.0, 4.5)):
    return g.WaveParams(seed=seed, amplitudes=AMP, cycles=tuple(cycles),
                        omegas=tuple(omegas), phases=tuple(phases),
                        light_cycles=light_cycles)


def _cycles_eff(c, W):
    return max(1, min(c, int(W * MAX_CYCLE_RATIO)))


def _ripple(seed, x, t):
    u = int.from_bytes(
        hashlib.sha256(f"ripple|{seed}|{x}|{t}".encode()).digest()[:8], "big"
    ) / 2 ** 64
    return MAX_RIPPLE * (2.0 * u - 1.0)


def _heights(p, t, W):
    out = []
    for x in range(W):
        h = 0.0
        for i in range(3):
            k = TWO_PI * _cycles_eff(p.cycles[i], W) / W
            h += p.amplitudes[i] * math.sin(k * x + p.omegas[i] * t + p.phases[i])
        out.append(h + _ripple(p.seed, x, t))
    return out


def _lights(p, t, W):
    k_l = TWO_PI * _cycles_eff(p.light_cycles, W) / W
    out = []
    for x in range(W):
        v = (0.5
             + 0.3 * math.sin(k_l * x + p.omegas[0] * t + p.phases[0])
             + 0.25 * math.cos(TWO_PI * x / 7 + 0.7 * t))
        out.append(max(0.0, min(1.0, v)))
    return out


def _check_flags(st, hs, light, W):
    """Compare production flags to transcribed ones; cells whose expected
    values sit within FLAG_MARGIN of a pinned threshold are skipped
    (legitimate float-order disagreement near the boundary)."""
    for x in range(W):
        slope = abs(hs[(x + 1) % W] - hs[(x - 1) % W]) / 2.0
        if (abs(light[x] - FOAM_LIGHT) < FLAG_MARGIN
                or abs(slope - FOAM_SLOPE) < FLAG_MARGIN
                or abs(light[x] - GLINT_LIGHT) < FLAG_MARGIN):
            continue
        exp_foam = light[x] > FOAM_LIGHT and slope > FOAM_SLOPE
        exp_glint = exp_foam and light[x] > GLINT_LIGHT
        assert st.foam[x] == exp_foam, f"foam mismatch at x={x}"
        assert st.glint[x] == exp_glint, f"glint mismatch at x={x}"


def test_spec_constants_and_interfaces_pinned():
    assert g.MAX_AMPLITUDE == MAX_AMPLITUDE
    assert g.MAX_SLOPE == MAX_SLOPE
    assert g.MAX_RIPPLE == MAX_RIPPLE
    assert g.MIN_WIDTH == MIN_WIDTH
    assert g.MAX_CYCLE_RATIO == MAX_CYCLE_RATIO
    assert g.FOAM_SLOPE == FOAM_SLOPE
    assert g.FOAM_LIGHT == FOAM_LIGHT
    assert g.GLINT_LIGHT == GLINT_LIGHT
    wp = {f.name for f in dataclasses.fields(g.WaveParams)}
    assert wp == {"seed", "amplitudes", "cycles", "omegas", "phases", "light_cycles"}
    fs = {f.name for f in dataclasses.fields(g.FrameState)}
    assert fs == {"heights", "light", "foam", "glint"}


def test_E1_derivation_matches_spec():
    for seed in (0, 1, 2, 7, 42, 12345):
        p = g.make_params(seed)
        e = _derive(seed)
        assert p.seed == seed
        assert p.amplitudes == AMP
        assert tuple(p.cycles) == e.cycles
        assert all(c in (2, 3, 4) for c in p.cycles)
        assert p.light_cycles == e.light_cycles
        for i in range(3):
            assert p.omegas[i] == pytest.approx(e.omegas[i], abs=ABS_TOL)
            assert 0.04 <= p.omegas[i] < 0.12
            assert p.phases[i] == pytest.approx(e.phases[i], abs=ABS_TOL)
            assert 0.0 <= p.phases[i] < TWO_PI
        # determinism follows from matching the transcription; assert it too
        q = g.make_params(seed)
        assert (q.cycles, q.omegas, q.phases) == (p.cycles, p.omegas, p.phases)


def test_E1_frozen_and_seed_negative():
    with pytest.raises(ValueError):
        g.make_params(-1)
    p = _hand()
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.phases = (0.0, 0.0, 0.0)


def test_E2_surface_matches_transcription():
    p = _hand()
    for W in (12, 25):
        for t in (0, 2):
            exp = _heights(p, t, W)
            for x in range(W):
                assert g.surface_height(p, x, t, W) == pytest.approx(exp[x], abs=ABS_TOL)
            assert g.surface_height(p, W, t, W) == pytest.approx(exp[0], abs=ABS_TOL)
            assert g.surface_height(p, 2 * W + 5, t, W) == pytest.approx(exp[5], abs=ABS_TOL)


def test_E2_periodicity_and_ripple_bound():
    p = _hand()
    for W in (12, 49):
        for t in (0, 3):
            for x in (0, 7, W - 1):
                assert g.surface_height(p, x, t, W) == pytest.approx(
                    g.surface_height(p, x + W, t, W), abs=1e-12)
                assert g.surface_height(p, x, t, W) == pytest.approx(
                    g.surface_height(p, x % W, t, W), abs=1e-12)
            pure = 0.0
            for x in range(W):
                h = g.surface_height(p, x, t, W)
                assert abs(h) <= MAX_AMPLITUDE + 1e-12
                pure = 0.0
                for i in range(3):
                    k = TWO_PI * _cycles_eff(p.cycles[i], W) / W
                    pure += p.amplitudes[i] * math.sin(
                        k * x + p.omegas[i] * t + p.phases[i])
                assert abs(h - pure) <= MAX_RIPPLE + 1e-12


def test_E2_width_negative():
    p = _hand()
    with pytest.raises(ValueError):
        g.surface_height(p, 0, 0, MIN_WIDTH - 1)
    with pytest.raises(ValueError):
        g.frame_state(p, 0, MIN_WIDTH - 1)


def test_E3_frame_heights_equal_surface():
    p = _hand()
    W = 16
    st = g.frame_state(p, 2, W)
    for x in range(W):
        assert st.heights[x] == pytest.approx(g.surface_height(p, x, 2, W), abs=ABS_TOL)


def test_E6_golden_seed1_width48_t0():
    prod = g.frame_state(g.make_params(1), 0, 48)
    p = _derive(1)  # expected params via transcription — pins make_params too
    W = 48
    hs = _heights(p, 0, W)
    light = _lights(p, 0, W)
    assert len(prod.heights) == W and len(prod.light) == W
    assert len(prod.foam) == W and len(prod.glint) == W
    for x in range(W):
        assert prod.heights[x] == pytest.approx(hs[x], abs=ABS_TOL)
        assert prod.light[x] == pytest.approx(light[x], abs=ABS_TOL)
        assert abs(prod.heights[x]) <= MAX_AMPLITUDE + 1e-12
        assert 0.0 <= prod.light[x] <= 1.0
    _check_flags(prod, hs, light, W)


def test_E3_invariants_and_flag_definitions():
    combos = [
        (_hand(cycles=(4, 4, 4), light_cycles=3), 12),
        (_hand(cycles=(2, 3, 4), light_cycles=2), 13),
        (_hand(cycles=(3, 2, 4), light_cycles=3), 49),
        (_hand(cycles=(4, 4, 2), light_cycles=2), 80),
    ]
    for p, W in combos:
        for t in (0, 1, 7):
            st = g.frame_state(p, t, W)
            assert len(st.heights) == W
            hs = list(st.heights)
            for x in range(W):
                assert abs(hs[(x + 1) % W] - hs[x]) <= MAX_SLOPE + 1e-12
                assert 0.0 <= st.light[x] <= 1.0
            _check_flags(st, hs, list(st.light), W)


def test_E4_immutability_and_independence():
    p = _hand()
    snap = dataclasses.asdict(p)
    st1 = g.frame_state(p, 1, 12)
    st2 = g.frame_state(p, 1, 20)
    for st in (st1, st2):
        for name in ("heights", "light", "foam", "glint"):
            assert isinstance(getattr(st, name), tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        st1.heights = ()
    st1b = g.frame_state(p, 1, 12)
    assert st1 == st1b
    assert st1.heights is not st2.heights
    assert dataclasses.asdict(p) == snap


def test_E5_temporal_bound():
    for p, W in ((_hand(omegas=(0.10, 0.09, 0.11)), 12),
                 (_hand(omegas=(0.05, 0.11, 0.07)), 25)):
        for t in range(0, 6):
            for x in range(0, W, 3):
                d = abs(g.surface_height(p, x, t + 1, W)
                        - g.surface_height(p, x, t, W))
                assert d <= 0.50
