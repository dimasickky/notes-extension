"""Notes · Sidebar panel (left)."""
from __future__ import annotations

import logging

from imperal_sdk import ui

from app import (
    ext, _api_get, _user_id, _tenant_id,
    FoldersCacheEntry, FolderStatsCacheEntry,
)

log = logging.getLogger("notes")


@ext.panel(
    "sidebar", slot="left", title="Notes", icon="StickyNote",
    default_width=280, min_width=200, max_width=500,
    stale_while_revalidate=True, cache_ttl=60,
    # Two naming schemes have to be listed, not one.
    #
    # The kernel publishes a domain event under the name the *caller* supplied:
    # when it carries an explicit event_type that is the tool name, and when it
    # falls back to result.event it is the `event=` declared on the handler. Both
    # happen in production for the same function — `create_note` was observed
    # publishing `notes.create_note` (the tool name) far more often than
    # `notes.created` (its declared event). The panel matcher is exact-match, so
    # a list holding only the declared names silently misses most refreshes and
    # a new note never shows up in the sidebar.
    #
    # Listing both names is harmless (a refresh that fires twice costs one
    # re-fetch) and is the only variant that works regardless of which path the
    # kernel took. `bulk_moved` / `move_notes` were missing entirely, which is
    # why batch moves never refreshed the list.
    refresh=(
        "on_event:"
        # declared `event=` names
        "notes.created,notes.updated,notes.deleted,notes.moved,"
        "notes.restored,notes.permanently_deleted,notes.emptied,"
        "notes.bulk_deleted,notes.bulk_archived,notes.bulk_unarchived,"
        "notes.bulk_restored,notes.bulk_moved,"
        "notes.folder_created,notes.folder_renamed,"
        "notes.folder_deleted,notes.folder_with_contents_deleted,"
        "notes.folders_bulk_deleted,"
        # tool names — same events as published on the other kernel path
        "notes.create_note,notes.update_note,notes.append_to_note,"
        "notes.note_save,notes.duplicate_note,notes.move_note,notes.move_notes,"
        "notes.delete_note,notes.delete_notes,notes.delete_notes_from_folder,"
        "notes.permanent_delete_note,notes.archive_notes,notes.unarchive_notes,"
        "notes.restore_note,notes.restore_notes,notes.empty_trash,"
        "notes.create_folder,notes.rename_folder,notes.delete_folder,"
        "notes.delete_folder_with_contents,notes.delete_folders"
    ),
)
async def notes_sidebar(ctx, folder_id: str = "", view: str = "notes",
                        active_note_id: str = "", **kwargs):
    uid, tid = _user_id(ctx), _tenant_id(ctx)

    # ── Folders (cached 60s per user) ────────────────────────────────────
    folders_failed = False
    folders: list = []
    try:
        async def _load_folders():
            data = await _api_get(ctx, "/folders", {"user_id": uid, "tenant_id": tid})
            return FoldersCacheEntry(folders=data.get("folders", []))

        entry = await ctx.cache.get_or_fetch(
            f"folders:{uid}", FoldersCacheEntry, ttl_seconds=60, fetcher=_load_folders,
        )
        folders = entry.folders
    except Exception as e:
        log.warning("sidebar: GET /folders failed for user=%s: %s", uid, e)
        folders_failed = True

    # ── Notes list (not cached — primary content, freshness required) ────
    # When a specific folder is selected, fetch server-side with folder_id filter
    # so the list is never capped by a 200-note global limit. "All Notes" and
    # "Unfiled" views still fetch up to 200 (no server-side "unfiled" filter exists).
    notes_failed = False
    all_notes: list = []
    total_count = 0
    try:
        if folder_id and folder_id not in ("", "__unfiled__"):
            notes_resp = await _api_get(ctx, "/notes", {
                "user_id": uid, "tenant_id": tid,
                "folder_id": folder_id,
                "is_archived": False, "is_trashed": False, "limit": 200,
            }) or {}
        else:
            notes_resp = await _api_get(ctx, "/notes", {
                "user_id": uid, "tenant_id": tid,
                "is_archived": False, "is_trashed": False, "limit": 200,
            }) or {}
        all_notes   = notes_resp.get("notes", [])
        total_count = int(notes_resp.get("total_count", len(all_notes)))
    except Exception as e:
        log.warning("sidebar: GET /notes failed for user=%s: %s", uid, e)
        notes_failed = True

    # ── Folder stats (cached 30s per user) ───────────────────────────────
    stats: dict = {}
    try:
        async def _load_stats():
            data = await _api_get(ctx, "/folders/stats", {"user_id": uid, "tenant_id": tid})
            return FolderStatsCacheEntry(counts=data.get("counts", {}))

        stats_entry = await ctx.cache.get_or_fetch(
            f"stats:{uid}", FolderStatsCacheEntry, ttl_seconds=30, fetcher=_load_stats,
        )
        stats = stats_entry.counts
    except Exception as e:
        log.warning("sidebar: GET /folders/stats failed for user=%s: %s — "
                    "falling back to in-memory bucketing (capped at 200)", uid, e)

    children: list = []

    trash_variant     = "secondary" if view == "trash"    else "ghost"
    archive_variant   = "secondary" if view == "archived" else "ghost"
    new_folder_variant = "secondary" if view == "new_folder" else "ghost"
    children.append(ui.Stack([
        ui.Button("New Note", icon="Plus", variant="primary", size="sm",
                  on_click=ui.Call("__panel__editor", note_id="new")),
        ui.Button("New Folder", icon="FolderPlus", variant=new_folder_variant, size="sm",
                  on_click=ui.Call("__panel__sidebar",
                                   view="notes" if view == "new_folder" else "new_folder",
                                   folder_id=folder_id)),
        ui.Button("Archived", icon="Archive", variant=archive_variant, size="sm",
                  on_click=ui.Call("__panel__sidebar",
                                   view="notes" if view == "archived" else "archived")),
        ui.Button("Trash", icon="Trash2", variant=trash_variant, size="sm",
                  on_click=ui.Call("__panel__sidebar",
                                   view="notes" if view == "trash" else "trash")),
    ], direction="h", wrap=True, sticky=True))

    if view == "new_folder":
        children.append(ui.Input(
            placeholder="Folder name, press Enter...",
            param_name="name",
            on_submit=ui.Call("create_folder", name="{{value}}"),
        ))

    rename_target_id = ""
    if view.startswith("rename_folder:"):
        rename_target_id = view.split(":", 1)[1]
        current = next((f["name"] for f in folders if f["id"] == rename_target_id), "")
        children.append(ui.Input(
            placeholder="New folder name, press Enter...",
            param_name="name",
            value=current,
            on_submit=ui.Call("rename_folder",
                              folder_id=rename_target_id, name="{{value}}"),
        ))

    if view == "archived":
        children.append(ui.Button(
            "Back to Notes", icon="ArrowLeft", variant="ghost", size="sm",
            on_click=ui.Call("__panel__sidebar", view=""),
        ))
        await _append_archived(children, ctx)
    elif view == "trash":
        children.append(ui.Button(
            "Back to Notes", icon="ArrowLeft", variant="ghost", size="sm",
            on_click=ui.Call("__panel__sidebar", view=""),
        ))
        await _append_trash(children, ctx)
    elif notes_failed or folders_failed:
        children.append(ui.Empty(
            message="Couldn't load notes. Try refreshing the page.",
            icon="AlertTriangle",
        ))
    else:
        _append_folders(children, folders, folder_id, all_notes, total_count, stats)
        _append_notes(children, all_notes, folder_id, folders, active_note_id)

    root = ui.Stack(children=children, gap=2, className="min-h-full")

    if not active_note_id and all_notes and view != "trash":
        root.props["auto_action"] = ui.Call("__panel__editor", note_id=all_notes[0]["id"])

    return root


