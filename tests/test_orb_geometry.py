import numpy as np
from therion.interface.orb_geometry import build_orb, fib_sphere, DOTS, ORBIT, AXIS, RUNNER, VERTEX_FLOATS


def test_dot_count_follows_request():
    for n in (1800, 3200):
        pts = build_orb(n).points
        assert (pts[:, 7] == DOTS).sum() == n


def test_dots_are_on_the_unit_sphere():
    pts = build_orb(3200).points
    dots = pts[pts[:, 7] == DOTS][:, :3]
    assert np.allclose(np.linalg.norm(dots, axis=1), 1., atol=1e-6)


def test_orbits_axis_and_runners_exist():
    mesh = build_orb()
    assert set(np.unique(mesh.lines[:, 7])) == {ORBIT, AXIS}
    assert (mesh.points[:, 7] == RUNNER).sum() == 3
    assert mesh.surfaces.shape == (0, VERTEX_FLOATS)


def test_orbit_radii_match_prototype():
    lines = build_orb().lines
    for index, radius in enumerate((1.24, 1.32, 1.42)):
        ring = lines[(lines[:, 7] == ORBIT) & (lines[:, 8] == index)][:, :3]
        assert len(ring) and np.allclose(np.linalg.norm(ring, axis=1), radius, atol=1e-6)


def test_build_is_deterministic():
    a, b = build_orb(seed=7), build_orb(seed=7)
    assert np.array_equal(a.points, b.points) and np.array_equal(a.lines, b.lines)


def test_fib_sphere_is_even():
    p = fib_sphere(400)
    assert p.shape == (400, 3) and abs(p[:, 1].mean()) < 1e-6
