from __future__ import annotations

import importlib
import json
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    Callable,
    Concatenate,
    Final,
    Generator,
    Iterable,
    Literal,
    Self,
    TypedDict,
    Unpack,
    overload,
)
from unittest import mock

import pytest
import pytest_asyncio
from allure import step
from anki.collection import Card, Note
from anki.consts import (
    CARD_TYPE_LRN,
    CARD_TYPE_NEW,
    CARD_TYPE_REV,
    QUEUE_TYPE_LRN,
    QUEUE_TYPE_NEW,
    QUEUE_TYPE_REV,
)

if TYPE_CHECKING:
    from anki.collection import Collection

    from ankiwanikanisync import types
    from ankiwanikanisync.collection import FieldDict, WKCard, WKNote


class Lazy:
    PROPS: Final = {
        "config": ("ankiwanikanisync.config", "config"),
        "sync": ("ankiwanikanisync.sync",),
        # The timers and sync modules have a cyclic dependency, and the sync
        # module must be loaded first. To ensure that it always is, we import
        # timers from sync.
        "timers": ("ankiwanikanisync.sync", "timers"),
        "wk": ("ankiwanikanisync.wk_api", "wk"),
        "wk_col": ("ankiwanikanisync.collection", "wk_col"),
    }

    def __getattr__(self, attr: str):
        if path := self.PROPS.get(attr):
            val: Any = importlib.import_module(path[0])
            if len(path) > 1:
                val = getattr(val, path[1])

            setattr(self, attr, val)
            return val
        raise AttributeError()


if TYPE_CHECKING:
    import ankiwanikanisync.collection
    import ankiwanikanisync.sync
    import ankiwanikanisync.wk_api
    from ankiwanikanisync.config import config

    class lazy:
        config: Final = config
        sync: Final = ankiwanikanisync.sync
        timers = sync.timers
        wk = ankiwanikanisync.wk_api.wk
        wk_col = ankiwanikanisync.collection.wk_col
else:
    lazy = Lazy()


class Forwarder[**P]:
    def __call__[R](self, fn: Callable[P, R]) -> Callable[P, R]:
        return fn


def forward_args[**P](fn: Callable[P, Any]) -> Forwarder[P]:
    """
    A decorator for a function which forwards its arguments to another
    function but has an independent return type. See `iso_reltime`, which
    forwards its arguments to `timedelta` and returns a string, for an example.
    """
    return Forwarder[P]()


def forward_args_method[**P](fn: Callable[P, Any]) -> Forwarder[Concatenate[Any, P]]:
    """
    A decorator for a function which forwards its arguments to another
    function but has an independent return type. See `iso_reltime`, which
    forwards its arguments to `timedelta` and returns a string, for an example.
    """
    return Forwarder[Concatenate[Any, P]]()


class TimeDeltaArgs(TypedDict, total=False):
    days: float
    seconds: float
    microseconds: float
    milliseconds: float
    minutes: float
    hours: float
    weeks: float


def to_timedelta(
    delta: timedelta | None = None, /, **kwargs: Unpack[TimeDeltaArgs]
) -> timedelta:
    if delta is not None:
        if kwargs:
            raise TypeError("Must pass a timedelta or keyword arguments, not both")
        return delta
    return timedelta(**kwargs)


@forward_args(to_timedelta)
def reltime(*args, **kwargs) -> datetime:
    """
    Returns an datetime object relative to the current time, offset by a
    `timedelta` created with the given arguments. For instance,
    `iso_reltime(seconds=5)` returns a datetime for a time 5 seconds in the
    future, and `reltime(minutes=-5)` creates one for a time 5 minutes in the
    past.
    """
    return datetime.now(timezone.utc) + to_timedelta(*args, **kwargs)


@forward_args(to_timedelta)
def iso_reltime(*args, **kwargs) -> str:
    """
    Returns an ISO time string for a time relative to the current time, as
    created by the `reltime` function. See that function for more details.
    """
    return reltime(*args, **kwargs).isoformat()


