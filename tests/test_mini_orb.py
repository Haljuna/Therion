"""Mini orbe: posição (padrão, limites, restauração, encaixe) e janela flutuante com etiqueta e painel."""
import json
import time

import pytest
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

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
        self.disabled = False

    def set_visual(self, state, intensity):
        self.visuals.append(state)

    def set_quality(self, quality):
        pass

    def set_active(self, active):
        self.active = active

    def cleanup(self):
        self.cleaned += 1

    def make_transparent(self):
        self.transparent = True


class FakeWidgetRenderer(QWidget, FakeRenderer):   # como a OrbGL: um widget filho
    def __init__(self):
        QWidget.__init__(self)
        FakeRenderer.__init__(self)


def make(tmp_path, **kwargs):
    calls = {'full': 0}

    def full():
        calls['full'] += 1
        return FULL

    kwargs.setdefault('renderer_factory', None)
    kwargs.setdefault('key_state', lambda vk: False)
    return MiniOrb(path=str(tmp_path / 'pos.json'), reader=full, **kwargs), calls


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
    center = QPoint(48, 48)
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


def test_hovering_shows_and_reads_nothing(app, tmp_path):
    window, calls = make(tmp_path)
    window.show()
    QApplication.sendEvent(window, QEvent(QEvent.Enter))
    QTest.qWait(50)
    assert calls['full'] == 0 and not window.panel.isVisible() and not hasattr(window, 'label')
    window.shut()


def test_panel_refreshes_every_second_only_while_open(app, tmp_path):
    window, calls = make(tmp_path)
    window.show()
    assert window.refresh_timer.interval() == 1000
    assert not window.refresh_timer.isActive()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(48, 48))
    assert window.refresh_timer.isActive()
    assert wait_for(app, lambda: calls['full'] >= 1)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(48, 48))
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


def test_escape_closes_the_panel_without_focus(app, tmp_path):
    pressed = set()
    window, _ = make(tmp_path, key_state=lambda vk: vk in pressed)
    window.show()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(48, 48))
    assert window.panel.isVisible() and window.watch_timer.isActive() and window.watch_timer.interval() == 30
    window._watch()
    assert window.panel.isVisible()
    pressed.add(0x1B)
    window._watch()
    assert not window.panel.isVisible() and not window.watch_timer.isActive()
    window.shut()


def test_a_click_outside_closes_the_panel_but_inside_does_not(app, tmp_path):
    state = {'point': QPoint(0, 0)}
    window, _ = make(tmp_path, key_state=lambda vk: vk == 0x01, cursor_pos=lambda: state['point'])
    window.move(300, 300)
    window.show()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(48, 48))
    state['point'] = window.frameGeometry().center()
    window._watch()
    assert window.panel.isVisible()
    state['point'] = window.panel.frameGeometry().center()
    window._watch()
    assert window.panel.isVisible()
    state['point'] = QPoint(window.frameGeometry().right() + 900, 5)
    window._watch()
    assert not window.panel.isVisible()
    window.shut()


def test_a_four_pixel_move_is_still_a_click(app, tmp_path):
    window, _ = make(tmp_path)
    window.show()
    before = window.pos()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, QPoint(48, 48))
    QTest.mouseMove(window, QPoint(52, 48))
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, QPoint(52, 48))
    assert window.pos() == before and window.panel.isVisible()
    window.shut()


def test_a_slow_reading_never_stacks_and_stops_once_the_panel_closes(app, tmp_path):
    window, calls = make(tmp_path)
    window.show()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(48, 48))
    window._busy = True                      # leitura ainda em andamento quando o próximo segundo chega
    window._request(); window._request()
    assert window._pending is True and calls['full'] <= 1
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(48, 48))
    before = calls['full']
    window._deliver(FULL)                    # chega depois de fechar: não pede outra
    QTest.qWait(50)
    assert calls['full'] == before and window._pending is False
    window.shut()


def test_hiding_for_a_game_also_closes_the_panel_and_stops_its_watch(app, tmp_path):
    window, _ = make(tmp_path)
    window.show()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(48, 48))
    assert window.panel.isVisible() and window.watch_timer.isActive()
    window.hide_for_game(True)
    assert not window.panel.isVisible() and not window.watch_timer.isActive()
    window.shut()


def test_amber_also_shows_after_a_successful_command_or_a_cancel(app, tmp_path):
    fake = FakeRenderer()
    window, _ = make(tmp_path, renderer_factory=lambda: fake)
    for state in ('success', 'responding', 'cancelled'):
        window.set_state(state, True)
        assert fake.visuals[-1] == 'error'
    window.set_state('success', False)
    assert fake.visuals[-1] == 'idle'
    window.shut()


def test_open_main_menu_action_calls_the_callback(app, tmp_path, monkeypatch):
    from PySide6.QtGui import QContextMenuEvent
    from therion.interface import mini_orb

    class FakeMenu:   # QMenu.exec bloquearia o teste; "clica" na primeira ação
        def __init__(self, _parent):
            self.actions = []

        def addAction(self, _text, callback):
            self.actions.append(callback)

        def exec(self, _pos):
            self.actions[0]()
    opened = []
    window, _ = make(tmp_path, on_open_main=lambda: opened.append(1))
    monkeypatch.setattr(mini_orb, 'QMenu', FakeMenu)
    window.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(1, 1)))
    assert opened == [1]
    window.shut()