def _count_notes_in_folder(notes: list, folder_id: str) -> int:
    return sum(1 for n in notes if n.get("folder_id") == folder_id)


def _append_folders(children: list, folders: list, active_folder: str,
                    all_notes: list, total: int, stats: dict) -> None:
    all_count = stats.get("__all__", total)
    unfiled   = stats.get("__unfiled__",
                          sum(1 for n in all_notes if not n.get("folder_id")))

    items = [
        ui.ListItem(
            id="__all__",
            title="All Notes",
            icon="FileText",
            meta=str(all_count),
            selected=(not active_folder or active_folder == "__all__"),
            on_click=ui.Call("__panel__sidebar", folder_id=""),
        ),
    ]
    for f in folders:
        count = stats.get(f["id"], _count_notes_in_folder(all_notes, f["id"]))
        items.append(ui.ListItem(
            id=f["id"],
            title=f["name"],
            icon="Folder",
            meta=str(count),
            selected=(active_folder == f["id"]),
            droppable=True,
            on_drop=ui.Call("move_note", folder_id=f["id"]),
            on_click=ui.Call("__panel__sidebar", folder_id=f["id"]),
            actions=[
                {
                    "icon": "Pencil",
                    "on_click": ui.Call("__panel__sidebar",
                                        view=f"rename_folder:{f['id']}",
                                        folder_id=f["id"]),
                },
                {
                    "icon": "Trash2",
                    "on_click": ui.Call("delete_folder", folder_id=f["id"]),
                    "confirm": f"Delete folder '{f['name']}'? Notes move to root.",
                },
            ],
        ))
    items.append(ui.ListItem(
        id="__unfiled__",
        title="Unfiled",
        icon="Inbox",
        meta=str(unfiled),
        selected=(active_folder == "__unfiled__"),
        droppable=True,
        on_drop=ui.Call("move_note", folder_id=""),
        on_click=ui.Call("__panel__sidebar", folder_id="__unfiled__"),
    ))
    children.append(ui.Divider("Folders"))
    children.append(ui.List(
        items=items,
        selectable=True,
        bulk_actions=[
            {"label": "Delete",         "icon": "Trash2",
             "action": ui.Call("delete_folders")},
            {"label": "Delete + notes", "icon": "XCircle",
             "action": ui.Call("delete_folders", with_contents=True)},
        ],
    ))