class ApproxDatetime:
    """
    Helper for asserting the approximate values of datetime objects. The
    equality overload will return true if the datetime object being compared
    against is within 10 seconds of the datetime passed to the constructor.
    The subject of the comparison may also be a date/time string in ISO format
    or a timestamp number in seconds since the Epoch.

    >>> dt = datetime.fromtimestamp(100).astimezone(timezone.utc)

    >>> ApproxDatetime(dt) == 101
    True

    >>> ApproxDatetime(dt) == 99
    True

    >>> ApproxDatetime(dt) == 111
    False

    >>> ApproxDatetime(dt) == '1970-01-01T00:01:41+00:00'
    True

    >>> ApproxDatetime(dt) == '1970-01-01T00:00:00+00:00'
    False

    >>> ApproxDatetime(reltime(seconds=10)) == reltime(seconds=11)
    True

    >>> ApproxDatetime(reltime(seconds=10)) == reltime(seconds=100)
    False
    """

    DELTA: Final = timedelta(seconds=10)

    def __init__(self, dt: datetime):
        self.datetime = dt

    def __repr__(self):
        return f"{self.datetime!r} ± {self.DELTA!r}"

    def __eq__(self, other: object):
        match other:
            case str():
                with suppress(Exception):
                    other = datetime.fromisoformat(other)
            case int() | float():
                other = datetime.fromtimestamp(other).astimezone(timezone.utc)

        return isinstance(other, datetime) and (
            self.datetime - self.DELTA <= other <= self.datetime + self.DELTA
        )


@forward_args(reltime)
def approx_reltime(*args, **kwargs):
    """
    >>> approx_reltime(seconds=1) == reltime()
    True

    >>> approx_reltime(seconds=20) == reltime()
    False
    """
    return ApproxDatetime(reltime(*args, **kwargs))


class PartialDict[K, V](dict[K, V]):
    """
    An assertion helper for testing that all keys in the given `PartialDict`
    are present, and have equal values, in a dict that it is compared against.
    May be compared using either the <= operator (for direct use in
    assertions) or the == operator (when part of a more complex object
    hierarchy).

    >>> PartialDict({'a': 1}) <= {'a': 1, 'b': 2}
    True

    >>> PartialDict({'a': 1}) <= {'a': 2, 'b': 2}
    False

    >>> PartialDict({'a': 1}) <= {'b': 2}
    False

    >>> [42, PartialDict({'a': 1})] == [42, {'a': 1, 'b': 2}]
    True

    >>> [42, PartialDict({'a': 1})] == [42, {'b': 2}]
    False
    """
    def __le__(self, other: object) -> bool:
        if isinstance(other, dict):
            return self.items() <= other.items()
        return NotImplemented

    def __eq__(self, other: object):
        return self.__le__(other)

    @staticmethod
    def assertrepr_compare(
        config: pytest.Config, op: str, left: object, right: object
    ) -> list[str]:
        from _pytest._io.saferepr import saferepr, saferepr_unlimited
        from _pytest.assertion.util import assertrepr_compare

        verbose = config.get_verbosity(pytest.Config.VERBOSITY_ASSERTIONS)
        if verbose > 1:
            repr_: Callable[[Any], str] = saferepr_unlimited
        else:
            maxsize = (80 - 15 - len(op) - 2) // 2
            repr_ = partial(saferepr, maxsize=maxsize)

        summary = f"{repr_(left)} {op} {repr_(right)}"

        def subdict(sup: dict, sub: PartialDict) -> dict:
            return {k: v for k, v in sup.items() if k in sub}

        if isinstance(left, PartialDict):
            assert op == "<="
            assert isinstance(right, dict)
            res = assertrepr_compare(config, "==", left, subdict(right, left))
        else:
            assert op == ">="
            assert isinstance(right, PartialDict)
            assert isinstance(left, dict)
            res = assertrepr_compare(config, "==", subdict(left, right), right)

        assert res
        return [summary, *res[1:]]


