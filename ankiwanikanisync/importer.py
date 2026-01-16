from __future__ import annotations

import functools
import html
import json
import lzma
import pathlib
import pickle
import re
import shutil
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from itertools import chain
from time import sleep
from typing import (
    TYPE_CHECKING,
    Any,
    Final,
    Literal,
    NamedTuple,
    Optional,
    Sized,
    cast,
    get_args,
    override,
)

from anki.cards import CardId
from anki.collection import Collection, SearchNode
from anki.decks import DeckDict
from anki.importing.noteimp import UPDATE_MODE, ForeignNote, NoteImporter
from anki.models import NotetypeDict
from anki.notes import NoteId
from aqt import mw
from pyrate_limiter import Duration, Limiter, Rate
from typing_extensions import TypedDict

from . import hooks
from .collection import FieldName, format_id, wk_col
from .config import config
from .promise import Promise
from .types import (
    KeiseiCompound,
    KeiseiJSON,
    RelatedSubject,
    WKAudio,
    WKContextSentence,
    WKMeaning,
    WKReading,
    WKStudyMaterialData,
    WKSubject,
    WKSubjectData,
    WKVocabBase,
)
from .utils import assert_unreachable, query_op, report_progress, show_tooltip
from .wk_api import (
    is_WKAmalgumData,
    is_WKRadicalData,
    is_WKReadable,
    is_WKVocabBase,
    wk,
)
from .wk_ctx_parser import WKContextParser

ROOT_DIR: Final = pathlib.Path(__file__).parent.resolve()

# Escape HTML metacharacters in JSON strings to prevent the importer from
# mangling them.
html_trans: Final = str.maketrans({"<": r"\u003c", ">": r"\u003e", "&": r"\u0026"})

san_re = re.compile(r"(\\*)(`|\$\{|$)")


def to_json(val: object) -> str:
    r"""
    >>> to_json(r"<img>")
    '"\\u003cimg\\u003e"'

    >>> to_json(r"嬉しい")
    '"嬉しい"'
    """
    return json.dumps(val, ensure_ascii=False).translate(html_trans)


def sanitize(val: str) -> str:
    r"""
    >>> sanitize(r"`")
    '\\`'

    >>> sanitize(r"\`")
    '\\\\\\`'

    >>> sanitize(r"\\")
    '\\\\\\\\'

    >>> sanitize(r"${")
    '\\${'
    """
    def repl(m: re.Match) -> str:
        return f'{m[1]}{m[1]}{fr"\{m[2]}" if m[2] else ""}'
    return san_re.sub(repl, val)


class ImportCancelledException(Exception):
    pass


def audio_filename(audio: WKAudio) -> str:
    return f"wk3_{audio['metadata']['source_id']}.mp3"


class Downloader[ResultsType: Sized, ValType](ABC):
    limiter: Final = Limiter(
        Rate(10, 5 * Duration.SECOND), raise_when_fail=False, max_delay=10000
    )

    def __init__(self, col: Collection) -> None:
        self.col = col
        self.session = wk.session
        self.results = self.emptyresults()

    @abstractmethod
    def emptyresults(self) -> ResultsType: ...

    @property
    @abstractmethod
    def tag(self) -> str: ...

    def do_limit(self, name: str) -> bool:
        while not hooks.anki_closing:
            if self.limiter.try_acquire(name):
                return True
            else:  # pragma: no cover
                assert self.limiter.max_delay
                sleep(self.limiter.max_delay / 1000)
        raise ImportCancelledException("The import was cancelled.")  # pragma: no cover

    @abstractmethod
    def update_results(self, ResultsType) -> Any: ...

    def flush(self):
        if self.results:
            results = self.results
            self.results = self.emptyresults()

            @mw.taskman.run_on_main
            def update_results():
                self.update_results(results)

    @abstractmethod
    def process_note(self, note_id: NoteId, val: ValType) -> None: ...

    # Note: This operation can take a very long time, so it's important that
    # it run in an op without access to the Anki collection so that it does
    # not block other functionality. It only needs access to the network and
    # the filesystem.
    @query_op(without_collection=True)
    def process_notes_op(self, notes: Mapping[NoteId, ValType]) -> None:
        for note_id, val in notes.items():
            self.process_note(note_id, val)
            if len(self.results) >= 64:
                self.flush()
        self.flush()

    @abstractmethod
    def get_value(self, subj: WKSubject) -> ValType: ...

    @query_op
    def collect_notes_op(self) -> Mapping[NoteId, ValType]:
        query = SearchNode(tag=self.tag)
        notes = {}
        for note_id in wk_col.find_notes(query):
            data = json.loads(wk_col.get_note(note_id)["raw_data"])
            notes[note_id] = self.get_value(data)

        return notes

    @Promise.wrap
    async def process_notes(self) -> None:
        notes = await self.collect_notes_op()
        await self.process_notes_op(notes)