def _append_notes(children: list, all_notes: list, folder_id: str,
                  folders: list, active_note_id: str) -> None:
    if folder_id and folder_id != "__unfiled__":
        notes = [n for n in all_notes if n.get("folder_id") == folder_id]
    elif folder_id == "__unfiled__":
        notes = [n for n in all_notes if not n.get("folder_id")]
    else:
        notes = all_notes

    folder_map = {f["id"]: f["name"] for f in folders}

    items = []
    for n in notes:
        subtitle_parts = []
        if n.get("word_count"):
            subtitle_parts.append(f"{n['word_count']} words")
        fid = n.get("folder_id")
        if fid and fid in folder_map and not folder_id:
            subtitle_parts.append(folder_map[fid])

        items.append(ui.ListItem(
            id=n["id"],
            title=n.get("title", "Untitled"),
            subtitle=" · ".join(subtitle_parts) if subtitle_parts else "",
            badge=ui.Badge("pinned", color="yellow") if n.get("is_pinned") else None,
            selected=(n["id"] == active_note_id),
            draggable=True,
            on_click=ui.Call("__panel__editor", note_id=n["id"]),
            actions=[{
                "icon": "Trash2",
                "on_click": ui.Call("delete_note", note_id=n["id"]),
                "confirm": f"Move '{n.get('title', 'Untitled')}' to trash?",
            }],
        ))

    children.append(ui.Divider(f"Notes ({len(items)})"))
    children.append(ui.List(
        items=items, searchable=True, page_size=20,
        selectable=True,
        bulk_actions=[
            {"label": "Archive",  "icon": "Archive",
             "action": ui.Call("archive_notes")},
            {"label": "To Trash", "icon": "Trash2",
             "action": ui.Call("delete_notes")},
            {"label": "Delete",   "icon": "XCircle",
             "action": ui.Call("delete_notes", permanent=True)},
        ],
    ))


