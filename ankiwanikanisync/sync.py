from __future__ import annotations

import contextlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from enum import IntEnum, auto
from typing import Literal, NamedTuple

import requests.exceptions
from anki.cards import Card
from anki.collection import OpChangesWithCount, SearchNode
from anki.consts import (
    CARD_TYPE_LRN,
    CARD_TYPE_NEW,
    CARD_TYPE_REV,
    QUEUE_TYPE_LRN,
    QUEUE_TYPE_REV,
)
from anki.notes import NoteId
from aqt import gui_hooks, mw
from aqt.reviewer import Reviewer

from .collection import (
    WKCard,
    WKNote,
    note_is_guru,
    note_is_wk,
    wk_col,
)
from .config import config
from .importer import ensure_deck, ensure_notes, sort_new_cards
from .promise import Promise
from .timers import timers
from .types import (
    DateString,
    SubjectId,
    WKAssignment,
    WKAssignmentData,
    WKAssignmentsResponse,
    WKStudyMaterialData,
    WKSubject,
)
from .utils import (
    chunked,
    collection_op,
    maybe_chunked,
    query_op,
    report_progress,
    show_tooltip,
    wknow,
    wkparsetime,
)
from .wk_api import (
    WKAssignmentsQuery,
    WKReviewDataReview,
    WKStudyMaterialsQuery,
    WKSubjectsQuery,
    is_WKAmalgumData,
    is_WKComponentData,
    is_WKKanjiData,
    wk,
)


def get_available_subject_ids() -> list[SubjectId]:
    query = WKAssignmentsQuery(unlocked=True, hidden=False)

    if last_sync := config._last_assignments_sync:
        query["updated_after"] = last_sync

    report_progress("Fetching unlocked assignments...", 0, 0)

    # FIXME: This should be set after the entire operation succeeds.
    config._last_assignments_sync = wknow()

    assignments = wk.query("assignments", query)["data"]

    return [assignment["data"]["subject_id"] for assignment in assignments]


def fetch_subjects_internal(
    id_str,
    ids: Sequence[SubjectId] | None = None,
    last_sync: str | None = None,
    max_lvl: int = 3,
) -> dict[SubjectId, WKSubject]:
    subjects = {}
    for chunk in maybe_chunked(f"{id_str} subjects", ids):
        query = WKSubjectsQuery(levels=range(max_lvl + 1))
        if chunk:
            query["ids"] = chunk
        if last_sync:
            query["updated_after"] = last_sync

        for subject in wk.query("subjects", query)["data"]:
            subjects[subject["id"]] = subject

    return subjects


def fetch_study_mats_internal(
    subject_ids: None | list[SubjectId] = None, last_sync: str | None = None
) -> dict[int, WKStudyMaterialData]:
    study_mats = {}
    for chunk in maybe_chunked("study materials", subject_ids):
        query = WKStudyMaterialsQuery(hidden=False)
        if last_sync:
            query["updated_after"] = last_sync
        if chunk:
            query["subject_ids"] = chunk

        for mat in wk.query("study_materials", query)["data"]:
            study_mats[mat["data"]["subject_id"]] = mat["data"]

    return study_mats


