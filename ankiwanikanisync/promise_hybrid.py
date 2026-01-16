from __future__ import annotations

import contextlib
from typing import override

from .promise import Scheduler


class Cancellable(Scheduler.Cancellable):
    def __init__(self, cancellables: list[Scheduler.Cancellable]):
        self._cancellables = cancellables

    @override
    def cancel(self) -> None:
        for canc in self._cancellables:
            with contextlib.suppress(Exception):
                canc.cancel()

    @override
    def cancelled(self) -> bool:
        return all(canc.cancelled() for canc in self._cancellables)


class HybridScheduler(Scheduler):
    """
    A scheduler which defers to any number of other schedulers, calling each
    given callback only once, the first time any of the given schedulers
    attempt to call it. This is useful for tests which may need to use a mix
    of Qt and asyncio event loops.
    """

    def __init__(self, *schedulers: Scheduler):
        self.schedulers = schedulers

    @override
    def call_soon(self, callback: Scheduler.Callback):
        class CallOnce:
            def __init__(self, callback: Scheduler.Callback):
                self.callback = callback
                self.called = False

            def __call__(self):
                if not self.called:
                    self.called = True
                    cancellable.cancel()
                    self.callback()

        cb = CallOnce(callback)
        cancellable = Cancellable([sched.call_soon(cb) for sched in self.schedulers])
        return cancellable
