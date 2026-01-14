from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence, cast, get_args

import pytest
from anki.consts import QUEUE_TYPE_SUSPENDED
from anki.notes import Note
from pyfakefs.fake_filesystem import FakeFilesystem

from ankiwanikanisync.types import (
    WKAudio,
    WKMeaning,
    WKReading,
    WKReadingType,
    WKSubject,
    WKSubjectDataBase,
)

from .fixtures import SubSession
from .utils import (
    SaveAttr,
    cleanup_after,
    get_dist_fixtures,
    get_note,
    iso_reltime,
    lazy,
    open_fixture,
    pending_ops_complete,
    step,
    sync_subjects,
    write_fixtures,
)

if TYPE_CHECKING:
    from anki.collection import Collection
    from aqt.qt import QAction

    from ankiwanikanisync.collection import WKCollection
    from ankiwanikanisync.importer import Pitch

cleanup = cleanup_after("function")


def pitchify(*moras: tuple[Pitch, str]) -> str:
    def mora(class_: str, *text: str) -> str:
        return f'<span class="mora-{class_}">{"".join(text)}</span>'

    return f'<span class="mora">{
        "".join(mora(pitch, chars) for (pitch, chars) in moras)
    }</span>'


def meaning(meaning: str, primary: bool = True) -> WKMeaning:
    return WKMeaning(meaning=meaning, primary=primary, accepted_answer=True)


def reading(
    reading: str,
    primary: bool = True,
    type_: WKReadingType | None = None,
    accepted_answer: bool = True,
) -> WKReading:
    res = WKReading(reading=reading, primary=primary, accepted_answer=accepted_answer)
    if type_:
        res["type"] = type_
    return res


