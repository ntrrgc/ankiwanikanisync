# ruff: noqa: RUF029
from __future__ import annotations

import asyncio
import gc
import unittest.mock
from typing import Any, Awaitable, Never
from unittest.mock import MagicMock

import pytest

from ankiwanikanisync.promise import (
    CancellationError,
    CancelledError,
    Promise,
    PromiseFulfilledOutcome,
    PromiseRejectedOutcome,
    ResFn,
)


async def test_promise_resolve():
    result = await Promise.resolve(42)
    assert result == 42


async def test_promise_reject():
    with pytest.raises(ValueError):
        await Promise.reject(ValueError())

    @Promise
    def promise(resolve, reject):
        reject(ValueError("12"))
        reject(ValueError("13"))

    with pytest.raises(ValueError, match="12"):
        await promise


async def test_promise_resolve_callback():
    @Promise[int]
    def promise(resolve: ResFn[int], reject: ResFn):
        resolve(42)

    result = await promise
    assert result == 42


async def test_promise_reject_callback():
    @Promise[int]
    def promise(resolve: ResFn[int], reject: ResFn):
        reject(ValueError)

    with pytest.raises(ValueError):
        await promise


async def test_promise_then_resolve():
    @Promise
    def promise(resolve: ResFn[int], reject: ResFn):
        @Promise.resolve(42).then
        def promise2(val: int):
            resolve(val)

    result = await promise
    assert result == 42


async def test_promise_then_reject():
    @Promise
    def promise(resolve: ResFn, reject: ResFn):
        def on_reject(val):
            reject(val)

        Promise.reject(ValueError()).then(None, on_reject)

    with pytest.raises(ValueError):
        await promise


async def test_promise_catch():
    @Promise
    def promise(resolve: ResFn, reject: ResFn):
        @Promise.reject(ValueError()).catch
        def promise2(val):
            reject(val)

    with pytest.raises(ValueError):
        await promise


async def test_promise_all_resolve():
    result = await Promise.all(map(Promise.resolve, (1, 2, 3)))
    assert result == [1, 2, 3]


async def test_promise_all_reject():
    with pytest.raises(ValueError):
        await Promise.all(
            (
                Promise.resolve(1),
                Promise.reject(ValueError()),
                Promise(lambda resolve, reject: None),
            )
        )


async def test_promise_all_empty():
    result: list[Never] = await Promise.all([])
    assert result == []


async def test_promise_all_settled():
    error = ValueError(42)
    result = await Promise.all_settled(
        (
            Promise.resolve(1),
            Promise.reject(error),
            Promise.resolve(3),
        )
    )
    assert result == [
        PromiseFulfilledOutcome(1),
        PromiseRejectedOutcome(error),
        PromiseFulfilledOutcome(3),
    ]
    assert PromiseFulfilledOutcome(1) != PromiseRejectedOutcome(1)
    assert PromiseRejectedOutcome(1) != PromiseFulfilledOutcome(1)


async def test_promise_race_resolved():
    result = await Promise.race(
        (
            Promise.resolve(42),
            Promise(lambda resolve, reject: None),
        )
    )
    assert result == 42


async def test_promise_race_rejected():
    with pytest.raises(ValueError):
        await Promise.race(
            (
                Promise.reject(ValueError()),
                Promise(lambda resolve, reject: None),
            )
        )


@Promise.wrap
async def async_func[T](val: Awaitable[T]) -> T:
    return await val


async def test_promise_wrap_promise_resolve():
    result = await async_func(Promise.resolve(42))
    assert result == 42


async def test_promise_wrap_promise_reject():
    with pytest.raises(ValueError):
        await async_func(Promise.reject(ValueError))


async def test_promise_wrap_cancel():
    promise = async_func(Promise(None))
    assert promise.cancel() is True

    with pytest.raises(CancellationError):
        await promise

    assert promise.cancel() is False


async def test_promise_wrap_cancel_catch_raise():
    @Promise.wrap
    async def async_func():
        try:
            await Promise(None)
        except CancelledError:
            raise ValueError()

    await Promise.resolve()

    promise = async_func()
    await Promise.resolve()
    promise.cancel()

    with pytest.raises(ValueError):
        await promise


async def test_promise_wrap_cancel_catch_return():
    @Promise.wrap
    async def async_func() -> int:
        try:
            await Promise(None)
        except CancelledError:
            return 42
        # FIXME: Zuban thinks this is unreachable
        return 43  # type: ignore

    promise = async_func()
    await Promise.resolve()
    promise.cancel()

    result = await promise
    assert result == 42


async def test_promise_wrap_never_awaited():
    @Promise
    def promise(resolve: ResFn[int], reject: ResFn):
        @Promise.wrap
        async def async_func() -> None:
            await Promise.resolve()
            resolve(42)

        async_func()

    result = await promise
    assert result == 42


@unittest.mock.patch.object(Promise, "report_error")
async def test_promise_unhandled_rejection_reported(report_error: MagicMock):
    gc.collect()
    report_error.reset_mock()

    error = ValueError(42)
    promise = Promise.reject(error)
    assert not report_error.called

    gc.collect()
    assert not report_error.called

    promise = None  # noqa: F841

    report_error.assert_called_once_with(error)