class AudioDownloader(Downloader[list[NoteId], Sequence[WKAudio]]):
    WK_AUDIO_INCOMPLETE_TAG: Final = "WkAudioIncomplete"
    tag: Final = WK_AUDIO_INCOMPLETE_TAG

    def __init__(self, col: Collection) -> None:
        super().__init__(col)

        self.dest_dir = pathlib.Path(self.col.media.dir())

    @override
    def emptyresults(self):
        return list[NoteId]()

    def process_note(self, note_id: NoteId, audios: Sequence[WKAudio]) -> None:
        for audio in audios:
            if audio["content_type"] != "audio/mpeg":
                continue

            filepath = self.dest_dir / audio_filename(audio)

            if not filepath.exists():
                self.do_limit("download_audio")
                req = self.session.get(audio["url"])
                req.raise_for_status()
                filepath.write_bytes(req.content)

        self.results.append(note_id)

    @override
    def get_value(self, subj: WKSubject) -> list[WKAudio]:
        assert is_WKVocabBase(subj["data"])
        return subj["data"]["pronunciation_audios"]

    @override
    @query_op
    def update_results(self, note_ids: list[NoteId]):
        self.col.tags.bulk_remove(note_ids, self.WK_AUDIO_INCOMPLETE_TAG)


class ContextDownloader(Downloader[dict[NoteId, str], str]):
    WK_CONTEXT_INCOMPLETE_TAG: Final = "WkContextIncomplete"
    tag: Final = WK_CONTEXT_INCOMPLETE_TAG

    @override
    def emptyresults(self):
        return dict[NoteId, str]()

    def process_note(self, note_id: NoteId, document_url: str) -> None:
        self.do_limit("download_context_patterns")

        req = self.session.get(document_url)
        req.raise_for_status()

        res = dict[str, list[WKContextSentence]]()
        try:
            parser = WKContextParser()
            parser.feed(req.text)

            for id in parser.patterns:
                res[parser.patterns[id]] = [
                    {"en": c.en, "ja": c.ja} for c in parser.collos[id]
                ]
        except Exception as e:  # pragma: no cover
            print(f"Failed parsing context: {e!r}")

        self.results[note_id] = to_json(res)

    @override
    @query_op
    def update_results(self, results: dict[NoteId, str]):
        changed_notes = []
        for note_id, ctx in results.items():
            note = wk_col.get_note(note_id)
            note["Context_Patterns"] = ctx
            note.remove_tag(self.WK_CONTEXT_INCOMPLETE_TAG)
            changed_notes.append(note)

        wk_col.col.update_notes(changed_notes)

    @override
    def get_value(self, subj: WKSubject):
        return subj["data"]["document_url"]


class KeiseiKanjiDataBase(TypedDict):
    readings: list[str]
    category: Literal[
        "gaiji",
        "jinmeiyou",
        "jouyou",
    ]
    decomposition: Optional[Sequence[str]]
    kyuujitai: Optional[str]
    comment: Optional[str]


class KeiseiKanjiDataStd(KeiseiKanjiDataBase):
    type: Literal[
        "comp_indicative",
        "derivative",
        "hieroglyph",
        "indicative",
        "kokuji",
        "rebus",
        "shinjitai",
        "unknown",
        "unprocessed",
    ]


class KeiseiKanjiDataPhonetic(KeiseiKanjiDataBase):
    type: Literal["comp_phonetic"]
    semantic: str
    phonetic: str


type KeiseiKanjiData = KeiseiKanjiDataStd | KeiseiKanjiDataPhonetic


KeiseiPhoneticData = TypedDict(
    "KeiseiPhoneticData",
    {
        "readings": list[str],
        "compounds": list[str],
        "non_compounds": list[str],
        "xrefs": list[str],
        "wk-radical": str,
    },
)


class KeiseiWKKanjiData(TypedDict):
    level: int
    character: str
    meaning: str
    onyomi: str | None
    kunyomi: str | None
    nanori: str | None
    important_reading: Literal["kunyomi", "nanori", "onyomi"]


class KeiseiData(TypedDict):
    kanji: dict[str, KeiseiKanjiData]
    phonetic: dict[str, KeiseiPhoneticData]
    wk_kanji: dict[str, KeiseiWKKanjiData]


