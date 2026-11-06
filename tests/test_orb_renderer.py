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
