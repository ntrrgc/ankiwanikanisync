from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aqt import mw
from aqt.qt import QTimer

# Note: We have an import cycle with the sync module
from . import sync
from .config import config
from .promise import Promise


class Timers:
    def __init__(self):
        self.submit_reviews_timer = QTimer(mw)
        self.submit_reviews_timer.setSingleShot(True)
        self.submit_reviews_timer.timeout.connect(self.submit_reviews_timeout)

        self.submit_lessons_timer = QTimer(mw)
        self.submit_lessons_timer.timeout.connect(self.submit_lessons_timeout)

        self.sync_due_timer = QTimer(mw)
        self.sync_due_timer.timeout.connect(self.sync_due_timeout)

    def start_timers(self):
        delta = timedelta(**config.SYNC_INTERVAL_LESSONS)
        self.submit_lessons_timer.start(int(delta.total_seconds() * 1000))

        delta = timedelta(**config.SYNC_INTERVAL_DUE)
        self.sync_due_timer.start(int(delta.total_seconds() * 1000))

        self.start_reviews_timer()

    def stop_timers(self):
        self.submit_lessons_timer.stop()
        self.sync_due_timer.stop()
        self.submit_reviews_timer.stop()

    def submit_reviews_at(self, time: datetime):
        now = datetime.now(timezone.utc)
        remaining = self.submit_reviews_timer.remainingTime()
        if remaining < 0 or time < now + timedelta(milliseconds=remaining):
            self.submit_reviews_timer.start(int((time - now).total_seconds() * 1000))

    @Promise.wrap
    async def start_reviews_timer(self):
        time = await sync.SyncOp().get_next_assignment_available_op()
        self.submit_reviews_at(time)

    def submit_reviews_timeout(self):
        sync.SyncOp().upstream_available_assignments_op(reviews=True, lessons=False)
        self.start_reviews_timer()

    def sync_due_timeout(self):
        sync.SyncOp().update_intervals()

    @Promise.wrap
    async def submit_lessons_timeout(self):
        timestamp = await sync.SyncOp().upstream_available_assignments_op(
            reviews=False,
            lessons=True,
            updated_after=config._last_lessons_sync,
        )

        config._last_lessons_sync = timestamp.isoformat()


timers = Timers()