class Components(NamedTuple):
    characters: list[str]
    meanings: list[str]
    readings: list[str]


class UserStudy(NamedTuple):
    meaning_synonyms: Sequence[str]
    meaning_note: str
    reading_note: str


type FieldsDict = dict[FieldName | Literal["_tags"], str]


def permissive_dict[T: str, U](val: dict[T, U]) -> dict[str, U]:
    return cast(dict[str, U], val)


def read_json_xz(file: pathlib.Path) -> Any:
    with lzma.open(file, mode="rt", encoding="utf-8") as f:
        return json.load(f)


class Keisei:
    def __init__(self):
        self.keisei_data = self.load()

    def load(self) -> KeiseiData:
        keiseidir = ROOT_DIR / "keisei"
        return {
            "kanji": read_json_xz(keiseidir / "kanji.json.xz"),
            "phonetic": read_json_xz(keiseidir / "phonetic.json.xz"),
            "wk_kanji": read_json_xz(keiseidir / "wk_kanji.json.xz"),
        }

    def get(self, subject: WKSubject) -> KeiseiJSON | None:
        data: KeiseiJSON = {"type": "", "compounds": []}

        def split(val):
            return (val or "").split(", ")

        match subject["object"]:
            case "radical":
                # Note: For some WaniKani radicals, there is not corresponding
                # Unicode codepoint, and the character image is actually an
                # SVG. Don't try to look up the empty string in the keisei
                # database in that case.
                item = subject["data"]["characters"]
                if not (item and item in self.keisei_data["phonetic"]):
                    return {"type": "nonradical"}

                data["type"] = "phonetic"

                ph_item = self.keisei_data["phonetic"][item]
                if ph_item["wk-radical"]:
                    data["radical"] = ph_item["wk-radical"].replace("-", " ").title()

                if self.keisei_data["kanji"].get(item, None):
                    if wk_kanji := self.keisei_data["wk_kanji"].get(item):
                        meaning = split(wk_kanji["meaning"])[0].title()
                        data["kanji"] = (meaning, self.get_reading(item))
                    else:
                        data["kanji"] = ("Non-WK", "-")

                data["component"] = item
                data["readings"] = ph_item["readings"]

                for compound in sorted(ph_item["compounds"], key=self.get_level):
                    if wk_kanji := self.keisei_data["wk_kanji"].get(compound):
                        meaning = split(wk_kanji["meaning"])[0]
                        data["compounds"].append(
                            KeiseiCompound(
                                character=compound,
                                reading=self.get_reading(compound),
                                meaning=meaning.title(),
                            )
                        )
                    else:
                        data["compounds"].append(
                            KeiseiCompound(
                                character=compound, reading="-", meaning="Non-WK"
                            )
                        )
            case "kanji":
                item = subject["data"]["characters"]
                if item not in self.keisei_data["kanji"]:
                    return {"type": "unprocessed"}

                kanji = self.keisei_data["kanji"][item]

                if item in self.keisei_data["phonetic"]:
                    data["type"] = "phonetic"
                    component = item
                elif kanji["type"] == "comp_phonetic":
                    data["type"] = "compound"
                    component = kanji["phonetic"]
                else:
                    return {"type": kanji["type"]}

                ph_comp = self.keisei_data["phonetic"][component]

                if rad := ph_comp["wk-radical"]:
                    data["radical"] = rad.replace("-", " ").title()

                if component in self.keisei_data["kanji"]:
                    if wk_kanji := self.keisei_data["wk_kanji"].get(component):
                        meaning = split(wk_kanji["meaning"])[0].title()
                        data["kanji"] = (meaning, self.get_reading(component))
                    else:
                        data["kanji"] = ("Non-WK", "-")

                data["component"] = component
                data["readings"] = ph_comp["readings"]
                if kanji["type"] == "comp_phonetic":
                    assert kanji["semantic"]
                    data["semantic"] = kanji["semantic"]

                for compound in sorted(ph_comp["compounds"], key=self.get_level):
                    if wk_kanji := self.keisei_data["wk_kanji"].get(compound):
                        meaning = split(wk_kanji["meaning"])[0]
                        data["compounds"].append(
                            KeiseiCompound(
                                character=compound,
                                reading=self.get_reading(compound),
                                meaning=meaning.title(),
                            )
                        )
                    else:
                        data["compounds"].append(
                            KeiseiCompound(
                                character=compound, reading="-", meaning="Non-WK"
                            )
                        )
            case _:
                return None

        return data

    def get_reading(self, item: str) -> str:
        if kanji := self.keisei_data["kanji"].get(item):
            return kanji["readings"][0]
        # pragma: no cover: start
        if not TYPE_CHECKING:
            assert_unreachable()

        if phonetic := self.keisei_data["phonetic"].get(item):
            return phonetic["readings"][0]

        def split(val):
            return (val or "").split(", ")

        wk = self.keisei_data["wk_kanji"][item]
        return next(
            chain(split(wk["onyomi"]), split(wk["kunyomi"]), split(wk["nanori"]))
        )
        # pragma: no cover: stop

    def get_level(self, item) -> int:
        if wk_kanji := self.keisei_data["wk_kanji"].get(item):
            return wk_kanji["level"]
        return 100