@pytest.mark.asyncio
async def test_import_fields(
    session_mock: SubSession, wk_col: WKCollection, subtests: pytest.Subtests
):
    from ankiwanikanisync.collection import format_id
    from ankiwanikanisync.importer import audio_filename

    def make_url(type_: str, slug: str) -> str:
        return f"https://www.wanikani.com/{type_}/{slug}"

    def make_link(type_: str, chars: str) -> str:
        return f'<a href="{make_url(type_, chars)}">{chars}</a>'

    def get_url[T: WKSubjectDataBase](subj: WKSubject[T]):
        return make_url(subj["object"], subj["data"]["slug"])

    def get_link[T: WKSubjectDataBase](subj: WKSubject[T]):
        return f'<a href="{get_url(subj)}">{subj["data"]["characters"]}</a>'

    def user_note(note: str) -> str:
        return f'<p class="explanation">User Note</p>{note}'

    Reading_Mnemonic = "Phasellus egestas purus in tristique sodales."

    def make_expected[T: WKSubjectDataBase](
        subj: WKSubject[T],
    ) -> dict[str, str | object]:
        res: dict[str, str | object] = {
            "card_id": subj["id"],
            "Level": subj["data"]["level"],
            "DocumentURL": get_url(subj),
            "Characters": subj["data"]["characters"],
            "Card_Type": subj["object"].replace("_", " ").title(),
            "Meaning_Blacklist": "Baz",
            "Meaning_Mnemonic": "Lorem ipsem",
            "Word_Type": "",
            "Meaning_Hint": "",
            "Reading": "",
            "Reading_Onyomi": "",
            "Reading_Kunyomi": "",
            "Reading_Nanori": "",
            "Reading_Whitelist": "",
            "Reading_Mnemonic": "",
            "Reading_Hint": "",
            "Context_Patterns": {},
            "Context_Sentences": [],
            "Comps": [],
            "Similar": [],
            "Found_in": [],
            "Audio": "",
            "Keisei": None,
            "components": "",
            "last_upstream_sync_time": "",
            "raw_data": subj,
        }

        if subj["object"] in ("vocabulary", "kana_vocabulary"):
            res["Context_Sentences"] = [
                {
                    "en": "Lorem ipsum dolor sit amet.",
                    "ja": "こんにちは、とても痛いですね。",
                }
            ]
            res["Word_Type"] = "noun, の adjective"

        if subj["object"] == "vocabulary":
            res["Reading_Mnemonic"] = Reading_Mnemonic

        if comps := cast(list[int], subj["data"].get("component_subject_ids")):
            res["components"] = " ".join(map(format_id, comps))

        if audios := cast(list[WKAudio], subj["data"].get("pronunciation_audios")):
            res["Audio"] = "".join(
                f"[sound:{audio_filename(audio)}]"
                for audio in audios
                if audio["content_type"] == "audio/mpeg"
            )

        return res

    with step("Add subjects"):
        radical1 = session_mock.add_subject(
            "radical",
            characters="大",
            meanings=[meaning("Big")],
        )
        radical1_expected = make_expected(radical1) | {
            "Meaning_Whitelist": "Quux, Big",
            "Meaning": "Big",
            "Found_in": [
                {
                    "characters": make_link("kanji", "美"),
                    "meaning": "Beauty",
                    "reading": "び",
                }
            ],
            "Keisei": {
                "type": "phonetic",
                "compounds": [
                    {"character": "戻", "reading": "れい", "meaning": "Return"},
                    {"character": "泰", "reading": "たい", "meaning": "Peace"},
                ],
                "radical": "Big",
                "kanji": ["Big", "だい"],
                "component": "大",
                "readings": ["だい", "たい"],
            },
        }

        radical2 = session_mock.add_subject(
            "radical",
            characters="口",
            meanings=[meaning("Mouth")],
        )
        radical2_expected = make_expected(radical2) | {
            "Meaning": "Mouth",
            "Meaning_Whitelist": "Quux, Mouth",
            "Found_in": [
                {
                    "characters": make_link("kanji", "右"),
                    "meaning": "Right",
                    "reading": "ゆう",
                }
            ],
            "Keisei": {
                "type": "phonetic",
                "compounds": [
                    {"character": "句", "reading": "く", "meaning": "Paragraph"},
                    {"character": "勾", "reading": "-", "meaning": "Non-WK"},
                ],
                "radical": "Mouth",
                "kanji": ["Mouth", "こう"],
                "component": "口",
                "readings": ["こう", "く"],
            },
        }

        kanji1 = session_mock.add_subject(
            "kanji",
            characters="美",
            component_subject_ids=[radical1["id"]],
            meanings=[
                meaning("Beauty"),
                meaning("Beautiful", False),
            ],
            readings=[
                reading("び", True, "onyomi"),
                reading("み", False, "onyomi"),
                reading("うつく", False, "kunyomi"),
            ],
        )
        radical1["data"]["amalgamation_subject_ids"] = [kanji1["id"]]
        kanji1_expected = make_expected(kanji1) | {
            "Meaning": "Beauty, Beautiful",
            "Meaning_Whitelist": "Quux, Beauty, Beautiful",
            "Reading_Onyomi": "<reading>び</reading>, み",
            "Reading_Kunyomi": "うつく",
            "Reading_Whitelist": "び, み, うつく",
            "Reading_Mnemonic": "dolor sit amet",
            "Comps": [
                {
                    "characters": get_link(radical1),
                    "meaning": "Big",
                    "reading": "",
                }
            ],
            "Found_in": [
                {
                    "characters": make_link("vocabulary", "美しい"),
                    "meaning": "Beautiful",
                    "reading": pitchify(("l-h", "う"), ("h-l", "つくし"), ("l", "い")),
                }
            ],
            "Keisei": {"type": "comp_indicative"},
        }

        kanji2 = session_mock.add_subject(
            "kanji",
            characters="右",
            component_subject_ids=[radical2["id"]],
            meanings=[meaning("Right")],
            readings=[
                reading("ゆう", True, "onyomi"),
                reading("う", False, "onyomi"),
                reading("みぎ", False, "kunyomi"),
            ],
        )
        radical2["data"]["amalgamation_subject_ids"] = [kanji2["id"]]
        kanji2_expected = make_expected(kanji2) | {
            "Meaning": "Right",
            "Meaning_Whitelist": "Quux, Right",
            "Reading_Onyomi": "<reading>ゆう</reading>, う",
            "Reading_Kunyomi": "みぎ",
            "Reading_Whitelist": "ゆう, う, みぎ",
            "Reading_Mnemonic": "dolor sit amet",
            "Comps": [
                {
                    "characters": get_link(radical2),
                    "meaning": "Mouth",
                    "reading": "",
                }
            ],
            "Found_in": [
                {
                    "characters": make_link("vocabulary", "左右"),
                    "meaning": "Left And Right",
                    "reading": pitchify(("h-l", "さ"), ("l", "ゆう")),
                },
                {
                    "characters": '<a href="https://www.wanikani.com/vocabulary/右">右</a>',
                    "meaning": "Right",
                    "reading": '<span class="mora"><span class="mora-l-h">み</span>'
                    '<span class="mora-h">ぎ</span></span>',
                },
            ],
            "Keisei": {
                "type": "phonetic",
                "compounds": [{"character": "佑", "reading": "-", "meaning": "Non-WK"}],
                "radical": "Right",
                "kanji": ["Right", "う"],
                "component": "右",
                "readings": ["う", "ゆう"],
            },
        }

        kanji3 = session_mock.add_subject(
            "kanji",
            characters="左",
            meanings=[meaning("Left")],
            readings=[
                reading("さ", True, "onyomi"),
                reading("ひだり", False, "kunyomi"),
            ],
        )

        kanji_s1 = session_mock.add_subject(
            "kanji",
            characters="人",
            meanings=[meaning("Person")],
            readings=[
                reading("にん", True, "onyomi"),
                reading("じん", False, "onyomi"),
                reading("ひと", False, "kunyomi"),
            ],
        )

        kanji_s2 = session_mock.add_subject(
            "kanji",
            characters="入",
            meanings=[meaning("Enter")],
            readings=[
                reading("にゅう", True, "onyomi"),
                reading("はい", False, "kunyomi"),
            ],
            visually_similar_subject_ids=[kanji_s1["id"]],
        )
        kanji_s1["data"]["visually_similar_subject_ids"] = [kanji_s2["id"]]

        kanji_s1_expected = make_expected(kanji_s1) | {
            "Keisei": {
                "type": "hieroglyph",
            },
            "Reading_Kunyomi": "ひと",
            "Reading_Mnemonic": "dolor sit amet",
            "Reading_Onyomi": "<reading>にん</reading>, じん",
            "Reading_Whitelist": "にん, じん, ひと",
            "Similar": [
                {
                    "characters": get_link(kanji_s2),
                    "meaning": "Enter",
                    "reading": "にゅう",
                },
            ],
        }

        kanji_s2_expected = make_expected(kanji_s2) | {
            "Keisei": {
                "type": "indicative",
            },
            "Reading_Kunyomi": "はい",
            "Reading_Mnemonic": "dolor sit amet",
            "Reading_Onyomi": "<reading>にゅう</reading>",
            "Reading_Whitelist": "にゅう, はい",
            "Similar": [
                {
                    "characters": get_link(kanji_s1),
                    "meaning": "Person",
                    "reading": "にん",
                },
            ],
        }

        vocab1 = session_mock.add_subject(
            "vocabulary",
            characters="左右",
            component_subject_ids=[kanji2["id"], kanji3["id"]],
            meanings=[
                meaning("Left And Right"),
                meaning("Both Ways", False),
                meaning("Influence", False),
                meaning("Control", False),
            ],
            readings=[reading("さゆう")],
        )
        kanji2["data"]["amalgamation_subject_ids"] = [vocab1["id"]]
        kanji3["data"]["amalgamation_subject_ids"] = [vocab1["id"]]
        vocab1_expected = make_expected(vocab1) | {
            "Meaning": "Left And Right, Both Ways, Influence, Control",
            "Meaning_Whitelist": "Quux, Left And Right, Both Ways, Influence, Control",
            "Reading": f"<reading>{pitchify(('h-l', 'さ'), ('l', 'ゆう'))}</reading>",
            "Reading_Whitelist": pitchify(("h-l", "さ"), ("l", "ゆう")),
            "Comps": [
                {
                    "characters": get_link(kanji2),
                    "meaning": "Right",
                    "reading": "ゆう",
                },
                {
                    "characters": get_link(kanji3),
                    "meaning": "Left",
                    "reading": "さ",
                },
            ],
        }

        vocab2 = session_mock.add_subject(
            "vocabulary",
            characters="美しい",
            component_subject_ids=[kanji1["id"]],
            meanings=[meaning("Beautiful")],
            readings=[reading("うつくしい")],
        )
        kanji1["data"]["amalgamation_subject_ids"] = [vocab2["id"]]

        vocab2_study_materials = session_mock.add_study_materials(
            subject_id=vocab2["id"],
            meaning_note="Foo",
            meaning_synonyms=["Bar"],
            reading_note="Baz",
        )

        vocab2_expected = make_expected(vocab2) | {
            "Meaning": "Beautiful",
            "Meaning_Mnemonic": f"Lorem ipsem{user_note('Foo')}",
            "Meaning_Whitelist": "Quux, Beautiful, Bar",
            "Reading": f"<reading>{
                pitchify(('l-h', 'う'), ('h-l', 'つくし'), ('l', 'い'))
            }</reading>",
            "Reading_Whitelist": pitchify(
                ("l-h", "う"), ("h-l", "つくし"), ("l", "い")
            ),
            "Reading_Mnemonic": Reading_Mnemonic + user_note("Baz"),
            "Comps": [
                {
                    "characters": get_link(kanji1),
                    "meaning": "Beauty",
                    "reading": "び",
                }
            ],
        }

        vocab3 = session_mock.add_subject(
            "kana_vocabulary",
            characters="これ",
            meanings=[meaning("This One")],
        )
        vocab3_expected = make_expected(vocab3) | {
            "Meaning": "This One",
            "Meaning_Whitelist": "Quux, This One",
            "Reading": f"<reading>{pitchify(('l-h', 'こ'), ('h', 'れ'))}</reading>",
        }

        vocab4 = session_mock.add_subject(
            "vocabulary",
            characters="右",
            component_subject_ids=[kanji2["id"]],
            meanings=[meaning("Right")],
            readings=[reading("みぎ")],
        )
        kanji2["data"]["amalgamation_subject_ids"].append(vocab4["id"])
        vocab4_expected = make_expected(vocab4) | {
            "Meaning": "Right",
            "Meaning_Whitelist": "Quux, Right",
            "Reading": f"<reading>{pitchify(('l-h', 'み'), ('h', 'ぎ'))}</reading>",
            "Reading_Whitelist": pitchify(("l-h", "み"), ("h", "ぎ")),
            "Reading_Onyomi": "<reading>ゆう</reading>, う",
            "Reading_Kunyomi": "みぎ",
            "Comps": [
                {
                    "characters": get_link(kanji2),
                    "meaning": "Right",
                    "reading": "ゆう",
                },
            ],
        }

        vocab5 = session_mock.add_subject(
            "vocabulary",
            characters="七",
            meanings=[meaning("Seven")],
            readings=[
                reading("なな"),
                reading("しち", False),
            ],
        )
        vocab5_expected = make_expected(vocab5) | {
            "Reading": f"<reading>{pitchify(('h-l', 'な'), ('l', 'な'))}</reading>, "
            f"{pitchify(('l-h', 'し'), ('h-l', 'ち'))}",
            "Reading_Whitelist": f"{pitchify(('h-l', 'な'), ('l', 'な'))}, "
            f"{pitchify(('l-h', 'し'), ('h-l', 'ち'))}",
        }

    await sync_subjects()

    if TYPE_CHECKING:
        # Print the fields of all notes for updating test
        for nid in wk_col.find_notes():
            print("")
            note = wk_col.get_note(nid)
            assert note
            for k, v in note.items():
                if k in wk_col.JSON_FIELDS:
                    v = json.loads(v)
                print(f"  {k!r}: {v!r},")

    def check_expected(expected: dict[str, Any], name: str):
        note = cast(Note, wk_col.get_note_for_subject(int(expected["card_id"])))
        actual = dict[str, Any]()
        for key in expected:
            actual[key] = note[key]
            if key in wk_col.JSON_FIELDS:
                actual[key] = json.loads(note[key])

        with subtests.test(msg="check_expected", name=name):
            assert expected == actual

    with step("Check results"):
        check_expected(radical1_expected, "radical1")
        check_expected(radical2_expected, "radical2")
        check_expected(kanji1_expected, "kanji1")
        check_expected(kanji2_expected, "kanji2")
        check_expected(kanji_s1_expected, "kanji_s1")
        check_expected(kanji_s2_expected, "kanji_s2")
        check_expected(vocab1_expected, "vocab1")
        check_expected(vocab2_expected, "vocab2")
        check_expected(vocab3_expected, "vocab3")
        check_expected(vocab4_expected, "vocab4")
        check_expected(vocab5_expected, "vocab5")

    with subtests.test(msg="get_components(kanji2)"):
        comps = [int(n["card_id"]) for n in wk_col.get_components(get_note(vocab1))]
        assert sorted(comps) == sorted([kanji2["id"], kanji3["id"]])

    with step("Update subjects"):
        vocab3["data_updated_at"] = iso_reltime()
        vocab3["data"]["meanings"][0]["meaning"] = "This"
        vocab3_expected["Meaning"] = "This"
        vocab3_expected["Meaning_Whitelist"] = "Quux, This"

        vocab2_study_materials["data_updated_at"] = iso_reltime()
        vocab2_study_materials["data"]["meaning_synonyms"] = ["Baz"]
        vocab2_expected["Meaning_Whitelist"] = "Quux, Beautiful, Baz"

        session_mock.add_study_materials(
            subject_id=vocab1["id"],
            meaning_note="A",
            meaning_synonyms=["B"],
            reading_note="C",
        )
        if TYPE_CHECKING:
            assert isinstance(vocab1_expected["Meaning_Mnemonic"], str)
            assert isinstance(vocab1_expected["Reading_Mnemonic"], str)
            assert isinstance(vocab1_expected["Meaning_Whitelist"], str)
        vocab1_expected["Meaning_Mnemonic"] += user_note("A")
        vocab1_expected["Reading_Mnemonic"] += user_note("C")
        vocab1_expected["Meaning_Whitelist"] += ", B"

    with step("Sync subjects"):
        await pending_ops_complete()
        await lazy.sync.do_sync()

    with step("Check results"):
        check_expected(vocab3_expected, "vocab3 after update")
        check_expected(vocab2_expected, "vocab2 after update")
        check_expected(vocab1_expected, "vocab1 after update")

    write_fixtures(__name__, "test_import_fields")


