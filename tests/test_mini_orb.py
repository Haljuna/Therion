"""Posição da mini orbe: padrão, limites, restauração e encaixe perto das bordas."""
from PySide6.QtCore import QPoint, QRect, QSize

from therion.interface.mini_orb import beside, clamp, default_position, restore, save

PRIMARY, SECOND = QRect(0, 0, 1920, 1040), QRect(1920, 0, 1280, 984)


def test_starts_in_the_bottom_right_corner_of_the_second_monitor():
    assert default_position([PRIMARY, SECOND], PRIMARY, QSize(96, 96)) == QPoint(1920 + 1280 - 96 - 24, 984 - 96 - 24)
    assert default_position([PRIMARY], PRIMARY, QSize(96, 96)) == QPoint(1920 - 96 - 24, 1040 - 96 - 24)


def test_a_saved_position_outside_every_screen_is_ignored(tmp_path):
    save(str(tmp_path / 'm.json'), QPoint(5000, 100))
    assert restore(str(tmp_path / 'm.json'), [PRIMARY, SECOND], QSize(96, 96)) is None
    save(str(tmp_path / 'm.json'), QPoint(2000, 100))
    assert restore(str(tmp_path / 'm.json'), [PRIMARY, SECOND], QSize(96, 96)) == QPoint(2000, 100)
    (tmp_path / 'm.json').write_text('lixo'); assert restore(str(tmp_path / 'm.json'), [PRIMARY], QSize(96, 96)) is None


def test_dragging_past_the_edge_keeps_the_whole_orb_on_screen():
    assert clamp(QPoint(3190, 970), QSize(96, 96), [PRIMARY, SECOND]) == QPoint(3200 - 96, 984 - 96)


def test_panel_opens_to_the_side_that_has_room():
    orb = QRect(3080, 860, 96, 96)
    spot = beside(orb, QSize(360, 420), SECOND)
    assert spot.x() + 360 <= orb.left() and SECOND.contains(QRect(spot, QSize(360, 420)))