@functools.cache
def get_keisei() -> Keisei:
    return Keisei()


type PitchKey = tuple[str, str]
type PitchData = tuple[str, int]


def get_pitch_data() -> dict[PitchKey, list[PitchData]]:
    pitchfile = ROOT_DIR / "pitch" / "accent_data.pickle.xz"
    with lzma.open(pitchfile, mode="rb") as f:
        return pickle.load(f)


type Pitch = Literal["l-h", "h-l", "l", "h"]


class WKImporter(NoteImporter):
    # Don't include the _tags key
    FIELDS: Final[Sequence[str]] = get_args(FieldName)

    def __init__(
        self,
        collection: Collection,
        model: NotetypeDict,
        subjects: Sequence[WKSubject],
        related_subjects: Mapping[int, WKSubject],
        study_mats: Mapping[int, WKStudyMaterialData],
    ) -> None:
        super().__init__(collection, "")
        self.allowHTML = True
        self.importMode = UPDATE_MODE
        self.model = model
        self.subjects = subjects
        self.related_subjects = related_subjects
        self.study_mats = study_mats

        self.session = wk.session
        self.limiter = Limiter(
            Rate(100, Duration.MINUTE), raise_when_fail=False, max_delay=250
        )

        self.pitch_data = get_pitch_data()
        self.keisei = get_keisei()

        self.radical_svg_cache: dict[str, str] = {}

        self.fetch_patterns = config.FETCH_CONTEXT_PATTERNS

    def do_limit(self, name: str) -> bool:
        while not mw.progress.want_cancel():
            if self.limiter.try_acquire(name):
                return True
            else:  # pragma: no cover
                assert self.limiter.max_delay
                sleep(self.limiter.max_delay / 1000)
        raise ImportCancelledException("The import was cancelled.")  # pragma: no cover

    def fields(self) -> int:
        return len(self.model["flds"]) + 1  # Final unnamed field is _tags

    def initMapping(self) -> None:
        super().initMapping()
        assert self.mapping
        for i, field in enumerate(self.mapping):
            if field not in self.FIELDS and field != "_tags":
                self.mapping[i] = ""  # pragma: no cover

    def foreignNotes(self) -> list[ForeignNote]:
        res = []
        for i, subj in enumerate(self.subjects):
            if mw.progress.want_cancel():  # pragma: no cover
                raise ImportCancelledException("The import was cancelled.")

            report_progress(
                f"Importing subject {i}/{len(self.subjects)}...",
                i,
                len(self.subjects),
            )
            if note := self.makeNote(subj):
                res.append(note)
        return res

    def makeNote(self, subject: WKSubject) -> ForeignNote | None:
        assert self.mapping

        data = subject["data"]
        if data["hidden_at"]:
            return None

        meanings = self.get_meanings(subject)
        meanings_whitelist = []
        meanings_blacklist = []
        for item in subject["data"]["auxiliary_meanings"]:
            if item["type"] == "whitelist":
                meanings_whitelist.append(item["meaning"].strip())
            else:
                meanings_blacklist.append(item["meaning"].strip())

        readings = self.get_readings(subject)

        user_study = self.get_user_study(subject)

        comps = self.get_components(subject, "component_subject_ids")
        similars = self.get_components(subject, "visually_similar_subject_ids")
        amalgums = self.get_components(subject, "amalgamation_subject_ids")

        def get_readings(key: str):
            return ", ".join(readings.get(key, []))

        field_values: FieldsDict = {
            "card_id": str(subject["id"]),
            "sort_id": str(self.get_sort_id(subject)),
            "raw_data": to_json(subject),
            "Level": str(data["level"]),
            "DocumentURL": data["document_url"],
            "Characters": self.get_character(data),
            "Card_Type": subject["object"].replace("_", " ").title(),
            "Meaning": ", ".join(meanings),
            "Meaning_Mnemonic": self.html_newlines(
                ((data.get("meaning_mnemonic") or "") + user_study.meaning_note).strip()
            ),
            "Meaning_Hint": self.html_newlines(str(data.get("meaning_hint") or "")),
            "Meaning_Whitelist": ", ".join(
                [*meanings_whitelist, *meanings, *user_study.meaning_synonyms]
            ),
            "Meaning_Blacklist": ", ".join(meanings_blacklist),
            "Reading": get_readings("primary"),
            "Reading_Onyomi": get_readings("onyomi"),
            "Reading_Kunyomi": get_readings("kunyomi"),
            "Reading_Nanori": get_readings("nanori"),
            "Reading_Whitelist": get_readings("accepted"),
            "Reading_Mnemonic": self.html_newlines(
                (
                    str(data.get("reading_mnemonic") or "") + user_study.reading_note
                ).strip()
            ),
            "Reading_Hint": self.html_newlines(str(data.get("reading_hint") or "")),
            "Comps": to_json(comps),
            "Similar": to_json(similars),
            "Found_in": to_json(amalgums),
            "Context_Patterns": "{}",
            "Context_Sentences": to_json(self.get_context_sentences(subject)),
            "Keisei": to_json(self.keisei.get(subject)),
        }

        if is_WKAmalgumData(data):
            subject_ids = data["component_subject_ids"]
            field_values["components"] = " ".join(map(format_id, subject_ids))

            if subject["object"] == "vocabulary":
                for subj_id in subject_ids:
                    subj = self.related_subjects[subj_id]
                    if subj["data"]["characters"] == subject["data"]["characters"]:
                        readings = self.get_readings(subj)
                        field_values.update(
                            {
                                "Reading_Onyomi": get_readings("onyomi"),
                                "Reading_Kunyomi": get_readings("kunyomi"),
                                "Reading_Nanori": get_readings("nanori"),
                            }
                        )

        tags = [f"Lesson_{data['level']}", subject["object"].title()]

        if is_WKVocabBase(data):
            tags.append(AudioDownloader.WK_AUDIO_INCOMPLETE_TAG)
            field_values["Audio"] = self.ensure_audio(data)
            field_values["Word_Type"] = ", ".join(data["parts_of_speech"])

        if self.fetch_patterns and subject["object"] in (
            "vocabulary",
            "kana_vocabulary",
        ):
            tags.append(ContextDownloader.WK_CONTEXT_INCOMPLETE_TAG)

        field_values["_tags"] = " ".join(tags)

        def field_value(field: str) -> str:
            val = permissive_dict(field_values).get(field, "")
            if field not in wk_col.JSON_FIELDS:
                val = sanitize(val)
            return val

        note = ForeignNote()
        note.fields = list(map(field_value, self.mapping))
        return note

    def get_user_study(self, subject: WKSubject) -> UserStudy:
        study_mat = self.study_mats.get(subject["id"])

        def user_note(key: Literal["meaning_note", "reading_note"]):
            if note := study_mat and study_mat[key]:
                return f'<p class="explanation">User Note</p>{note}'
            return ""

        return UserStudy(
            meaning_synonyms=study_mat["meaning_synonyms"] if study_mat else [],
            meaning_note=user_note("meaning_note"),
            reading_note=user_note("reading_note"),
        )

    def get_sort_id(self, subject: WKSubject):
        data = subject["data"]

        tp = subject["object"].lower()
        tpo = 30000
        match tp:
            case "vocabulary" | "kana_vocabulary":
                tpo = 20000
            case "kanji":
                tpo = 10000
            case "radical":
                tpo = 0

        return data["level"] * 100000 + tpo + data["lesson_position"]

    def get_character(self, data: WKSubjectData):
        if res := data["characters"]:
            return res

        if is_WKRadicalData(data):
            if data["slug"] in self.radical_svg_cache:
                return self.radical_svg_cache[data["slug"]]

            # Try to fetch the svg for this radical
            for img in data["character_images"]:
                if img["content_type"] == "image/svg+xml":
                    self.do_limit("wk_import")

                    req = self.session.get(img["url"])
                    req.raise_for_status()
                    res = f"<wk-radical-svg>{req.text}</wk-radical-svg>"

                    self.radical_svg_cache[data["slug"]] = res
                    return res

            # If that somehow fails, emit the old method as fallback
            return f'<i class="radical-{data["slug"]}"></i>'  # pragma: no cover

        return "Not found"

    def get_meanings(self, subject: WKSubject) -> list[str]:
        res: list[str] = []
        for meaning in subject["data"]["meanings"]:
            if meaning["accepted_answer"]:
                meaning["meaning"] = meaning["meaning"].strip()
                if meaning["primary"]:
                    res.insert(0, meaning["meaning"])
                else:
                    res.append(meaning["meaning"])
        return res

    def get_readings(self, subject: WKSubject) -> dict[str, list[str]]:
        data = subject["data"]
        readings = data["readings"] if is_WKReadable(data) else []

        res: dict[str, tuple[list[str], list[str]]] = {
            "primary": ([], []),
            "accepted": ([], []),
        }

        for reading in readings:
            cur_reading = self.apply_pitch_pattern(subject, reading["reading"])

            if reading["accepted_answer"]:
                if subject["object"] != "kanji":
                    if reading["primary"]:
                        res["primary"][0].append(f"<reading>{cur_reading}</reading>")
                    else:
                        res["primary"][1].append(cur_reading)

                if reading["primary"]:
                    res["accepted"][0].append(cur_reading)
                else:
                    res["accepted"][1].append(cur_reading)

            if "type" in reading:
                val = res.setdefault(reading["type"], ([], []))

                if reading["primary"]:
                    val[0].append(f"<reading>{cur_reading}</reading>")
                else:
                    val[1].append(cur_reading)

        if subject["object"] == "kana_vocabulary":
            cur_reading = self.apply_pitch_pattern(
                subject, subject["data"]["characters"]
            )
            res["primary"][0].append(f"<reading>{cur_reading}</reading>")

        return {key: val[0] + val[1] for key, val in res.items()}

    def apply_pitch_internal(self, reading: str, accent: int) -> str:
        def mora(class_: Pitch, *text: str) -> str:
            return f'<span class="mora-{class_}">{"".join(text)}</span>'

        moras = re.findall(r".[ょゃゅョャュぁぃぅぇぉァィゥェゥ]?", reading)
        if accent <= 0:
            res = mora("l-h", moras[0]) + mora("h", *moras[1:])
        elif accent == 1:
            res = mora("h-l", moras[0]) + mora("l", *moras[1:])
        else:
            res = mora("l-h", moras[0]) + mora("h-l", *moras[1:accent])
            if end := moras[accent:]:
                res += mora("l", *end)
        return res

    def apply_pitch_pattern(self, subject: WKSubject, reading: str) -> str:
        reading = reading.strip()
        if subject["object"] in ("radical", "kanji"):
            return reading

        key = (subject["data"]["characters"].strip(), reading)
        if key not in self.pitch_data:
            return reading

        if res := "".join(
            self.apply_pitch_internal(part[0], part[1]) for part in self.pitch_data[key]
        ):
            return f'<span class="mora">{res}</span>'

        raise Exception(  # pragma: no cover
            html.escape(f"Invalid pitch output for {key}: {self.pitch_data[key]!r}")
        )

    def get_components(self, subject, key: str) -> list[RelatedSubject]:
        if key not in subject["data"]:
            return []

        def find_primary[T: WKMeaning | WKReading](elts: Sequence[T]) -> T:
            for elt in elts:
                if elt["primary"]:
                    return elt
            raise IndexError()  # pragma: no cover

        res = []
        for sub_id in subject["data"][key]:
            if subj := self.related_subjects.get(sub_id):
                data = subj["data"]

                char = self.get_character(data)
                entry = RelatedSubject(
                    characters=f'<a href="{data["document_url"]}">{char}</a>',
                    meaning=find_primary(data["meanings"])["meaning"],
                    reading="",
                )

                if is_WKReadable(data):
                    reading = find_primary(data["readings"])
                    entry["reading"] = self.apply_pitch_pattern(
                        subj, reading["reading"]
                    )
                res.append(entry)
        return res

    def get_context_sentences(self, subject: WKSubject) -> list[WKContextSentence]:
        if is_WKVocabBase(subject["data"]):
            return subject["data"]["context_sentences"]
        return []

    def ensure_audio(self, data: WKVocabBase) -> str:
        audios = data["pronunciation_audios"]
        readings = data["readings"] if is_WKReadable(data) else []

        def audio_sort(audio: WKAudio) -> int:
            meta = audio["metadata"]
            for i, reading in enumerate(readings):
                if reading["reading"] == meta["pronunciation"]:
                    ret = 1000 + (i * 1000) + meta["voice_actor_id"]
                    if not reading["primary"]:
                        ret += 1000000
                    return ret
            return (
                abs(hash(meta["pronunciation"]))
                + 2000000
                + 1000 * len(readings)
                + meta["voice_actor_id"]
            )

        return "".join(
            f"[sound:{audio_filename(audio)}]"
            for audio in sorted(audios, key=audio_sort)
            if audio["content_type"] == "audio/mpeg"
        )

    def html_newlines(self, inp: str) -> str:
        return inp.replace("\r", "").replace("\n", "<br/>")


