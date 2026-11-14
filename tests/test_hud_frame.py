from PySide6.QtGui import QImage, QPainter, QColor
from therion.interface.hud_frame import FrameState, paint_hud_frame
from therion.interface.hud_style import hud_layout


def frame(**kw):
    base = dict(label='OUVINDO', level=.5, arc_deg=68, arc_scale=1, arc_rotation=0, tick_rotation=0,
                dash_rotation=0, blink=1, amber=0, voice_ring=0, voice=0)
    base.update(kw)
    return FrameState(**base)


def render(w, h, f, dpr=1.):
    img = QImage(int(w*dpr), int(h*dpr), QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    paint_hud_frame(p, hud_layout(0, 0, w, h), f)
    p.end()
    return img


def lit_box(img):
    xs, ys = [], []
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 20:
                xs.append(x); ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def test_frame_draws_something(app):
    assert lit_box(render(400, 400, frame()))


def test_frame_fits_inside_small_area(app):
    for dpr in (1., 1.5):
        img = render(160, 160, frame(label='AGUARDANDO RESPOSTA', level=1.), dpr)
        x0, y0, x1, y1 = lit_box(img)
        assert x0 > 0 and y0 > 0 and x1 < img.width()-1 and y1 < img.height()-1


def test_amber_frame_is_warmer(app):
    def mean_red_minus_blue(img):
        s = n = 0
        for y in range(0, img.height(), 2):
            for x in range(0, img.width(), 2):
                c = img.pixelColor(x, y)
                if c.alpha() > 40:
                    s += c.red()-c.blue(); n += 1
        return s/max(1, n)
    assert mean_red_minus_blue(render(400, 400, frame(amber=1))) > mean_red_minus_blue(render(400, 400, frame()))+60


def test_blink_dims_the_arcs(app):
    def arc_alpha(img):   # arco direito, em 0,97 Rf do centro
        lay = hud_layout(0, 0, 400, 400)
        return img.pixelColor(round(lay.cx+.97*lay.Rf), round(lay.cy)).alpha()
    assert arc_alpha(render(400, 400, frame(blink=.2))) < arc_alpha(render(400, 400, frame()))-80


def test_painter_state_is_restored(app):
    img = QImage(200, 200, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setOpacity(.3)
    paint_hud_frame(p, hud_layout(0, 0, 200, 200), frame())
    assert abs(p.opacity()-.3) < 1e-9
    p.end()
