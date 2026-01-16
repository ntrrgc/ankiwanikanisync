# ruff: noqa: F401,F403,F405
from __future__ import annotations

import asyncio
from typing import Callable, Self

from PyQt6 import sip
from PyQt6.QtCore import *

# conflicting Qt and qFuzzyCompare definitions require an ignore
from PyQt6.QtGui import *  # type: ignore[no-redef,assignment]
from PyQt6.QtNetwork import QLocalServer, QLocalSocket, QNetworkProxy
from PyQt6.QtQuick import *
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWidgets import *


def qconnect(signal: Callable | pyqtSignal | pyqtBoundSignal, func: Callable) -> None:
    signal.connect(func)  # type: ignore


class QTimer(QObject):
    timeout = pyqtSignal()

    loop: asyncio.AbstractEventLoop | None = None
    timer_handle: asyncio.TimerHandle | None = None
    interval: float = -1
    _single_shot = False

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

    def setSingleShot(self, val: bool) -> None:
        self._single_shot = val

    def isSingleShot(self) -> bool:
        return self._single_shot

    @classmethod
    def singleShot(cls, interval: float, callback: Callable[[], None]) -> Self:
        res = cls()
        res.setSingleShot(True)
        res.timeout.connect(callback)
        res.start(interval)
        return res

    def _on_timeout(self):
        self.timer_handle = None
        if self._single_shot:
            self.loop = None
            self.interval = -1
        else:
            self._start_timer()

        self.timeout.emit()

    def _start_timer(self):
        from . import mw

        if self.timer_handle:
            self.timer_handle.cancel()

        assert mw.taskman.loop
        self.loop = mw.taskman.loop
        self.timer_handle = self.loop.call_later(self.interval, self._on_timeout)

    def start(self, msec: int | float) -> None:
        self.interval = msec / 1000
        self._start_timer()

    def stop(self):
        if self.timer_handle:
            self.timer_handle.cancel()
            self.timer_handle = None
            self.loop = None
            self.interval = -1

    def remainingTime(self) -> int:
        if self.timer_handle:
            assert self.loop
            remaining = self.timer_handle.when() - self.loop.time()
            return max((0, int(remaining * 1000)))
        return -1