def fetch_subjects(
    subject_ids: None | Sequence[SubjectId] = None,
    existing_subject_ids: set[SubjectId] = set(),
    max_lvl: int = 3,
):
    last_sync = config._last_subjects_sync

    dt = None if subject_ids else last_sync
    subjects = fetch_subjects_internal("Main", subject_ids, dt, max_lvl)
    study_mats = fetch_study_mats_internal(last_sync=last_sync)
    study_subj_ids = set(study_mats.keys())

    if subject_ids:
        # We don't want to fetch subjects we wouldn't fetch already, so if
        # we're not fetching all subjects, only keep study mat subjects if
        # they're in either of the two other lists.
        study_subj_ids &= set(subject_ids) | existing_subject_ids

        # If the previous fetch did not already fetch all subjects anyway,
        # fetch more specific ones.
        ids = existing_subject_ids - set(subjects.keys())
        subjects.update(
            fetch_subjects_internal("Existing", list(ids), last_sync, max_lvl)
        )

    # If the main fetch did not fetch absolutely _all_ subjects, fetch the
    # ones that had study material updates.
    if last_sync or subject_ids:
        # Only updated or new study material subject ids are in this list, do
        # not apply last_sync.
        ids = study_subj_ids - set(subjects.keys())
        subjects.update(
            fetch_subjects_internal("Custom Study", list(ids), None, max_lvl)
        )

    # If we did not sync for the first time, we need to fetch study materials
    # again. Subjects might have gotten updated, where the corresponding study
    # material did not.
    if last_sync:
        # Construct a set of all subjects we fetched, minus the ones of the
        # study mats we already fetched.
        new_study_mat_subjs = set(subject_ids or ())
        new_study_mat_subjs.update(existing_subject_ids)
        new_study_mat_subjs -= study_subj_ids

        study_mats.update(fetch_study_mats_internal(list(new_study_mat_subjs)))

    report_progress("Done fetching subjects...", 0, 0)

    return list(subjects.values()), study_mats


def fetch_related_subjects(subjects: Sequence[WKSubject]) -> dict[SubjectId, WKSubject]:
    related_subject_ids = set[SubjectId]()
    for subject in subjects:
        data = subject["data"]
        if is_WKComponentData(data):
            related_subject_ids.update(data["amalgamation_subject_ids"])
        if is_WKAmalgumData(data):
            related_subject_ids.update(data["component_subject_ids"])
        if is_WKKanjiData(data):
            related_subject_ids.update(data["visually_similar_subject_ids"])

    # Collect subjects which are in the already fetched list
    related_subjects = dict[SubjectId, WKSubject]()
    for subj in subjects:
        if subj["id"] in related_subject_ids:
            related_subjects[subj["id"]] = subj

    for subj_id, note in wk_col.find_notes_for_subjects(
        list(related_subject_ids)
    ).items():
        with contextlib.suppress(json.decoder.JSONDecodeError):
            related_subjects[subj_id] = json.loads(note["raw_data"])

    # Download missing ones from WK
    related_subject_ids -= set(related_subjects.keys())
    related_subjects.update(
        fetch_subjects_internal("sub-subjects", list(related_subject_ids), max_lvl=60)
    )

    report_progress("Done fetching sub-subjects...", 0, 0)

    return related_subjects


type Ease = Literal[1, 2, 3, 4]
type EaseTuple = tuple[bool, Ease]


class ReviewHandler:
    was_guru = NoteId(0), False

    def __init__(self) -> None:
        gui_hooks.reviewer_will_answer_card.append(self.will_answer_card)
        gui_hooks.reviewer_did_answer_card.append(self.did_answer_card)

    def will_answer_card(
        self, ease_tuple: EaseTuple, reviewer: Reviewer, card_: Card
    ) -> EaseTuple:
        # Have the type checker treat the card as a WKCard so that its dict
        # fields can be validated.
        card = WKCard.cast(card_)

        if note_is_wk(card.note()):
            self.was_guru = card.nid, note_is_guru(card.note())

        return ease_tuple

    def did_answer_card(self, reviewer: Reviewer, card_: Card, ease: Ease) -> None:
        # Have the type checker treat the card as a WKCard so that its dict
        # fields can be validated.
        card = WKCard.cast(card_)

        if not note_is_wk(card.note()):
            return  # pragma: no cover

        # If the card just reached guru status, update the status of cards
        # that depend on it, and check whether the current level has reached
        # completion.
        if self.was_guru != (card.nid, True) and note_is_guru(card.note()):
            wk_col.update_dependents(card.note())
            if int(card.note()["Level"]) == config._current_level:
                wk_col.update_current_level_op()

        # If no cards for this card's note are currently due, attempt to sync
        # the review upstream.
        if not wk_col.find_notes(SearchNode(nid=card.nid), "is:due"):
            SyncOp().upstream_review_op(card.note())


review_handler = ReviewHandler()