def test_the_position_is_saved_as_soon_as_a_drag_ends(app, tmp_path):
    window, _ = make(tmp_path)
    window.move(300, 300)
    window.show()
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, QPoint(48, 48))
    QTest.mouseMove(window, QPoint(78, 48))
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, QPoint(78, 48))
    saved = json.loads((tmp_path / 'pos.json').read_text(encoding='utf-8'))
    assert saved == {'x': window.x(), 'y': window.y()} and saved['x'] == 330
    window.shut()


def test_the_panel_opens_with_the_last_reading_or_says_reading_not_unavailable(app, tmp_path):
    window, _ = make(tmp_path)
    window.show()
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(48, 48))
    texts = [row.text() for row, _ in window.panel.rows.values()] + [label.text() for label in window.panel.tops.values()]
    assert 'indisponível' not in ' '.join(texts) and 'lendo…' in ' '.join(texts)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(48, 48))
    assert wait_for(app, lambda: window._last_full is not None)
    QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, QPoint(48, 48))
    assert 'lendo…' not in window.panel.rows['ram'][0].text() and 'chrome' in window.panel.tops['top_ram'].text()
    assert window.panel.tops['top_vram'].text() == 'indisponível'   # leitura real sem VRAM por processo
    window.shut()


def test_the_watch_polls_fast_enough_not_to_miss_a_click(app, tmp_path):
    window, _ = make(tmp_path)
    assert window.watch_timer.interval() == 30
    window.shut()


def test_calls_after_shut_do_nothing_and_the_renderer_is_disabled(app, tmp_path):
    fake = FakeRenderer()
    window, _ = make(tmp_path, renderer_factory=lambda: fake)
    window.shut()
    assert fake.disabled is True
    visuals, active = list(fake.visuals), fake.active
    window.set_state('thinking', False)
    window.set_quiet(False)
    window.hide_for_game(False)
    assert fake.visuals == visuals and fake.active == active and not window.isVisible()


def test_the_mini_orb_renders_at_most_30_fps(app, tmp_path):
    fake = FakeRenderer()
    window, _ = make(tmp_path, renderer_factory=lambda: fake)
    assert fake.min_interval_ms == 100              # em repouso, 10 quadros/s
    window.set_state('speaking', False)
    assert fake.min_interval_ms == 33               # ouvindo, pensando, falando: 30 quadros/s
    window.set_state('idle', True)
    assert fake.min_interval_ms == 100              # âmbar também é parado
    window.shut()


def test_only_the_orb_and_its_ring_show_with_no_cut_out_around(app, tmp_path):
    from therion.interface.hud_style import hud_layout
    fake = FakeWidgetRenderer()
    window, _ = make(tmp_path, renderer_factory=lambda: fake)
    assert window.size() == QSize(110, 110) and fake.geometry() == window.rect()
    assert fake.transparent is True and fake.show_label is False   # fundo some; sem o nome do estado
    assert window.mask().isEmpty()                                  # nada de recorte em círculo
    lay = hud_layout(0, 0, 110, 110)
    assert lay.cy - 1.25 * lay.Rf >= 0 and lay.cy + 1.25 * lay.Rf <= 110   # o anel inteiro cabe
    window.shut()


def test_mini_orb_forwards_timer_to_renderer(app, tmp_path):
    from therion.core.focus import TimerLook
    fake = FakeRenderer()
    fake.timers = []
    fake.set_timer = fake.timers.append
    window, _ = make(tmp_path, renderer_factory=lambda: fake)
    look = TimerLook(.5, '25', 'focus', False)
    window.set_timer(look)
    window.set_timer(None)
    assert fake.timers == [look, None]
    window.shut()
    window.set_timer(look)                          # depois de fechar não mexe mais no renderizador
    assert fake.timers == [look, None]


def test_a_screen_going_away_pulls_the_orb_back_inside(app, tmp_path, monkeypatch):
    from therion.interface import mini_orb
    window, _ = make(tmp_path)
    window.move(2500, 300)
    monkeypatch.setattr(mini_orb, '_screens', lambda: [QRect(0, 0, 1920, 1040)])
    window._reclamp()
    assert window.pos() == QPoint(1920 - mini_orb.ORB_PX, 300)
    window.shut()


def test_the_listen_for_my_name_action_shows_only_when_available_and_toggles(app, tmp_path, monkeypatch):
    from PySide6.QtGui import QAction, QContextMenuEvent
    from therion.interface import mini_orb
    seen = []

    class FakeMenu:
        def __init__(self, _parent):
            self.items = []

        def addAction(self, text, callback=None):
            action = QAction(text)
            if callback:
                action.triggered.connect(callback)
            self.items.append(action)
            return action

        def exec(self, _pos):
            seen.append([(a.text(), a.isCheckable(), a.isChecked()) for a in self.items])
            wake = [a for a in self.items if a.text() == 'Ouvir meu nome']
            if wake:
                wake[0].trigger()
    toggled = []
    window, _ = make(tmp_path, on_toggle_wake=lambda checked: toggled.append(checked))
    monkeypatch.setattr(mini_orb, 'QMenu', FakeMenu)
    event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(1, 1))
    window.contextMenuEvent(event)
    assert [t for t, *_ in seen[-1]] == ['Abrir o Therion', 'Esconder até reiniciar']   # indisponível: escondida
    window.set_wake('on')
    window.contextMenuEvent(event)
    assert ('Ouvir meu nome', True, True) in seen[-1] and len(toggled) == 1
    window.set_wake('off')
    window.contextMenuEvent(event)
    assert ('Ouvir meu nome', True, False) in seen[-1]
    window.shut()
