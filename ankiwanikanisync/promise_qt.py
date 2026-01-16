from __future__ import annotations

from typing import override

from aqt.qt import QApplication, QEvent, QObject

from .promise import Scheduler


class RunnableEvent(QEvent):
    TYPE = QEvent.registerEventType()

    def __init__(self, callback: Scheduler.Callback, /) -> None:
        super().__init__(QEvent.Type(self.TYPE))
        self.callback = callback
        self.cancelled = False


class Cancellable(Scheduler.Cancellable):
    def __init__(self, event: RunnableEvent):
        self.event = event

    @override
    def cancel(self) -> None:
        self.event.cancelled = True

    @override
    def cancelled(self) -> bool:
        return self.event.cancelled


class QtScheduler(QObject, Scheduler):
    """
    A stub object which acts as an event dispatch target for RunnableEvents in
    order to run callables at the top of the Qt application event loop.
    """

    def event(self, event: QEvent | None) -> bool:
        if isinstance(event, RunnableEvent):
            if not event.cancelled:
                event.callback()
            return True
        return False  # pragma: no cover

    @override
    def call_soon(self, callable: Scheduler.Callback, /) -> Scheduler.Cancellable:
        """
        Runs the given callback at the top of the Qt application event loop.
        """
        event = RunnableEvent(callable)
        QApplication.postEvent(self, event)
        return Cancellable(event)
