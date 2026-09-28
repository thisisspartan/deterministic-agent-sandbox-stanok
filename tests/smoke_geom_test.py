"""Reference tests for src/smoke_geom.py (TASK-STANOK-CC-171).

Covers the ticket contract:
- distance(p1, p2): Euclidean distance; 3-4-5 integer case, zero
  distance, negative coordinates, float inputs.
- midpoint(p1, p2): midpoint as a 2-tuple of floats; int inputs ->
  float tuple, negative coordinates, identical points.
- triangle_area(a, b, c): shoelace area, always non-negative; right
  triangle, collinear -> 0.0, vertex order independence, float inputs.
"""

from smoke_geom import distance, midpoint, triangle_area


def test_distance_integer_3_4_5():
    assert distance((0, 0), (3, 4)) == 5.0
    assert distance((3, 4), (0, 0)) == 5.0


def test_distance_zero():
    assert distance((2.5, -1.0), (2.5, -1.0)) == 0.0
    assert distance((0, 0), (0, 0)) == 0.0


def test_distance_negative_coordinates():
    assert distance((-3, -4), (0, 0)) == 5.0
    assert distance((-1, -2), (-4, 2)) == 5.0


def test_distance_float_inputs():
    assert distance((0.5, 0.5), (1.5, 1.5)) == 2.0 ** 0.5
    assert distance((0.0, 0.0), (0.6, 0.8)) == 1.0


def test_distance_returns_float():
    assert isinstance(distance((0, 0), (3, 4)), float)


def test_midpoint_int_inputs_give_float_tuple():
    assert midpoint((0, 0), (4, 6)) == (2.0, 3.0)
    assert isinstance(midpoint((0, 0), (4, 6)), tuple)
    assert all(isinstance(c, float) for c in midpoint((0, 0), (4, 6)))


def test_midpoint_negative_coordinates():
    assert midpoint((-2, -4), (2, 4)) == (0.0, 0.0)
    assert midpoint((-1, -3), (-5, -7)) == (-3.0, -5.0)


def test_midpoint_identical_points():
    assert midpoint((7, 9), (7, 9)) == (7.0, 9.0)
    assert midpoint((-2.5, 0.5), (-2.5, 0.5)) == (-2.5, 0.5)


def test_triangle_area_right_triangle():
    assert triangle_area((0, 0), (4, 0), (0, 3)) == 6.0
    assert triangle_area((0, 0), (3, 0), (0, 4)) == 6.0


def test_triangle_area_collinear_is_zero():
    assert triangle_area((0, 0), (1, 1), (2, 2)) == 0.0
    assert triangle_area((-5, 0), (0, 0), (5, 0)) == 0.0


def test_triangle_area_vertex_order_independence():
    a, b, c = (0, 0), (4, 0), (0, 3)
    assert triangle_area(a, b, c) == triangle_area(b, a, c)
    assert triangle_area(a, b, c) == triangle_area(a, c, b)
    assert triangle_area(a, b, c) == triangle_area(b, c, a)
    assert triangle_area(a, b, c) == triangle_area(c, b, a)
    assert triangle_area(a, b, c) == triangle_area(c, a, b)


def test_triangle_area_float_inputs():
    assert triangle_area((0.0, 0.0), (2.5, 0.0), (0.0, 1.5)) == 1.875
    assert triangle_area((1.5, 2.5), (4.5, 2.5), (1.5, 5.5)) == 4.5


def test_triangle_area_returns_float():
    assert isinstance(triangle_area((0, 0), (4, 0), (0, 3)), float)
