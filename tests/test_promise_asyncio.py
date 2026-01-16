from __future__ import annotations

from unittest import mock
from unittest.mock import Mock

import pytest

from ankiwanikanisync.promise import Promise
from ankiwanikanisync.promise_asyncio import AsyncIOScheduler, StubHandle


@pytest.mark.asyncio
async def test_promise_asyncio_call_soon():
    sched = Promise.scheduler
    assert isinstance(sched, AsyncIOScheduler)

    mock_cb = Mock()
    sched.call_soon(mock_cb)

    assert not mock_cb.called

    await Promise.resolve()

    assert mock_cb.called


@pytest.mark.asyncio
async def test_promise_asyncio_call_soon_cancel():
    with mock.patch("threading.current_thread"):
        sched = Promise.scheduler
        assert isinstance(sched, AsyncIOScheduler)

        mock_cb = Mock()

        canc = sched.call_soon(mock_cb)
        assert isinstance(canc, StubHandle)
        assert not canc.cancelled()

        canc.cancel()
        assert canc.cancelled()

        await Promise.resolve()

        assert not mock_cb.called
