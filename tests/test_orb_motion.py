"""Continuidade, cadência e vínculo real da animação com a intensidade recebida."""
import math
import pytest
from therion.interface.orb_motion import OrbMotion, SPEEDS, EXPRESSIONS


def run(motion,seconds,rate=60,reduced=False):
    for _ in range(round(seconds*rate)): motion.advance(1/rate,reduced=reduced)


def test_state_changes_keep_phase_and_blend_velocity_without_a_jump():
    motion=OrbMotion(); run(motion,2)
    phase,speed=motion.phase,motion.speed
    motion.set_visual('awaiting_confirmation')
    assert (motion.phase,motion.speed)==(phase,speed)
    motion.advance(1/60)
    assert phase<motion.phase<phase+speed/60
    assert SPEEDS['awaiting_confirmation']<motion.speed<speed
    phase=motion.phase
    motion.set_visual('speaking',.8)
    assert motion.phase==phase and motion.energy==0
    run(motion,.4)
    assert motion.phase>phase and .7<motion.energy<.8


def test_motion_and_envelope_are_independent_of_frame_rate():
    samples=[]
    for rate in (30,60,120):
        motion=OrbMotion(); motion.set_visual('speaking',.7); run(motion,2,rate)
        samples.append((motion.phase,motion.speed,motion.energy,motion.tension,motion.pulse,*motion.presence))
    for sample in samples[1:]: assert sample==pytest.approx(samples[0],abs=1e-10)


@pytest.mark.parametrize('state',[state for state in SPEEDS if state not in {'speaking','listening'}])
def test_non_audio_states_never_manufacture_a_voice_envelope(state):
    motion=OrbMotion(); motion.set_visual('speaking',1); run(motion,.5)
    motion.set_visual(state,1)
    assert motion.energy==motion.target_energy==0
    run(motion,.5)
    assert motion.energy==0


@pytest.mark.parametrize('state',['speaking','listening'])
def test_received_audio_has_soft_attack_and_release_and_stop_clears_it(state):
    motion=OrbMotion(); motion.set_visual(state,0); run(motion,.3)
    assert motion.energy==0
    motion.set_visual(state,1); motion.advance(1/60)
    assert 0<motion.energy<.3
    run(motion,.5); peak=motion.energy
    motion.set_visual(state,0); motion.advance(1/60)
    assert .8*peak<motion.energy<peak
    motion.set_visual('idle')
    assert motion.energy==0


def test_repeated_poll_does_not_retrigger_attention_pulse():
    a,b=OrbMotion(),OrbMotion()
    a.set_visual('listening'); b.set_visual('listening')
    for _ in range(120):
        a.set_visual('listening');a.advance(1/60);b.advance(1/60)
    assert a.pulse==pytest.approx(b.pulse) and a.pulse<.005


def test_surface_relaxes_without_retaining_an_old_voice_envelope():
    motion=OrbMotion(); motion.set_visual('listening',.8); run(motion,.5)
    tension=motion.tension
    motion.set_visual('thinking')
    assert motion.energy==motion.target_energy==0 and motion.tension==tension
    motion.advance(1/60)
    assert .8*tension<motion.tension<tension
    run(motion,.5)
    assert motion.tension<.02 and motion.energy==0


def test_reduced_motion_freezes_phase_and_drops_audio_and_transient():
    motion=OrbMotion(); motion.set_visual('speaking',1); run(motion,.5)
    phase=motion.phase
    run(motion,2,reduced=True)
    assert motion.phase==phase and motion.energy==motion.tension==motion.pulse==0
    assert motion.presence==(0.,0.,1.,0.)
    motion.advance(1/60)
    assert phase<motion.phase<phase+SPEEDS['speaking']/60


def test_non_finite_and_suspended_time_cannot_create_a_phase_jump():
    motion=OrbMotion(); motion.set_visual('thinking')
    for dt in (0,-1,math.nan,math.inf,-math.inf): motion.advance(dt)
    assert motion.phase==0 and motion.speed==1
    motion.advance(3600)
    assert 0<motion.phase<.17
    for value in (math.nan,math.inf,-5,0):
        motion.set_visual('speaking',value)
        assert motion.target_energy==0


def test_executing_has_a_distinct_smooth_channel_without_fake_audio():
    motion=OrbMotion();motion.set_visual('thinking');run(motion,.5)
    assert motion.action==0
    phase=motion.phase;motion.set_visual('executing',1)
    assert motion.phase==phase and motion.action==0 and motion.energy==0
    run(motion,.4)
    assert .95<motion.action<1 and motion.speed>SPEEDS['thinking']
    motion.set_visual('thinking');run(motion,.4)
    assert motion.action<.05 and motion.energy==0


def test_expressions_are_distinct_and_blend_without_resetting_body_or_clock():
    motion=OrbMotion()
    assert set(EXPRESSIONS)==set(SPEEDS)
    profiles=[]
    for state in ('listening','thinking','executing','speaking','awaiting_confirmation'):
        previous=motion.expression[:];phase=motion.phase
        motion.set_visual(state,0)
        assert motion.expression==previous and motion.phase==phase
        motion.advance(1/60)
        assert max(abs(a-b) for a,b in zip(previous,motion.expression))<.15
        run(motion,1)
        assert motion.expression==pytest.approx(EXPRESSIONS[state],abs=.001)
        assert motion.energy==0
        profiles.append(tuple(motion.expression))
    assert len(set(profiles))==5


