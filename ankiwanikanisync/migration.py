from __future__ import annotations

from typing import Any, Final, Generator

from anki.cards import Card
from anki.collection import OpChangesWithCount, SearchNode
from anki.consts import CARD_TYPE_NEW
from anki.notes import Note

from .collection import WKCard, WKNote, search_node, wk_col
from .utils import collection_op, report_progress

S: Final = SearchNode

REVLOG_COLS: Final = (
    "usn",
    "ease",
    "ivl",
    "lastIvl",
    "factor",
    "time",
    "type",
)


class Migrator:
    QUERY_REVLOG_READ = f"""
        SELECT
            {", ".join(REVLOG_COLS)}
        FROM
            revlog
        WHERE
            cid = ?
    """
    QUERY_REVLOG_WRITE = f"""
        INSERT
        INTO
            revlog (cid, id, {", ".join(REVLOG_COLS)})
        VALUES
            (?, ?, {", ".join("?" for col in REVLOG_COLS)})
    """

    def __init__(self, to_note: str, from_note: str):
        self.col = wk_col.col

        to_model = wk_col.col.models.by_name(to_note)
        from_model = wk_col.col.models.by_name(from_note)

        assert to_model
        assert from_model
        self.from_model = from_model
        self.to_model = to_model

        def tmpl_map(tmpls: list[dict[str, Any]]) -> dict[str, int]:
            return {tmpl["name"]: i for i, tmpl in enumerate(tmpls)}

        to_card = tmpl_map(self.to_model["tmpls"])
        from_card = tmpl_map(self.from_model["tmpls"])

        self.card_map = {i: to_card[name] for name, i in from_card.items()}

        self.changes = 0

    @collection_op
    def do_migrate(self) -> OpChangesWithCount:
        self.migrate_notes()

        result = OpChangesWithCount()
        result.changes.card = True
        result.count = self.changes
        return result

    def find_notes(self) -> Generator[Note]:
        filter = self.col.build_search_string(
            S(note=self.from_model["name"]), S(negated=S(card_state=S.CARD_STATE_NEW))
        )

        for nid in self.col.find_notes(filter):
            yield self.col.get_note(nid)

    def migrate_notes(self) -> None:
        notes = list(self.find_notes())
        for i, from_note in enumerate(notes):
            report_progress("Migrating notes {i + 1}/{len(notes)}...", i, len(notes))

            try:
                filter: list[str | SearchNode] = [
                    search_node(Card_Type=from_note["Card_Type"].replace("_", " ")),
                ]
                if from_note["Characters"].startswith("<i class="):
                    filter.append(search_node(Meaning=from_note["Meaning"]))
                else:
                    filter.append(search_node(Characters=from_note["Characters"]))

                if nids := wk_col.find_notes(*filter):
                    self.migrate_note(wk_col.get_note(nids[0]), from_note)
            except Exception:
                import traceback

                traceback.print_exc()

    def migrate_note(self, to_note: WKNote, from_note: Note) -> None:
        to_cards = {c.ord: c for c in to_note.cards()}
        cards = {c: to_cards.get(self.card_map[c.ord]) for c in from_note.cards()}

        changed_cards = list[WKCard]()
        for from_card, to_card in cards.items():
            if to_card and from_card.type != CARD_TYPE_NEW:
                self.migrate_card(to_card, from_card)
                changed_cards.append(to_card)
                self.changes += 1
        self.col.update_cards(changed_cards)

    def migrate_card(self, to_card: WKCard, from_card: Card) -> None:
        self.copy_stats(to_card, from_card)
        self.copy_revlog(to_card, from_card)

    def copy_revlog(self, to_card: Card, from_card: Card):
        db = self.col.db
        assert db

        @db.transact
        def transaction():
            first_id = db.scalar("SELECT MAX(id) FROM revlog") + 1

            from_rows = db.all(self.QUERY_REVLOG_READ, from_card.id)
            to_rows = db.all(self.QUERY_REVLOG_READ, to_card.id)

            rows = [
                [to_card.id, first_id + i, *cols]
                for i, cols in enumerate(from_rows)
                if cols not in to_rows
            ]
            db.executemany(self.QUERY_REVLOG_WRITE, rows)

    def copy_stats(self, to_card: Card, from_card: Card):
        if from_card.type > to_card.type:
            to_card.type = from_card.type
            to_card.queue = from_card.queue

            to_card.due = from_card.due
            to_card.ivl = from_card.ivl
            to_card.odue = from_card.odue
            to_card.left = from_card.left
        elif from_card.type == to_card.type:
            to_card.due = max((to_card.due, from_card.due))
            to_card.ivl = max((to_card.ivl, from_card.ivl))
            to_card.odue = max((to_card.odue, from_card.odue))
            to_card.left = min((to_card.left, from_card.left))

        if from_card.decay is not None:
            to_card.decay = from_card.decay
        to_card.factor = from_card.factor
        to_card.flags |= from_card.flags
        to_card.lapses += from_card.lapses
        if from_card.memory_state is not None:
            to_card.memory_state = from_card.memory_state
        to_card.reps += from_card.reps

        if from_card.last_review_time is not None:
            if to_card.last_review_time is not None:
                to_card.last_review_time = max(
                    from_card.last_review_time,
                    to_card.last_review_time,
                )
            else:
                to_card.last_review_time = from_card.last_review_time
