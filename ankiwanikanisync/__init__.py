from __future__ import annotations

import sys
from pathlib import Path

from aqt import gui_hooks

from .promise import Promise
from .promise_qt import QtScheduler

sys.path.append(str(Path(__file__).parent / "deps"))

__version__ = "0.3.0"

Promise.set_scheduler(QtScheduler())


class Hooks:
    just_loaded = False
    anki_closing = False

    def __init__(self):
        gui_hooks.profile_did_open.append(self.on_load)
        gui_hooks.profile_will_close.append(self.on_close)
        gui_hooks.sync_did_finish.append(self.on_synced)
        gui_hooks.main_window_did_init.append(self.on_init)

    def on_init(self):
        from . import importer, ui
        from .config import config

        ui.init()

        if config._version != __version__:
            importer.update_html()

            config._version = __version__

    def on_load(self):
        self.just_loaded = True
        self.anki_closing = False

    def on_close(self):
        self.anki_closing = True

    def on_synced(self):
        if self.anki_closing:
            return
        if self.just_loaded:
            from .sync import auto_sync

            auto_sync()
        self.just_loaded = False

        from .collection import wk_col

        wk_col.update_current_level_op()


hooks = Hooks()