def get_note[T: types.WKSubjectDataBase](subj: types.WKSubject[T]) -> WKNote:
    note = lazy.wk_col.get_note_for_subject(subj["id"])
    assert note
    return note


@contextmanager
def make_card_x(obj: Card | Note, *, save: bool = True) -> Generator[list[Card]]:
    cards: list[Card] = obj.cards() if isinstance(obj, Note) else [obj]
    yield cards

    if save:
        lazy.wk_col.col.update_cards(cards)


def make_card_new(obj: Card | Note, *, due: int | None = None, save: bool = True):
    with make_card_x(obj, save=save) as cards:
        for card in cards:
            card.type = CARD_TYPE_NEW
            card.queue = QUEUE_TYPE_NEW
            card.ivl = 0
            if due is not None:
                card.due = due


def make_card_learn(
    obj: Card | Note, *, due: datetime, ivl: int | None = None, save: bool = True
):
    with make_card_x(obj, save=save) as cards:
        for card in cards:
            card.type = CARD_TYPE_LRN
            card.queue = QUEUE_TYPE_LRN
            card.due = int(due.timestamp())
            if ivl is not None:
                card.ivl = ivl


def make_card_review(obj: Card | Note, *, ivl: int, due: int = 1, save: bool = True):
    with make_card_x(obj, save=save) as cards:
        for card in cards:
            card.type = CARD_TYPE_REV
            card.queue = QUEUE_TYPE_REV
            card.due = due
            card.ivl = ivl


def update_note(note: WKNote, **kwargs: Unpack[FieldDict]):
    for key, val in kwargs.items():
        note[key] = val
    lazy.wk_col.col.update_note(note)


class CardMatcher:
    """
    An assertion helper which returns true when compared against a Card object
    with the same ID as the one passed to the constructor.
    """
    def __init__(self, card: WKCard):
        self.card = card

    def __eq__(self, other: object):
        return isinstance(other, Card) and other.id == self.card.id


class NoteMatcher:
    """
    An assertion helper which returns true when compared against a Note object
    with the same ID as the one passed to the constructor.
    """
    def __init__(self, note: WKNote):
        self.note = note

    def __eq__(self, other: object):
        return isinstance(other, Note) and other.id == self.note.id


type Ease = Literal[1, 2, 3, 4]


@dataclass
class RevlogEntry:
    button_chosen: Ease
    time: float


@dataclass
class CardStats:
    revlog: list[RevlogEntry]


class MockRevlog:
    def __init__(self, col: Collection):
        self.card_stats = dict[int, CardStats]()
        self.patcher = mock.patch.object(col, "card_stats_data")
        self.mock = self.patcher.__enter__()
        self.mock.side_effect = self.get_stats

    def __enter__(self):
        return self

    def __exit__(self, exc_type: type, exc_val, tb) -> None:
        self.patcher.__exit__(exc_type, exc_val, tb)

    # It would be nice if we could append arbitrary args to forward_args, so
    # this could use something like @forward_args[Self, WKCard](RevlogEntry),
    # but that appears to be impossible. Adding a fixed number of args to the
    # beginning of the ParamSpec works, but concatenating a variable number of
    # args appears to be impossible, as does using the positional params from
    # one ParamSpec and the keyword args from another.
    def add_entry(
        self, card: WKCard | WKNote, button_chosen: Ease, time: float
    ) -> None:
        self.add_entries(card, [RevlogEntry(button_chosen=button_chosen, time=time)])

    def _cards(self, card: Card | Note) -> list[Card]:
        return [card] if isinstance(card, Card) else card.cards()

    def add_entries(
        self, card: WKCard | WKNote, entries: Iterable[RevlogEntry]
    ) -> None:
        for c in self._cards(card):
            stats = self.card_stats.setdefault(c.id, CardStats(revlog=[]))
            stats.revlog.extend(entries)

    def clear_entries(self, card: WKCard | WKNote):
        for c in self._cards(card):
            if stats := self.card_stats.get(c.id):
                stats.revlog.clear()

    def get_stats(self, card_id: int) -> CardStats | None:
        if stats := self.card_stats.get(card_id):
            return CardStats(list(stats.revlog))
        return CardStats([])


