"""Desenho da Orbe HUD: funções puras e fumaça com OpenGL real."""
import math
import os
import time
import pytest
from PySide6.QtWidgets import QApplication
from therion.interface.orb_renderer import line_width_px, frame_interval_ms, bloom_levels
from therion.interface.graphics import FRAME_INTERVAL_MS


def pump(seconds):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        QApplication.processEvents(); time.sleep(.005)


def settle(predicate, timeout=3):
    deadline = time.monotonic()+timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents(); time.sleep(.005)
    assert predicate()


@pytest.mark.parametrize('px', [0, 40, 259, 500, 4000])
def test_helpers_stay_finite_and_bounded(px):
    w = line_width_px(px)
    assert math.isfinite(w) and w >= 1


def test_helper_values_from_spec():
    assert line_width_px(500) == pytest.approx(1.2) and line_width_px(100) == 1
    assert frame_interval_ms('thinking') == frame_interval_ms('executing') == 33
    assert frame_interval_ms('idle') == FRAME_INTERVAL_MS
    assert bloom_levels('high', 'idle') == 3 and bloom_levels('high', 'thinking') == 2
    assert bloom_levels('low', 'thinking') == 1


gl = pytest.mark.skipif(os.environ.get('QT_QPA_PLATFORM') in {'offscreen', 'minimal'}, reason='sem OpenGL')


@gl
def test_orb_draws_something_and_survives_resize(app):
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(400, 400); w.show(); w.set_active(True)
    settle(lambda: w.ready or w.disabled)
    assert w.ready
    for size in (200, 900, 120, 400):
        w.resize(size, size); pump(.15)
        assert w.ready and not w.disabled
    img = w.grabFramebuffer(); cx, cy = img.width()//2, img.height()//2
    brightest = max(img.pixelColor(x, y).lightness()
                    for x in range(cx-10, cx+11) for y in range(cy-30, cy+11))
    assert brightest > 120
    w.close()


@gl
def test_cleanup_is_idempotent(app):
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(300, 300); w.show(); settle(lambda: w.ready)
    w.cleanup(); w.cleanup(); w.close(); w.cleanup()


@gl
def test_bloom_chain_follows_quality_and_state(app):
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(600, 600); w.show(); w.set_quality('high'); w.set_active(True)
    settle(lambda: w.ready); pump(.2)
    sizes = w.bloom_chain_sizes()
    assert len(sizes) == 3 and sizes[0].width() == round(600*w.devicePixelRatioF()/2)
    w.set_visual('thinking', 0); pump(.2); assert len(w.bloom_chain_sizes()) == 2
    w.set_quality('low'); pump(.2); assert len(w.bloom_chain_sizes()) == 1
    w.close()


def test_trail_keep_values():
    from therion.interface.orb_renderer import trail_keep
    assert trail_keep(0, 1/60) < .45 and trail_keep(1, 1/60) > .9
    assert trail_keep(1, 0) == 1 and 0 <= trail_keep(.5, 10) < 1e-6


@gl
def test_reduced_motion_clears_trail_next_frame(app):
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(400, 400); w.show(); w.set_active(True); settle(lambda: w.ready)
    w.set_visual('executing', 0); pump(1.)
    assert not w.trail_cleared
    w.reduced = True; w.update(); pump(.1)
    assert w.trail_cleared and w.animation.trail == 0
    w.close()


def _mean_lit_color(img):
    """Cor média dos pixels acesos perto do centro (ignora o fundo)."""
    cx, cy = img.width()//2, img.height()//2
    total, n = [0, 0, 0], 0
    for x in range(cx-60, cx+61, 2):
        for y in range(cy-60, cy+61, 2):
            c = img.pixelColor(x, y)
            if c.lightness() > 40:
                total[0] += c.red(); total[1] += c.green(); total[2] += c.blue(); n += 1
    assert n > 50
    return [v/n for v in total]


@gl
def test_error_turns_the_orb_amber_and_dimmer_than_idle(app):
    from therion.interface.orb_renderer import OrbGL
    measured = {}
    for state in ('idle', 'error'):
        w = OrbGL(); w.resize(300, 300); w.show(); w.set_active(True); settle(lambda: w.ready)
        w.set_visual(state, 0); pump(.8)
        measured[state] = _mean_lit_color(w.grabFramebuffer()); w.close()
    warmth = {s: r-b for s, (r, _, b) in measured.items()}   # âmbar puxa para o vermelho
    assert warmth['error'] > warmth['idle']+10
    assert sum(measured['error']) < sum(measured['idle'])


def test_static_fallback_draws_dots_and_label(app):
    from therion.interface.constellation import StaticConstellation
    w = StaticConstellation(); w.resize(400, 400); w.set_state('error')
    img = w.grab().toImage()
    lit = sum(1 for y in range(0, 400, 4) for x in range(0, 400, 4) if img.pixelColor(x, y).lightness() > 60)
    assert lit > 40
    # erro: a moldura fica âmbar (mais vermelho que azul no arco direito)
    from therion.interface.hud_style import hud_layout
    lay = hud_layout(0, 0, 400, 400)
    arc = img.pixelColor(round(lay.cx+.97*lay.Rf), round(lay.cy))
    assert arc.red() > arc.blue()+40


def test_constellation_passes_state_to_static_fallback(app):
    from therion.interface.constellation import Constellation
    c = Constellation(static=True); c.set_visual('listening', .5)
    assert c.still.state == 'listening'
    c.set_visual('nada'); assert c.still.state == 'nada'   # cai em repouso ao desenhar
    c.resize(300, 300); c.still.grab()


