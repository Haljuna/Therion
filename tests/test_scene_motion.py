"""Inércia independente da cadência e respeito ao movimento reduzido."""
import math
import pytest
from therion.interface.scene_motion import SceneMotion


def test_pointer_inertia_is_frame_rate_independent_and_has_no_overshoot():
    samples=[]
    for fps in (30,60,144):
        scene=SceneMotion();scene.aim(1,-1)
        for _ in range(fps):scene.advance(1/fps)
        assert all(-1<=value<=1 for value in scene.pointer)
        samples.append(scene.pointer)
    assert samples[0]==pytest.approx(samples[1],abs=1e-10)
    assert samples[1]==pytest.approx(samples[2],abs=1e-10)


def test_reduced_motion_removes_parallax_even_with_old_input():
    scene=SceneMotion();scene.aim(1,1)
    for _ in range(30):scene.advance(1/30)
    assert scene.pointer[0]>.8
    phase=scene.phase;scene.advance(1,reduced=True)
    assert scene.pointer==[0,0]
    assert scene.phase==phase


def test_scene_clock_runs_without_pointer_input_and_is_cadence_independent():
    phases=[]
    for fps in (30,60,144):
        scene=SceneMotion()
        for _ in range(3*fps):scene.advance(1/fps)
        assert scene.pointer==[0,0]
        phases.append(scene.phase)
    assert phases==pytest.approx([3,3,3])


@pytest.mark.parametrize('value',[float('inf'),float('nan'),-10,10])
def test_invalid_or_outside_pointer_never_produces_invalid_shader_input(value):
    scene=SceneMotion();scene.aim(value,value);scene.advance(1/60)
    assert all(math.isfinite(value) and -1<=value<=1 for value in scene.pointer)
