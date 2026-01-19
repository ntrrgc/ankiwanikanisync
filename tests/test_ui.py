from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, call

import pytest
from anki.cards import Card
from aqt import gui_hooks
from aqt.qt import QAction, QMenu
from pytest_mock import MockerFixture


def test_tools_menu(tools_menu: dict[str, QAction]):
    assert list(tools_menu.keys()) == [
        "Sync Notes",
        "Sync Due Dates",
        "Clear Cache",
        "Overwrite Card HTML",
        "Migrate from WK3: Tokyo Drift",
    ]


def test_browser_menu(mocker: MockerFixture):
    from aqt import mw
    from aqt.browser.browser import Browser

    from ankiwanikanisync import ui
    from ankiwanikanisync.collection import wk_col

    ui.init_browser_menu()

    unlockable = list[int]()
    is_unlockable = mocker.patch.object(
        wk_col, "is_unlockable", side_effect=lambda id: id in unlockable
    )
    unlock_notes = mocker.patch.object(wk_col, "unlock_notes")
    mocker.patch.object(wk_col, "get_note", side_effect=lambda id_: id_)

    browser = Browser(mw)
    menu = QMenu("Context Menu", browser)

    selected_notes = [1, 2]
    browser.table.get_selected_note_ids.side_effect = lambda: list(selected_notes)  # type: ignore

    gui_hooks.browser_menus_did_init(browser)

    action = browser.form.menu_Notes.actions()[0]
    assert action.text() == "Study WaniKani note"

    gui_hooks.browser_will_show_context_menu(browser, menu)
    is_unlockable.assert_has_calls(list(map(call, selected_notes)))
    is_unlockable.reset_mock()

    assert not action.isEnabled()

    unlockable.append(2)
    gui_hooks.browser_will_show_context_menu(browser, menu)
    is_unlockable.assert_has_calls(list(map(call, selected_notes)))
    is_unlockable.reset_mock()

    assert action.isEnabled()

    action.triggered.emit()
    unlock_notes.assert_called_once_with(selected_notes)


def test_play_all(subtests: pytest.Subtests):
    import aqt
    from aqt.browser.previewer import Previewer
    from aqt.clayout import CardLayout
    from aqt.reviewer import Reviewer

    from ankiwanikanisync import ui

    ui.install_play_all_audio()

    card_mock = MagicMock()
    card_mock.question_av_tags.return_value = ["q"]
    card_mock.answer_av_tags.return_value = ["a"]

    card = cast(Card, card_mock)

    res = gui_hooks.card_will_show("::__IS_PLAY_ALL_AVAILABLE__::", card, "")
    assert res == "::__YES_IT_IS__::"

    play_tags = cast(MagicMock, aqt.sound.av_player.play_tags)

    pycmd_hook = gui_hooks.webview_did_receive_js_message

    for cls, attrs in {
        CardLayout: {"rendered_card": card},
        Previewer: {"card": lambda: card},
        Reviewer: {"card": card},
    }.items():
        ctx = cast(MagicMock, cls())
        for attr, val in attrs.items():
            setattr(ctx, attr, val)

        with subtests.test(f"pycmd({cls!r})"):
            result = pycmd_hook((False, None), "play:q:all", ctx)
            assert result == (True, None)
            play_tags.assert_called_once_with(["q"])
            play_tags.reset_mock()

            result = pycmd_hook((False, None), "play:a:all", ctx)
            assert result == (True, None)
            play_tags.assert_called_once_with(["a"])
            play_tags.reset_mock()

            result = pycmd_hook((False, None), "play:q", ctx)
            assert result == (False, None)
            assert not play_tags.called

    result = pycmd_hook((False, None), "play:q:all", MagicMock)
    assert result == (False, None)
    assert not play_tags.called