def ensure_media_files(col: Collection) -> None:
    datadir = ROOT_DIR / "data"

    source_dir = datadir / "files"
    dest_dir = pathlib.Path(col.media.dir())
    for source_file in source_dir.iterdir():
        dest_file = dest_dir / source_file.name
        if not dest_file.exists() or source_file.suffix in (".js", ".map"):
            shutil.copy(source_file, dest_file)


class TemplateData(TypedDict, closed=True):
    qfmt: str
    afmt: str


class ModelData(TypedDict):
    css: str
    templates: Mapping[str, TemplateData]


def get_model_data() -> ModelData:
    datadir = ROOT_DIR / "data"

    def subs(field: str) -> str:
        return "{{" + field + "}}"

    card_data = """
        <script>
            function deepFreeze(obj) {
                Object.freeze(obj);
                for (const val of Object.values(obj)) {
                    if (typeof val === "object" && val != null) {
                        deepFreeze(val);
                    }
                }
                return obj;
            }
            var _ = deepFreeze({
"""
    for field in [*WKImporter.FIELDS, "Card"]:
        if field in wk_col.JSON_FIELDS:
            card_data += f'\
                "{field}": {subs(field)},\n'
        else:
            card_data += f'\
                "{field}": String.raw`{subs(field)}`,\n'
    card_data += """
            });
    </script>
"""

    def read_common(path: pathlib.Path) -> str:
        return path.read_text(encoding="utf-8").replace("__CARD_DATA__", card_data)

    common_back = read_common(datadir / "common_back.html")
    common_front = read_common(datadir / "common_front.html")

    def read_template(path: pathlib.Path) -> str:
        return (
            path.read_text(encoding="utf-8")
            .replace("__COMMON_BACK__", common_back)
            .replace("__COMMON_FRONT__", common_front)
        )

    return {
        "css": (datadir / "style.css").read_text(encoding="utf-8"),
        "templates": {
            # Meaning has to be first, for sorting
            "Meaning": {
                "qfmt": read_template(datadir / "meaning_front.html"),
                "afmt": read_template(datadir / "meaning_back.html"),
            },
            "Reading": {
                "qfmt": read_template(datadir / "reading_front.html"),
                "afmt": read_template(datadir / "reading_back.html"),
            },
        },
    }


