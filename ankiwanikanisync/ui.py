from __future__ import annotations

import re
from typing import Any, Callable

from anki.models import NotetypeDict
from aqt import gui_hooks, mw
from aqt.browser.browser import Browser
from aqt.qt import QAction, QMenu, qconnect

from .collection import wk_col
from .config import config
from .importer import ensure_audio, ensure_context, update_html
from .migration import Migrator
from .play_all_audio import install_play_all_audio
from .sync import do_clear_cache, do_sync, do_update_intervals
from .timers import timers
from .utils import choose_list, show_tooltip


def wk3_migrate() -> None:
    FIELDS = (
        "Card_Type",
        "Characters",
        "Meaning",
    )

    def filter_model(model: NotetypeDict) -> bool:
        fields = wk_col.col.models.field_map(model)
        return model["name"] != config.NOTE_TYPE_NAME and all(
            f in fields for f in FIELDS
        )

    models = wk_col.col.models.all()
    note_names: list[str] = [model["name"] for model in models if filter_model(model)]

    if not note_names:
        show_tooltip("No compatible note type found")
        return

    expr = re.compile(r"wanikani.*3", re.I)
    sel_idx = 0
    for i, name in enumerate(note_names):
        if expr.search(name):
            sel_idx = i
            break

    res = choose_list("Select note type to migrate from", note_names, sel_idx)
    if res is not None:
        migrator = Migrator(config.NOTE_TYPE_NAME, note_names[res])
        migrator.do_migrate()


def init_tools_menu():
    menu = QMenu("WaniKani", mw)
    mw.form.menuTools.addMenu(menu)

    def add_action(label: str, fn: Callable[[], Any]) -> None:
        def callback():
            fn()

        action = QAction(label, mw)
        qconnect(action.triggered, callback)
        menu.addAction(action)

    add_action("Sync Notes", do_sync)

    add_action("Sync Due Dates", do_update_intervals)

    # add_action("Review Mature Cards", do_autoreview)

    menu.addSeparator()

    add_action("Clear Cache", do_clear_cache)

    menu.addSeparator()

    add_action("Overwrite Card HTML", update_html)
    add_action("Migrate from WK3: Tokyo Drift", wk3_migrate)


class BrowserMenu(object):
    def __init__(self):
        gui_hooks.browser_menus_did_init.append(self.create_browser_menu)
        gui_hooks.browser_will_show_context_menu.append(self.update_browser_menu)

    def create_browser_menu(self, browser: Browser) -> None:
        self.browser = browser

        self.unlock_action = QAction("Study WaniKani note", self.browser)
        self.browser.form.menu_Notes.addAction(self.unlock_action)
        qconnect(self.unlock_action.triggered, self.unlock_selected_notes)

    def update_browser_menu(self, browser: Browser, menu: QMenu) -> None:
        enable = any(
            wk_col.is_unlockable(wk_col.get_note(note_id))
            for note_id in self.browser.table.get_selected_note_ids()
        )
        self.unlock_action.setDisabled(not enable)

    def unlock_selected_notes(self) -> None:
        wk_col.unlock_notes(self.browser.table.get_selected_note_ids())


browser_menu = None


def init_browser_menu():
    global browser_menu
    browser_menu = BrowserMenu()


def init():  # pragma: no cover
    init_tools_menu()
    init_browser_menu()
    install_play_all_audio()

    timers.start_timers()
    ensure_audio()
    ensure_context()
