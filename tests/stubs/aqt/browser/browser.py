from __future__ import annotations

from unittest.mock import MagicMock

from ..qt import QMenu, QWidget


class Browser(QWidget):
    def __init__(self, mw: QWidget):
        super().__init__(mw)

        self.form = MagicMock()
        self.form.menu_Notes = QMenu("Notes", self)

        self.table = MagicMock()
        self.table.get_selected_note_ids.return_value = []

