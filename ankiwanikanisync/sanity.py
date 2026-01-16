# ruff: noqa: RUF029
from __future__ import annotations

from collections.abc import Awaitable
from typing import (  # noqa: F401
    Any,
    Callable,
    Generator,
    Protocol,
    assert_type,
    cast,
    overload,
    reveal_type,
)

from anki.collection import OpChangesWithCount

from .promise import HandlerFn, Promise, PromiseOutcome, ResFn
from .utils import collection_op, query_op


@query_op
def query_str_int(foo: str, /) -> int:
    return 42


assert_type(query_str_int, Callable[[str], Promise[int]])


@query_op(without_collection=True)
def query_str_int_2(foo: str, /) -> int:
    return 42


assert_type(query_str_int_2, Callable[[str], Promise[int]])


@collection_op
def col_op_str(foo: str, /) -> OpChangesWithCount:
    return OpChangesWithCount()


assert_type(col_op_str, Callable[[str], Promise[OpChangesWithCount]])


@Promise.wrap
async def foo_str_int(foo: str, /) -> int:
    return 42


@Promise.wrap
async def foo_int() -> int:
    return 42


assert_type(foo_str_int, Callable[[str], Promise[int]])


class AssertCompatible[T]:
    def __init__(self, p: T) -> None:
        pass


class Compatible:
    pass


class Incompatible:
    pass


class CheckCompatible[T]:
    @overload
    def result(self, p: T) -> Compatible: ...

    @overload
    def result(self, p: object) -> Incompatible: ...

    def result(self, p: Any) -> Any:
        pass


@Promise[int]
def promise(resolve: ResFn[int], reject: ResFn):
    pass


assert_type(promise, Promise[int])

AssertCompatible[Callable[[HandlerFn[int, None], HandlerFn[Any, None]], Promise[None]]](
    promise.then
)
AssertCompatible[Callable[[HandlerFn[int, None]], Promise[None]]](promise.then)
AssertCompatible[Callable[[None, HandlerFn[Any, None]], Promise[int | None]]](
    promise.then
)

AssertCompatible[Callable[[HandlerFn[int, str]], Promise[str]]](promise.then)
AssertCompatible[Callable[[None, HandlerFn[Any, str]], Promise[int | str]]](
    promise.then
)
AssertCompatible[Callable[[HandlerFn[int, str], HandlerFn[Any, str]], Promise[str]]](
    promise.then
)
AssertCompatible[Callable[[HandlerFn[int, None], HandlerFn[Any, str]], Promise[Any]]](
    promise.then
)

AssertCompatible[Callable[[HandlerFn[int, Promise[str]]], Promise[str]]](promise.then)
AssertCompatible[Callable[[None, HandlerFn[int, Promise[str]]], Promise[int | str]]](
    promise.then
)

assert_type(
    CheckCompatible[Callable[[HandlerFn[int, str]], Promise[str]]]().result(
        promise.then
    ),
    Compatible,
)
assert_type(
    CheckCompatible[Callable[[HandlerFn[str, str]], Promise[str]]]().result(
        promise.then
    ),
    Incompatible,
)


def handler(arg: int) -> str:
    return "foo"


assert_type(promise.then(handler), Promise[str])
assert_type(promise.then(handler, lambda _: "foo"), Promise[str])
assert_type(promise.then(None, lambda _: _), Promise[int | Any])


def handler2(arg: int) -> Promise[str]:
    return cast(Promise[str], None)


assert_type(promise.then(handler2), Promise[str])
assert_type(promise.then(handler2, lambda _: cast(Promise[str], None)), Promise[str])


@Promise.resolve(42).then
def promise_resolve_handler(result: int) -> None:
    pass


assert_type(Promise.resolve(42), Promise[int])
assert_type(Promise.all([promise]), Promise[list[int]])
assert_type(Promise.race([promise]), Promise[int])
assert_type(Promise.all_settled([promise]), Promise[list[PromiseOutcome[int]]])


@Promise.all([promise]).then
def promise_all_handler(results: list[int]) -> None:
    pass


@Promise.race([promise]).then
def promise_race_handler(result: int) -> None:
    pass


@Promise.all_settled([promise]).then
def handle_all_settled(outcomes: list[PromiseOutcome[int]]) -> None:
    if outcomes[0].status == "fulfilled":
        assert_type(outcomes[0].value, int)
    else:
        assert_type(outcomes[0].reason, Any)


@Promise.wrap
async def wrapped_str_int(foo: str, /) -> int:
    return 42


assert_type(wrapped_str_int, Callable[[str], Promise[int]])


async def async_int() -> int:
    return 42


assert_type(Promise.from_awaitable(async_int()), Promise[int])

AssertCompatible[Awaitable[int]](Promise.resolve(42))

assert_type(Promise.resolve(42).__await__(), Generator[Promise[int], int, int])
