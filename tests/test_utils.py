from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Sequence

from aqt import qt

from .utils import saving_attr


@dataclass
class ChooseList:
    msg: str
    choices: Sequence[str]
    initial: int
    result: int | None


class MockQDialog(qt.QDialog):
    mock_result: ClassVar[ChooseList | None] = None

    def exec(self) -> int:
        mock_result = self.mock_result
        assert mock_result

        layout = self.layout()
        assert layout

        def item(idx: int) -> qt.QWidget:
            item = layout.itemAt(idx)
            assert item
            widget = item.widget()
            assert widget
            return widget

        label = item(0)
        assert isinstance(label, qt.QLabel)
        assert label.text() == mock_result.msg

        listbox = item(1)
        assert isinstance(listbox, qt.QListWidget)
        assert listbox.currentRow() == mock_result.initial
        assert listbox.count() == len(mock_result.choices)
        for i, choice in enumerate(mock_result.choices):
            listitem = listbox.item(i)
            assert listitem
            assert listitem.text() == choice

        if mock_result.result is None:
            return 0

        listbox.setCurrentRow(mock_result.result)
        return 1


def call_choose_list(
    msg: str, choices: Sequence[str], init: int, result: int | None
) -> int | None:
    from ankiwanikanisync import utils

    with saving_attr(utils, "QDialog"):
        utils.QDialog = MockQDialog

        MockQDialog.mock_result = ChooseList(
            msg=msg, choices=choices, initial=init, result=result
        )

        return utils.choose_list(msg, choices, init)


def test_choose_list_initial_value():
    CHOICES = ["a", "b", "c"]

    res = call_choose_list("Foo", CHOICES, 0, 0)
    assert res == 0

    res = call_choose_list("Foo", CHOICES, 2, 0)
    assert res == 0

    res = call_choose_list("Foo", CHOICES, 2, 1)
    assert res == 1


def test_choose_list_cancel():
    CHOICES = ["a", "b", "c"]

    res = call_choose_list("Foo", CHOICES, 0, None)
    assert res is None
