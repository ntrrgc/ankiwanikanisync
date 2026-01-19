from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Sequence
from unittest.mock import patch

import pytest
from anki.collection import (
    Card,
    CardStats,
    ImportAnkiPackageOptions,
    ImportAnkiPackageRequest,
)
from anki.consts import (
    CARD_TYPE_LRN,
    CARD_TYPE_NEW,
    CARD_TYPE_REV,
    QUEUE_TYPE_LRN,
    QUEUE_TYPE_REV,
    QUEUE_TYPE_SUSPENDED,
)
from aqt.qt import QAction
from pytest import approx
from pytest_mock import MockerFixture

from ankiwanikanisync.types import WKMeaning

from .fixtures import SubSession
from .utils import fixture_path, get_note, lazy, pending_ops_complete

if TYPE_CHECKING:
    from ankiwanikanisync.collection import WKCollection


def meaning(meaning: str, primary: bool = True) -> WKMeaning:
    return WKMeaning(meaning=meaning, primary=primary, accepted_answer=True)


@pytest.mark.asyncio
async def test_migration_migrate(
    add_finalizer: Callable[[Callable[[], None]], None],
    mocker: MockerFixture,
    session_mock: SubSession,
    wk_col: WKCollection,
    subtests: pytest.Subtests,
    tools_menu: dict[str, QAction],
):
    radical1 = session_mock.add_subject(
        "radical",
        characters="口",
        meanings=[meaning("Mouth")],
    )

    radical2 = session_mock.add_subject(
        "radical",
        characters="",
        meanings=[meaning("Tofu")],
    )

    kanji1 = session_mock.add_subject(
        "kanji",
        characters="二",
        meanings=[meaning("Two")],
    )

    kanji2 = session_mock.add_subject(
        "kanji",
        characters="八",
        meanings=[meaning("Eight")],
    )

    vocab1 = session_mock.add_subject(
        "vocabulary",
        characters="一",
        meanings=[meaning("One")],
    )

    kana_vocab1 = session_mock.add_subject(
        "kana_vocabulary",
        characters="ちょっと",
        meanings=[meaning("A Little"), meaning("A Moment")],
    )

    await lazy.sync.do_sync()

    with (
        subtests.test("Test no compatible note type"),
        patch("ankiwanikanisync.ui.show_tooltip", autospec=True) as show_tooltip,
    ):
        tools_menu["Migrate from WK3: Tokyo Drift"].triggered.emit()
        show_tooltip.assert_called_once_with("No compatible note type found")

    @add_finalizer
    def finalizer():
        if deck_id := wk_col.col.decks.id("Wanikani Ultimate 3 Fixtures", create=False):
            wk_col.col.decks.remove([deck_id])

    wk_col.col.import_anki_package(
        ImportAnkiPackageRequest(
            package_path=str(fixture_path("wk3_fixture.apkg")),
            options=ImportAnkiPackageOptions(with_scheduling=True),
        )
    )

    NOTE_TYPE = "Wanikani Ultimate 3"

    def side_effect(msg: str, choices: Sequence[str], initial: int) -> int:
        assert msg == "Select note type to migrate from"
        assert choices == [NOTE_TYPE]
        assert initial == choices.index(NOTE_TYPE)
        return choices.index(NOTE_TYPE)

    prompt_mock = mocker.patch(
        "ankiwanikanisync.ui.choose_list", autospec=True, side_effect=side_effect
    )

    tools_menu["Migrate from WK3: Tokyo Drift"].triggered.emit()
    prompt_mock.assert_called_once()

    await pending_ops_complete()

    notes = {
        "口": get_note(radical1),
        '<i class="radical-tofu"></i>': get_note(radical2),
        "二": get_note(kanji1),
        "八": get_note(kanji2),
        "一": get_note(vocab1),
        "ちょっと": get_note(kana_vocab1),
    }

    def revlog_to_dict(entry: CardStats.StatsRevlogEntry) -> dict[str, Any]:
        return {
            "time": entry.time,
            "button_chosen": entry.button_chosen,
            "interval": entry.interval,
            "ease": entry.ease,
            "memory_state": {
                "stability": entry.memory_state.stability,
                "difficulty": entry.memory_state.difficulty,
            },
        }

    def card_to_dict(card: Card) -> dict[str, Any]:
        stats = wk_col.col.card_stats_data(card.id)
        return {
            "ivl": card.ivl,
            "type": card.type,
            "queue": card.queue,
            "left": card.left,
            "decay": card.decay,
            "factor": card.factor,
            "lapses": card.lapses,
            "reps": card.reps,
            "stats": {
                "latest_review": stats.latest_review,
                "revlog": stats.revlog and list(map(revlog_to_dict, stats.revlog)),
            },
        }

    EXPECTED = {
        '<i class="radical-tofu"></i>': {
            0: {
                "decay": approx(0.2680000066757202),
                "factor": 0,
                "ivl": 0,
                "lapses": 0,
                "left": 1,
                "queue": QUEUE_TYPE_LRN,
                "reps": 1,
                "stats": {
                    "latest_review": 1768780860,
                    "revlog": [
                        {
                            "button_chosen": 3,
                            "ease": 400,
                            "interval": 600,
                            "memory_state": {
                                "difficulty": approx(2.1181039810180664),
                                "stability": approx(2.30649995803833),
                            },
                            "time": 1768780860,
                        }
                    ],
                },
                "type": CARD_TYPE_LRN,
            }
        },
        "ちょっと": {
            0: {
                "decay": approx(0.2680000066757202),
                "factor": 0,
                "ivl": 0,
                "lapses": 0,
                "left": 1,
                "queue": QUEUE_TYPE_LRN,
                "reps": 1,
                "stats": {
                    "latest_review": 1768780860,
                    "revlog": [
                        {
                            "button_chosen": 3,
                            "ease": 400,
                            "interval": 600,
                            "memory_state": {
                                "difficulty": approx(2.1181039810180664),
                                "stability": approx(2.30649995803833),
                            },
                            "time": 1768780860,
                        },
                    ],
                },
                "type": QUEUE_TYPE_LRN,
            }
        },
        "一": {
            0: {
                "decay": approx(0.2680000066757202),
                "factor": 0,
                "ivl": 0,
                "lapses": 0,
                "left": 2,
                "queue": QUEUE_TYPE_LRN,
                "reps": 1,
                "stats": {
                    "latest_review": 1768780860,
                    "revlog": [
                        {
                            "button_chosen": 2,
                            "ease": 595,
                            "interval": 330,
                            "memory_state": {
                                "difficulty": approx(5.112170696258545),
                                "stability": approx(1.2930999994277954),
                            },
                            "time": 1768780860,
                        }
                    ],
                },
                "type": CARD_TYPE_LRN,
            },
            1: {
                "decay": approx(0.2680000066757202),
                "factor": 2500,
                "ivl": 29,
                "lapses": 0,
                "left": 0,
                "queue": QUEUE_TYPE_REV,
                "reps": 1,
                "stats": {
                    "latest_review": 1768780860,
                    "revlog": [
                        {
                            "button_chosen": 4,
                            "ease": 100,
                            "interval": 2505600,
                            "memory_state": {
                                "difficulty": approx(1.0),
                                "stability": approx(8.295599937438965),
                            },
                            "time": 1768780860,
                        }
                    ],
                },
                "type": CARD_TYPE_REV,
            },
        },
        "二": {
            0: {
                "decay": approx(0.2680000066757202),
                "factor": 2500,
                "ivl": 32,
                "lapses": 0,
                "left": 0,
                "queue": QUEUE_TYPE_REV,
                "reps": 1,
                "stats": {
                    "latest_review": 1768780860,
                    "revlog": [
                        {
                            "button_chosen": 4,
                            "ease": 100,
                            "interval": 2764800,
                            "memory_state": {
                                "difficulty": approx(1.0),
                                "stability": approx(8.295599937438965),
                            },
                            "time": 1768780860,
                        }
                    ],
                },
                "type": CARD_TYPE_REV,
            },
            1: {
                "decay": None,
                "factor": 0,
                "ivl": 0,
                "lapses": 0,
                "left": 0,
                "queue": QUEUE_TYPE_SUSPENDED,
                "reps": 0,
                "stats": {"latest_review": 0, "revlog": []},
                "type": CARD_TYPE_NEW,
            },
        },
        "八": {
            0: {
                "decay": None,
                "factor": 0,
                "ivl": 0,
                "lapses": 0,
                "left": 0,
                "queue": QUEUE_TYPE_SUSPENDED,
                "reps": 0,
                "stats": {"latest_review": 0, "revlog": []},
                "type": CARD_TYPE_NEW,
            },
            1: {
                "decay": None,
                "factor": 0,
                "ivl": 0,
                "lapses": 0,
                "left": 0,
                "queue": QUEUE_TYPE_SUSPENDED,
                "reps": 0,
                "stats": {"latest_review": 0, "revlog": []},
                "type": CARD_TYPE_NEW,
            },
        },
        "口": {
            0: {
                "decay": approx(0.2680000066757202),
                "factor": 0,
                "ivl": 0,
                "lapses": 0,
                "left": 1,
                "queue": QUEUE_TYPE_LRN,
                "reps": 1,
                "stats": {
                    "latest_review": 1768780860,
                    "revlog": [
                        {
                            "button_chosen": 3,
                            "ease": 400,
                            "interval": 600,
                            "memory_state": {
                                "difficulty": approx(2.1181039810180664),
                                "stability": approx(2.30649995803833),
                            },
                            "time": 1768780860,
                        }
                    ],
                },
                "type": CARD_TYPE_LRN,
            }
        },
    }

    with subtests.test("Test migration results"):
        for name, note in notes.items():
            for card in note.cards():
                assert EXPECTED[name][card.ord] == card_to_dict(card)

    mocker.stopall()
    with subtests.test("Test canceling prompt"):
        Migrator_mock = mocker.patch("ankiwanikanisync.ui.Migrator", autospec=True)
        prompt_mock = mocker.patch(
            "ankiwanikanisync.ui.choose_list", autospec=True, return_value=None
        )

        tools_menu["Migrate from WK3: Tokyo Drift"].triggered.emit()
        prompt_mock.assert_called_once()
        assert not Migrator_mock.called
