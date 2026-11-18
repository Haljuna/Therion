from PySide6.QtGui import QImage, QPainter, QColor
from therion.interface.hud_frame import FrameState, paint_hud_frame
from therion.interface.hud_style import hud_layout


def frame(**kw):
    base = dict(label='OUVINDO', level=.5, arc_deg=68, arc_scale=1, arc_rotation=0, tick_rotation=0,
                dash_rotation=0, blink=1, amber=0, voice_ring=0, voice=0)
    base.update(kw)
    return FrameState(**base)


def render(w, h, f, dpr=1., label=True):
    img = QImage(int(w*dpr), int(h*dpr), QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img)
    paint_hud_frame(p, hud_layout(0, 0, w, h), f, label=label)
    p.end()
    return img


def test_without_label_only_the_ring_is_drawn(app):
    lay = hud_layout(0, 0, 400, 400)
    with_label, ring_only = lit_box(render(400, 400, frame())), lit_box(render(400, 400, frame(), label=False))
    assert with_label[3] > lay.label_y                       # nome do estado embaixo do anel
    assert ring_only[3] <= lay.cy + 1.25 * lay.Rf + 1        # sem o nome nem os pontinhos de nível
    assert ring_only[3] < lay.label_y - 10 * max(.75, lay.R / 170.)


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


def mini_timer_image(look):
    """O que a mini orbe (110 px, sem rótulo) cola por cima da cena com o tempo ligado, recortado na janela dela."""
    from therion.interface.orb_renderer import OrbGL
    orb = OrbGL(); orb.show_label = False; orb.setMinimumSize(0, 0); orb.resize(110, 110); orb.reduced = True
    orb.set_timer(look)
    lay = orb._layout()
    left, top, hud = orb._hud_image()
    img = QImage(110, 110, QImage.Format_ARGB32_Premultiplied); img.fill(QColor(0, 0, 0, 0))
    p = QPainter(img); p.drawImage(left, top, hud); p.end()
    orb.deleteLater()
    return img, lay


def arc_pixel(img, lay, degrees_from_top):
    """O pixel mais aceso em volta do ponto do arco (o traço da mini tem pouco mais de 1 px)."""
    import math
    a = math.radians(degrees_from_top)
    x, y = round(lay.cx+1.30*lay.Rf*math.sin(a)), round(lay.cy-1.30*lay.Rf*math.cos(a))
    return max((img.pixelColor(x+dx, y+dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)), key=lambda c: c.alpha())


def test_paint_timer_draws_arc_inside_bounds_mini(app):
    from therion.core.focus import TimerLook
    img, lay = mini_timer_image(TimerLook(1., '50', 'focus', False))
    lit = arc_pixel(img, lay, 90)
    assert lit.alpha() > 120 and lit.blue() > lit.red()                   # ciano no raio do arco
    border = [(x, y) for x in range(110) for y in (0, 109)]+[(x, y) for y in range(110) for x in (0, 109)]
    assert all(img.pixelColor(x, y).alpha() == 0 for x, y in border)      # nada encosta na borda de 1 px


def test_paint_timer_empties_clockwise_from_the_top(app):
    from therion.core.focus import TimerLook
    img, lay = mini_timer_image(TimerLook(.25, '13', 'focus', False))   # sobra o último quarto (de 9h a 12h)
    assert arc_pixel(img, lay, 315).alpha() > 120
    assert arc_pixel(img, lay, 90).alpha() < 60                           # só a trilha apagada


def test_paint_timer_colors(app):
    from therion.core.focus import TimerLook
    def color(look):
        img, lay = mini_timer_image(look)
        return arc_pixel(img, lay, 90)
    cyan, amber, green = (color(TimerLook(1., '50', 'focus', False)), color(TimerLook(1., '4', 'focus', True)),
                          color(TimerLook(1., '5', 'pause', False)))
    assert cyan.blue() > cyan.red()+60
    assert amber.red() > amber.blue()+80
    assert green.green() > green.red()+40 and green.green() > green.blue()+20


def test_paint_timer_puts_the_number_on_a_dark_disc(app):
    from therion.core.focus import TimerLook
    img, lay = mini_timer_image(TimerLook(.64, '32', 'focus', False))
    near = [img.pixelColor(x, y) for x in range(round(lay.cx-.5*lay.R), round(lay.cx+.5*lay.R))
            for y in range(round(lay.cy-.3*lay.R), round(lay.cy+.3*lay.R))]
    assert any(c.alpha() > 200 and c.lightness() > 120 for c in near)     # algarismos acesos
    assert any(80 < c.alpha() < 200 and c.lightness() < 30 for c in near)   # disco escuro atrás


def test_painter_state_is_restored(app):
    img = QImage(200, 200, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setOpacity(.3)
    paint_hud_frame(p, hud_layout(0, 0, 200, 200), frame())
    assert abs(p.opacity()-.3) < 1e-9
    p.end()
