"""Mini orbe: posição (padrão, limites, restauração, encaixe) e janela flutuante com etiqueta e painel."""
import json
import time

import pytest
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from therion.interface.mini_orb import MiniOrb, beside, clamp, default_position, restore, save

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


def test_absurd_numbers_in_the_saved_file_are_ignored(tmp_path):
    path = tmp_path / 'm.json'
    for text in ('{"x": Infinity, "y": 0}', '{"x": 1000000000000000000000000000000, "y": 0}'):
        path.write_text(text, encoding='utf-8')
        assert restore(str(path), [PRIMARY, SECOND], QSize(96, 96)) is None


QUICK = {'ram': 0.62, 'vram': 0.18, 'c_free': 2.5 * 1024 ** 3}
FULL = dict(QUICK, ram_used=10 * 1024 ** 3, ram_total=16 * 1024 ** 3, commit_used=12 * 1024 ** 3,
            commit_total=30 * 1024 ** 3, vram_used=1 * 1024 ** 3, vram_total=6 * 1024 ** 3, gpu_temp=55,
            top_ram=[('chrome', 2 * 1024 ** 3)], top_vram=[])


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


class FakeRenderer:
    def __init__(self):
        self.visuals, self.reduced, self.active, self.cleaned = [], False, None, 0

    def set_visual(self, state, intensity):
        self.visuals.append(state)

    def set_quality(self, quality):
        pass

    def set_active(self, active):
        self.active = active

    def cleanup(self):
        self.cleaned += 1


def make(tmp_path, **kwargs):
    calls = {'quick': 0, 'full': 0}

    def quick():
        calls['quick'] += 1
        return QUICK

    def full():
        calls['full'] += 1
        return FULL

    kwargs.setdefault('renderer_factory', None)
    return MiniOrb(path=str(tmp_path / 'pos.json'), readers=(quick, full), **kwargs), calls


def wait_for(app, condition, seconds=3):
    end = time.time() + seconds
    while not condition() and time.time() < end:
        app.processEvents()
        QTest.qWait(10)
    return condition()


def test_click_opens_and_closes_the_panel_but_a_drag_only_moves(app, tmp_path):
    window, _ = make(tmp_path)
    window.move(300, 300)
    window.show()
    center = QPoint(36, 36)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, center)
    assert window.panel.isVisible()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, center)
    assert not window.panel.isVisible()
    before = window.pos()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, center)
    QTest.mouseMove(window, center + QPoint(30, 0))
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, center + QPoint(30, 0))
    assert window.pos() == before + QPoint(30, 0)
    assert not window.panel.isVisible()
    window.shut()


def test_hover_shows_the_label_with_the_quick_numbers(app, tmp_path):
    window, _ = make(tmp_path)
    window.show()
    QApplication.sendEvent(window, QEvent(QEvent.Enter))
    assert wait_for(app, window.label.isVisible)
    assert window.label.text() == 'RAM 62% · VRAM 18% · C 2,5 GB'
    QApplication.sendEvent(window, QEvent(QEvent.Leave))
    assert not window.label.isVisible()
    window.shut()


def test_panel_refreshes_every_three_seconds_only_while_open(app, tmp_path):
    window, calls = make(tmp_path)
    window.show()
    assert window.refresh_timer.interval() == 3000
    assert not window.refresh_timer.isActive()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(36, 36))
    assert window.refresh_timer.isActive()
    assert wait_for(app, lambda: calls['full'] >= 1)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(36, 36))
    assert not window.refresh_timer.isActive()
    window.shut()


def test_idle_with_a_tight_pc_turns_amber_but_activity_wins(app, tmp_path):
    fake = FakeRenderer()
    window, _ = make(tmp_path, renderer_factory=lambda: fake)
    window.set_state('idle', True)
    assert fake.visuals[-1] == 'error'
    window.set_state('speaking', True)
    assert fake.visuals[-1] == 'speaking'
    window.set_state('idle', False)
    assert fake.visuals[-1] == 'idle'
    window.set_quiet(True)
    assert fake.reduced is True and fake.active is False
    window.shut()
    assert fake.cleaned == 1


def test_shut_saves_the_position_and_can_run_twice(app, tmp_path):
    window, _ = make(tmp_path)
    window.show()
    window.move(200, 100)
    window.shut()
    window.shut()
    assert json.loads((tmp_path / 'pos.json').read_text(encoding='utf-8')) == {'x': 200, 'y': 100}
