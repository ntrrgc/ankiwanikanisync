from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps
from typing import (
    Any,
    Callable,
    Final,
    Generator,
    Never,
    ParamSpec,
    Sequence,
    TypeVar,
    overload,
)

from aqt import mw
from aqt.operations import CollectionOp, QueryOp, ResultWithChanges
from aqt.utils import tooltip

from .promise import Promise, ResFn

QP = ParamSpec("QP")
QR = TypeVar("QR")


# When fetching objects from WaniKani by lists of IDs, break requests into
# chunks of this size.
CHUNK_SIZE: Final = 1024


def chunked[T](
    seq: Sequence[T], /, chunk_size: int = CHUNK_SIZE
) -> Generator[tuple[int, Sequence[T]], None, None]:
    """
    >>> list(chunked([1, 2, 3, 4, 5], chunk_size=2))
    [(0, [1, 2]), (2, [3, 4]), (4, [5])]
    """
    for i in range(0, len(seq), chunk_size):
        yield i, seq[i : i + chunk_size]


def maybe_chunked[T](
    desc: str, seq: Sequence[T] | None, /, chunk_size: int = CHUNK_SIZE
) -> Generator[Sequence[T] | None, None, None]:
    """
    >>> list(maybe_chunked("", [1, 2, 3, 4, 5], chunk_size=2))
    [[1, 2], [3, 4], [5]]

    >>> list(maybe_chunked("", None, chunk_size=2))
    [None]
    """

    if seq is None:
        report_progress(f"Fetching all {desc}...", 0, 0)
        yield None
    else:
        for i in range(0, len(seq), chunk_size):
            chunk = seq[i : i + chunk_size]
            report_progress(
                f"Fetching {desc} {i}-{i + len(chunk) - 1}/{len(seq)}...", i, len(seq)
            )
            yield chunk


def assert_unreachable(msg: str = "Unreachable") -> Never:
    assert False, msg


@overload
def query_op(
    *, with_progress: bool = False, without_collection=False
) -> Callable[[Callable[QP, QR]], Callable[QP, Promise[QR]]]: ...


@overload
def query_op(func: Callable[QP, QR], /) -> Callable[QP, Promise[QR]]: ...


def query_op(
    func: Callable[..., Any] | None = None,
    /,
    *,
    with_progress: bool = False,
    without_collection=False,
):
    def decorator(func: Callable[QP, QR], /) -> Callable[QP, Promise[QR]]:
        @wraps(func)
        def wrapper(*args, **kwargs):
            @Promise
            def promise(resolve: ResFn, reject: ResFn):
                query_op = QueryOp(
                    parent=mw,
                    op=lambda _: func(*args, **kwargs),
                    success=resolve,
                )
                query_op.failure(reject)
                if without_collection:
                    query_op.without_collection()
                if with_progress:
                    query_op.with_progress()
                query_op.run_in_background()
            return promise

        return wrapper

    if func:
        return decorator(func)
    return decorator


def collection_op(
    func: Callable[QP, ResultWithChanges],
) -> Callable[QP, Promise[ResultWithChanges]]:
    @wraps(func)
    def wrapper(*args: QP.args, **kwargs: QP.kwargs):
        @Promise[ResultWithChanges]
        def promise(resolve: ResFn[ResultWithChanges], reject: ResFn):
            op = CollectionOp(
                mw,
                lambda _: func(*args, **kwargs),
            )
            op.success(resolve)
            op.failure(reject)
            op.run_in_background()
        return promise

    return wrapper


def compose[FRT, **GP, GRT](
    f: Callable[[GRT], FRT], g: Callable[GP, GRT]
) -> Callable[GP, FRT]:
    def composed(*args: GP.args, **kwargs: GP.kwargs) -> FRT:
        return f(g(*args, **kwargs))

    composed.__name__ = f"{f.__name__}∘{g.__name__}"
    composed.__qualname__ = f"{f.__qualname__}∘{g.__qualname__}"
    if False:
        # This might be nice in some limited use cases, but probably isn't
        # worth the computational cost of copying the __annotations__ dict
        # most of the time.
        composed.__type_params__ = g.__type_params__ # type: ignore
        composed.__annotations__ = dict(g.__annotations__)
        composed.__annotations__["return"] = f.__annotations__["return"]
    return composed


def wknow():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def wkparsetime(txt):
    return datetime.fromisoformat(txt.replace("Z", "+00:00"))


def report_progress(txt, val, max):
    mw.taskman.run_on_main(lambda: mw.progress.update(label=txt, value=val, max=max))


def show_tooltip(txt, period=3000): # pragma: no cover
    mw.taskman.run_on_main(lambda: tooltip(txt, period=period))