class Assignment:
    def __init__(self, assignment: WKAssignment, subject: WKSubject):
        self.assignment = assignment
        self.subject = subject

        self.srs = wk.get_srs(subject["data"]["spaced_repetition_system_id"])
        self.srs_stage = self.srs.stages[self.data["srs_stage"]]

        self.available_at = (
            datetime.fromisoformat(self.data["available_at"])
            if self.data["available_at"]
            else None
        )

        assert assignment["data_updated_at"]
        self.data_updated_at = wkparsetime(assignment["data_updated_at"])

        # This is basically a best-effort approximation, since WaniKani no
        # longer provides actual records of past reviews.
        self.last_review_time = (
            self.available_at - self.srs_stage.interval
            if self.available_at and self.srs_stage.interval
            else None
        )

    @property
    def id(self) -> int:
        return self.assignment["id"]

    @property
    def data(self) -> WKAssignmentData:
        return self.assignment["data"]


def ts_to_datetime(ts):
    return datetime.fromtimestamp(ts).astimezone()


class Reason(IntEnum):
    LAST_REVIEW_AFTER_WK_AVAILABLE = auto()
    NO_WK_REVIEWS = auto()
    NEXT_ANKI_DUE_AFTER_NEXT_WK_DUE = auto()
    SUBSEQUENT_ANKI_DUE_AFTER_NEXT_WK_DUE = auto()