@pytest.mark.asyncio
async def test_import_sanitize(session_mock: SubSession):
    unsan = r"` \` ${ \ "[:-1]
    with step("Add subjects"):
        vocab = session_mock.add_subject(
            "vocabulary",
            meaning_mnemonic=unsan,
            context_sentences=[{"en": unsan, "ja": ""}],
        )

    await sync_subjects()

    with step("Check results"):
        note = get_note(vocab)

        assert note["Meaning_Mnemonic"] == r"\` \\\` \${ \\ "[:-1]

        assert json.loads(note["Context_Sentences"]) == [{"en": unsan, "ja": ""}]

    write_fixtures(__name__, "test_import_sanitize")


@pytest.mark.asyncio
async def test_import_keisei(session_mock: SubSession):
    def get_keisei[T: WKSubjectDataBase](subj: WKSubject[T]):
        note = get_note(subj)
        return json.loads(note["Keisei"])

    with step("Add subjects"):
        kanji1 = session_mock.add_subject(
            "kanji",
            characters="字",
        )

        kanji2 = session_mock.add_subject(
            "kanji",
            characters="歌",
        )

        kanji3 = session_mock.add_subject(
            "kanji",
            characters="頁",
        )

        kanji4 = session_mock.add_subject(
            "kanji",
            characters="了",
        )

        radical1 = session_mock.add_subject(
            "radical",
            characters="酉",
        )

        radical2 = session_mock.add_subject(
            "radical",
            characters="一",
        )

    await sync_subjects()

    with step("Check results"):
        assert get_keisei(kanji1) == {
            "component": "子",
            "compounds": [
                {"character": "字", "meaning": "Letter", "reading": "じ"},
            ],
            "kanji": ["Child", "し"],
            "radical": "Child",
            "readings": ["し", "す"],
            "semantic": "宀",
            "type": "compound",
        }

        assert get_keisei(kanji2) == {
            "compounds": [
                {"character": "歌", "reading": "か", "meaning": "Song"},
            ],
            "type": "compound",
            "kanji": ["Non-WK", "-"],
            "component": "哥",
            "readings": ["か"],
            "semantic": "欠",
        }

        assert get_keisei(kanji3) == {"type": "unprocessed"}

        assert get_keisei(kanji4) == {"type": "unknown"}

        assert get_keisei(radical1) == {
            "compounds": [
                {"character": "酒", "reading": "しゅ", "meaning": "Alcohol"},
                {"character": "醜", "reading": "しゅう", "meaning": "Ugly"},
            ],
            "type": "phonetic",
            "radical": "Alcohol",
            "kanji": ["Non-WK", "-"],
            "component": "酉",
            "readings": ["ゆう", "しゅう", "しゅ"],
        }

        assert get_keisei(radical2) == {"type": "nonradical"}

    write_fixtures(__name__, "test_import_keisei")


