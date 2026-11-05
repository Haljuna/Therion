"""Controles do cartão não podem aparecer como janelas independentes."""
import pytest
from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QApplication, QWidget
from therion.interface.autonomy_widgets import ExpandableRow


@pytest.mark.parametrize('with_parent', [False, True])
@pytest.mark.parametrize('check_text,remove', [('Sem confirmação', True), ('Automática', False), ('', False)])
def test_creating_app_card_never_shows_a_top_level_control(with_parent, check_text, remove):
    app = QApplication.instance() or QApplication([])
    class Spy(QObject):
        def __init__(self):
            super().__init__(); self.shown = []
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
                self.shown.append(type(obj).__name__)
            return False
    parent = QWidget() if with_parent else None
    spy = Spy(); app.installEventFilter(spy)
    row = None
    try:
        row = ExpandableRow('chrome', 'Google Chrome', check_text, remove, parent)
        assert spy.shown == []
        assert row.check.parentWidget() is row
        assert row.remove.parentWidget() is row
    finally:
        app.removeEventFilter(spy)
        if row is not None: row.deleteLater()
        if parent is not None: parent.deleteLater()
        app.processEvents()