def test_expression_transition_is_cadence_independent_and_reduced_motion_is_still():
    samples=[]
    for rate in (30,60,120):
        motion=OrbMotion();motion.set_visual('executing');run(motion,.5,rate)
        samples.append(motion.expression)
    assert samples[0]==pytest.approx(samples[1],abs=1e-10)
    assert samples[0]==pytest.approx(samples[2],abs=1e-10)
    motion.set_visual('listening',1);phase=motion.phase
    run(motion,1,reduced=True)
    assert motion.phase==phase and motion.energy==0
    assert motion.expression==list(EXPRESSIONS['listening'])


# Canais da orbe holográfica.
from therion.interface.orb_motion import SPIN_SECONDS


def test_spin_follows_spec_seconds_per_turn():
    for state, seconds in (('idle', 40), ('thinking', 6), ('executing', 4), ('listening', 120)):
        m = OrbMotion(); m.set_visual(state); run(m, 3)
        assert m.spin_rate == pytest.approx(2*math.pi/seconds, rel=.01)
        assert SPIN_SECONDS[state] == seconds
    m = OrbMotion(); m.set_visual('error'); run(m, 3)
    assert m.spin_rate == pytest.approx(0, abs=1e-3)


def test_trail_grows_with_speed():
    vals = []
    for state in ('idle', 'thinking', 'executing'):
        m = OrbMotion(); m.set_visual(state); run(m, 3); vals.append(m.trail)
    assert vals[0] == pytest.approx(0, abs=.01) and vals[0] < vals[1] < vals[2]
    assert vals[2] == pytest.approx(1, abs=.01)


def test_flash_only_on_think_to_speak_and_at_most_every_four_seconds():
    m = OrbMotion(); m.set_visual('idle'); run(m, 5)
    m.set_visual('speaking'); assert m.flash == 0
    m.set_visual('thinking'); run(m, 1); m.set_visual('speaking'); assert m.flash == 1
    run(m, .3); assert m.flash < .06
    for _ in range(4):
        m.set_visual('thinking'); run(m, .25); m.set_visual('speaking'); assert m.flash < .06; run(m, .25)
    run(m, 2); m.set_visual('executing'); run(m, .1); m.set_visual('synthesizing')
    assert m.flash == 1


def test_rim_tracks_voice_while_listening_and_blinks_while_waiting():
    m = OrbMotion(); m.set_visual('listening', .8); run(m, .5)
    assert m.rim == pytest.approx(m.energy)
    m.set_visual('awaiting_confirmation'); seen = []
    for _ in range(120):
        m.advance(1/60); seen.append(m.rim)
    assert min(seen) < .1 and max(seen) > .9
    m.set_visual('idle'); run(m, .1); assert m.rim == 0


def test_eye_and_tint_targets():
    for state, eye, tint in (('idle', .7, 0), ('error', .25, 1), ('partial', .55, 0)):
        m = OrbMotion(); m.set_visual(state); run(m, 1)
        assert m.eye == pytest.approx(eye, abs=.01) and m.tint == pytest.approx(tint, abs=.01)
    m = OrbMotion(); m.set_visual('speaking', 1); run(m, 1)
    assert m.eye == pytest.approx(1.2, abs=.02)


def test_assembly_plays_during_preparing():
    m = OrbMotion(); m.set_visual('preparing'); run(m, .6); assert .4 < m.assembly < .6
    run(m, 1); assert m.assembly == 1
    m.set_visual('idle'); assert m.assembly == 1


def test_reduced_motion_has_no_spin_trail_or_flash():
    m = OrbMotion(); m.set_visual('thinking'); run(m, 1); m.set_visual('speaking')
    spin = m.spin; run(m, 1, reduced=True)
    assert m.spin == spin and m.spin_rate == m.trail == m.flash == 0 and m.assembly == 1
    m.set_visual('error'); run(m, .1, reduced=True)
    assert m.tint == 1 and m.eye == .25


def test_new_channels_are_frame_rate_independent():
    out = []
    for rate in (30, 60, 120):
        m = OrbMotion(); m.set_visual('thinking'); run(m, 1, rate); m.set_visual('speaking', .6); run(m, 1, rate)
        out.append((m.spin, m.spin_rate, m.trail, m.flash, m.eye))
    for s in out[1:]:
        assert s == pytest.approx(out[0], abs=1e-6)


def test_relief_amplitude_follows_state_and_voice():
    for state, value in (('idle', .3), ('thinking', .6), ('executing', .8),
                         ('awaiting_confirmation', .15), ('error', 0)):
        m = OrbMotion(); m.set_visual(state); run(m, 1)
        assert m.relief == pytest.approx(value, abs=.01)
    m = OrbMotion(); m.set_visual('listening', .8); run(m, 1)
    assert m.relief == pytest.approx(.3+.6*m.energy, abs=.01)
    run(m, .5, reduced=True); assert m.relief == 0