@pytest.mark.asyncio
async def test_import_input_fixture(session_mock: SubSession):
    with step("Add subjects"):
        kanji1 = session_mock.add_subject(
            "kanji",
            characters="病",
            meanings=[
                meaning("Sick"),
                meaning("Ill", False),
                meaning("Coma", False),
            ],
            readings=[
                reading("びょう", True, "onyomi"),
                reading("へい", False, "onyomi"),
                reading("や", False, "kunyomi", False),
                reading("やまい", False, "kunyomi", False),
            ],
            auxiliary_meanings=[
                {"meaning": "flu", "type": "whitelist"},
                {"meaning": "fly", "type": "blacklist"},
            ],
        )

        vocab1 = session_mock.add_subject(
            "vocabulary",
            characters="病",
            component_subject_ids=[kanji1["id"]],
            readings=[reading("びょう")],
            meanings=[meaning("Sick")],
        )
        kanji1["data"]["amalgamation_subject_ids"] = [vocab1["id"]]

    await sync_subjects()

    write_fixtures(__name__, "test_import_input_fixture")


@pytest.mark.asyncio
async def test_import_hidden(session_mock: SubSession, wk_col: WKCollection):
    with step("Add subjects"):
        kanji1 = session_mock.add_subject(
            "kanji",
            characters="字",
            level=1,
            hidden_at=iso_reltime(),
        )

        kanji2 = session_mock.add_subject(
            "kanji",
            characters="歌",
            level=1,
        )

    await sync_subjects()

    with step("Check results"):
        assert wk_col.get_note_for_subject(kanji1["id"]) is None

    with step("Update subjects"):
        kanji2["data"]["hidden_at"] = iso_reltime()
        kanji2["data_updated_at"] = iso_reltime()

    await sync_subjects()

    with step("Check results"):
        note = get_note(kanji2)
        assert note.has_tag("Hidden")
        assert all(c.queue == QUEUE_TYPE_SUSPENDED for c in note.cards())