@unittest.mock.patch.object(Promise, "report_error")
async def test_promise_handled_rejection_not_reported(report_error: MagicMock):
    gc.collect()
    report_error.reset_mock()

    error = ValueError(42)
    promise = Promise.reject(error)
    assert not report_error.called

    promise.catch(lambda _: None)
    promise = None

    gc.collect()

    assert not report_error.called


async def test_promise_chain_reject_then_catch():
    error = ValueError(42)
    promise1 = Promise.reject(error)

    @promise1.then
    def promise2(val: Any):
        return None

    @promise2.catch
    def promise3(val: Exception):
        return val

    result = await promise3
    assert result is error


async def test_promise_chain_resolve_then_then():
    promise1 = Promise.resolve(42)

    @promise1.then
    def promise2(val: int):
        return val + 13

    @promise2.then
    def promise3(val: int):
        return val + 7

    result = await promise3
    assert result == 62


async def test_promise_chain_resolve_catch():
    promise1 = Promise.resolve(42)

    @promise1.catch
    def promise2(val: int):
        return 43

    result = await promise2
    assert result == 42


async def test_promise_then_raises():
    @Promise.resolve(42).then
    def promise(val: int):
        raise ValueError(42)

    with pytest.raises(ValueError):
        await promise


async def test_promise_catch_raises():
    @Promise.reject(Exception()).catch
    def promise(val: Any):
        raise ValueError(42)

    with pytest.raises(ValueError):
        await promise


async def test_promise_finally_resolved():
    @Promise.resolve(42).finally_
    def promise():
        pass

    result = await promise
    assert result == 42


async def test_promise_finally_resolved_rejects():
    @Promise.resolve(42).finally_
    def promise():
        return Promise.reject(ValueError())

    with pytest.raises(ValueError):
        await promise


async def test_promise_finally_resolved_raises():
    @Promise.resolve(42).finally_
    def promise():
        raise ValueError()

    with pytest.raises(ValueError):
        await promise


async def test_promise_finally_rejected():
    @Promise.reject(ValueError()).finally_
    def promise():
        pass

    with pytest.raises(ValueError):
        await promise


async def test_promise_finally_rejected_rejects():
    @Promise.reject(Exception()).finally_
    def promise():
        return Promise.reject(ValueError())

    with pytest.raises(ValueError):
        await promise


async def test_promise_finally_rejected_raises():
    @Promise.reject(Exception()).finally_
    def promise():
        raise ValueError()

    with pytest.raises(ValueError):
        await promise


async def test_promise_cb_raises():
    @Promise
    def promise(resolve: ResFn, reject: ResFn):
        raise ValueError(42)

    with pytest.raises(ValueError):
        await promise


async def test_promise_cancel_no_handler():
    promise = Promise[Any](None)
    promise.cancel()

    with pytest.raises(CancellationError):
        await promise


async def test_promise_cancel_handler():
    class vars:
        handler_called = False
        on_cancel_called = False

    def on_cancel():
        vars.on_cancel_called = True

    promise_w_r = Promise.with_resolvers[Any](on_cancel=on_cancel)

    @promise_w_r.promise.finally_
    def finally_():
        vars.handler_called = True

    finally_.catch(lambda _: None)

    promise_w_r.promise.cancel()
    assert vars.on_cancel_called

    for i in range(0, 5):
        await Promise.resolve()
        assert not vars.handler_called

    promise_w_r.reject(ValueError())
    with pytest.raises(ValueError):
        await promise_w_r.promise

    assert vars.handler_called


async def test_promise_cancel_handler_raises():
    def on_cancel():
        raise ValueError()

    promise = Promise[Any](None, on_cancel)
    promise.cancel()

    with pytest.raises(ValueError):
        await promise


async def test_promise_CancelledError_becomes_CancellationError():
    error = CancelledError()
    with pytest.raises(CancellationError) as exc_info:
        await Promise.reject(error)

    assert exc_info.value.__cause__ is error

    err = await Promise.reject(CancelledError()).catch(lambda err: err)
    assert isinstance(err, CancellationError)
    assert err.__traceback__


@pytest.mark.asyncio
async def test_promise_future_interface():
    assert Promise.resolve(None).done()
    assert Promise.reject(None).done()

    with pytest.raises(ValueError):
        Promise.reject(ValueError(12)).exception()

    promise = Promise(lambda a, b: None, lambda: None)
    assert not promise.done()
    assert not promise.cancelled()

    with pytest.raises(asyncio.InvalidStateError):
        promise.result()

    promise.cancel()
    assert promise.done()
    assert promise.cancelled()
    with pytest.raises(asyncio.CancelledError):
        promise.exception()

    with pytest.raises(asyncio.CancelledError):
        promise.result()

    assert Promise.resolve(42).exception() is None

    assert Promise.wrap(promise) is promise

    future = asyncio.get_event_loop().create_future()
    future.set_exception(ValueError())

    with pytest.raises(ValueError):
        await Promise.wrap(future)

    future = asyncio.get_event_loop().create_future()
    Promise.wrap(future).cancel()

    with pytest.raises(asyncio.CancelledError):
        await future
