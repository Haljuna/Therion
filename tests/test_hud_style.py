from therion.interface import hud_style as hs
from therion.interface.presentation import LABELS


def test_every_state_has_label_and_look():
    assert set(hs.STATES) == set(LABELS)
    assert set(hs.HUD_LABELS) == set(LABELS) == set(hs.LOOKS)


def test_labels_match_spec():
    assert hs.label_for('listening') == 'OUVINDO'
    assert hs.label_for('error') == 'ATENÇÃO'
    assert hs.label_for('awaiting_confirmation') == 'AGUARDANDO VOCÊ'


def test_unknown_state_falls_back_to_idle():
    assert hs.look_for('nada') == hs.LOOKS['idle']
    assert hs.label_for('nada') == 'EM REPOUSO'


def test_alert_states_are_amber_and_dim():
    assert hs.look_for('error').amber == 1 and hs.look_for('error').dim == .5
    assert 0 < hs.look_for('uncertain').amber < 1
    assert hs.look_for('idle').amber == 0


def test_point_count_by_quality_and_size():
    assert hs.point_count('high', 500) == 3200
    assert hs.point_count('medium', 500) == 3200
    assert hs.point_count('low', 500) == 1800
    assert hs.point_count('high', 259) == 1800


def test_layout_proportions():
    lay = hs.hud_layout(0, 0, 1000, 800)
    assert lay.cx == 500 and abs(lay.cy - 352) < 1e-9
    assert abs(lay.R - 172) < 1e-9 and abs(lay.Rf - 1.62*172) < 1e-9
    assert abs(lay.label_y - (lay.cy + 1.3*lay.Rf)) < 1e-9