@pytest.mark.asyncio
async def test_import_partial(
    save_attr: SaveAttr, session_mock: SubSession, wk_col: WKCollection
):
    save_attr(lazy.config, "SYNC_ALL")
    lazy.config.SYNC_ALL = False

    with step("Add subjects"):
        kanji1 = session_mock.add_subject(
            "kanji",
            characters="字",
        )

        session_mock.add_assignment(subject_id=kanji1["id"])

        kanji2 = session_mock.add_subject(
            "kanji",
            characters="歌",
        )

    await sync_subjects()

    with step("Check results"):
        assert get_note(kanji1)
        assert wk_col.get_note_for_subject(kanji2["id"]) is None

    with step("Add assignment"):
        session_mock.add_assignment(subject_id=kanji2["id"])

    await sync_subjects()

    with step("Check results"):
        assert get_note(kanji2)


@pytest.mark.asyncio
async def test_import_context_patterns(save_attr: SaveAttr, session_mock: SubSession):
    from ankiwanikanisync.importer import ContextDownloader

    save_attr(lazy.config, "FETCH_CONTEXT_PATTERNS")
    lazy.config.FETCH_CONTEXT_PATTERNS = True

    with step("Add session fixtures"):
        ctx_url = "ctxt_patterns_migi.html"
        with open_fixture(ctx_url, "r") as f:
            ctx_data = f.read()
        session_mock.get(ctx_url, text=ctx_data)

        vocab = session_mock.add_subject(
            "vocabulary",
            characters="右",
            document_url=f"{session_mock.BASE_URL}/{ctx_url}",
        )

    await sync_subjects()
    await pending_ops_complete()

    with step("Check results"):
        note = get_note(vocab)

        assert ContextDownloader.WK_CONTEXT_INCOMPLETE_TAG not in note.tags

        assert json.loads(note["Context_Patterns"]) == {
            "右の〜": [
                {"ja": "右のボタン", "en": "right button"},
                {"ja": "右のグラフ", "en": "graph on the right"},
                {"ja": "右のアイコン", "en": "right icon"},
            ],
            "右〜": [
                {"ja": "右上", "en": "upper right"},
                {"ja": "右ひざ", "en": "right knee"},
                {"ja": "右下", "en": "lower right"},
            ],
        }

    write_fixtures(__name__, "test_import_context_patterns")


