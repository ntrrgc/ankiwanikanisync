from __future__ import annotations

import asyncio
import threading
from typing import override

from .promise import Scheduler


class StubHandle(Scheduler.Cancellable):
    def __init__(self, callback: Scheduler.Callback):
        self._callback = callback
        self._cancelled = False

    def __call__(self):
        if not self._cancelled:
            self._callback()

    def cancel(self):
        self._cancelled = True

    def cancelled(self):
        return self._cancelled


class AsyncIOScheduler(Scheduler):
    loop: asyncio.AbstractEventLoop | None = None

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None):
        self.loop = loop

    def get_loop(self) -> asyncio.AbstractEventLoop:
        return self.loop or asyncio.get_event_loop()

    @override
    def call_soon(self, callback: Scheduler.Callback) -> Scheduler.Cancellable:
        if threading.current_thread() is threading.main_thread():
            return self.get_loop().call_soon(callback)

        handle = StubHandle(callback)
        self.get_loop().call_soon_threadsafe(handle)
        return handle