def cleanup_collection() -> None:
    lazy.wk_col.col.remove_notes(lazy.wk_col.find_notes())
    lazy.config._current_level = 1


def cleanup_after(scope: Literal["session", "package", "module", "class", "function"]):
    @pytest_asyncio.fixture(autouse=True, scope=scope)
    async def fixture():
        yield
        await pending_ops_complete()
        cleanup_collection()

    return fixture


async def pending_ops_complete():
    from .conftest import aqt

    with step("Wait for pending ops"):
        await aqt.mw.taskman.pending_ops_completed()


@overload
def open_fixture(name: str, mode: Literal["r"]) -> IO[str]: ...


@overload
def open_fixture(name: str, mode: Literal["rb"]) -> IO[bytes]: ...


def open_fixture(name: str, mode: Literal["r", "rb"]):
    res = importlib.resources.files("tests")
    file = res / "fixtures" / name
    return file.open(mode)


def read_fixture_json(name: str) -> object:
    with open_fixture(name, "r") as f:
        return json.load(f)


class saving_attr[T]:
    """
    >>> class Foo:
    ...     foo = 42

    >>> foo = Foo()

    >>> with saving_attr(foo, "foo"):
    ...     foo.foo = 12
    ...     foo.foo
    12

    >>> foo.foo
    42

    >>> with saving_attr(foo, "foo") as val:
    ...     val
    42
    """
    def __init__(self, obj: object, attr: str):
        self._obj = obj
        self._attr = attr
        self._orig: T = getattr(obj, attr)

    def __enter__(self) -> T:
        return self._orig

    def __exit__(self, exc_type: type, exc_value, traceback) -> None:
        setattr(self._obj, self._attr, self._orig)


class SaveAttr:
    """
    >>> class Foo:
    ...     foo = 42
    ...     bar = 12

    >>> foo = Foo()

    >>> with SaveAttr() as save:
    ...     save(foo, "foo")
    ...     save(foo, "bar")
    ...     foo.foo = 1
    ...     foo.bar = 2
    ...     foo.foo, foo.bar
    (1, 2)

    >>> foo.foo, foo.bar
    (42, 12)
    """
    def __init__(self):
        self.saved = list[tuple[object, str, Any]]()

    def __call__(self, obj: object, attr: str):
        self.saved.append((obj, attr, getattr(obj, attr)))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type, exc_value, traceback) -> None:
        for obj, attr, val in self.saved:
            setattr(obj, attr, val)


class Step:
    def __init__(self, name: str):
        self.name = name

    def __call__[**P, R](self, fn: Callable[P, R]) -> Callable[P, R]:
        return fn

    def __enter__(self) -> None:
        pass

    def __exit__(self, exc_type: type, exc_val, traceback) -> None:
        pass


def step_stub(name: str) -> Step:
    return Step(name)


def get_dist_fixtures() -> Path:
    import ankiwanikanisync

    dist = Path(ankiwanikanisync.__file__).resolve().parent.parent

    fixtures = dist / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    return fixtures


@step("Write fixtures")
def write_fixtures(mod: str, test: str) -> None:
    from ankiwanikanisync.collection import wk_col

    res = dict[str, dict[str, dict[str, str | object]]]()
    for nid in wk_col.find_notes():
        note = wk_col.get_note(nid)
        note_type = note["Card_Type"].lower()

        fields = dict[str, str | object]()
        for k, v in note.items():
            fields[k] = json.loads(v) if k in wk_col.JSON_FIELDS else v

        res.setdefault(note_type, {})[note["Characters"]] = fields

    fixtures = get_dist_fixtures()

    fn = f"{mod}.{test}.json"
    with (fixtures / fn).open("w") as f:
        json.dump(res, f, ensure_ascii=False, indent=4)


async def sync_subjects():
    with step("Sync subjects"):
        await lazy.sync.do_sync()