@gl
def test_cadence_follows_state(app):
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(600, 600); w.show(); w.set_active(True); settle(lambda: w.ready)
    w.set_visual('thinking', 0); pump(.1); assert w.timer.interval() == 33
    w.set_visual('idle', 0); pump(.1); assert w.timer.interval() == FRAME_INTERVAL_MS
    w.close()


def test_min_interval_caps_the_cadence_and_zero_leaves_the_big_orb_alone(app):
    from therion.interface.orb_renderer import OrbGL
    big, mini = OrbGL(), OrbGL()
    mini.min_interval_ms = 33
    for orb in (big, mini):
        orb.set_visual('idle', 0)
    assert big.timer.interval() == FRAME_INTERVAL_MS and mini.timer.interval() == 33
    mini.set_visual('thinking', 0)
    assert mini.timer.interval() == 33


@gl
def test_repeated_state_polls_do_not_restart_the_frame_timer(app):
    # O painel chama set_visual a cada 50 ms; reiniciar o timer derrubava os quadros/s.
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(300, 300); w.show(); w.set_active(True); settle(lambda: w.ready)
    w.set_visual('thinking', 0)
    timer_id = w.timer.timerId()
    for _ in range(5):
        w.set_visual('thinking', 0)
    assert w.timer.timerId() == timer_id
    w.close()


def test_widget_framebuffer_has_no_extra_msaa(app):
    # A cena já tem MSAA própria; a janela só recebe quadros cheios.
    from therion.interface.orb_renderer import OrbGL
    assert OrbGL().format().samples() == 0


@gl
def test_quality_change_rebuilds_point_count(app):
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(520, 520); w.show(); w.set_quality('high'); w.set_active(True)
    settle(lambda: w.ready); pump(.1)
    assert w.point_count == 3200
    w.set_quality('low'); pump(.1); assert w.point_count == 1800 and w.ready
    w.set_quality('high'); pump(.1); assert w.point_count == 3200 and w.ready
    w.close()


@gl
def test_small_orb_uses_fewer_points(app):
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(200, 200); w.show(); w.set_quality('high'); w.set_active(True)
    settle(lambda: w.ready); pump(.1)
    assert w.point_count == 1800
    w.close()


@gl
def test_trail_only_while_thinking(app):
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(400, 400); w.show(); w.set_active(True); settle(lambda: w.ready)
    w.set_visual('idle', 0); pump(.5); assert w.trail_cleared
    w.set_visual('thinking', 0); pump(1.); assert not w.trail_cleared
    w.close()


@gl
def test_frame_label_is_drawn_below_the_orb(app):
    # A moldura é pintada por cima do OpenGL: tem de haver algo aceso na altura do nome do estado.
    from therion.interface.hud_style import hud_layout
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(400, 400); w.show(); w.set_active(True); settle(lambda: w.ready); pump(.3)
    img = w.grabFramebuffer(); scale = img.width()/400
    lay = hud_layout(0, 0, 400, 400)
    rows = range(round(lay.label_y*scale), round((lay.label_y+14)*scale))
    lit = sum(img.pixelColor(x, y).lightness() > 90 for y in rows for x in range(img.width()))
    assert lit > 30
    w.close()


def test_shader_clocks_stay_small_after_days_running():
    # float32 no shader: relógios enormes fariam o movimento andar aos trancos.
    from therion.interface.orb_renderer import shader_clocks
    from therion.interface.orb_motion import OrbMotion
    m = OrbMotion(); m.clock = 1e6+.3; m.spin = 2e5+.1; m.orbit_phase = 3e5+.7; m.sweep_phase = 4e5+.2
    c = shader_clocks(m)
    assert all(0 <= v < 70 for v in c.values())
    for k in (1.2, .8, 2.2, 6., 1.6, 31.):
        assert math.sin(k*c['clock']) == pytest.approx(math.sin(k*m.clock), abs=1e-6)
    for k in (1., .3, .5):
        assert math.sin(k*c['spin']) == pytest.approx(math.sin(k*m.spin), abs=1e-6)
    for speed in (.7, .5, -.35):
        assert math.sin(math.tau*speed*c['orbitPhase']) == pytest.approx(math.sin(math.tau*speed*m.orbit_phase), abs=1e-6)
    assert math.sin(c['sweepPhase']) == pytest.approx(math.sin(m.sweep_phase), abs=1e-6)


@gl
def test_scene_is_drawn_with_multisampling_on(app):
    # O QPainter da moldura desliga o multisample; sem religar, órbitas e eixo ficam serrilhados.
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(300, 300); w.show(); w.set_active(True); settle(lambda: w.ready); pump(.2)
    seen, draw = [], w._scene
    w._scene = lambda *a: (seen.append(bool(w.gl.glIsEnabled(0x809D))), draw(*a))
    pump(.2)
    assert seen and all(seen)
    w.close()


@gl
def test_frame_arcs_are_antialiased_on_the_gl_path(app):
    from therion.interface.hud_style import hud_layout
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(400, 400); w.show(); w.set_active(True); settle(lambda: w.ready); pump(.3)
    img = w.grabFramebuffer(); scale = img.width()/400
    lay = hud_layout(0, 0, 400, 400)
    # Faixa só com o arco direito (fora das órbitas, em 1,42 R = 0,88 Rf, e dentro das marquinhas).
    xs = range(round((lay.cx+.93*lay.Rf)*scale), round((lay.cx+1.01*lay.Rf)*scale))
    ys = range(round((lay.cy-.25*lay.Rf)*scale), round((lay.cy+.25*lay.Rf)*scale))
    levels = {img.pixelColor(x, y).blue()//8 for x in xs for y in ys}
    assert len(levels) >= 14, len(levels)
    w.close()