@pytest.mark.asyncio
async def test_import_audio(session_mock: SubSession, wk_col: WKCollection):
    from ankiwanikanisync.importer import AudioDownloader, audio_filename

    with step("Add subjects"):
        vocab = session_mock.add_subject(
            "vocabulary",
            characters="左右",
            readings=[reading("さゆう")],
        )

        media = Path(wk_col.col.media.dir())
        audios = [
            audio
            for audio in vocab["data"]["pronunciation_audios"]
            if audio["content_type"] == "audio/mpeg"
        ]

    with session_mock.base_session.audio_lock:
        await sync_subjects()

        # Give the audio downloader task a bit of time to complete a download,
        # to make sure the locking is working as expected.
        with step("Sleep"):
            await asyncio.sleep(1)

        # Make sure that audio download is blocked during sync and that it
        # doesn't interfere with completion. Audios should be downloaded
        # afterwards.
        with step("Check for presence of audio files"):
            for audio in audios:
                path = media / audio_filename(audio)
                assert not path.exists(), "Audio should not be fetched while lock held"

        with step("Check for presence of audio incomplete tag"):
            note = get_note(vocab)
            assert note.has_tag(AudioDownloader.WK_AUDIO_INCOMPLETE_TAG), (
                "Incomplete note should still have audio incomplete tag"
            )

    await pending_ops_complete()

    with step("Check for presence of audio files"):
        for audio in audios:
            path = media / audio_filename(audio)
            assert path.exists(), "Audio should have been downloaded"
            with path.open("r") as f:
                assert f.read() == audio["url"], (
                    "Audio contents should match URL for audio/mpeg source"
                )

    with step("Check for presence of audio incomplete tag"):
        note = get_note(vocab)
        assert not note.has_tag(AudioDownloader.WK_AUDIO_INCOMPLETE_TAG), (
            "Audio incomplete tag should be removed when download is complete"
        )