def ensure_deck(col: Collection, deck_name: str) -> bool:
    ensure_media_files(col)

    changes = 0

    if model := col.models.by_name(config.NOTE_TYPE_NAME):
        fields = col.models.field_map(model)
        for field in set(WKImporter.FIELDS) - set(fields.keys()):
            col.models.add_field(model, col.models.new_field(field))
            changes += 1

        fields = col.models.field_map(model)
        i, field_dict = fields[WKImporter.FIELDS[0]]
        if i != 0:
            col.models.reposition_field(model, field_dict, 0)
            changes += 1

        if changes:
            col.models.update_dict(model)
    else:
        model = col.models.new(config.NOTE_TYPE_NAME)

        for field in WKImporter.FIELDS:
            col.models.add_field(model, col.models.new_field(field))

        col.models.set_sort_index(model, 2)

        model_data = get_model_data()

        for name, tmpl_data in model_data["templates"].items():
            tmpl = col.models.new_template(name)
            tmpl.update(tmpl_data.items())
            col.models.add_template(model, tmpl)

        model["css"] = model_data["css"]

        col.models.add_dict(model)
        model = col.models.by_name(config.NOTE_TYPE_NAME)

        changes += 1

    assert model

    def create_deck(name: str) -> DeckDict:
        deck = col.decks.new_deck_legacy(False)
        deck["name"] = name
        deck["mid"] = model["id"]
        deck["conf"] = deck_preset_id
        deck["id"] = col.decks.add_deck_legacy(deck).id
        return deck

    deck_preset_id = None
    if deck := col.decks.by_name(deck_name):
        deck_preset_id = deck["conf"]
    else:
        deck_preset = col.decks.add_config(deck_name)
        deck_preset["autoplay"] = False
        deck_preset_id = deck_preset["id"]
        col.decks.update_config(deck_preset)

        deck = create_deck(deck_name)

        model["did"] = deck["id"]
        col.models.update_dict(model)

        changes += 1

    deck_names = {d.name for d in col.decks.all_names_and_ids()}

    def ensure_subdeck(name: str) -> bool:
        if res := name not in deck_names:
            create_deck(name)
        return res

    for lvl in range(1, 61):
        changes += ensure_subdeck(f"{deck_name}::Level {lvl:02}")
        for kind in ["1 - Radicals", "2 - Kanji", "3 - Vocab"]:
            changes += ensure_subdeck(f"{deck_name}::Level {lvl:02}::{kind}")

    return bool(changes)


