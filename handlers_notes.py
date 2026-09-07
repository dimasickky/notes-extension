"""Notes · CRUD handlers."""
from __future__ import annotations

import asyncio
import logging

from app import (
    chat, ActionResult,
    NotesAPIError,
    _api_get, _api_patch, _api_post, _api_delete,
    require_user_id, _tenant_id, _resolve_folder_id_or_name, _bad_id,
)
from models_notes import (  # noqa: E402
    MAX_NOTES_PER_PAGE, MAX_SEARCH_PER_PAGE,
    AppendNoteParams, CreateNoteParams, DeleteNotesFromFolderParams, ListNotesParams,
    MoveNoteParams, MoveNotesParams, NoteIdParams, SearchNotesParams, UpdateNoteParams,
    BulkNotesParams, DeleteNotesParams,
)
from models_return import (
    ListNotesResult, NoteEntity, NoteListItem, SearchNoteItem,
    CreateNoteResult, UpdateNoteResult,
    MoveNoteResult, DeleteNoteResult, BulkDeleteNotesResult, SearchNotesResult,
    BulkNotesActionResult, BulkFanoutResult,
)
from imperal_sdk.chat.error_codes import VALIDATION_MISSING_FIELD, INTERNAL
from error_codes import NOTES_INVALID_NOTE_ID, NOTES_FOLDER_NOT_FOUND, NOTES_BACKEND_ERROR, NOTES_NOTE_NOT_FOUND

log = logging.getLogger("notes.handlers")