class SyncOp(object):
    """"""

    # The amount of fuzz to add to time stamps when determining whether the
    # last review came from Anki or WaniKani. A few seconds should be
    # sufficient, but a conservative hour is safer, especially given that
    # WaniKani requires a minimum of an hour between successive reviews.
    FUZZ = timedelta(hours=1)

    def __init__(self) -> None:
        self.subjects: dict[SubjectId, WKSubject] = {}

    def get_subject(self, subject_id: SubjectId) -> WKSubject:
        """
        Returns the subject for the given ID. If the subject has already been
        fetched, returns the cached copy. If there is an existing Note with
        the subject data, that data is returned. Otherwise, it is fetched
        from WaniKani.
        """
        if subject_id not in self.subjects:
            if note := wk_col.get_note_for_subject(subject_id):
                with contextlib.suppress(json.decoder.JSONDecodeError):
                    self.subjects[subject_id] = json.loads(note["raw_data"])
            if subject_id not in self.subjects:
                self.subjects[subject_id] = wk.api_req("subjects", subject_id)
        return self.subjects[subject_id]

    def fetch_subjects(self, subject_ids: Iterable[SubjectId]) -> None:
        """
        Pre-fetch subjects with the given IDs and store them in
        `self.subjects`. Any subjects with existing Notes will use the cached
        data from the Note. Any others will be fetched from WaniKani.
        """
        subjs = {id_ for id_ in subject_ids if id_ not in self.subjects}
        for id_, note in wk_col.find_notes_for_subjects(list(subjs), True).items():
            with contextlib.suppress(json.decoder.JSONDecodeError):
                self.subjects[id_] = json.loads(note["raw_data"])
                subjs.discard(id_)

        for i, chunk in chunked(list(subjs)):
            result = wk.query("subjects", WKSubjectsQuery(ids=chunk))
            for subj in result["data"]:
                self.subjects[subj["id"]] = subj

    @query_op
    def fetch_assignments_op(self, query: WKAssignmentsQuery) -> WKAssignmentsResponse:
        """
        Fetches assignments for the given query and pre-fetches any related
        subjects.
        """
        resp = wk.query("assignments", query)

        self.fetch_subjects(
            assignment["data"]["subject_id"] for assignment in resp["data"]
        )

        return resp

    def maybe_sync_downstream(self, card: WKCard, assignment: Assignment) -> bool:
        """
        Syncs the review due time and interval from WaniKani if it seems
        appropriate.

        Generally:
            - Any card which has been reviewed on WaniKani but is New in Anki
              will take its due date an interval from WaniKani.
            - Any card with a longer interval in WaniKani will take is
              interval from WaniKani
            - Any card with a later due date in WaniKani will take its due
              date from WaniKani.
            - Any card with an interval of one day or longer in WaniKani will
              become a review card. Any non-review card with an interval of
              less than one day on WaniKani will become a Learning card.
        """
        # Don't try to sync assignments that haven't been reviewed upstream
        if not assignment.last_review_time:
            return False

        # Don't try to sync assignments that had their last reviews synced
        # from Anki
        if last_upstream_sync := card.note()["last_upstream_sync_time"]:
            # `last_review_time` is a best effort guess based on the
            # assignment's available timestamp and interval. It may not be
            # very accurate. Likewise, its update timestamp will definitely
            # have been updated by the last review, but it also may have been
            # updated by changes to the assignment's subject. So, reject the
            # card if either of these timestamps came before our last upstream
            # sync.
            dt = datetime.fromisoformat(last_upstream_sync) + self.FUZZ
            if dt >= assignment.last_review_time or dt >= assignment.data_updated_at:
                return False

        # At this point, we've already rejected assignments that haven't been
        # reviewed, so everything should have an SRS interval and an available
        # time.
        stage = assignment.srs_stage
        assert assignment.available_at
        assert stage.interval

        changed = False
        is_review = card.type == CARD_TYPE_REV
        if stage.interval.days >= 1:
            # If the review interval on WaniKani is a day or longer, make the
            # card a review card locally.
            if not is_review:
                card.type = CARD_TYPE_REV
                card.queue = QUEUE_TYPE_REV
                changed = True

            # If the card is not already a review card or WaniKani's interval
            # is greater than Anik's, take WaniKani's interval
            if not is_review or card.ivl <= stage.interval.days:
                card.ivl = int(stage.interval.days)
                changed = True

            # If the card is not a review card and WaniKani's due time is
            # greater than ours, take WaniKani's due time
            # Note: For review cards, card.due is the number of days since the
            # day the scheduler was first initiated.
            due = (
                wk_col.col.sched.today
                + (assignment.available_at - datetime.now(timezone.utc)).days
                + 1
            )
            if not is_review or due > card.due:
                card.due = due
                card.last_review_time = int(assignment.last_review_time.timestamp())
                changed = True
        elif not is_review:
            # If the card not a review card and WaniKani's interval is less
            # than one day, make it a learning card locally.
            is_learn = card.type == CARD_TYPE_LRN

            if not is_learn:
                card.type = CARD_TYPE_LRN
                card.queue = QUEUE_TYPE_LRN
                changed = True

            # If the card is not a learning card, or WaniKani's review time is
            # later than Anik's, use WaniKani's due time.
            # Note: For learning cards, card.due is a timestamp in seconds
            # since the epoch.
            due = int(assignment.available_at.timestamp())
            if not is_learn or due > card.due:
                card.due = due
                changed = True
        return changed

    @query_op
    def get_next_assignment_available_op(self) -> datetime:
        """
        Returns the time when the next assignment will be available for review
        on WaniKani within the time period defined by
        `config.SYNC_INTERVAL_REVIEWS_MAX`. If no reviews are available in
        that interval, the timestamp of the end of that interval is returned.
        """
        now = datetime.now(timezone.utc)
        max_ivl = now + timedelta(**config.SYNC_INTERVAL_REVIEWS_MAX)

        query = WKAssignmentsQuery(available_after=now, available_before=max_ivl)
        resp = wk.query("assignments", query)

        subject_ids = [a["data"]["subject_id"] for a in resp["data"]]

        self.fetch_subjects(subject_ids)
        notes = wk_col.find_notes_for_subjects(subject_ids)

        assignments = [
            Assignment(assignment, self.get_subject(assignment["data"]["subject_id"]))
            for assignment in resp["data"]
        ]

        dates = list[datetime]()
        for assignment in assignments:
            assert assignment.available_at
            if (
                note := notes.get(assignment.data["subject_id"])
            ) and self.should_sync_upstream(note, assignment, assignment.available_at):
                dates.append(assignment.available_at)

        return min(dates) if dates else max_ivl

    def should_sync_upstream(
        self, note: WKNote, assignment: Assignment, as_of: datetime
    ) -> dict[str, int] | None:
        """
        Determines whether the review status of the given note should be
        synced upstream to WaniKani. If it should, returns a dict containing
        the number of lapses for each card type, and a "timestamp" key
        containing the timestamp that should be used to create the review.
        """
        if assignment.data["burned_at"]:
            return None

        stage = assignment.srs_stage

        if assignment.available_at and assignment.available_at > as_of:
            return None

        class DueDate(NamedTuple):
            due_date: datetime
            ivl: int

        avail_ts = (assignment.available_at or as_of).timestamp()
        review_ts = 0

        result: dict[str, int] = {}
        due_dates: list[DueDate] = []
        reasons = list[Reason]()
        for card in note.cards():
            # Don't attempt an upstream sync for any new cards
            if card.type == CARD_TYPE_NEW:
                return None

            # Skip any notes with cards without any logged reviews
            stats = wk_col.col.card_stats_data(card.id)
            if not stats.revlog:
                return None

            reviews = sorted(stats.revlog, key=lambda r: r.time, reverse=True)
            # Find the timestamp of the first review completed after the
            # assignment became available.
            # TODO: Use the available_at timestamp if we would have submitted
            # an earlier upstream review had we been able.
            ts = 0
            for review in reviews:
                if review.time < avail_ts:
                    break
                if review.button_chosen >= 2 and (ts == 0 or review.time < review_ts):
                    ts = int(review.time)
            review_ts = max((ts, review_ts))

            lapses = 0
            for i, review in enumerate(reviews):
                if review.button_chosen >= 2:
                    if i == 0:
                        continue
                    break
                # Skip any notes with a card whose last review was an Again
                if i == 0:
                    return None
                # Otherwise, count any Again reviews as lapses to report along
                # with the review
                lapses += 1

            result[str(card.template()["name"])] = lapses

            # Now comes the tricky part. We have a card with a positive
            # review. Decide whether that review is recent enough to qualify
            # as a review for this assignment.

            last_review_time = ts_to_datetime(reviews[0].time)
            # If the last review happened after the assignment became
            # available, accept it.
            if (
                not assignment.available_at
                or last_review_time >= assignment.available_at
            ):
                reasons.append(Reason.LAST_REVIEW_AFTER_WK_AVAILABLE)
                continue

            # If the subject has never been reviewed on WaniKani, accept the
            # card.
            if stage.position == 0:
                reasons.append(Reason.NO_WK_REVIEWS)
                continue

            # If the card is in a learning queue, just wait for the next
            # review.
            if card.queue != QUEUE_TYPE_REV:
                return None

            # The relationship between Anki and WaniKani due dates is
            # complicated. Do some further checks before allowing the review.
            due_dates.append(
                DueDate(
                    as_of + timedelta(days=card.due - wk_col.col.sched.today), card.ivl
                )
            )

        result["timestamp"] = review_ts

        if not due_dates:
            result["reason"] = min(reasons)
            return result

        # Figure out approximately when the next WaniKani due date would be
        # if we submitted a review now (but pretend that the burned stage
        # doesn't exist).
        srs_idx = stage.position
        next_srs_idx = (
            max((1, srs_idx - 1))
            if lapses
            else min((srs_idx + 1, len(assignment.srs.stages) - 2))
        )
        next_stage = assignment.srs.stages[next_srs_idx]
        assert next_stage.interval
        next_wk_due = as_of + next_stage.interval

        # If WaniKani's next due date would come before our next due date,
        # submit the review now.
        next_due = min(due_dates)
        if next_wk_due < next_due.due_date:
            result["reason"] = Reason.NEXT_ANKI_DUE_AFTER_NEXT_WK_DUE
            return result

        # If WaniKani's next due date would come *after* any of our subsequent
        # reviews at the current interval, do not submit the review.
        for due_date, ivl in due_dates:
            if due_date + timedelta(days=ivl) < next_wk_due:
                return None

        result["reason"] = Reason.SUBSEQUENT_ANKI_DUE_AFTER_NEXT_WK_DUE
        return result

    def upstream_assignment(self, assignment: Assignment, note: WKNote) -> bool:
        """
        Submits an upstream review to WaniKani for the given assignment, if
        appropriate (as determined by `should_sync_upstream`). Otherwise,
        updates the review timer to submit the review when an assignment
        becomes available, if a review would be appropriate then.

        Returns True if a review was submitted, and there is a chance that the
        subject will reach Guru status as a result. Otherwise returns False.
        """
        now = datetime.now(timezone.utc)

        def maybe_schedule_review(assignment: Assignment):
            if (
                (ts := assignment.available_at)
                and ts > now
                and self.should_sync_upstream(note, assignment, ts)
            ):
                mw.taskman.run_on_main(lambda: timers.submit_reviews_at(ts))

        if result := self.should_sync_upstream(note, assignment, now):
            if not assignment.data["started_at"]:
                resp: WKAssignment = wk.api_req(
                    f"assignments/{assignment.id}/start", data={}, put=True
                )

                note["last_upstream_sync_time"] = wknow()
                wk_col.col.update_note(note)

                # Starting an assignment counts as the first review, and
                # schedules the next review for a few hours in the future. If
                # the note is mature enough for us to submit a review at that
                # point, schedule the next review submission when it's
                # available.
                assignment = Assignment(resp, assignment.subject)
                maybe_schedule_review(assignment)
                return False

            assert assignment.available_at
            timestamp = assignment.available_at
            if result["timestamp"]:
                timestamp = max((timestamp, ts_to_datetime(result["timestamp"])))

            review = WKReviewDataReview(
                assignment_id=assignment.id,
                incorrect_meaning_answers=result["Meaning"],
                incorrect_reading_answers=result.get("Reading", 0),
                created_at=timestamp.isoformat(),
            )

            try:
                wk.post("reviews", data={"review": review})
            except requests.exceptions.RequestException as e:  # pragma: no cover
                print(f"Failed to submit review for nid:{note.id}: {review!r} {e}")
                show_tooltip(
                    f'Failed to submit review for note "{note["Characters"]}":<br>{e}'
                )
                return False

            note["last_upstream_sync_time"] = wknow()
            wk_col.col.update_note(note)

            return (
                assignment.srs_stage.position + 1
                == assignment.srs.passing_stage_position
            )

        maybe_schedule_review(assignment)
        return False

    def upstream_assignments(
        self, assignments: Sequence[WKAssignment], notes: Mapping[SubjectId, WKNote]
    ) -> None:
        """
        Submits upstream reviews to WaniKani for the given assignments and
        notes.
        """
        self.fetch_subjects(a["data"]["subject_id"] for a in assignments)

        might_guru = 0
        for assignment in assignments:
            subj_id = assignment["data"]["subject_id"]
            if subj_id in notes:
                might_guru += self.upstream_assignment(
                    Assignment(assignment, self.get_subject(subj_id)), notes[subj_id]
                )

        # If submitting the review might have made the note Guru, check whether
        # any new lessons have been unlocked that we can submit reviews for.
        if might_guru:

            @mw.taskman.run_on_main
            def runnable():
                self.upstream_available_assignments_op(lessons=True, reviews=False)

    @query_op
    def upstream_review_op(self, note: WKNote) -> None:
        """
        Submits an upstream review to WaniKani for the given note if there
        is an assignment available for review.
        """
        subject_id = int(note["card_id"])
        assignments = wk.query("assignments", {"subject_ids": [subject_id]})["data"]

        self.upstream_assignments(assignments, {subject_id: note})

    @query_op
    def upstream_available_assignments_op(
        self,
        lessons=True,
        reviews=True,
        updated_after: DateString | None = None,
    ) -> datetime:
        """
        Submits upstream reviews to WaniKani for any available assignments. If
        `lessons` is True, checks assignments which are available for lessons.
        If `reviews` is true, checks assignments which are available for
        review.
        """
        dates = [datetime.now(timezone.utc)]

        def query(filter: WKAssignmentsQuery):
            if updated_after:
                filter["updated_after"] = updated_after
            resp = wk.query("assignments", filter)

            if resp["data_updated_at"]:
                dates.append(datetime.fromisoformat(resp["data_updated_at"]))

            return resp["data"]

        assignments = list[WKAssignment]()
        if lessons:
            assignments.extend(query({"immediately_available_for_lessons": True}))
        if reviews:
            assignments.extend(query({"immediately_available_for_review": True}))

        notes = wk_col.find_notes_for_subjects(
            [a["data"]["subject_id"] for a in assignments], update_progress=True
        )
        self.upstream_assignments(assignments, notes)

        return min(dates)

    @collection_op
    def update_ivl_from_assignments_op(
        self, timestamp: str | None, assignments: Sequence[WKAssignment]
    ) -> OpChangesWithCount:
        """
        Updates the interval and due time of local Notes based on the given
        assignments. See `maybe_sync_downstream` for details.

        If `timestamp` is provided, it should be the time the given
        assignments were last updated, and will be stored in
        `config._last_due_sync` on success.
        """
        cards = wk_col.find_cards_for_subjects(
            [a["data"]["subject_id"] for a in assignments],
            update_progress=True,
        )

        changed_cards = []
        for i, wkassignment in enumerate(assignments):
            if mw.progress.want_cancel():
                break  # pragma: no cover

            report_progress(
                f"Updating assignments {i + 1}/{len(assignments)}...",
                i,
                len(assignments),
            )

            subject = self.get_subject(wkassignment["data"]["subject_id"])
            assignment = Assignment(wkassignment, subject)
            for card in cards[subject["id"]]:
                if self.maybe_sync_downstream(card, assignment):
                    changed_cards.append(card)

        wk_col.col.update_cards(changed_cards)

        if timestamp:
            config._last_due_sync = timestamp

        result = OpChangesWithCount()
        result.count = len(changed_cards)
        result.changes.card = True
        return result

    @Promise.wrap
    async def update_intervals(self) -> None:
        """
        Updates the intervals of Notes based on the intervals and due dates of
        WaniKani assignments. See `maybe_sync_downstream` for details.

        If `config._last_due_sync` is set, only checks assignments updated
        since that timestamp. Updates `config._last_due_sync` on success.
        """
        query = WKAssignmentsQuery(hidden=False)

        if config._last_due_sync:
            query["updated_after"] = config._last_due_sync

        resp = await self.fetch_assignments_op(query)

        await self.update_ivl_from_assignments_op(resp["data_updated_at"], resp["data"])