def do_update_html() -> None:
    model = wk_col.col.models.by_name(config.NOTE_TYPE_NAME)
    if not model:  # pragma: no cover
        show_tooltip("WK note type not found.")
        return

    ensure_media_files(wk_col.col)

    model_data = get_model_data()

    for tmpl in model["tmpls"]:
        if tmpl_data := model_data["templates"].get(tmpl["name"]):
            tmpl.update(tmpl_data)
        else:  # pragma: no cover
            show_tooltip("Unknown template name in note type.")

    model["css"] = model_data["css"]

    wk_col.col.models.update_dict(model)


@query_op
def update_html():
    do_update_html()


def sort_new_cards(col: Collection) -> None:
    card_ids = wk_col.find_cards("is:new")

    sort_keys = {}
    for cid in card_ids:
        card = wk_col.get_card(cid)
        note = card.note()

        tp = note["Card_Type"].lower()
        tpo = 30
        match tp:
            case "vocabulary" | "kana vocabulary":
                tpo = 20
            case "kanji":
                tpo = 10
            case "radical":
                tpo = 0

        # The Meaning template has the lowest template index(ord), so add it in
        # to have Meaning-Cards first.
        sort_keys[cid] = int(float(note["sort_id"])) * 1000 + tpo + card.ord

    card_ids = sorted(card_ids, key=lambda cid: sort_keys[cid])

    col.sched.reposition_new_cards(
        card_ids=card_ids,
        starting_from=0,
        step_size=1,
        randomize=False,
        shift_existing=False,
    )


