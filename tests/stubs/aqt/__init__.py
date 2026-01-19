from __future__ import annotations

import asyncio
import sys
from typing import Any, Callable
from unittest.mock import MagicMock

from anki.collection import Collection

from .qt import QApplication, QMenu, QWidget

sys.modules["aqt.sound"] = MagicMock()
sound = sys.modules["aqt.sound"]

for (mod, cls_name) in {
    "aqt.browser.previewer": "Previewer",
    "aqt.clayout": "CardLayout",
    "aqt.reviewer": "Reviewer",
}.items():
    class Class(MagicMock):
        pass

    Class.__name__ = cls_name
    Class.__qualname__ = cls_name

    module = MagicMock()
    setattr(module, cls_name, Class)

    sys.modules[mod] = module


class Hooks[**P, RT](list[Callable[P, RT]]):
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> RT | None:
        res = None
        for callable in self:
            res = callable(*args, **kwargs)
        return res


class GuiHooks:
    def __getattr__(self, attr: str) -> list[Callable[..., Any]]:
        val = Hooks[..., Any]()
        setattr(self, attr, val)
        return val


gui_hooks = GuiHooks()

# anikwanikanisync.__init__ needs to import aqt.gui_hooks, and we can't import
# anikwanikanisync.promise without importing __init__, so we need to delay
# importing Promise until after we initialize gui_hooks. In the future, the
# Promise implementation should probably be moved to a separate package and
# loaded from the deps folder like pyrate_limiter currently is.
from ankiwanikanisync.promise import Promise  # noqa


class TaskMan:
    loop: asyncio.AbstractEventLoop | None = None

    def __init__(self):
        self.pending_ops = set[Promise]()

    def add_pending_op(self, promise: Promise):
        self.pending_ops.add(promise)

        def remove():
            self.pending_ops.remove(promise)

        promise.finally_(remove)

    @Promise.wrap
    async def pending_ops_completed(self):
        while self.pending_ops:
            await Promise.all_settled(self.pending_ops)

    def run_on_main(self, callback: Callable[[], None]):
        def cb():
            callback()
        self.add_pending_op(Promise.resolve().finally_(cb))


class App:
    def activeWindow(self) -> QWidget:
        return mw


class MW(QWidget):
    col: Collection | None = None

    def __init__(self):
        super().__init__()
        self.addonManager = MagicMock()
        self.app = App()
        self.form = MagicMock()
        self.form.menuTools = QMenu("Tools", self)
        self.progress = MagicMock()
        self.taskman = TaskMan()


app = QApplication([])
mw = MW()
