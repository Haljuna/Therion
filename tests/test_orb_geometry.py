"""Forma da orbe holográfica: camadas, limites e nível de detalhe."""
import numpy as np
import pytest
from therion.interface.orb_geometry import (build_orb, shell_plates, raised_heights, VERTEX_FLOATS,
    ANTENNA, CAGE, SHELL, CORE, GYRO, EYE, SPARKS)


def test_mesh_has_every_layer_inside_the_sphere():
    mesh = build_orb()
    allv = np.vstack((mesh.surfaces, mesh.lines, mesh.points))
    assert allv.dtype == np.float32 and allv.shape[1] == VERTEX_FLOATS
    assert np.isfinite(allv).all()
    assert set(np.unique(allv[:, 7]).astype(int)) == {ANTENNA, CAGE, SHELL, CORE, GYRO, EYE, SPARKS}
    assert np.linalg.norm(allv[:, :3], axis=1).max() <= 1.2
    assert len(mesh.surfaces) % 3 == 0 and len(mesh.lines) % 6 == 0


def test_shell_covers_between_half_and_seventy_percent():
    plates = shell_plates()
    assert 60 <= len(plates) <= 80
    rng = np.random.default_rng(1)
    v = rng.normal(size=(20000, 3)); v /= np.linalg.norm(v, axis=1)[:, None]
    lat = np.arcsin(v[:, 1]); lon = np.mod(np.arctan2(v[:, 2], v[:, 0]), 2*np.pi)
    hit = np.zeros(len(v), bool)
    for lat0, lat1, lon0, lon1 in plates:
        d = np.mod(lon - lon0, 2*np.pi)
        hit |= (lat >= lat0) & (lat <= lat1) & (d <= np.mod(lon1 - lon0, 2*np.pi))
    assert .5 <= hit.mean() <= .7


def test_detail_flags_follow_the_spec():
    mesh = build_orb()
    def share(arr, layer):
        sel = arr[arr[:, 7] == layer]
        return (sel[:, 9] == 1).mean()
    assert share(mesh.points, SPARKS) == pytest.approx(.7, abs=.05)
    assert share(mesh.lines, CORE) > .8
    assert share(mesh.lines, CAGE) == pytest.approx(.5, abs=.1)
    for layer in (ANTENNA, GYRO, EYE):
        assert share(mesh.lines, layer) == 0


def test_spin_factors_and_counts():
    mesh = build_orb()
    spins = {l: set(np.round(mesh.lines[mesh.lines[:, 7] == l, 8], 3).tolist())
             for l in (ANTENNA, CAGE, SHELL, CORE, GYRO)}
    assert spins == {ANTENNA: {1.0}, CAGE: {1.0}, SHELL: {1.0}, CORE: {-0.5}, GYRO: {1.5}}
    assert 1400 <= (mesh.points[:, 7] == SPARKS).sum() <= 1600
    eye = mesh.lines[mesh.lines[:, 7] == EYE]
    assert set(np.round(eye[:, 8], 3).tolist()) <= {0.0, 2.0}


def test_build_is_deterministic():
    a, b = build_orb(), build_orb()
    assert all(np.array_equal(x, y) for x, y in
               zip((a.surfaces, a.lines, a.points), (b.surfaces, b.lines, b.points)))


def test_some_plates_are_raised_within_the_sphere():
    h = raised_heights()
    assert len(h) == len(shell_plates())
    assert .2 <= np.mean(h > 0) <= .3
    assert h[h > 0].min() >= .03 and h.max() <= .10
    mesh = build_orb()
    assert VERTEX_FLOATS == 14
    allv = np.vstack((mesh.surfaces, mesh.lines, mesh.points))
    lifted = np.linalg.norm(allv[:, :3], axis=1)+np.maximum(allv[:, 12], allv[:, 13])*1.35
    assert lifted.max() <= 1.2
    walls = mesh.lines[(mesh.lines[:, 7] == SHELL) & (mesh.lines[:, 12] != mesh.lines[:, 13])]
    assert len(walls) > 0   # quinas verticais ligam a base ao topo


def test_raised_plate_shares_one_seed_so_it_moves_as_a_block():
    mesh = build_orb()
    top = mesh.lines[(mesh.lines[:, 7] == SHELL) & (mesh.lines[:, 12] > 0) & (mesh.lines[:, 13] > 0)]
    seeds_per_height = {}
    for row in top:
        seeds_per_height.setdefault(round(float(row[12]), 6), set()).add(round(float(row[11]), 6))
    assert all(len(seeds) == 1 for seeds in seeds_per_height.values())