def suspend_hidden_notes(col: Collection, subjects: Sequence[WKSubject]) -> None:
    changed_notes = []
    for subject in subjects:
        if not subject["data"]["hidden_at"]:
            continue

        if note := wk_col.get_note_for_subject(subject["id"]):
            col.sched.suspend_notes([note.id])
            note.add_tag("Hidden")
            changed_notes.append(note)
    col.update_notes(changed_notes)


def assign_subdecks(col, deck_name: str) -> None:
    # Note: The * character still acts as a wildcard when it is enclused in
    # double quotes unless it is also escaped with a \
    card_ids = col.find_cards(f'"deck:{deck_name}" -"deck:{deck_name}::*"')

    moves: dict[int, list[CardId]] = {}
    for cid in card_ids:
        card = wk_col.get_card(cid)
        note = card.note()

        lvl = int(note["Level"])
        match note["Card_Type"].lower():
            case "radical":
                kind = "1 - Radicals"
            case "kanji":
                kind = "2 - Kanji"
            case _:
                kind = "3 - Vocab"
        sub_deck_name = f"{deck_name}::Level {lvl:02}::{kind}"

        if (did := col.decks.id(sub_deck_name, create=False)) and did != card.did:
            moves.setdefault(did, []).append(cid)

    if moves:
        for did in moves:
            col.set_deck(moves[did], did)


def ensure_audio():
    audio_downloader = AudioDownloader(wk_col.col)
    audio_downloader.process_notes()


def ensure_context():
    context_downloader = ContextDownloader(wk_col.col)
    context_downloader.process_notes()


def ensure_notes(
    col: Collection,
    subjects: Sequence[WKSubject],
    related_subjects: Mapping[int, WKSubject],
    study_mats: Mapping[int, WKStudyMaterialData],
):
    model = col.models.by_name(config.NOTE_TYPE_NAME)
    assert model
    deck_id = col.decks.id(config.DECK_NAME, create=False)
    assert deck_id

    col.set_aux_notetype_config(model["id"], "lastDeck", deck_id)

    importer = WKImporter(col, model, subjects, related_subjects, study_mats)
    importer.initMapping()
    importer.run()

    report_progress("Assigning to correct subdecks...", 100, 100)
    assign_subdecks(col, config.DECK_NAME)

    report_progress("Suspending hidden subjects...", 100, 100)
    suspend_hidden_notes(col, subjects)

    report_progress("Suspending locked subjects...", 100, 100)
    wk_col.update_suspended_cards()

    ensure_audio()
    ensure_context()

    return len(subjects) > 0
