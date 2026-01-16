from __future__ import annotations

from typing import Any

import aqt.sound
from anki.cards import Card
from aqt import gui_hooks
from aqt.browser.previewer import Previewer
from aqt.clayout import CardLayout
from aqt.reviewer import Reviewer

type PyCmdRes = tuple[bool, Any]


def pycmd_handler(result: PyCmdRes, pycmd: str, context: Any) -> PyCmdRes:
    match pycmd.split(":"):
        case ["play", ctx, "all"]:
            card: Card | None = None
            match context:
                case CardLayout():
                    card = context.rendered_card
                case Previewer():
                    card = context.card()
                case Reviewer():
                    card = context.card
            if card:
                tags = card.question_av_tags() if ctx == "q" else card.answer_av_tags()

                aqt.sound.av_player.play_tags(tags)
                return (True, None)
    return result


def leave_marker(html: str, card: Card, context: Any) -> str:
    return html.replace("__IS_PLAY_ALL_AVAILABLE__", "__YES_IT_IS__")


def install_play_all_audio():
    gui_hooks.card_will_show.append(leave_marker)
    gui_hooks.webview_did_receive_js_message.append(pycmd_handler)
