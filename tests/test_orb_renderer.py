"""Desenho da orbe holográfica: funções puras e fumaça com OpenGL real."""
import math
import os
import time
import pytest
from PySide6.QtWidgets import QApplication
from therion.interface.orb_renderer import line_width_px, detail_level, frame_interval_ms, bloom_levels
from therion.interface.graphics import FRAME_INTERVAL_MS


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


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
    w, d = line_width_px(px), detail_level(px)
    assert math.isfinite(w) and w >= 1 and math.isfinite(d) and 0 <= d <= 1


def test_helper_values_from_spec():
    assert line_width_px(500) == pytest.approx(1.2) and line_width_px(100) == 1
    assert detail_level(200) == 0 and detail_level(320) == 1 and 0 < detail_level(260) < 1
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
def test_error_turns_the_orb_redder_and_dimmer_than_idle(app):
    from therion.interface.orb_renderer import OrbGL
    measured = {}
    for state in ('idle', 'error'):
        w = OrbGL(); w.resize(300, 300); w.show(); w.set_active(True); settle(lambda: w.ready)
        w.set_visual(state, 0); pump(.8)
        measured[state] = _mean_lit_color(w.grabFramebuffer()); w.close()
    ratio = {s: r/b for s, (r, _, b) in measured.items()}
    assert ratio['error'] > ratio['idle']+.07   # mistura de 30% da spec dá ~+0,09
    assert sum(measured['error']) < sum(measured['idle'])


def test_static_fallback_uses_new_shape(app):
    from PySide6.QtGui import QColor
    from therion.interface.constellation import StaticConstellation
    s = StaticConstellation(); s.resize(300, 300)
    img = s.grab().toImage()
    background = QColor('#09090F')
    lit = sum(img.pixelColor(x, y) != background for x in range(0, 300, 3) for y in range(0, 300, 3))
    assert lit > 500


@gl
def test_cadence_and_detail_follow_state_and_size(app):
    from PySide6.QtCore import QRectF
    from therion.interface.orb_renderer import OrbGL
    w = OrbGL(); w.resize(600, 600); w.show(); w.set_active(True); settle(lambda: w.ready)
    w.set_visual('thinking', 0); pump(.1); assert w.timer.interval() == 33
    w.set_visual('idle', 0); pump(.1); assert w.timer.interval() == FRAME_INTERVAL_MS
    w.focus_rect = QRectF(0, 0, 150, 150); pump(.2); assert w.current_detail() == 0
    w.focus_rect = QRectF(0, 0, 500, 500); pump(.2); assert w.current_detail() == 1
    w.close()


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