@pytest.mark.asyncio
async def test_import_radical_image(session_mock: SubSession, wk_col: WKCollection):
    SVG = "<svg>Hallo</svg>"
    SVG_FILENAME = "svg/hallo.svg"
    SVG_URL = f"{session_mock.BASE_URL}/{SVG_FILENAME}"

    PNG_FILENAME = "png/hello.png"
    PNG_URL = f"{session_mock.BASE_URL}/{PNG_FILENAME}"

    with step("Add session fixtures"):
        session_mock.get(SVG_FILENAME, text=SVG)
        session_mock.get(PNG_FILENAME, text="image/png")

        radical = session_mock.add_subject(
            "radical",
            characters="",
            character_images=[
                {
                    "content_type": "image/png",
                    "url": PNG_URL,
                    "metadata": {},
                },
                {
                    "content_type": "image/svg+xml",
                    "url": SVG_URL,
                    "metadata": {},
                },
            ],
            slug="Big",
            meanings=[meaning("Big")],
        )

        kanji = session_mock.add_subject(
            "kanji",
            component_subject_ids=[radical["id"]],
        )

    await sync_subjects()

    with step("Check results"):
        note = get_note(radical)

        assert note["DocumentURL"] == "https://www.wanikani.com/radical/Big"
        assert note["Characters"] == f"<wk-radical-svg>{SVG}</wk-radical-svg>"
        assert json.loads(get_note(kanji)["Comps"]) == [
            {
                "characters": f'<a href="{note["DocumentURL"]}">{
                    note["Characters"]
                }</a>',
                "meaning": "Big",
                "reading": "",
            },
        ]


@pytest.fixture(scope="module", autouse=True)
def ensure_deck(col: Collection):
    from ankiwanikanisync.importer import ensure_deck

    ensure_deck(col, lazy.config.DECK_NAME)


