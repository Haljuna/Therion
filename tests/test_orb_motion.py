import pytest
from therion.interface.orb_motion import OrbMotion
from therion.interface.hud_style import LOOKS, STATES


def run(m, seconds, step=1/60):
    for _ in range(int(seconds/step)):
        m.advance(step)


def test_unknown_state_is_idle():
    m = OrbMotion(); m.set_visual('nada')
    assert m.state == 'idle' and m.frame_state().label == 'EM REPOUSO'


def test_look_blends_without_jump():
    m = OrbMotion(); run(m, 1); m.set_visual('listening')
    before = m.look.arc_deg; m.advance(1/60)
    assert abs(m.look.arc_deg-before) < 5
    run(m, 2); assert abs(m.look.arc_deg-LOOKS['listening'].arc_deg) < .5


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -3, 7, 'x'])
def test_intensity_is_clamped(value):
    m = OrbMotion(); m.set_visual('speaking', value); run(m, .5)
    assert 0. <= m.level <= 1. and 0. <= m.voice <= 1.
    assert 0. <= m.frame_state().level <= 1.


def test_repeated_state_does_not_restart_assembly_or_flash():
    m = OrbMotion(); m.set_visual('thinking'); run(m, 1)
    m.set_visual('speaking'); run(m, .05); flash = m.flash
    m.set_visual('speaking'); assert m.flash == flash > 0
    m.set_visual('preparing'); assert m.assembly == 0
    run(m, .6); assembly = m.assembly
    for _ in range(10):
        m.set_visual('preparing'); m.advance(.05)
    assert m.assembly > assembly


def test_error_is_amber_and_stops_spin():
    m = OrbMotion(); m.set_visual('error'); run(m, 3)
    assert m.look.amber > .95 and abs(m.look.dim-.5) < .02
    spin = m.spin; run(m, 1); assert abs(m.spin-spin) < 1e-3


def test_waiting_blinks_and_idle_does_not():
    m = OrbMotion(); m.set_visual('awaiting_confirmation'); run(m, 3)
    values = []
    for _ in range(100):
        m.advance(1/60); values.append(m.blink)
    assert max(values)-min(values) > .5
    m.set_visual('idle'); run(m, 3); assert m.blink > .99


def test_reduced_mode_jumps_to_target_and_freezes():
    m = OrbMotion(); m.set_visual('thinking'); m.advance(1/60, reduced=True)
    assert m.look == LOOKS['thinking'] and m.trail == 0 and m.blink == 1
    spin = m.spin; m.advance(1., reduced=True); assert m.spin == spin


def test_frame_state_label_follows_state():
    m = OrbMotion(); m.set_visual('listening'); run(m, .2)
    assert m.frame_state().label == 'OUVINDO'


def test_voice_moves_level_only_while_listening_or_speaking():
    for state in STATES:
        m = OrbMotion(); m.set_visual('speaking', 1); run(m, .5)
        m.set_visual(state, 1); run(m, 2)
        if state in {'listening', 'speaking'}:
            assert m.energy > .9 and m.level > .8
        else:
            assert m.energy == 0 and m.voice == 0 and m.level < .5


def test_trail_only_while_thinking_or_executing():
    for state in STATES:
        m = OrbMotion(); m.set_visual(state); run(m, 2)
        assert (m.trail > .3) == (state in {'thinking', 'executing'})


def test_arcs_stop_turning_after_thinking():
    m = OrbMotion(); m.set_visual('thinking'); run(m, 3)
    a = m.frame_state().arc_rotation; m.advance(1/60)
    assert m.frame_state().arc_rotation != a
    m.set_visual('idle'); run(m, 5)
    a = m.frame_state().arc_rotation; run(m, 1)
    assert abs(m.frame_state().arc_rotation-a) < 1e-3


def test_arcs_keep_turning_while_transcribing():
    m = OrbMotion(); m.set_visual('transcribing'); run(m, 3)
    a = m.frame_state().arc_rotation; run(m, 3)
    assert m.frame_state().arc_rotation > a+.3


def test_leaving_preparing_early_does_not_pop():
    m = OrbMotion(); m.set_visual('preparing'); run(m, .3)
    before = m.assembly; m.set_visual('listening'); m.advance(1/60)
    assert before < m.assembly < before+.05
    run(m, 2); assert m.assembly == 1
