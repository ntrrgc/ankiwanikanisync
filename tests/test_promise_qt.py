from __future__ import annotations

from unittest.mock import Mock

from pytestqt.qtbot import QtBot

from ankiwanikanisync.promise_qt import QtScheduler

sched = QtScheduler()


def test_promise_qt_call_soon(qtbot: QtBot):
    with qtbot.waitCallback() as cb:
        sched.call_soon(cb)


def test_promise_qt_call_soon_cancel(qtbot: QtBot):
    mock_cb = Mock()

    canc = sched.call_soon(mock_cb)
    assert not canc.cancelled()

    canc.cancel()
    assert canc.cancelled()

    with qtbot.waitCallback() as cb:
        sched.call_soon(cb)

    assert not mock_cb.called
