"""CC-299 — water_engine reference tests (pins E1..E5).

The contract (docs/water_engine.md): pure, deterministic water-surface
functions — no I/O, no random, no global state, stdlib only. Every expected
value here is an in-test transcription of the SPEC-pinned formulas; the
production module is never used to derive an expectation (except where the
claim IS a definition over the frame's own fields, e.g. foam/glint).

Fixtures are defined inside this file (no conftest.py).
"""

import dataclasses
import hashlib
import math

import pytest

import water_engine as g  # pythonpath=src

TWO_PI = 2.0 * math.pi
AMP = (0.45, 0.30, 0.15)
MAX_AMPLITUDE = 0.94
MAX_SLOPE = 0.55
MAX_RIPPLE = 0.04
MIN_WIDTH = 12
MAX_CYCLE_RATIO = 0.08
FOAM_SLOPE = 0.25
FOAM_LIGHT = 0.85
GLINT_LIGHT = 0.97
ABS_TOL = 1e-9
FLAG_MARGIN = 1e-7

WIDTHS = (12, 16, 48, 80)
SEEDS = (0, 1, 2, 7, 42, 12345)


# --- in-test transcription of the pinned formulas -------------------------


def _derive(seed):
    """Transcription of E1 make_params for seed >= 0."""
    d = hashlib.sha256(f"water|{seed}".encode()).digest()
    return dict(
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
    """A hand-built WaveParams carrier (deterministic, no derivation)."""
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


def _pure_height(p, x, t, W):
    """Sum of the three sines only (no ripple)."""
    h = 0.0
    for i in range(3):
        k = TWO_PI * _cycles_eff(p.cycles[i], W) / W
        h += p.amplitudes[i] * math.sin(k * x + p.omegas[i] * t + p.phases[i])
    return h


def _height(p, x, t, W):
    return _pure_height(p, x, t, W) + _ripple(p.seed, x % W, t)


def _light(p, x, t, W):
    k_l = TWO_PI * _cycles_eff(p.light_cycles, W) / W
    v = (0.5
         + 0.3 * math.sin(k_l * x + p.omegas[0] * t + p.phases[0])
         + 0.25 * math.cos(TWO_PI * x / 7 + 0.7 * t))
    return max(0.0, min(1.0, v))


# --- fixtures (inside the file) -------------------------------------------


@pytest.fixture
def hand_params():
    return _hand()


@pytest.fixture
def derived_params():
    return {seed: g.make_params(seed) for seed in SEEDS}


# --- E1: make_params ------------------------------------------------------


def test_make_params_matches_the_pinned_derivation(derived_params):
    for seed, p in derived_params.items():
        e = _derive(seed)
        assert p.seed == seed
        assert tuple(p.amplitudes) == e["amplitudes"]
        assert tuple(p.cycles) == e["cycles"]
        assert p.light_cycles == e["light_cycles"]
        for i in range(3):
            assert p.omegas[i] == pytest.approx(e["omegas"][i], abs=ABS_TOL)
            assert p.phases[i] == pytest.approx(e["phases"][i], abs=ABS_TOL)


def test_make_params_is_deterministic(derived_params):
    for seed in SEEDS:
        assert g.make_params(seed) == g.make_params(seed)
        assert g.make_params(seed) == derived_params[seed]


def test_make_params_ranges(derived_params):
    for p in derived_params.values():
        assert len(p.cycles) == 3 and len(p.omegas) == 3 and len(p.phases) == 3
        for c in p.cycles:
            assert c in (2, 3, 4)
        for omega in p.omegas:
            assert 0.04 <= omega < 0.12
        for phase in p.phases:
            assert 0.0 <= phase < TWO_PI
        assert p.light_cycles in (2, 3)


def test_amplitudes_are_exactly_the_pinned_triple(derived_params):
    for p in derived_params.values():
        assert tuple(p.amplitudes) == AMP
    assert _hand().amplitudes == AMP


def test_different_seeds_differ_in_phases():
    for seed_a, seed_b in ((0, 1), (1, 2), (7, 42), (0, 12345), (2, 99999)):
        assert g.make_params(seed_a).phases != g.make_params(seed_b).phases


def test_params_are_frozen(hand_params):
    with pytest.raises(dataclasses.FrozenInstanceError):
        hand_params.phases = (0.0, 0.0, 0.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        hand_params.cycles = (2, 2, 2)
    with pytest.raises(dataclasses.FrozenInstanceError):
        hand_params.light_cycles = 2


@pytest.mark.parametrize("seed", [-1, -2, -1000])
def test_negative_seed_raises_value_error(seed):
    with pytest.raises(ValueError):
        g.make_params(seed)


# --- E2: surface_height ---------------------------------------------------


@pytest.mark.parametrize("width", [0, 1, 5, 11])
def test_width_below_min_raises(hand_params, width):
    with pytest.raises(ValueError):
        g.surface_height(hand_params, 0, 0, width)
    with pytest.raises(ValueError):
        g.frame_state(hand_params, 0, width)


def test_surface_is_periodic_in_width(hand_params):
    for width in WIDTHS:
        for t in (0, 1, 7):
            for x in (0, 1, width - 1, width // 2):
                base = g.surface_height(hand_params, x, t, width)
                assert base == pytest.approx(
                    g.surface_height(hand_params, x + width, t, width), abs=1e-12)
                assert base == pytest.approx(
                    g.surface_height(hand_params, x + 3 * width, t, width), abs=1e-12)
                assert base == pytest.approx(
                    g.surface_height(hand_params, x - width, t, width), abs=1e-12)
                assert base == pytest.approx(
                    g.surface_height(hand_params, x % width, t, width), abs=1e-12)
            # x is reduced BEFORE the ripple hash: a wrapped x hashes wrapped.
            assert g.surface_height(hand_params, width + 5, t, width) == pytest.approx(
                g.surface_height(hand_params, 5, t, width), abs=1e-12)


def test_surface_matches_the_transcribed_formula(hand_params, derived_params):
    for p in (hand_params,) + tuple(derived_params.values()):
        for width in (12, 25, 48):
            for t in (0, 2):
                for x in range(width):
                    assert g.surface_height(p, x, t, width) == pytest.approx(
                        _height(p, x, t, width), abs=ABS_TOL)


def test_amplitude_bound_on_grid(derived_params):
    for p in (_hand(),) + tuple(derived_params.values()):
        for width in WIDTHS:
            for t in (0, 1, 7):
                for x in range(width):
                    assert abs(g.surface_height(p, x, t, width)) <= MAX_AMPLITUDE


def test_ripple_is_bounded(hand_params, derived_params):
    for p in (hand_params,) + tuple(derived_params.values()):
        for width in (12, 16, 49):
            for t in (0, 3):
                for x in range(width):
                    h = g.surface_height(p, x, t, width)
                    assert abs(h - _pure_height(p, x, t, width)) <= MAX_RIPPLE


# --- E3: frame_state ------------------------------------------------------


def test_frame_lengths_and_types(hand_params):
    for width in WIDTHS:
        st = g.frame_state(hand_params, 1, width)
        assert len(st.heights) == width
        assert len(st.light) == width
        assert len(st.foam) == width
        assert len(st.glint) == width
        assert all(isinstance(v, float) for v in st.heights)
        assert all(isinstance(v, float) for v in st.light)
        assert all(isinstance(v, bool) for v in st.foam)
        assert all(isinstance(v, bool) for v in st.glint)


def test_frame_heights_equal_surface(derived_params):
    for p in (_hand(),) + tuple(derived_params.values()):
        for width in (12, 16, 48):
            for t in (0, 2):
                st = g.frame_state(p, t, width)
                for x in range(width):
                    assert st.heights[x] == pytest.approx(
                        g.surface_height(p, x, t, width), abs=ABS_TOL)


def test_neighbour_slope_bound_including_wrap(derived_params):
    for p in (_hand(cycles=(4, 4, 4)), _hand(cycles=(2, 3, 4))) + tuple(
        derived_params.values()
    ):
        for width in WIDTHS:
            for t in (0, 1, 7):
                heights = g.frame_state(p, t, width).heights
                for x in range(width):
                    assert abs(heights[(x + 1) % width] - heights[x]) <= MAX_SLOPE


def test_light_is_clamped_to_unit_interval(derived_params):
    for p in (_hand(cycles=(4, 4, 4), light_cycles=3),
              _hand(cycles=(2, 3, 4), light_cycles=2)) + tuple(
        derived_params.values()
    ):
        for width in WIDTHS:
            for t in (0, 1, 7):
                for value in g.frame_state(p, t, width).light:
                    assert 0.0 <= value <= 1.0


def test_light_matches_the_transcribed_formula(derived_params):
    for p in (_hand(),) + tuple(derived_params.values()):
        for width in (12, 13, 49):
            for t in (0, 1, 7):
                light = g.frame_state(p, t, width).light
                for x in range(width):
                    assert light[x] == pytest.approx(_light(p, x, t, width), abs=ABS_TOL)


def test_foam_and_glint_are_defined_from_the_frame_itself(derived_params):
    """Definition check over the frame's own fields — exact, no float-order slack."""
    for p in (_hand(cycles=(4, 4, 4), light_cycles=3),
              _hand(cycles=(3, 2, 4), light_cycles=2)) + tuple(
        derived_params.values()
    ):
        for width in WIDTHS:
            for t in (0, 1, 7):
                st = g.frame_state(p, t, width)
                for x in range(width):
                    slope = abs(st.heights[(x + 1) % width]
                               - st.heights[(x - 1) % width]) / 2.0
                    expected_foam = st.light[x] > g.FOAM_LIGHT and slope > g.FOAM_SLOPE
                    expected_glint = expected_foam and st.light[x] > g.GLINT_LIGHT
                    assert st.foam[x] is expected_foam, f"foam at x={x}"
                    assert st.glint[x] is expected_glint, f"glint at x={x}"
                    assert not (st.glint[x] and not st.foam[x])


def test_foam_cell_zero_against_a_hand_computed_formula(derived_params):
    """foam[0] from a fully independent transcription (margin-skip near thresholds)."""
    for p in (_hand(),) + tuple(derived_params.values()):
        for width in (12, 16, 49):
            for t in (0, 1, 7):
                st = g.frame_state(p, t, width)
                heights = [_height(p, x, t, width) for x in range(width)]
                light = [_light(p, x, t, width) for x in range(width)]
                slope = abs(heights[1] - heights[width - 1]) / 2.0
                if (abs(light[0] - FOAM_LIGHT) < FLAG_MARGIN
                        or abs(slope - FOAM_SLOPE) < FLAG_MARGIN
                        or abs(light[0] - GLINT_LIGHT) < FLAG_MARGIN):
                    continue
                expected_foam = light[0] > FOAM_LIGHT and slope > FOAM_SLOPE
                assert st.foam[0] is expected_foam
                assert st.glint[0] is (expected_foam and light[0] > GLINT_LIGHT)


def test_frame_state_reaches_both_foam_and_plain_cells():
    """Sanity: the flags are not a constant (a real surface has foam somewhere)."""
    seen_foam = seen_plain = False
    for seed in SEEDS:
        p = g.make_params(seed)
        for width in (16, 48, 80):
            for t in (0, 1, 7):
                st = g.frame_state(p, t, width)
                seen_foam = seen_foam or any(st.foam)
                seen_plain = seen_plain or not all(st.foam)
        if seen_foam and seen_plain:
            return
    assert seen_foam and seen_plain


# --- E4: immutability and independence ------------------------------------


def test_all_frame_fields_are_tuples(hand_params):
    st = g.frame_state(hand_params, 1, 16)
    for name in ("heights", "light", "foam", "glint"):
        assert isinstance(getattr(st, name), tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.heights = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.foam = ()


def test_equal_arguments_give_equal_states(hand_params):
    assert g.frame_state(hand_params, 1, 12) == g.frame_state(hand_params, 1, 12)
    assert g.frame_state(hand_params, 1, 12) != g.frame_state(hand_params, 2, 12)


def test_different_widths_share_no_mutable_objects(hand_params):
    st1 = g.frame_state(hand_params, 1, 12)
    st2 = g.frame_state(hand_params, 1, 20)
    for name in ("heights", "light", "foam", "glint"):
        a, b = getattr(st1, name), getattr(st2, name)
        assert a is not b
        assert id(a) != id(b)
    st3 = g.frame_state(hand_params, 1, 12)
    for name in ("heights", "light", "foam", "glint"):
        assert getattr(st1, name) is not getattr(st3, name)


def test_params_are_unchanged_by_frame_calls(hand_params):
    snapshot = dataclasses.asdict(hand_params)
    for width in (12, 16, 48):
        for t in (0, 1):
            g.frame_state(hand_params, t, width)
            g.surface_height(hand_params, 3, t, width)
    assert dataclasses.asdict(hand_params) == snapshot


# --- E5: temporal coherence -----------------------------------------------


def test_height_changes_at_most_half_per_tick(derived_params):
    for p in (_hand(omegas=(0.10, 0.09, 0.11)),
              _hand(omegas=(0.05, 0.11, 0.07))) + tuple(derived_params.values()):
        for width in (12, 16, 48):
            for t in range(6):
                for x in range(width):
                    delta = abs(g.surface_height(p, x, t + 1, width)
                                - g.surface_height(p, x, t, width))
                    assert delta <= 0.50
