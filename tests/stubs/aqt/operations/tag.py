from __future__ import annotations

from typing import Any, Sequence

from anki.notes import NoteId

from . import CollectionOp


def remove_tags_from_notes(
    *,
    parent: Any,
    note_ids: Sequence[NoteId],
    space_separated_tags: str,
) -> CollectionOp:
    return CollectionOp(
        parent, lambda col: col.tags.bulk_remove(note_ids, space_separated_tags)
    )