def test_ensure_deck(wk_col: WKCollection):
    expected = ["Default", lazy.config.DECK_NAME]
    for level in range(1, 61):
        level_name = f"{lazy.config.DECK_NAME}::Level {level:02d}"
        expected.append(level_name)

        for i, subj_type in enumerate(("Radicals", "Kanji", "Vocab")):
            expected.append(f"{level_name}::{i + 1} - {subj_type}")

    actual = sorted([deck.name for deck in wk_col.col.decks.all_names_and_ids()])

    assert expected == actual

    def get_deck(name: str):
        deck = wk_col.col.decks.by_name(name)
        assert deck
        return deck

    model = wk_col.col.models.by_name(lazy.config.NOTE_TYPE_NAME)
    assert model

    default = get_deck(expected[0])
    root = get_deck(expected[1])
    assert default["conf"] != root["conf"]
    assert model["did"] == root["id"]

    for name in expected[1:]:
        deck = get_deck(name)
        assert deck["conf"] == root["conf"]
        assert deck["mid"] == model["id"]


@contextmanager
def template_fields_test(fs: FakeFilesystem, col: Collection):
    import ankiwanikanisync
    from ankiwanikanisync.importer import do_update_html

    with step("Create files"):
        res = Path(ankiwanikanisync.__file__).parent / "data"
        for fn, contents in {
            "common_back.html": "Common Back",
            "common_front.html": "Common Front",
            "meaning_back.html": "Meaning Back :: __COMMON_BACK__",
            "meaning_front.html": "Meaning Front {{card_id}} :: __COMMON_FRONT__",
            "reading_back.html": "Reading Back :: __COMMON_BACK__",
            "reading_front.html": "Reading Front {{card_id}} :: __COMMON_FRONT__",
            "style.css": "Style",
        }.items():
            fs.create_file(str(res / fn), contents=contents)

        fs.create_dir(str(res / "files"))

    with step("Run test body"):
        yield

    def get_templates() -> dict[str, Any]:
        model = col.models.by_name(lazy.config.NOTE_TYPE_NAME)
        assert model

        return {
            "css": model["css"],
            "cards": {tmpl["name"]: tmpl for tmpl in model["tmpls"]},
        }

    with step("Check templates"):
        tmpl = get_templates()
        cards = tmpl["cards"]

        for card in ("Meaning", "Reading"):
            assert (
                cards[card]["qfmt"] == f"{card} Front {{{{card_id}}}} :: Common Front"
            )
            assert cards[card]["afmt"] == f"{card} Back :: Common Back"

        assert tmpl["css"] == "Style"

    with step("Restore default templates"):
        fs.pause()
        do_update_html()

    with step("Dump templates fixture"):
        tmpl = get_templates()
        with (get_dist_fixtures() / "templates.json").open("w") as f:
            json.dump(tmpl, f, ensure_ascii=False, indent=4)


def test_model_templates(fs: FakeFilesystem, col: Collection):
    from ankiwanikanisync.importer import ensure_deck

    if model := col.models.by_name(lazy.config.NOTE_TYPE_NAME):
        col.models.remove(model["id"])

    with template_fields_test(fs, col):
        ensure_deck(col, lazy.config.DECK_NAME)


@pytest.mark.asyncio
async def test_update_html(
    fs: FakeFilesystem, tools_menu: dict[str, QAction], col: Collection
):
    with template_fields_test(fs, col):
        tools_menu["Overwrite Card HTML"].triggered.emit()
        await pending_ops_complete()


def test_update_fields(col: Collection):
    from ankiwanikanisync.collection import FieldName

    FIELDS: Sequence[str] = get_args(FieldName)

    with step("Setup model"):
        model = col.models.by_name(lazy.config.NOTE_TYPE_NAME)
        assert model

        fields = col.models.field_map(model)
        col.models.reposition_field(model, fields[FIELDS[0]][1], 10)
        col.models.remove_field(model, fields[FIELDS[-1]][1])
        col.models.update_dict(model)

    with step("Ensure deck"):
        lazy.sync.ensure_deck(col, lazy.config.DECK_NAME)

    with step("Check results"):
        model = col.models.by_name(lazy.config.NOTE_TYPE_NAME)
        assert model
        field_names = col.models.field_names(model)

        assert field_names[0] == FIELDS[0]
        assert FIELDS[-1] in field_names