@collection_op
def do_sync() -> OpChangesWithCount:
    if not config.WK_API_KEY:
        raise Exception("Configure your WK API key first.")  # pragma: no cover

    now = wknow()

    user_data = wk.query("user")
    granted_lvl = user_data["data"]["subscription"]["max_level_granted"]

    subject_ids = None
    existing_subject_ids = set()
    if not config.SYNC_ALL:
        subject_ids = get_available_subject_ids()
        existing_subject_ids = {
            int(wk_col.get_note(nid)["card_id"]) for nid in wk_col.find_notes()
        }

    subjects, study_mats = fetch_subjects(
        subject_ids, existing_subject_ids, granted_lvl
    )
    related_subjects = fetch_related_subjects(subjects)

    result = OpChangesWithCount()
    result.count = len(subjects)

    if ensure_deck(wk_col.col, config.DECK_NAME):
        result.changes.notetype = True
        result.changes.deck = True
        result.changes.deck_config = True

    if ensure_notes(wk_col.col, subjects, related_subjects, study_mats):
        result.changes.card = True
        result.changes.note = True

    if result.changes.card or result.changes.study_queues:
        report_progress("Sorting deck...", 100, 100)
        sort_new_cards(wk_col.col)
        result.changes.study_queues = True

    SyncOp().update_intervals()

    config._last_subjects_sync = now

    return result


def do_update_intervals():
    SyncOp().update_intervals()


def do_clear_cache():
    config._last_assignments_sync = ""
    config._last_subjects_sync = ""
    config._last_due_sync = ""


def auto_sync():
    if config.WK_API_KEY and config.AUTO_SYNC:
        do_sync()