@chat.function(
    "list_notes",
    action_type="read",
    description=(
        "List notes (paginated). Returns up to `limit` rows per call "
        f"(max {MAX_NOTES_PER_PAGE}). If `has_more` is true, call again with "
        "`offset=offset+limit` to fetch the next page."
    ),
    data_model=ListNotesResult,
)
async def fn_list_notes(ctx, params: ListNotesParams) -> ActionResult:
    try:
        qp: dict = {
            "user_id":   require_user_id(ctx),
            "tenant_id": _tenant_id(ctx),
            "limit":     params.limit,
            "offset":    params.offset,
        }
        if params.folder_id:
            folder_id = await _resolve_folder_id_or_name(ctx, params.folder_id)
            if not folder_id:
                return ActionResult.error(
                    f"Folder '{params.folder_id}' not found. "
                    "Use list_folders() to see available folders.",
                    code=NOTES_FOLDER_NOT_FOUND,
                )
            qp["folder_id"] = folder_id
        if params.search:                  qp["search"] = params.search
        if params.tags:                    qp["tags"] = ",".join(params.tags)
        if params.is_archived is not None: qp["is_archived"] = params.is_archived
        if params.is_trashed is not None:  qp["is_trashed"] = params.is_trashed

        resp = await _api_get(ctx, "/notes", qp)
        notes = resp.get("notes", [])

        total_count = resp.get("total_count")
        if total_count is None:
            has_more = len(notes) == params.limit
            total_known = False
        else:
            has_more = (params.offset + len(notes)) < int(total_count)
            total_known = True

        next_offset = params.offset + len(notes) if has_more else None

        return ActionResult.success(
            data={
                "items": [
                    NoteListItem(
                        id=n["id"],
                        title=n["title"] or "Untitled",
                        kind="note",
                        tags=n.get("tags") or [],
                        is_pinned=n.get("is_pinned", False),
                        is_archived=n.get("is_archived", False),
                        is_trashed=n.get("is_trashed", False),
                        word_count=n.get("word_count", 0),
                        folder_id=n.get("folder_id"),
                        created_at=str(n.get("created_at") or ""),
                        updated_at=str(n.get("updated_at") or ""),
                    ).model_dump()
                    for n in notes
                ],
                "page_size":   len(notes),
                "offset":      params.offset,
                "limit":       params.limit,
                "has_more":    has_more,
                "next_offset": next_offset,
                "total_count": int(total_count) if total_known else None,
            },
            summary=(
                f"{len(notes)} note(s) on this page"
                + (f" of {total_count} total" if total_known else "")
                + (f"; more available (next_offset={next_offset})" if has_more else "")
            ),
        )
    except NotesAPIError as e:
        return ActionResult.error(f"list_notes backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("list_notes: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "get_note",
    action_type="read",
    description="Get full content of a note by ID.",
    data_model=NoteEntity,
)
async def fn_get_note(ctx, params: NoteIdParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)
        data = await _api_get(ctx, f"/notes/{params.note_id}", {"user_id": require_user_id(ctx)})
        note = data.get("note", {})
        entity = NoteEntity(
            id=note.get("id"),
            title=note.get("title") or "Untitled",
            kind="note",
            body=note.get("content_text", ""),
            tags=note.get("tags") or [],
            is_pinned=note.get("is_pinned", False),
            is_archived=note.get("is_archived", False),
            is_trashed=note.get("is_trashed", False),
            word_count=note.get("word_count", 0),
            folder_id=note.get("folder_id"),
            created_at=str(note.get("created_at") or ""),
            updated_at=str(note.get("updated_at") or ""),
        )
        return ActionResult.success(
            data=entity,
            summary=f"Note '{entity.title}' (id={entity.id})",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"get_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("get_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "create_note",
    action_type="write",
    chain_callable=True,
    effects=["create:note"],
    event="created",
    description="Create a new note with title, content, tags, and optional folder.",
    data_model=CreateNoteResult,
)
async def fn_create_note(ctx, params: CreateNoteParams) -> ActionResult:
    try:
        title   = params.title.strip()
        content = params.content_text

        if not title and not content.strip():
            return ActionResult.error(
                "Note must have a title or content. Pass title and/or content_text.",
                code=VALIDATION_MISSING_FIELD,
            )

        # A title with an empty body is a legitimate note ("make a note called
        # Shopping list"), so it is not rejected. But it is ALSO the exact shape
        # produced when the caller's own output got cut off mid-arguments: the
        # title survives, the body never arrives, and the note is saved at zero
        # characters with a cheerful "Note created" — the failure looks like a
        # success and is only discovered when the user opens an empty note.
        #
        # So the emptiness is reported instead of hidden: it goes in the summary
        # the caller reads back, and `content_chars` makes it machine-checkable.
        # Nothing is blocked, but nothing is silent either.
        if title and not content.strip():
            log.warning(
                "create_note: empty body with title=%r — intentional title-only "
                "note, or truncated arguments upstream",
                title[:60],
            )

        if title and len(title) >= 3 and content.startswith(title):
            log.warning(
                "title-bleed detected on create_note (title=%r); stripping duplicate prefix",
                title[:40],
            )
            content = content[len(title):].lstrip(": \n\t")

        folder_id = await _resolve_folder_id_or_name(ctx, params.folder_id)
        if params.folder_id and not folder_id:
            return ActionResult.error(
                f"Folder '{params.folder_id}' not found. "
                "Use list_folders() to see available folders.",
                code=NOTES_FOLDER_NOT_FOUND,
            )

        body: dict = {
            "user_id":      require_user_id(ctx),
            "tenant_id":    _tenant_id(ctx),
            "title":        title,
            "content_text": content,
            "tags":         params.tags,
        }
        if folder_id:
            body["folder_id"] = folder_id

        note = (await _api_post(ctx, "/notes", body)).get("note", {})
        content_chars = len(content)
        created_title = note.get("title") or params.title
        summary = f"Note created: {created_title}"
        if content_chars:
            summary += f" ({content_chars} chars)"
        else:
            summary += " — WARNING: the body is EMPTY (0 chars). If you meant to "
            summary += (
                "write content into it, the text did not arrive: add it with "
                "append_to_note instead of creating the note again."
            )
        return ActionResult.success(
            data={
                "note_id":   note.get("id"),
                "title":     note.get("title"),
                "folder_id": folder_id or None,
                "content_chars": content_chars,
            },
            summary=summary,
        )
    except NotesAPIError as e:
        return ActionResult.error(f"create_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("create_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "update_note",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="updated",
    description=(
        "Update note fields (title, tags, pin) or REPLACE its content. "
        "WARNING: content_text OVERWRITES the entire body — to ADD text to an "
        "existing note use append_to_note instead."
    ),
    data_model=UpdateNoteResult,
)
async def fn_update_note(ctx, params: UpdateNoteParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)
        # "Was this field passed?" is not the same question as "is this field
        # truthy", and only the first one is the right one here. A plain falsy
        # check cannot express "clear the body": passing content_text="" to
        # empty a note was silently dropped as if nothing had been asked, and
        # the note kept its old text forever. `model_fields_set` distinguishes
        # an omitted field (keep) from an explicitly passed empty one (clear).
        given = params.model_fields_set
        updates: dict = {}
        if params.title:                 updates["title"] = params.title
        if "content_text" in given:      updates["content_text"] = params.content_text
        if params.tags is not None:      updates["tags"] = params.tags
        if params.is_pinned is not None: updates["is_pinned"] = params.is_pinned
        if not updates:
            return ActionResult.error("No fields to update", code=VALIDATION_MISSING_FIELD)

        user_id = require_user_id(ctx)
        current = (await _api_get(ctx, f"/notes/{params.note_id}", {"user_id": user_id})).get("note", {})

        changed: dict = {}
        for field, value in updates.items():
            cur = current.get(field)
            if field == "tags":
                if set(value) != set(cur or []):
                    changed[field] = value
            else:
                if value != cur:
                    changed[field] = value

        title = current.get("title", "")

        if not changed:
            return ActionResult.success(
                data={"note_id": params.note_id, "title": title, "was_changed": False},
                summary=f"Note is already up to date: {title}",
            )

        data = await _api_patch(ctx, f"/notes/{params.note_id}", {"user_id": user_id}, changed)
        title = data.get("note", {}).get("title", title)
        return ActionResult.success(
            data={"note_id": params.note_id, "title": title, "fields_updated": list(changed.keys()), "was_changed": True},
            summary=f"Note updated: {title}",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"update_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("update_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "append_to_note",
    action_type="write",
    chain_callable=True,
    id_projection="note_id",
    effects=["update:note"],
    event="updated",
    description=(
        "Append text to the END of an existing note's body WITHOUT overwriting it. "
        "The text is added server-side in one atomic operation, so appending to a "
        "long note stays cheap and two appends can never overwrite each other. "
        "Use this for any 'add to note / append / допиши / добавь в заметку' request — never "
        "use update_note to add content, because update_note REPLACES the whole body."
    ),
    data_model=NoteEntity,
)
async def fn_append_to_note(ctx, params: AppendNoteParams) -> ActionResult:
    """Append to a note's body through the backend's atomic append.

    This used to read the whole note, join the pieces here, and PATCH the entire
    body back. Two problems with that, both of which show up exactly when a note
    is being built up over many appends — the case this function exists for:

      * lost updates — two appends that overlap both read the same "before" text
        and the second write silently discards the first one's addition;
      * cost — the full body crossed the network twice per append, so appending
        one line to a 47k-character note moved ~94k characters to add ~40.

    `POST /notes/{id}/append` does the concatenation inside a single SQL
    statement, so only the new fragment is sent and no interleaving is possible.
    """
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)
        addition = params.content_text.strip()
        if not addition:
            return ActionResult.error(
                "Nothing to append. Pass content_text with the text to add.",
                code=VALIDATION_MISSING_FIELD,
            )

        user_id = require_user_id(ctx)
        # user_id is a query param on this endpoint (like every other /notes
        # route), the fragment is the JSON body — passing it in the body instead
        # would fail validation before the append ever runs.
        resp = await _api_post(
            ctx, f"/notes/{params.note_id}/append",
            {"content_text": addition},
            {"user_id": user_id},
        )
        note = (resp or {}).get("note", {})

        entity = NoteEntity(
            id=note.get("id") or params.note_id,
            title=note.get("title") or "Untitled",
            kind="note",
            body=note.get("content_text", ""),
            tags=note.get("tags") or [],
            is_pinned=note.get("is_pinned", False),
            is_archived=note.get("is_archived", False),
            word_count=note.get("word_count", 0),
            folder_id=note.get("folder_id"),
        )
        added = (resp or {}).get("appended_chars", len(addition))
        return ActionResult.success(
            data=entity,
            summary=f"Appended {added} chars to note '{entity.title}'",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"append_to_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("append_to_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "move_note",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="moved",
    description="Move note to a folder, or root with empty folder_id.",
    data_model=MoveNoteResult,
)
async def fn_move_note(ctx, params: MoveNoteParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)
        folder_id = await _resolve_folder_id_or_name(ctx, params.folder_id)
        if params.folder_id and not folder_id:
            return ActionResult.error(
                f"Folder '{params.folder_id}' not found. "
                "Use list_folders() to see available folders.",
                code=NOTES_FOLDER_NOT_FOUND,
            )
        data = await _api_patch(
            ctx, f"/notes/{params.note_id}",
            {"user_id": require_user_id(ctx)},
            {"folder_id": folder_id if folder_id else None},
        )
        target = folder_id or "All Notes"
        return ActionResult.success(
            data={
                "note_id":   params.note_id,
                "title":     data.get("note", {}).get("title", ""),
                "folder_id": folder_id or None,
                "moved_to":  target,
            },
            summary=f"Note moved to {target}",
        )
    except NotesAPIError as e:
        return ActionResult.error(f"move_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("move_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "delete_note",
    action_type="destructive",
    chain_callable=True,
    effects=["trash:note"],
    event="deleted",
    description="Delete a note (moves to trash).",
    data_model=DeleteNoteResult,
)
async def fn_delete_note(ctx, params: NoteIdParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)
        await _api_delete(ctx, f"/notes/{params.note_id}",
                          {"user_id": require_user_id(ctx), "permanent": "false"})
        undo_action = {"action": "call", "function": "restore_note", "params": {"note_id": params.note_id}}
        return ActionResult.success(
            data={"note_id": params.note_id},
            summary="Note moved to trash",
            undo=undo_action,
        )
    except NotesAPIError as e:
        return ActionResult.error(f"delete_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("delete_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "permanent_delete_note",
    action_type="destructive",
    chain_callable=True,
    id_projection="note_id",
    effects=["delete:note"],
    event="permanently_deleted",
    description="Permanently delete a note. Cannot be undone.",
    data_model=DeleteNoteResult,
)
async def fn_permanent_delete_note(ctx, params: NoteIdParams) -> ActionResult:
    try:
        if err := _bad_id(params.note_id):
            return ActionResult.error(err, code=NOTES_INVALID_NOTE_ID)
        await _api_delete(ctx, f"/notes/{params.note_id}",
                          {"user_id": require_user_id(ctx), "permanent": "true"})
        return ActionResult.success(data={"note_id": params.note_id}, summary="Note permanently deleted")
    except NotesAPIError as e:
        return ActionResult.error(f"permanent_delete_note backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("permanent_delete_note: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "delete_notes_from_folder",
    action_type="destructive",
    chain_callable=True,
    id_projection="folder_id",
    effects=["trash:note", "delete:note"],
    event="bulk_deleted",
    description=(
        "Delete ALL notes in a folder (bulk). By default moves them to trash; "
        "pass permanent=true to permanently delete instead. "
        "folder_id accepts a folder UUID OR a folder name — auto-resolved either way."
    ),
    data_model=BulkDeleteNotesResult,
)
async def fn_delete_notes_from_folder(ctx, params: DeleteNotesFromFolderParams) -> ActionResult:
    try:
        folder_id = await _resolve_folder_id_or_name(ctx, params.folder_id.strip())
        if not folder_id:
            return ActionResult.error(
                "Folder not found. Pass folder_id with the folder name or UUID.",
                code=NOTES_FOLDER_NOT_FOUND,
            )
        resp = await _api_delete(ctx, "/notes/bulk", {
            "user_id":   require_user_id(ctx),
            "folder_id": folder_id,
            "permanent": "true" if params.permanent else "false",
        })
        deleted = resp.get("deleted_count", 0)
        action  = "permanently deleted" if params.permanent else "moved to trash"
        return ActionResult.success(
            data={"deleted_count": deleted, "folder_id": folder_id,
                  "permanent": params.permanent},
            summary=f"{deleted} note(s) {action}" if deleted else "No notes in folder — nothing to delete",
        )
    except NotesAPIError as e:
        return ActionResult.error(
            f"delete_notes_from_folder backend returned {e.status_code}: {e.detail}",
            code=NOTES_BACKEND_ERROR,
        )
    except Exception as e:
        log.error("delete_notes_from_folder: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


# ── Bulk actions over an explicit note-id set ─────────────────────────────── #

async def _resolve_bulk_ids(ctx, note_ids, note_titles, scope_filter: dict) -> tuple[list, list]:
    """Resolve note_ids + note_titles → (resolved_ids, not_found_titles). De-duped.

    Titles are matched against notes in the given scope (active / archived /
    trashed) via the list endpoint — NOT fulltext search, which by design never
    returns archived or trashed rows (so restore/unarchive by title would
    otherwise always miss the very notes they target).
    """
    ids: list = []
    seen: set = set()
    for nid in (note_ids or []):
        nid = (nid or "").strip()
        if nid and not _bad_id(nid) and nid not in seen:
            seen.add(nid)
            ids.append(nid)
    not_found: list = []
    titles = [t.strip() for t in (note_titles or []) if (t or "").strip()]
    if titles:
        qp = {"user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx),
              "limit": MAX_NOTES_PER_PAGE, "offset": 0}
        qp.update(scope_filter)
        resp = await _api_get(ctx, "/notes", qp)
        pool = resp.get("notes", []) if isinstance(resp, dict) else []
        for title in titles:
            tl = title.lower()
            match = next(
                (n for n in pool if (n.get("title") or "").strip().lower() == tl),
                next((n for n in pool if tl in (n.get("title") or "").strip().lower()), None),
            )
            if match and match.get("id") and match["id"] not in seen:
                seen.add(match["id"])
                ids.append(match["id"])
            elif not match:
                not_found.append(title)
    return ids, not_found


async def _titles_for(ctx, ids: list[str]) -> dict[str, str]:
    """Map note ids → titles in ONE request, for readable batch output.

    Batch results echo a label per row, and a UUID there tells the user
    nothing about which note succeeded. Titles come from a single list call
    rather than a GET per note: a 200-note batch would otherwise pay 200 extra
    round trips purely for cosmetics, which is not a trade worth making.

    Best-effort by design — a note missing from the page (or a failed lookup)
    just falls back to its id rather than failing the move itself.
    """
    try:
        qp = {"user_id": require_user_id(ctx), "tenant_id": _tenant_id(ctx),
              "limit": MAX_NOTES_PER_PAGE, "offset": 0}
        resp = await _api_get(ctx, "/notes", qp)
        pool = resp.get("notes", []) if isinstance(resp, dict) else []
        wanted = set(ids)
        return {
            n["id"]: (n.get("title") or "").strip() or n["id"]
            for n in pool if n.get("id") in wanted
        }
    except Exception as e:  # noqa: BLE001 — labels are cosmetic, never fatal
        log.warning("title lookup for batch labels failed: %s", e)
        return {}


# ─── fan-out batching (for actions with no /notes/bulk-action equivalent) ── #
#
# Most batches here are one POST to /notes/bulk-action, which is strictly
# better when the backend supports the action. Move and attachment-delete have
# no such action, so they issue one request per item — and that is exactly
# where the two extra guarantees below start to matter.
#
# The concurrency cap matches tasks._BULK_CONCURRENCY (8) for the same reason:
# a serial loop over 40 notes is 40 serialised round trips and walks into the
# 180s a tool call gets, while an unbounded gather over 200 hammers the notes
# backend. The ceiling is checked before any request goes out, because a limit
# enforced mid-flight protects nothing.
_BULK_CONCURRENCY = 8
MAX_BULK_ITEMS = 200


def _check_batch_size(items: list, noun: str) -> ActionResult | None:
    """Reject an empty or oversized batch before any network call happens."""
    if not items:
        return ActionResult.error(f"No {noun} given.", code=VALIDATION_MISSING_FIELD)
    if len(items) > MAX_BULK_ITEMS:
        return ActionResult.error(
            f"That's {len(items)} {noun} in one call — the limit is {MAX_BULK_ITEMS}. "
            "Split it into smaller batches.",
            code=VALIDATION_MISSING_FIELD,
        )
    return None


async def _run_fanout(ctx, rows: list[tuple[str, str]], op) -> list[dict]:
    """Run `op(item_id)` over rows concurrently, one result row per item.

    `rows` is [(id, label)]. `op` returns None on success or an error string.
    A failure never sinks the batch: the caller is entitled to know which of
    the eight moves happened and which did not, rather than getting a single
    verdict for the whole set.
    """
    sem = asyncio.Semaphore(_BULK_CONCURRENCY)
    done = 0

    async def _one(item_id: str, label: str) -> dict:
        nonlocal done
        async with sem:
            try:
                err = await op(item_id)
            except NotesAPIError as e:
                err = f"{e.status_code} {e.detail}"
            except Exception as e:  # noqa: BLE001 — one bad item must not kill the batch
                log.error("bulk item %s: %s", item_id, e)
                err = "unexpected error"
        done += 1
        if hasattr(ctx, "progress"):
            try:
                await ctx.progress(done / max(len(rows), 1), f"{done}/{len(rows)}")
            except Exception:  # noqa: BLE001 — progress is cosmetic, never fatal
                pass
        return {"id": item_id, "title": label, "ok": err is None, "error": err}

    return list(await asyncio.gather(*(_one(i, l) for i, l in rows)))


# Title-resolution scopes per action (list-endpoint filters).
_SCOPE_ACTIVE   = {"is_archived": False, "is_trashed": False}
_SCOPE_ARCHIVED = {"is_archived": True}
_SCOPE_TRASHED  = {"is_trashed": True}


async def _bulk_action(ctx, params, *, action: str, ok_verb: str, scope_filter: dict) -> ActionResult:
    # Same ceiling as the fan-out batches. Without it these went straight to the
    # backend, which caps /notes/bulk-action at 500 and answers with a raw 422 —
    # so a too-large delete failed with a backend error string instead of a
    # sentence saying to split the batch. Checked before resolving titles, since
    # resolving 400 titles only to refuse them wastes the work.
    oversized = _check_batch_size(
        (params.note_ids or []) + (params.note_titles or []), "notes",
    )
    if oversized:
        return oversized

    ids, not_found = await _resolve_bulk_ids(ctx, params.note_ids, params.note_titles, scope_filter)
    if not ids:
        if not_found:
            return ActionResult.error(f"No matching notes found for: {', '.join(not_found)}.", code=NOTES_NOTE_NOT_FOUND)
        return ActionResult.error("Pass note_ids or note_titles — nothing to act on.", code=VALIDATION_MISSING_FIELD)
    resp = await _api_post(ctx, "/notes/bulk-action", {
        "user_id": require_user_id(ctx), "note_ids": ids, "action": action,
    })
    affected = resp.get("affected_count", 0) if isinstance(resp, dict) else 0
    summary = f"{affected} note(s) {ok_verb}"
    if not_found:
        summary += f" ({len(not_found)} not found: {', '.join(not_found)})"
    return ActionResult.success(
        data={
            "affected_count": affected,
            "action": action,
            "note_ids": (resp.get("note_ids", ids) if isinstance(resp, dict) else ids),
            "not_found": not_found,
            # Bare panel id — the host resolves it against its own left/right/
            # center panel_ids. A "__panel__"-prefixed value is NOT a panel id:
            # it gets prefixed a second time, resolves to no known panel, and
            # the batch silently never refreshes the sidebar.
            "refresh_panels": ["sidebar"],
        },
        summary=summary,
    )


@chat.function(
    "delete_notes",
    action_type="destructive",
    chain_callable=True,
    effects=["trash:note", "delete:note"],
    event="bulk_deleted",
    description=(
        "Delete MULTIPLE notes at once. Pass note_ids (list of IDs) OR note_titles "
        "(list of names, auto-resolved). Moves them to trash by default; pass "
        "permanent=true to delete permanently. Use when the user wants to delete 2+ notes."
    ),
    data_model=BulkNotesActionResult,
)
async def fn_delete_notes(ctx, params: DeleteNotesParams) -> ActionResult:
    try:
        return await _bulk_action(
            ctx, params,
            action="permanent" if params.permanent else "trash",
            ok_verb="permanently deleted" if params.permanent else "moved to trash",
            scope_filter=_SCOPE_ACTIVE,
        )
    except NotesAPIError as e:
        return ActionResult.error(f"delete_notes backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("delete_notes: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "archive_notes",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="bulk_archived",
    description="Archive MULTIPLE notes at once. Pass note_ids (list) OR note_titles (list of names).",
    data_model=BulkNotesActionResult,
)
async def fn_archive_notes(ctx, params: BulkNotesParams) -> ActionResult:
    try:
        return await _bulk_action(ctx, params, action="archive", ok_verb="archived",
                                  scope_filter=_SCOPE_ACTIVE)
    except NotesAPIError as e:
        return ActionResult.error(f"archive_notes backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("archive_notes: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "unarchive_notes",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="bulk_unarchived",
    description="Remove MULTIPLE notes from the archive (unarchive). Pass note_ids OR note_titles.",
    data_model=BulkNotesActionResult,
)
async def fn_unarchive_notes(ctx, params: BulkNotesParams) -> ActionResult:
    try:
        return await _bulk_action(ctx, params, action="unarchive", ok_verb="unarchived",
                                  scope_filter=_SCOPE_ARCHIVED)
    except NotesAPIError as e:
        return ActionResult.error(f"unarchive_notes backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("unarchive_notes: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "restore_notes",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="bulk_restored",
    description="Restore MULTIPLE notes from trash. Pass note_ids OR note_titles.",
    data_model=BulkNotesActionResult,
)
async def fn_restore_notes(ctx, params: BulkNotesParams) -> ActionResult:
    try:
        return await _bulk_action(ctx, params, action="restore", ok_verb="restored",
                                  scope_filter=_SCOPE_TRASHED)
    except NotesAPIError as e:
        return ActionResult.error(f"restore_notes backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("restore_notes: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "search_notes",
    action_type="read",
    description=(
        "Full-text search across all notes (paginated). Returns up to `limit` "
        f"results per call (max {MAX_SEARCH_PER_PAGE}). If `has_more` is true, "
        "call again with `offset=offset+limit` to fetch the next page. "
        "Do NOT claim to have searched all notes until `has_more` is false."
    ),
    data_model=SearchNotesResult,
)
async def fn_search_notes(ctx, params: SearchNotesParams) -> ActionResult:
    try:
        if not params.query.strip():
            return ActionResult.error("Search query is required. Pass query (or q).", code=VALIDATION_MISSING_FIELD)
        resp = await _api_get(ctx, "/notes/search/fulltext", {
            "user_id":   require_user_id(ctx),
            "tenant_id": _tenant_id(ctx),
            "q":         params.query,
            "limit":     params.limit,
            "offset":    params.offset,
            "include_archived": params.include_archived,
            "include_trashed":  params.include_trashed,
        })
        results = resp.get("results", [])

        total_count = resp.get("total_count")
        if total_count is None:
            has_more = len(results) == params.limit
            total_known = False
        else:
            has_more = (params.offset + len(results)) < int(total_count)
            total_known = True

        next_offset = params.offset + len(results) if has_more else None

        return ActionResult.success(
            data={
                "items": [
                    SearchNoteItem(
                        id=r.get("id"),
                        title=r.get("title") or "Untitled",
                        kind="note",
                        excerpt=r.get("excerpt", "")[:200],
                    ).model_dump()
                    for r in results
                ],
                "query":       params.query,
                "page_size":   len(results),
                "offset":      params.offset,
                "limit":       params.limit,
                "has_more":    has_more,
                "next_offset": next_offset,
                "total_count": int(total_count) if total_known else None,
            },
            summary=(
                f"{len(results)} result(s) on this page for '{params.query}'"
                + (f" of {total_count} total" if total_known else "")
                + (f"; more available (next_offset={next_offset})" if has_more else "")
            ),
        )
    except NotesAPIError as e:
        return ActionResult.error(f"search_notes backend returned {e.status_code}: {e.detail}", code=NOTES_BACKEND_ERROR)
    except Exception as e:
        log.error("search_notes: %s", e)
        return ActionResult.error("An unexpected error occurred. Please try again.", retryable=True, code=INTERNAL)


@chat.function(
    "move_notes",
    action_type="write",
    chain_callable=True,
    effects=["update:note"],
    event="bulk_moved",
    description=(
        "Move MULTIPLE notes into the same folder at once. Pass note_ids (list of IDs) OR "
        "note_titles (list of names, auto-resolved), plus folder_id (a folder UUID or name — "
        "empty moves them to root). Use when the user wants to move 2+ notes."
    ),
    data_model=BulkFanoutResult,
)
async def fn_move_notes(ctx, params: MoveNotesParams) -> ActionResult:
    """Move a set of notes into one folder, reported per note.

    Filing a dozen notes into a folder was a dozen calls before this. There is
    no `move` action on /notes/bulk-action, so this fans out one PATCH per
    note — bounded, with a row per note so a partial run is visible.

    The target folder is resolved **once** for the whole batch rather than per
    note: the answer cannot change between notes, and resolving N times would
    add N lookups to no purpose. Getting it wrong is also the one failure that
    would hit every item at once, so it is checked before anything moves.
    """
    try:
        folder_id = await _resolve_folder_id_or_name(ctx, params.folder_id)
        if params.folder_id and not folder_id:
            return ActionResult.error(
                f"Folder '{params.folder_id}' not found. "
                "Use list_folders() to see available folders.",
                code=NOTES_FOLDER_NOT_FOUND,
            )

        oversized = _check_batch_size(
            (params.note_ids or []) + (params.note_titles or []), "notes",
        )
        if oversized:
            return oversized

        ids, not_found = await _resolve_bulk_ids(
            ctx, params.note_ids, params.note_titles, _SCOPE_ACTIVE,
        )
        if not ids:
            if not_found:
                return ActionResult.error(
                    f"No matching notes found for: {', '.join(not_found)}.",
                    code=NOTES_NOTE_NOT_FOUND,
                )
            return ActionResult.error(
                "Pass note_ids or note_titles — nothing to move.",
                code=VALIDATION_MISSING_FIELD,
            )

        uid = require_user_id(ctx)

        async def _move_one(note_id: str) -> str | None:
            await _api_patch(
                ctx, f"/notes/{note_id}", {"user_id": uid},
                {"folder_id": folder_id if folder_id else None},
            )
            return None

        # Label each row with the note's real title, not its id. `_run_fanout`
        # echoes the label back as `title`, so passing the id twice made every
        # row report a UUID where a human-readable name belongs — the batch
        # result was unreadable for the one thing it is meant to confirm.
        titles = await _titles_for(ctx, ids)
        rows = await _run_fanout(ctx, [(i, titles.get(i, i)) for i in ids], _move_one)

        moved = sum(1 for r in rows if r["ok"])
        failed = len(rows) - moved
        # Report the folder the user named, not the UUID it resolved to.
        target = (params.folder_id.strip() or "All Notes") if params.folder_id else "All Notes"

        summary = f"{moved} note(s) moved to {target}"
        if failed:
            summary += f", {failed} failed"
        if not_found:
            summary += f" ({len(not_found)} not found: {', '.join(not_found)})"

        return ActionResult.success(
            data={
                "succeeded_count": moved,
                "failed_count": failed,
                "results": rows,
                "not_found": not_found,
                "refresh_panels": ["sidebar"],
            },
            summary=summary,
        )
    except NotesAPIError as e:
        return ActionResult.error(
            f"move_notes backend returned {e.status_code}: {e.detail}",
            code=NOTES_BACKEND_ERROR,
        )
    except Exception as e:
        log.error("move_notes: %s", e)
        return ActionResult.error(
            "An unexpected error occurred. Please try again.",
            retryable=True, code=INTERNAL,
        )