async def _append_archived(children: list, ctx) -> None:
    uid, tid = _user_id(ctx), _tenant_id(ctx)
    try:
        resp = await _api_get(ctx, "/notes", {
            "user_id": uid, "tenant_id": tid,
            "is_archived": True, "is_trashed": False, "limit": 200,
        })
        archived = resp.get("notes", [])
    except Exception as e:
        log.warning("sidebar archived: failed for user=%s: %s", uid, e)
        children.append(ui.Empty(
            message="Couldn't load archived notes. Try refreshing.",
            icon="AlertTriangle",
        ))
        return

    if not archived:
        children.append(ui.Empty(message="No archived notes", icon="Archive"))
        return

    items = [
        ui.ListItem(
            id=n["id"],
            title=n.get("title", "Untitled"),
            subtitle=f"{n.get('word_count', 0)} words",
            icon="Archive",
            on_click=ui.Call("__panel__editor", note_id=n["id"]),
            actions=[
                {
                    "icon": "ArchiveRestore",
                    "on_click": ui.Call("note_save", note_id=n["id"], field="unarchive"),
                },
                {
                    "icon": "Trash2",
                    "on_click": ui.Call("delete_note", note_id=n["id"]),
                    "confirm": f"Move '{n.get('title', 'Untitled')}' to trash?",
                },
            ],
        )
        for n in archived
    ]
    children.append(ui.Divider(f"Archived ({len(archived)})"))
    children.append(ui.List(
        items=items,
        selectable=True,
        bulk_actions=[
            {"label": "Unarchive", "icon": "ArchiveRestore",
             "action": ui.Call("unarchive_notes")},
            {"label": "To Trash",  "icon": "Trash2",
             "action": ui.Call("delete_notes")},
            {"label": "Delete",    "icon": "XCircle",
             "action": ui.Call("delete_notes", permanent=True)},
        ],
    ))


async def _append_trash(children: list, ctx) -> None:
    uid, tid = _user_id(ctx), _tenant_id(ctx)
    try:
        trash = (await _api_get(ctx, "/notes", {
            "user_id": uid, "tenant_id": tid,
            "is_trashed": True, "limit": 200,
        })).get("notes", [])
    except Exception as e:
        log.warning("sidebar trash: failed for user=%s: %s", uid, e)
        children.append(ui.Empty(
            message="Couldn't load trash. Try refreshing.",
            icon="AlertTriangle",
        ))
        return

    if not trash:
        children.append(ui.Empty(message="Trash is empty", icon="CheckCircle"))
        return

    items = [
        ui.ListItem(
            id=n["id"],
            title=n.get("title", "Untitled"),
            subtitle=f"{n.get('word_count', 0)} words",
            icon="Trash2",
            actions=[
                {
                    "icon": "RotateCcw",
                    "on_click": ui.Call("restore_note", note_id=n["id"]),
                },
                {
                    "icon": "XCircle",
                    "on_click": ui.Call("permanent_delete_note", note_id=n["id"]),
                    "confirm": f"Permanently delete '{n.get('title', 'Untitled')}'?",
                },
            ],
        )
        for n in trash
    ]
    children.append(ui.Divider(f"Trash ({len(trash)})"))
    children.append(ui.List(
        items=items,
        selectable=True,
        bulk_actions=[
            {"label": "Restore", "icon": "RotateCcw",
             "action": ui.Call("restore_notes")},
            {"label": "Delete",  "icon": "XCircle",
             "action": ui.Call("delete_notes", permanent=True)},
        ],
    ))
    children.append(ui.Button(
        "Empty Trash", icon="Trash2", variant="destructive", size="sm",
        on_click=ui.Call("empty_trash"),
    ))
