"""Tests for notes bulk operations and time-travel undo."""
from unittest.mock import AsyncMock, patch

import pytest
from imperal_sdk.testing import MockContext

import handlers_notes
from models_notes import DeleteNotesParams, BulkNotesParams, NoteIdParams


@pytest.mark.asyncio
async def test_bulk_delete_notes_with_undo():
    ctx = MockContext(user_id="user-1")
    note_id = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"

    ctx.http.mock_post(
        "http://localhost:8000/notes/bulk-action",
        {"affected_count": 1, "note_ids": [note_id]},
    )

    params = DeleteNotesParams(note_ids=[note_id], permanent=False)
    res = await handlers_notes.fn_delete_notes(ctx, params)

    assert res.status == "success"
    assert res.data["affected_count"] == 1
    assert res.undo is not None
    assert res.undo["function"] == "restore_notes"
    assert res.undo["params"]["note_ids"] == [note_id]


@pytest.mark.asyncio
async def test_bulk_archive_notes_with_undo():
    ctx = MockContext(user_id="user-1")
    note_id = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"

    ctx.http.mock_post(
        "http://localhost:8000/notes/bulk-action",
        {"affected_count": 1, "note_ids": [note_id]},
    )

    params = BulkNotesParams(note_ids=[note_id])
    res = await handlers_notes.fn_archive_notes(ctx, params)

    assert res.status == "success"
    assert res.undo is not None
    assert res.undo["function"] == "unarchive_notes"
    assert res.undo["params"]["note_ids"] == [note_id]


@pytest.mark.asyncio
async def test_single_delete_note_with_undo():
    ctx = MockContext(user_id="user-1")
    note_id = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"

    params = NoteIdParams(note_id=note_id)
    with patch.object(handlers_notes, "_api_delete", new=AsyncMock(return_value={"id": note_id})):
        res = await handlers_notes.fn_delete_note(ctx, params=params)
    assert res.status == "success"
    assert res.undo is not None
    assert res.undo["function"] == "restore_note"
    assert res.undo["params"]["note_id"] == note_id
