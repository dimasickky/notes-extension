# Changelog

## [3.22.0] — 2026-09-07

### Added

- **Batch Undo Support (`delete_notes`, `archive_notes`)** — bulk note operations now emit an `undo` descriptor pointing to `restore_notes` / `unarchive_notes`, enabling one-click bulk restoration via Time-Travel.
- **Automated Test Suite** — added `tests/test_notes_bulk_undo.py` verifying bulk delete, bulk archive, and single delete undo flows.

## [3.21.0] — 2026-09-07

### Added

- **Semantic Omnisearch (`@ext.search_provider`)** — registered `notes` provider for Cmd+K search by title, tags, and content.
- **Stale-While-Revalidate Caching** — added `stale_while_revalidate=True, cache_ttl=60` to sidebar panel for instant UI render.
- **Action Ledger & Time-Travel (`ActionResult.success(undo=...)`)** — `delete_note` now returns an `undo` descriptor pointing to `restore_note`.

### Changed

- **imperal-sdk 5.13.1 → 5.15.1** — upgraded dependency pin and manifest contract.

## [3.20.2] — 2026-08-31

### Changed

- **imperal-sdk 5.9.22 → 5.13.1** — picks up the new gateway namespaces,
  unified callable catalog, `ui.BackButton`, tray/menu contributions and
  the `tests/`-fixture deploy scan fix.
- Note editor's action bar renders the standard `ui.BackButton`
  ("← Back") instead of a hand-rolled ghost `ArrowLeft` button — same
  `__panel__sidebar` target, one less private variant.

## [3.20.1] — 2026-08-16

### Changed

- **Bumped `imperal-sdk` 5.9.12 → 5.9.22.** Diffed both wheels directly
  (extension.py, context.py, store/client.py, types/models.py, billing/
  client.py, secrets/client.py, cli/main.py) before touching the pin: every
  change between the two versions is additive and defaulted (new
  `StoreClient.for_user()`, `if_match`/`etag` on Store, transparent retry
  wrapping in the secrets client, new billing fields, CLI fixes). Nothing in
  this module touches any of those surfaces. Zero behavior change — `imperal
  build`/`validate` both clean afterward.

## [3.20.0] — 2026-08-06

### Fixed

- **A note created in chat did not appear in the sidebar until the page was
  reloaded.** The sidebar refreshes on an exact list of event names, and that
  list held only the `event=` values declared on the handlers — but the platform
  publishes the *tool* name on one of its two publish paths, and in production
  that is the path `create_note` actually took (`notes.create_note`, not
  `notes.created`). Nothing matched, so nothing refreshed. Both naming schemes
  are now listed, so the refresh happens whichever path the platform takes. A
  duplicate refresh costs one re-fetch; a missed one loses the user's note from
  view, so listing both is the correct trade.

- **Batch actions never refreshed the sidebar.** `delete_notes`,
  `archive_notes`, `restore_notes` and the rest returned
  `refresh_panels: ["__panel__sidebar"]`. That is not a panel id — the host
  resolves bare ids (`"sidebar"`), and the prefixed value matched no panel, so
  the request went nowhere. Every batch appeared to do nothing until a reload.
  `note_save` had it right (`"sidebar"`); the bulk paths simply never followed.

- **Batch moves never refreshed either**, for a second and independent reason:
  `move_notes` publishes `notes.bulk_moved`, which was missing from the
  sidebar's list entirely.

- **`update_note` could not clear a note's body.** Emptiness was tested for
  truthiness, so `content_text=""` was indistinguishable from "field omitted"
  and the clear was silently dropped. It now distinguishes *sent* from
  *omitted* (`model_fields_set`), so passing an empty body clears it while
  leaving it out still means "keep what's there". Works through the aliases too
  (`content`, `body`), since Pydantic normalises those to the canonical name.

- **`word_count` changed after a note's first edit, without the text
  changing.** Creation counted words on the raw HTML — where `<p>` and `</p>`
  score as words — while every update stripped the tags first. Both endpoints
  now use the same counter, so the number no longer depends on which endpoint
  last wrote it. Clearing a body also resets the count, which it previously did
  not: the recount only ran when the new body was non-empty, leaving the old
  count on a now-empty note.

- **Oversized batches failed with a backend error instead of a clear message.**
  The fan-out batches enforced the 200-item ceiling, but the bulk-action ones
  went straight to a backend that caps at 500 and answers with a raw validation
  error. They now check the same ceiling, before resolving any titles — refusing
  after resolving 400 names wastes the work.

### Added

- **Atomic append — `POST /notes/{id}/append`.** `append_to_note` used to read
  the whole note, join the pieces client-side, and write the entire body back.
  Two appends that overlapped both read the same "before" text and the second
  write discarded the first one's addition — a lost update in exactly the
  scenario this function exists for. It also moved the full body across the
  network twice per append, so adding one line to a long note shipped the whole
  note twice. The concatenation now happens inside a single SQL statement, so
  only the new fragment is sent and interleaving is impossible. Verified with
  twelve concurrent appends: all twelve survive; the old path could not do that.

- **Autosave in the editor — `note_autosave`.** The body is saved as you type
  (debounced), and deliberately as a *separate* function with no declared
  event: an event would publish on every keystroke-batch, and the platform's
  event path re-fetches every panel — the open editor included — rebuilding it
  under the cursor. That is what made the earlier autosave attempt unusable in
  3.6.4. Returning an empty refresh list is not sufficient on its own, because
  the event path fires independently of it. Both stay silent. Explicit saves
  (Ctrl+S) still go through `note_save` and still refresh the sidebar.

### Changed

- **The "New Note" button can no longer leave empty notes behind.** Panel params
  are sticky — the host merges each call's params over the previous ones — so
  `note_id="new"` survived in that set and every later refresh re-entered the
  create branch and made *another* note. Nine blank "Untitled" notes came from
  this, four of them for one user inside seventy seconds, which is nobody's
  clicking speed. The branch is now idempotent: an untouched blank note is
  reopened instead of a second one being created. A note with any text in it
  never matches, and the body is confirmed before reuse — reopening a note that
  turned out to hold text would be worse than the extra empty note this avoids.

- **`create_note` no longer reports an empty note as a plain success.** A
  title-only note is legitimate and is still allowed, but it is also the exact
  shape produced when the caller's arguments get truncated mid-call: the title
  survives, the body never arrives, and the old summary said "Note created"
  either way. The emptiness is now stated in the summary and exposed as
  `content_chars`, so the failure cannot pass for a success.

## [3.19.0] — 2026-07-27

### Added

- **`move_notes`** — move several notes into one folder in a single call.
  Filing a dozen notes was a dozen calls before this.
- **`delete_attachments`** — delete several attachments in a single call.

### Notes

- **Why these two fan out while the other batches do not.** Every existing
  batch here (`delete_notes`, `archive_notes`, `restore_notes`, …) is one POST
  to `/notes/bulk-action`, which is strictly better *when the backend has an
  action for it*. There is no `move` action and no bulk attachment endpoint, so
  these two issue one request per item instead. That is the only honest option,
  and it is what makes the two extra guarantees below necessary rather than
  decorative.
- **Bounded concurrency (8), matching `tasks._BULK_CONCURRENCY`.** A serial
  loop over 40 notes is 40 serialised round trips and walks into the 180s a
  tool call gets; an unbounded gather over 200 hammers the notes backend.
- **A 200-item ceiling, checked before any request goes out.** A limit
  enforced mid-flight protects nothing — by then half the batch has already
  happened.
- **Per-item rows, not just a count.** The bulk-action tools legitimately
  return a single `affected_count` because the backend does the work in one
  shot. A fanned-out batch cannot honestly report that way: 8 separate requests
  can fail individually, so each item reports its own outcome and both counts
  appear in the summary. A partial run can never read as a clean one.
- **The target folder is resolved once per batch**, not per note. The answer
  cannot change between notes, and it is also the one failure that would hit
  every item at once — so it is checked before anything moves.

## [3.18.2] — 2026-07-27

### Fixed

- **Deleting folders by name made one backend request per name.**
  `delete_folders` resolved each name through `_resolve_folder_name`, and that
  helper fetches the *entire* folder list every call — so deleting 10 folders by
  name meant 10 identical `/folders` requests to answer a question one request
  already answers. Sibling code in `handlers_notes.py` had this right all along
  (fetch the pool once, match locally); the folder path simply never followed.

  Added `_resolve_folder_names` — one fetch, all names matched in memory. The
  matching precedence (exact, then prefix, then contains) moved into a pure
  `_match_folder_name` helper shared by both resolvers, so single-name and batch
  lookups cannot drift apart. `_resolve_folder_name` is now a one-name call into
  the same code and behaves exactly as before.

All notable changes to Imperal Notes are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

## v3.18.1 — 2026-07-27 — Skeleton freshness

### Changed
- Skeleton `ttl` 300s → 60s. Every `create_note` / `delete_note` / pin / move
  changes the counters and the recent-notes list, and the SDK's skeleton client
  is read-only — a handler cannot invalidate the section after a write, so the
  refresh tick is the only thing closing the gap. At 300s the assistant could
  answer "how many notes do I have" from a five-minute-old count immediately
  after creating one. Panels are unaffected (they always fetch fresh); this is
  purely about what the model sees.

## v3.18.0 — 2026-07-23 — Bulk folder delete

### Added
- New `delete_folders(folder_ids|folder_names, with_contents=False, permanent=False)`
  — bulk-delete multiple folders in one call, mirroring the existing bulk pattern
  for notes (`delete_notes`/`archive_notes`/etc). Backend: new `POST /folders/bulk-delete`
  on notes-api (additive, scoped to `user_id`, one transaction).
- Sidebar folder list is now `selectable=True` with bulk actions ("Delete",
  "Delete + notes") — multi-select delete instead of one-at-a-time only.
- New refresh event `notes.folders_bulk_deleted` wired into the sidebar panel.

## v3.17.1 — 2026-07-19 — SDK 5.9.12

### Changed
- Bumped `imperal-sdk` pin `5.9.11` → `5.9.12` (5.9.10 file_sinks manifest
  contract, 5.9.11 `ui.FileUpload` widget, 5.9.12 internal shared-httpx-pool
  refactor for gateway-facing clients — none of this extension's code paths
  are affected; pure pin bump, no source changes needed).

## v3.17.0 — 2026-07-18 — SDK 5.9.11 + structured error codes on every error path

### Changed
- Bumped `imperal-sdk` pin `5.9.9` → `5.9.11` (no breaking changes affect this
  extension — module imports verified clean under the new pin).
- Every `ActionResult.error(...)` call site (94 total across
  handlers_attachments.py, handlers_export.py, handlers_folders.py,
  handlers_notes.py, handlers_panel_actions.py) now carries a structured
  `code=` (SDK 5.9.7+, validator rule V32) instead of relying on prose
  alone: platform taxonomy codes (`imperal_sdk.chat.error_codes`) where
  they fit (`VALIDATION_MISSING_FIELD`, `VALIDATION_TYPE_ERROR`,
  `INTERNAL`), plus a small new app-declared set in `error_codes.py` for
  notes-specific failures the platform taxonomy doesn't cover
  (`NOTES_INVALID_NOTE_ID`, `NOTES_FOLDER_NOT_FOUND`,
  `NOTES_NOTE_NOT_FOUND`, `NOTES_BACKEND_ERROR`).
- No behavior change for users — this is diagnosability-only.

All handler modules import clean under the new pin; pyflakes clean on every
edited file (0 undefined names).

## [3.16.4] — 2026-07-18

### Fixed

- Replaced a leftover Russian example value (`'химарь'`) with an English placeholder
  (`'Groceries'`) in the `folder_id` parameter description on
  `DeleteFolderWithContentsParams` / `DeleteNotesFromFolderParams`. Cosmetic only —
  the parameter still auto-resolves any folder name, in any language.

## [3.16.3] — 2026-07-17

### Changed

- Maintenance release — rebuilt against `imperal-sdk==5.9.9` (picks up upstream fixes for
  structured error codes, provider tool-name length checks, and declared-capabilities
  enforcement). No functional or behavioral changes; `imperal validate` reports 0 errors
  against the new SDK.

## [3.16.2] — 2026-07-15

### Changed

- Maintenance release — rebuilt against `imperal-sdk==5.9.6` (picks up upstream fixes for
  app-scoped secret manifest validation and panel metadata roundtrip parity). No functional or
  behavioral changes.

---

## [3.16.1] — 2026-07-07

### Changed

- Maintenance release — rebuilt against `imperal-sdk==5.9.3` (fixes an intermittent `ctx.cache.set()`
  size-guard bug on large cache entries). No functional or behavioral changes.

---

## [3.16.0] — 2026-07-01

### Changed

- **Backend credentials are now managed as an encrypted secret.** The backend API key is declared as
  an app-scoped `@ext.secret` and read from encrypted secret storage at runtime instead of a plaintext
  environment variable — set it once in the Developer Portal → Secrets tab. No value ever lives in the
  source. Rebuilt against the latest platform SDK.

---

## [3.15.3] — 2026-06-25

### Fixed

- Extension icon now follows the active theme — light on dark backgrounds, dark on light — instead of a fixed colour.

---

## [3.15.2] — 2026-06-16

### Changed

- Maintenance release — rebuilt against the latest platform SDK. No functional or behavioral changes.

---

## [3.15.1] — 2026-06-11

### Changed

- Maintenance release — rebuilt against the latest platform SDK. No functional or behavioral changes.

---

## [3.15.0] — 2026-06-08

### Added

- Notes now carry **created** and **last-edited** timestamps in get/list results
  (the editor already displayed them), so you can ask for "my oldest note" or
  "what I edited most recently".
- **Search can reach archived/trashed notes** on request: `search_notes` accepts
  `include_archived` / `include_trashed`, and `list_notes` can filter to trash
  (`is_trashed`).

### Fixed

- **Bulk restore / unarchive by note title** now work — they look inside trash /
  archive respectively, instead of the default search (which never returns
  archived or trashed notes, so title lookup always missed them).

### Changed

- Search and the note count are active-only by default. The assistant now checks
  the archive and trash before saying a note doesn't exist, and reports
  active / archived / trash separately rather than passing off the active count
  as the grand total.

---

## [3.14.0] — 2026-06-08

### Added

- **Bulk actions on multiple notes at once.** New `delete_notes`, `archive_notes`,
  `unarchive_notes` and `restore_notes` — pass a list of note IDs or note titles and
  the action is applied to all of them in one call (delete defaults to trash; pass
  `permanent=true` to delete for good).
- **Multi-select in the sidebar.** Hover to reveal checkboxes, pick several notes, then
  use the bulk bar: in the notes view — Archive / To Trash / Delete; in Archived —
  Unarchive / To Trash / Delete; in Trash — Restore / Delete.

---

## [3.13.0] — 2026-06-03

### Changed

- **SDL: all note / folder / trash list reads now return real `sdl.EntityList[…]`**
  (`items=[...]`, `x-sdl="entity-list"`), mirroring the tasks v3.31.0 migration. Affected:
  `list_notes` → `sdl.EntityList[NoteListItem]`, `search_notes` → `sdl.EntityList[SearchNoteItem]`,
  `list_folders` → `sdl.EntityList[FolderEntity]`, `list_trash` → `sdl.EntityList[TrashNoteItem]`.
  Legacy list keys (`notes` / `results` / `folders` / `trash_notes`) are replaced by the canonical
  `items`; pagination cursors (`page_size`, `offset`, `limit`, `next_offset`, `total_count`, `query`)
  are kept as additive typed fields (`has_more` / `total` inherited from `EntityList`).
- **`TrashNoteItem` is now a real `sdl.Entity`** (`sdl.Entity, sdl.Categorized`; `id`=note_id,
  `kind="note"`) instead of a plain ad-hoc dict (`{note_id, title, …}`), so trash items expose a
  canonical SDL triple.
- **List items are `model_dump()`-ed to plain dicts** in the result payload (was: raw pydantic
  objects inside a plain `dict`, which `ActionResult.to_dict()` did not recurse into → repr-strings
  in `data_facts`).
- **Why:** the platform builds the cross-turn salient set / resolves plural anaphora ("удали эти",
  "вторую") / offers proactive set-actions ONLY from results it recognizes as an SDL entity-list.
  Note/folder reads previously did not match that shape (legacy list keys), so notes & folders
  were invisible to anaphora and proactive offers while other entity types worked. This release
  makes notes & folders behave consistently.

### Notes

- Pure extension-side change; the backend wire contract is unchanged. Panels / skeleton read the
  backend response (`{"notes":[…]}` / `{"folders":[…]}`) directly, NOT the chat-tool result, so the
  result-shape change has no panel/skeleton blast radius.

---

## [3.12.0] — 2026-06-02

### Added

- **`append_to_note(note_id, content_text)`** — appends text to the END of a note's body
  WITHOUT overwriting it (reads the current body, concatenates `old + "\n\n" + new`, then
  PATCHes the full merged text). `update_note(content_text=...)` is a FULL REPLACE with no
  append affordance, which forced the LLM to regenerate the entire body from incomplete
  context — losing prior content, or (when it had no real data) writing the user's own
  instruction text as the note body. `append_to_note` removes that pressure. Returns
  `NoteEntity` (SDL, `x-sdl=entity`) so the platform captures `note_id`/`title`
  cross-turn — same pattern as `resolve_folder` in 3.11.1.

### Changed

- **`update_note` description** now warns that `content_text` OVERWRITES the entire body
  and points to `append_to_note` for adding content.
- **system_prompt** — split "replace content" (`update_note`) vs "add/append content"
  (`append_to_note`); explicit rule that "допиши/добавь в заметку" routes to `append_to_note`
  and NEVER to `update_note`.

## [3.11.1] — 2026-06-01

### Fixed

- **`resolve_folder` now returns `FolderEntity` (SDL entity, `x-sdl=entity`).**
  Previously returned `ResolveFolderResult` (plain BaseModel) — the platform couldn't
  capture the folder UUID/title from it via the SDL path. Now returns a single `FolderEntity`
  with canonical `id`/`title`/`kind`, so the platform captures the real folder
  UUID immediately after resolve_folder is called, preventing hallucinated folder IDs
  in subsequent `create_note` chain steps.
  Not-found case now returns `ActionResult.error` with available folder names.

## [3.11.0] — 2026-05-31

### Changed

- **SDL migration (SDK 5.2.0).** `NoteEntity` (sdl.Entity + Bodied + Categorized) replaces
  `NoteRecord` for `get_note` — id/title/kind read directly by the platform.
  `NoteListItem` (sdl.Entity + Categorized) for list results. `SearchNoteItem` (sdl.Entity)
  for search results. `FolderEntity` (sdl.Entity) replaces `FolderItem` in folder lists.
- **SDK bump** `5.0.2` → `5.2.0`.
- `models_return` added to `main.py` hot-reload purge list.

## [3.10.0] — 2026-05-20

### Fixed
- **Skeleton — folders** — folder list now included in every skeleton tick (`folder_id`, `name` per folder, `folder_count`). Classifier previously had no folder data → hallucinated UUIDs when user referenced a folder by name.
- **Skeleton — `folder_id` in recent notes** — each recent note now carries its `folder_id`. Classifier can filter "last note in folder X" without guessing.
- **Skeleton — recent notes limit** — increased from 5 to 10 for better context coverage.
- **Skeleton — `asyncio.gather` resilience** — added `return_exceptions=True`; a single failing API call (e.g. `/folders` timeout) no longer drops the entire skeleton tick.

---

## [3.9.0] — 2026-05-18

### Added
- **`is_archived` filter in `list_notes`** — `ListNotesParams` now accepts `is_archived: bool | None`. Default `None` = active notes only (backend default). Pass `True` to list archived notes. Passes `is_archived` query param to backend `GET /notes`.

### Fixed
- **`export_markdown`** — `ui` widget moved from `data={}` to `ActionResult.success(ui=...)` kwarg. Putting a UINode inside `data` is incorrect per SDK contract; it bypassed DTO validation and could cause Pydantic warnings at emit time.
- **`note_save`** — added `_bad_id(params.note_id)` validation before the PATCH call. Was the only write handler missing UUID format validation.
- **`SearchNoteItem` DTO** — removed `is_archived` field. Backend `GET /notes/search/fulltext` does not return this field; it was always `False` (misleading to LLM). Handler updated to match.

---

## [3.8.0] — 2026-05-17

### Changed

- **SDK 5.0.1** — bumped `imperal-sdk` to `5.0.1` (typed return contract, additive).
- **`data_model=` migration** — all 23 `@chat.function` handlers now declare typed return DTOs via `data_model=`. New `models_return.py` with 22 Pydantic classes covering notes, folders, trash, attachments, export, and panel actions. Enables `$REF` path validation and classifier envelope `return_fields`.

---

## [3.7.0] — 2026-05-15

### Changed

- **SDK 5.0.0 migration** — bumped `imperal-sdk` to `5.0.0`. Removed deprecated `system_prompt=` kwarg from `ChatExtension` (no-op in 5.0.0). Manifest rebuilt — the legacy `tool_notes_chat` orchestrator-tool entry removed; the platform now dispatches handlers directly.
- **`update_note` — no-op detection** — handler now fetches current note before PATCH and compares fields. If nothing changed, returns `was_changed: false` without writing to backend. Response always includes `was_changed: bool` for accurate narration.

---

## [3.6.4] — 2026-05-13

### Fixed

- **Editor buttons unresponsive** — removed `on_change` from `RichEditor` (was firing on every keystroke, triggering `note_save` + panel re-render each character typed, which cancelled in-flight button clicks). `on_save` (Ctrl+S / toolbar button) is sufficient.
- **Error UX**: three places leaked raw exception details to UI — `panels_editor.py` create-note error, `note_save` unknown-field branch, `note_save` `NotesAPIError` branch — all replaced with generic messages + `log.error`.

---

## [3.6.3] — 2026-05-13

### Changed

- SDK bumped `4.2.6 → 4.2.10` — picks up OAuth callback infrastructure + `ctx.webhook_url()` (4.2.7), `SecretDecl` in Manifest schema (4.2.8/4.2.9), and `chain_callable=True` default for read handlers (4.2.10).
- `delete_notes_from_folder`: added `id_projection="folder_id"` — fixes deleting notes from a folder by name in multi-step operations (the platform previously derived the wrong target field for this compound handler name).
- `delete_attachment`: corrected `id_projection` from `"note_id"` → `"att_id"` — the platform now correctly targets the attachment ID in multi-step deletion operations.

---

## [3.6.2] — 2026-05-13

### Changed

- SDK bumped `4.2.1 → 4.2.6` — picks up EXT-SECRETS-V1 (unconditional Secrets panel in right slot), validator synthetic-tool fix (4.2.5), and `ui.Password` primitive (4.2.6). No behavioral changes for this extension.

---

## [3.6.1] — 2026-05-12

### Changed

- SDK bumped `4.2.0 → 4.2.1` — fixes MANIFEST-SKELETON-1 false positive on `@ext.tool("skeleton_alert_*")`.

---

## [3.6.0] — 2026-05-11

### Changed

- **SDK bumped `4.1.3 → 4.2.0`** — picks up manifest emitter/schema symmetry gate (4.1.6), `@ext.panel(center_overlay=True)` declarative kwarg (4.1.8), `imperal init` template fix (4.1.9), and an added validator (4.2.0). No behavioral changes for this extension.
- **Icon replaced** — new designer icon (notes-dark.svg) from Dimasickky design.

### Fixed

- **[Error UX] All 23 raw exception leaks eliminated** across all handler files. Raw `str(e)` and `f"...{e}"` were reaching users. Each site now does `log.error("fn_name: %s", e)` for operator visibility and returns a stable `ActionResult.error("An unexpected error occurred. Please try again.", retryable=True)`.
  - `handlers_notes.py` — 9 sites (list/get/create/update/move/delete/permanent_delete/bulk_delete/search)
  - `handlers_folders.py` — 9 sites (list/resolve/create/rename/delete/delete_with_contents/list_trash/restore/empty_trash)
  - `handlers_export.py` — 2 sites (duplicate_note, export_markdown)
  - `handlers_attachments.py` — 2 sites (upload_attachment, delete_attachment)
  - `handlers_panel_actions.py` — 1 site (note_save)
- **[Skeleton] `"error": str(e)` removed from degraded return in `skeleton.py`** — skeleton handlers must return zero-value dicts on failure; the previous `{"error": str(e)}` was injecting garbage into the AI assistant context on backend failure.
- **[V18] `from __future__ import annotations` removed** from `handlers_folders.py`, `handlers_attachments.py`, `handlers_panel_actions.py` — these files define Pydantic `BaseModel` param classes. Lazy string annotations created forward-reference risk that the SDK validator checks for. Files that only import models retain it.
- **[Logging] `import logging` + `log` added** to `handlers_folders.py`, `handlers_export.py`, `handlers_attachments.py`, `handlers_panel_actions.py` — required for the error logging pattern above.

---

## [3.5.0] — 2026-05-07

### Fixed

- **[P0] `fn_create_note` — folder name → 422** — `folder_id` now auto-resolved via `_resolve_folder_id_or_name` before POST. If folder not found → explicit error with folder name. Previously a 3-char name (e.g. "ало") hit the API's `len < 8` check and returned 422 with no actionable message.
- **[P0] `fn_move_note` — folder name → silent DB corruption** — same auto-resolve fix. Previously `folder_id="ало"` was stored verbatim in the DB (API PATCH has no `folder_exists` guard), leaving the note orphaned with a non-existent folder_id.
- **[P0] `fn_list_notes` — client-side tag re-filter removed** — server already does `JSON_CONTAINS` AND-match per tag. The extra client filter ran on the already-filtered page, reducing correct results. Now trusts server output entirely.
- **[P0] `fn_list_notes` — folder_id auto-resolved** — same `_resolve_folder_id_or_name` pattern. Previously a folder name silently produced `WHERE folder_id = "name"` → 0 results without error.
- **[P1] `fn_duplicate_note` — `event="notes.created"` → `event="created"`** — double prefix `notes.notes.created` was emitted; sidebar never refreshed after duplication. Fixed to `event="created"` → the platform emits `notes.created` correctly.
- **[P1] `fn_rename_folder` — folder name auto-resolved** — previously passed UUID raw; if LLM passed a name, PATCH silently returned `{status: "updated"}` with 0 rows updated.
- **[P1] `fn_delete_folder` — folder name auto-resolved** — same pattern; silent no-op on name input.
- **[P1] `fn_restore_note` — added `_bad_id()` UUID guard** — consistent with all other note-ID handlers. Previously only checked for empty string.
- **[P1] `_resolve_folder_name` — added `log.warning` on API exception** — previously caught all exceptions silently, making API errors indistinguishable from "folder not found".
- **[P1] `skeleton.py` — `pinned_notes` count now exact** — previously counted pinned notes from the first 100 results (client-side). Now uses `GET /notes?is_pinned=True&limit=1` → `total_count` from the API. Same fix for `trash_count`.
- **[P1] `list_trash` — added `has_more` / `total_count` pagination fields** — previously hard-capped at 50 with no indication of more results.

### Changed

- **`panels.py` sidebar — server-side folder filter** — when a specific folder is selected, `GET /notes?folder_id=<uuid>` is now used instead of fetching 200 notes globally and filtering client-side. Fixes missing notes in folder view for users with >200 total notes.
- **`_bad_id()` moved to `app.py`** — was duplicated in `handlers_notes.py`. Now exported from `app` and imported by both `handlers_notes` and `handlers_folders`. `handlers_notes.py` no longer defines its own `_UUID_RE`.
- **`folder_id` field descriptions updated** in `models_notes.py` (`CreateNoteParams`, `MoveNoteParams`, `ListNotesParams`) — now correctly document that folder names are accepted and auto-resolved.
- **`system_prompt.txt` routing rules updated** — rules 3, 9, 12, 13 simplified: LLM no longer needs to call `resolve_folder` before create/move/rename/delete operations; folder names accepted directly. DATA INTEGRITY section updated to reflect folder_id auto-resolution.
- **SDK bumped `4.1.2 → 4.1.3`** — pure refactor release (chat/handler.py split), no API or behavioral changes.

---

## [3.4.1] — 2026-05-05

### Fixed

- **Intent classifier anchoring** — `create_folder`, `rename_folder`, `resolve_folder` descriptions did not contain the word "notes". The intent classifier sees all tool descriptions from all extensions simultaneously with no extension-name context; generic descriptions like "Create a new folder." are ambiguous against tasks project/bucket concepts. Fixed by adding the "notes" qualifier: "Create a new notes folder.", "Rename an existing notes folder.", "Resolve a notes folder by name...".

---

## [3.4.0] — 2026-05-05

### Changed

- **SDK upgraded to `imperal-sdk==4.1.2`** — picks up Pydantic feedback-loop (4.1.0), narration schema tightening (4.1.1), and `id_projection` chain dispatch (4.1.2).
- **`id_projection` added to all compound-named chain functions** — fixes multi-step targeting for handler names where the platform would otherwise infer a non-existent target field:
  - `upload_attachment` → `id_projection="note_id"` (would infer `attachment_id` ✗)
  - `delete_attachment` → `id_projection="note_id"` (would infer wrong alias)
  - `delete_folder_with_contents` → `id_projection="folder_id"` (would infer `folder_with_contents_id` ✗)
  - `permanent_delete_note` → `id_projection="note_id"` (would infer `delete_note_id` ✗)
  - `note_save` → `id_projection="note_id"` (would infer `save_id` ✗)

---

## [3.3.1] — 2026-05-04

### Fixed

- **Removed platform-internals bypass** — `app.py` was reaching into platform internals from extension code and mutating them. Extensions must use SDK primitives only. In multi-step operations, this caused "Note must have a title or content" errors when `create_note` was auto-invoked downstream with only `folder_id` carried over. The bypass was removed; the related platform-side targeting issue for `delete_notes_from_folder` is tracked separately as a platform fix.
- **`create_note` empty params** — system prompt now explicitly instructs the LLM to ask the user for title or content (in the conversation language) instead of calling `create_note` with empty params when no details are provided.

---

## [3.3.0] — 2026-05-04

### Fixed

- **Folder operations by name** — `delete_notes_from_folder` and `delete_folder_with_contents` now accept a folder name OR UUID in `folder_id`. `_resolve_folder_id_or_name` in `app.py` detects non-UUID input and auto-resolves via `GET /folders` (exact → prefix → contains match). No separate `resolve_folder` call required from the LLM.
- **Explicit multi-step target mapping** — the platform would otherwise infer the wrong target field (`notes_from_folder_id`) for `delete_notes_from_folder`. Registered explicit target mappings for `delete_notes_from_folder`, `delete_folder_with_contents`, `create_note`, and `list_notes` so the platform correctly maps `folder_id` from the resolved folder item instead of throwing an internal error.
- **`folder_id` field description** — updated in both `DeleteNotesFromFolderParams` and `DeleteFolderWithContentsParams` to explicitly state "UUID or folder name — auto-resolved". Prevents LLM from treating the field as UUID-only and passing empty value.
- **`_UUID_RE` moved to `app.py`** — shared regex for UUID detection, used by `_resolve_folder_id_or_name`.

### Changed

- **`system_prompt.txt` routing rules 13a/13b** — updated to `folder_id=X` (name or UUID), removing the mandatory two-step `resolve_folder → delete` pattern. Both paths still work; direct name passing is now the primary.

---

## [3.2.0] — 2026-05-03

### Added

- **`delete_notes_from_folder` audit fixes** — sidebar refresh now triggers on `notes.bulk_deleted` and `notes.folder_with_contents_deleted` (previously missing); removed stale `notes.archived` / `notes.unarchived` from refresh trigger (events were never emitted).

### Fixed

- **`handlers_export.py`** — module-level `html2text.HTML2Text()` singleton replaced with `_make_h2t()` factory function; avoids shared mutable state across concurrent requests.
- **`handlers_export.py`** — removed duplicate `NoteIdParams` class; now imports canonical version from `models_notes`.
- **`main.py`** — added `models_notes` to `sys.modules` purge list so hot-reload correctly picks up model changes.
- **`system_prompt.txt`** — function count corrected 19 → 23; `duplicate_note`, `export_markdown`, `note_save`, `upload_attachment`, `delete_attachment` documented.

### Changed

- **`requirements.txt`** — SDK pin bumped `4.0.1` → `4.1.0` (Pydantic feedback loop, runtime invariants).

---

## [3.1.0] — 2026-05-02

### Added

- **`delete_notes_from_folder`** — bulk-delete all notes in a folder via `DELETE /notes/bulk`. `permanent=false` moves to trash; `permanent=true` hard-deletes. Replaces the previous loop pattern.
- **`delete_folder_with_contents`** — two-step atomic operation: (1) `DELETE /notes/bulk` for all notes in folder, (2) `DELETE /folders/{id}`. Needed because backend `DELETE /folders/{id}` only orphans notes (sets `folder_id=NULL`), it does not cascade-delete them.
- **`DELETE /notes/bulk` backend endpoint** — added to the backend; accepts `user_id`, `folder_id`, `permanent` query params. Removes or trashes all non-trashed notes in the folder in a single DB operation.
- **`system_prompt.txt` routing** — rules 13a (`delete_folder_with_contents`), 13b (`delete_notes_from_folder`), 13c (`resolve_folder`) added. Rule 13 clarified: `delete_folder` keeps notes (moves to root), does not cascade.

---

## [3.0.0] — 2026-05-01

### Breaking
- Requires `imperal-sdk==4.0.1` (SDK contract v4.0.0)

### Changed
- **SDK 4.0.1 migration** — `Extension()` now declares `display_name`, `description`, `icon`, `actions_explicit=True` (V14/V15/V21 compliance)
- **ctx.http** — replaced module-level `HTTPClient` singleton with per-request `ctx.http`; eliminates shared state between concurrent user requests
- **NotesAPIError** — replaced `httpx.HTTPStatusError` synthesis with a clean `NotesAPIError(status_code, detail, path)`; removed httpx dependency from extension code
- **chain_callable=True + effects=[]** on all write/destructive handlers (typed-dispatch contract; the platform now dispatches these directly)
- **@ext.emits declarations** — 10 event types registered in the manifest
- **ctx.cache** — folders list (TTL=60s) and folder stats (TTL=30s) cached in sidebar; folders (60s) and tags (120s) cached in editor; reduces API calls per panel render
- **Manifest schema v3** — `imperal.json` regenerated with per-tool `action_type`, `chain_callable`, `effects`, `owner_chat_tool`
- **skeleton.py** — removed `**kwargs` from `skeleton_refresh_notes`; fixed trash count query (`is_trashed=True`, was incorrectly using `is_archived=True`)
- **panels.py** — helper functions `_append_archived` / `_append_trash` now receive `ctx` directly (cleaner than `uid, tid` threading)
- **Stack direction** — updated to `"h"` / `"v"` (SDK canonical form)

### Fixed
- Skeleton trash count was reporting archived note count, not trashed note count

---

## [2.6.1] — 2026-04-30

### Fixed

- **Archive ≠ Trash** — `is_trashed` column added to DB (migration `001_add_is_trashed.sql`). Soft-delete (trash) now uses `is_trashed=TRUE`; `is_archived` is a separate flag for the Archive feature. Trash and Archived views now show different notes.
- **"Back to Notes" button** — passes `view=""` explicitly; platform was preserving previous view state without it.
- **Tag search** — backend `GET /notes` now accepts `tags=a,b` query param with `JSON_CONTAINS` per-tag filtering. Client-side fallback (capped at 200) removed.
- **Export Markdown** — `ui.Code` block with copy hint replaces the previous silent no-op. Browser file download not available from within DUI platform.
- **Restore from trash** — `restore_note` now patches `is_trashed=False` (was `is_archived=False`).

---

## [2.6.0] — 2026-04-30

### Added

- **⋮ Menu in editor action bar** — replaces standalone Archive/Delete buttons with a `ui.Menu` dropdown: Duplicate, Export Markdown, separator, Archive/Unarchive, Delete. Pin button stays standalone.
- **Duplicate note** — `duplicate_note` handler copies title, content, folder, and tags into a new note; refreshes the sidebar.
- **Export Markdown** — `export_markdown` handler converts note HTML→Markdown via `html2text`, returns `ui.Code` block with the result.
- **`handlers_export.py`** — new file for duplicate and export handlers.
- **`html2text>=2024.0.0`** — added to `requirements.txt`.

---

## [2.5.9] — 2026-04-30

### Added

- **Archive tab** — new "Archived" button in the sidebar toolbar opens a dedicated view of all archived notes with Unarchive / Delete actions. Sidebar refreshes on `notes.archived` and `notes.unarchived` events.
- **Archive/Unarchive button** in the editor action bar — toggles between "Archive" and "Unarchive" depending on the note's current state.
- **`fn_note_save` field="archive"/"unarchive"** — PATCHes `is_archived` boolean and refreshes the sidebar.

### Fixed

- **Trash "Back" button** — added explicit "← Back to Notes" button at the top of the trash view (toggling the "Trash" button was not obvious enough as a way to exit).

---

## [2.5.8] — 2026-04-30

### Fixed

- **Search pagination** — `GET /notes/search/fulltext` now supports `offset` parameter and returns `total_count` (DB-accurate, via COUNT(*)) instead of the previous `total: len(results)` which was always the page size. Extension correctly uses `total_count` to compute `has_more` and `next_offset`.
- **Search limit cap** — `SearchNotesParams.limit` max corrected from 200 → 50 to match the backend FULLTEXT cap. Added `MAX_SEARCH_PER_PAGE = 50` constant alongside existing `MAX_NOTES_PER_PAGE = 200`.

---

## [2.5.7] — 2026-04-30

### Added

- **Attachments** — new `ui.Accordion` section in the editor panel with `ui.FileUpload` (images, PDF, txt, md up to 20MB) and a list of existing attachments with delete buttons. Upload/delete handlers auto-refresh the editor panel.
- **`handlers_attachments.py`** — new file with `upload_attachment` and `delete_attachment` `@chat.function` handlers; base64 FileUpload payload decoded and forwarded to backend as multipart.
- **`_api_upload` helper** — added to `app.py` for multipart file uploads via `HTTPClient`.

---

## [2.5.6] — 2026-04-30

### Added

- **Folder selector** — `ui.Select` in the editor panel lets users move a note to a different folder without leaving the editor. Options are fetched from `GET /folders`, includes "No folder" to remove from any folder. Changes auto-save via `note_save(field="folder")` and refresh the sidebar.
- **`fn_note_save` field="folder"** — new save path in `handlers_panel_actions.py`; PATCHes `/notes/{id}` with the new `folder_id` (or `None` to unset).

---

## [2.5.5] — 2026-04-30

### Added

- **Tags editing** — `ui.TagInput` in the editor panel replaces the read-only `KeyValue("Tags: #a #b")` display. Tags are now editable inline with autocomplete suggestions sourced from all tags the user has used across their notes. Changes auto-save via `note_save(field="tags")`.
- **`GET /notes/tags` backend endpoint** — new backend route returns all unique tags for a user across active (non-archived) notes; used by the editor for tag suggestions.
- **`fn_note_save` field="tags"** — new save path in `handlers_panel_actions.py`; PATCHes `/notes/{id}` with the updated tag list and refreshes the sidebar.

---

## [2.5.4] — 2026-04-30

### Fixed

- **`handlers_folders.py`** — `fn_rename_folder` was sending `name` in the JSON body (2.5.2 regression). The backend `PATCH /folders/{id}` reads `name` as a Query parameter, not from the request body — so the body-driven path saw nothing to change and silently no-op'd. Moved `name` back to the query string; body is now empty `{}` as the API expects.
- **`requirements.txt`** — SDK pin bumped `==3.4.1` → `==3.5.0` to match the actual deployed runtime. Discrepancy was a deployment drift risk.

---

## [2.5.3] — 2026-04-29

### Changed

- **`requirements.txt`** — bump `imperal-sdk==3.0.0` → `==3.4.1`. Pulls in reasoning-model parameter handling (`max_completion_tokens` rename + `temperature` drop) so multi-step operations routed through reasoning models behave correctly. No source changes — extension code already complies with the 3.x surface (3.3.0 `ChatExtension(model=)` removal done in 2.5.2; 3.4.0 panel-slot whitelist already met by `panels.py` `slot="left"` + `panels_editor.py` `slot="center"`).

---

## [2.5.2] — 2026-04-29

Architecture audit pass: rename_folder fix + LLM-input hardening on the panel-action handler + SDK 3.3 deprecation cleanup.

### Fixed (P1)

- **`handlers_folders.py`** — `fn_rename_folder` previously sent the new name in the **query string** (`?name=…`) and an empty body to the backend PATCH. Body-driven update path saw nothing to change and the rename silently no-op'd. Moved `name` into the JSON body, query string now only carries `user_id`. Matches the pattern used by every other PATCH call in the file.

### Fixed (P2)

- **`handlers_panel_actions.py`** — `NoteSaveParams` now declares `validation_alias=AliasChoices(...)` on `note_id` / `field` / `title` / `content_text`, plus `model_config = ConfigDict(populate_by_name=True)`. Although the handler is invoked by the DUI editor's `ui.Call("note_save", ...)`, it is registered as `@chat.function` and therefore exposed to LLM tool surface; the previous shape would raise `VALIDATION_MISSING_FIELD` into chat on `noteId`/`action`/`body` calls.
- **`models_notes.py`** — `tags` field on `ListNotesParams`, `CreateNoteParams`, and `UpdateNoteParams` accepts a comma-separated string from the LLM in addition to a list (`"work,personal"` → `["work","personal"]`). LLMs occasionally serialize lists as strings; without coercion Pydantic raised `list_type` straight into chat.
- **`app.py`** — the hardcoded `ChatExtension(model=...)` was removed (deprecated since SDK 3.3.0). Model resolution now flows through the platform; the parameter will hard-error in SDK 4.0.
- **`app.py`** — health-check `except: pass`-style fallback now `log.warning(exc)` so probe failures show in the worker log, per the Dimasickky enterprise quality bar.
- **`main.py`** — module docstring no longer carries a stale `v2.4.0` version; entrypoint stays version-free, source of truth is `Extension(version=…)`.

### Compatibility

- SDK pin unchanged (`imperal-sdk==3.0.0`). 3.4.0 panel-slot validator (`slot="main"` → `ValueError`) does not affect this extension — `panels.py` already declares `slot="left"` and `panels_editor.py` `slot="center"`, both on the new whitelist.
- Wire contract with the backend unchanged. The `rename_folder` body shape was always the documented contract; pre-2.5.2 the extension just wasn't using it correctly.

---

## [2.5.1] — 2026-04-27

User-visible strings flipped to English to match the workspace English-only UI policy.

### Why

The Dimasickky enterprise quality bar was updated 2026-04-27: all user-visible static strings (`ActionResult.error/success` messages, `ui.Empty.message`, `ui.Input` placeholders, `ui.Button` labels, panel headers, footer status, validation errors) live in English. Webbee LLM localizes chat replies to the user's language automatically; static UI does not get ad-hoc translations. The previous "по-русски" directive predated international product positioning and is now retired.

### Changed

- **`handlers_notes.py`** — 6 `ActionResult.error(...)` strings flipped to English (note id required, content/title required, search query required).
- **`handlers_folders.py`** — 4 `ActionResult.error(...)` strings flipped (folder name required, folder id required, restore note id required, new folder name empty).
- **`panels.py`** — 2 `ui.Empty(message=...)` flipped (sidebar load failure, trash load failure) plus inline RU comments replaced with English.

### Not changed

- Backend, wire contract, SDK pin (`imperal-sdk==3.0.0`), `system_prompt.txt` (Russian phrases there are LLM negative-training corpus, intentional). Handler logic, routing, validation rules — all byte-equivalent to 2.5.0.

---

## [2.5.0] — 2026-04-27

SDK migration: `imperal-sdk==2.0.1` → `imperal-sdk==3.0.0` (Identity Contract Unification, W1).

### Why

SDK 3.0.0 (released 2026-04-27) deletes `imperal_sdk.auth.user.User`, makes `User`/`UserContext` frozen Pydantic v2 models with `extra="forbid"`, and renames `.id` → `.imperal_id` on user objects. There is no alias — `ctx.user.id` raises `AttributeError` on 3.x. The shared production runtime was upgraded to 3.0.0, so any 2.x-pinned extension breaks on every panel/skeleton/handler call that reads identity. Migration is mechanical but mandatory.

### Changed

- **`app.py`** — `_user_id(ctx)` and the `on_install` log line read `ctx.user.imperal_id` instead of `ctx.user.id`. `_tenant_id` already used `getattr(ctx.user, "tenant_id", None)` so it's unchanged. `require_user_id` docstring updated to reference `imperal_id`.
- **`requirements.txt`** — `imperal-sdk==2.0.1` → `imperal-sdk==3.0.0`. Equality pin retained as the workspace invariant.

### Not changed

- All other Python source, manifest, system_prompt, panels, models, handlers — byte-for-byte identical to 2.4.7. Yesterday's `/folders/stats` sidebar fix and the v2.4.x enterprise-quality hardening stand.

---

## [2.4.7] — 2026-04-27

Sidebar counters больше не упираются в 200. Раньше у юзеров с >200 заметок счётчики папок в sidebar были систематически занижены — панель тянула `/notes?limit=200` (server hard-cap) и считала bucket'ы по этим 200 строкам in-memory. Глобальный сортировщик `is_pinned DESC, updated_at DESC` смещал выборку, поэтому в разрезе папок количество было непредсказуемо неполным.

### Fixed

- **`panels.py`** — sidebar теперь читает per-folder counts из нового backend endpoint `GET /folders/stats`, который выдаёт DB-точный `GROUP BY folder_id` за один запрос. Counts для All Notes / Unfiled / каждой папки берутся из этих stats; in-memory bucketing остаётся только как graceful fallback на случай старого backend (capped, как было).

### Backend

- Новый endpoint `GET /folders/stats?user_id=&tenant_id=` (frozen wire contract, чисто аддитивный путь — старые ответы не меняются). Возвращает `{"counts": {"<folder_id>": N, "__unfiled__": M, "__all__": T, "__archived__": K}}`. Один SQL с `SUM(CASE WHEN is_archived=…)` агрегацией.
- **Bonus fix** — `POST /notes` и `POST /folders` больше не делают `SELECT *` после `INSERT`. Старый паттерн под нагрузкой давал flaky 500 (`fetchone() → None` → `AttributeError`) на ~1 из 11 параллельных insert'ов; вероятно из-за репликационного лага при routing INSERT→primary / SELECT→replica. Response теперь собирается из known data + явных `created_at/updated_at` timestamp'ов.

### Not changed

- SDK pin: `imperal-sdk==2.0.1` (без изменений).
- Wire contract существующих endpoint'ов: byte-for-byte identical.

---

## [2.4.6] — 2026-04-26

Pin bump only: `imperal-sdk==1.6.2` → `imperal-sdk==2.0.1`. No source changes.

### Why

`imperal-sdk` 2.0.1 (released 2026-04-25) supersedes the rolled-back 2.0.0 by restoring the v1.6.2 contract and shipping two platform-internal hotfixes:

- Destructive actions now defer to the platform's confirmation step instead of being blocked outright, mirroring the existing write-action behaviour.
- Action arguments are JSON-encoded for strict-mode model compatibility.

Both hotfixes are platform-internal; the SDK API surface exposed to extensions is identical to 1.6.2. Per the release note: *"v1.6.2 extensions upgrade by pin bump only."*

### Changed

- **`requirements.txt`** — `imperal-sdk==1.6.2` → `imperal-sdk==2.0.1`. Equality pin retained as the workspace invariant.

### Not changed

- All Python source, manifest tools list, system_prompt, panels, models, handlers — byte-for-byte identical to 2.4.5. Yesterday's enterprise-quality hardening (AliasChoices + fail-loud guards + AlertTriangle on API failure) stands.

---

## [2.4.5] — 2026-04-26

Enterprise-grade input hardening: no more raw Pydantic validation traces leaking to chat, no more silent `0` counters when an API call fails. First pass of the `feedback_dimasickky_enterprise_quality` checklist.

### Why this matters

Yesterday a user saw `1 validation error for CreateNoteParams content_text Field required [type=missing, input_value={'content': '...', 'title': 'Работа222'}, input_type=dict]` directly in chat. The classifier-LLM had passed `content` (a synonym) instead of `content_text`, Pydantic rejected, and the stack trace surfaced verbatim. That class of leak — internal validator output reaching the user — is incompatible with a paid extension on `panel.imperal.io`.

### Fixed

- **All Pydantic input fields wired with `validation_alias=AliasChoices(...)`** so LLM synonyms (`content`/`body`/`text` for `content_text`, `name`/`subject` for `title`, `id`/`uuid` for `note_id`, `q`/`search` for `query`, `folder`/`folderId` for `folder_id`, `labels` for `tags`, `pinned` for `is_pinned`, `page_size`/`per_page` for `limit`, `skip` for `offset`) are silently accepted instead of producing `MISSING_FIELD` errors. Wire contract with the backend stays stable — aliases are input-only.
- **All previously-required text fields now carry safe `default=""` / `default_factory=...`** — handlers normalize empty values explicitly with friendly Russian errors (`"Не указан note_id. Сначала найди заметку через search_notes."`) instead of letting Pydantic reject with a stack trace.
- **`fn_create_note` no longer creates empty notes** when both `title` and `content_text` are missing — returns an explicit error asking the LLM to provide at least one. Logs an `INFO` line when only `title` is filled (suspected folder/title confusion) so the system_prompt can be tuned later.
- **`models_notes.py` and `handlers_folders.py` model classes** all carry `model_config = ConfigDict(populate_by_name=True)` so both the canonical name and any alias can populate the field interchangeably.

### Sidebar UX

- **`panels.py` no longer renders a misleading `0` counter when the API call fails.** Both the active-notes and folders fetches now log a `WARNING` with the user id and the underlying exception, and the panel renders an explicit `ui.Empty(message="Не удалось загрузить заметки. Попробуй обновить страницу.", icon="AlertTriangle")` so the user can distinguish "no data" from "load failed". Trash view applies the same pattern.

### Out of scope

- `tool_notes_chat` system_prompt rules for title-vs-folder_id confusion and `total_count` discipline — slated for the next patch.
- `handlers_panel_actions.py` (`NoteSaveParams`) — it's panel-internal, not LLM-callable; not hardened in this pass.
- `models_notes.py` field type for `tags` (`list[str]`) when the LLM passes a comma-separated string — also next pass.

---

## [2.4.4] — 2026-04-26

Hotfix on top of 2.4.3 — sidebar showed `0` because the bumped fetch limit hit a backend server-side cap.

### Fixed

- **`panels.py` active-notes fetch limit reverted from `1000` to `200`.** The backend enforces `limit ≤ 200` at the query-validator level and returns HTTP 422 for anything higher; `_api_get` raised, the surrounding `try/except` caught it and fell through to the empty-list branch, so `total_count` ended up `0` and the sidebar displayed `0` for every user.
- **The global "All Notes" counter still reads `total_count` from the response** (the 2.4.3 intent), and that number is correct at any fetch limit — including 200 — because the API computes it server-side from the database, not from the returned page. So users past 200 notes still see the honest total.
- **Per-folder counters** stay computed from the fetched 200-item array, which keeps the bucketing correct for typical folder sizes. If a folder ever exceeds that, lifting the cap belongs in the backend, not the panel.

### Why this slipped past 2.4.3

There is no schema-shape test on `_api_get("/notes", {"limit": ...})` against the live backend validator; the change was reasoned from a curl test at `limit=1` and a PRD assumption that the cap was 200 at the panel layer, not the API layer. Adding a smoke check against the backend's query bounds before bumping limits anywhere is the lesson.

---

## [2.4.3] — 2026-04-26

Fix sidebar counters for users past the 200-note threshold. Trash counter likewise.

### Fixed

- **`panels.py` "All Notes" counter** now reads `total_count` from the backend response instead of `len(all_notes)`. Previously the sidebar fetched `limit=200` and reported the array length as the global total, so any user with more than 200 active notes saw `200` as the counter regardless of their actual count (e.g. 278 → displayed `200`).
- **Per-folder and unfiled counters** continue to be computed locally over the fetched array. To keep them accurate for larger libraries, the active-notes fetch limit moved from `200` to `1000`. Users approaching that ceiling will need a second-page fetch eventually — captured as future work, not addressed here.
- **Trash limit** raised from `50` to `200` for the same reason — archived counts past 50 were silently truncated.

### Why this matters

When the assistant said "you have 0 notes" yesterday, the underlying call was `list_notes(limit=1)` which returned a 1-element array; the LLM read the array length instead of the `total_count` field. The chat handlers (`handlers_notes.py`, `skeleton.py`) already use `total_count` correctly — only the sidebar panel and trash view were stuck on the array-length pattern. With this fix, panel UI and chat surface report the same number.

### Not changed

- `tool_notes_chat` system prompt — the LLM-side count hallucination is a separate concern (read `total_count` from the tool result instead of the array). Tracked, not patched here.

---

## [2.4.2] — 2026-04-25

Pin `imperal-sdk==1.6.2` after rolling back the v3.0.0 / SDK v2.0 rebuild. Code unchanged from 2.4.1; only the SDK constraint moves from `>=1.5.26,<1.6` to the exact runtime version in production. The v2.0 work is preserved on the `sdk-v2-migration` branch (and tagged `pre-1.6.2-rebuild-2026-04-25` on main pre-reset) for incremental re-roll once the platform's direct-dispatch path stabilises.

### Changed

- **`requirements.txt`** — `imperal-sdk>=1.5.26,<1.6` → `imperal-sdk==1.6.2`. Hard pin is required because PyPI `imperal-sdk==2.0.0` is immutable and resolver picks it without an explicit constraint (per fresh-session rollback validation 2026-04-25).

---

## [2.4.1] — 2026-04-23

Fundamental hygiene pass after a deep audit of a broken AI session where the assistant silently no-op'd on "delete notes tagged X", claimed to have "searched all N notes" after seeing only a 10-row window, and produced an inconsistent note count across multi-step operations. No behaviour changes for the assistant, but the extension now closes the feature gaps and observability holes that let those bugs hide. Mirror-patch of the sql-db 1.3.0 refactor.

### Added

- **`resolve_folder(name)`** — case-insensitive single-call folder lookup. Returns `folder_id` + `match_quality` (`exact` / `prefix` / `contains` / `none`) plus candidates on miss. Replaces the `list_folders` + re-match-by-name chain pattern, which was flaking in multi-step operations.
- **`list_notes(tags=[...])` filter** — AND-match tag filter on list. Passed to backend as `?tags=a,b`; extension-side fallback filter applied so the contract is stable even if the backend ignores the param (older backend versions).
- **`search_notes(limit, offset)`** — real pagination. Returns `has_more` / `next_offset` / `total_count` / `page_size` mirroring `list_notes`. Previously hardcoded `limit=10` with no pagination surface → LLM would claim "searched all N" after seeing a 10-row window.
- **`is_archived` on list/search/get results** — lets the LLM distinguish trashed notes from live without a round-trip to trash listing.
- **`require_user_id(ctx)` helper** — raises when `ctx` has no user attached. Used by every `@chat.function` handler so a multi-step operation that drops the user identity surfaces a loud error instead of silently scoping every backend query to no-user (indistinguishable from a real empty folder — this directly produced the inconsistent note count).
- **Title-bleed guard in `create_note`** — if `title` is a ≥3-char prefix of `content_text`, the duplicate is stripped from content start with a `log.warning`. Defends against automation/template bugs where an interpolated title ends up concatenated into the body.

### Changed

- **Raw `httpx.AsyncClient` → SDK `HTTPClient`** (`app.py`). Typed `HTTPResponse`, per-request sessioning, no cross-tenant bleed. `_raise_from()` preserves the `httpx.HTTPStatusError` contract so existing handler except-clauses keep working without ripple edits.
- **Manifest hygiene** (`imperal.json`):
  - Dropped legacy `scopes: ["*"]` wildcard on `tool_notes_chat`.
  - Dropped manually-declared `skeleton_refresh_notes` — auto-derived from `@ext.skeleton` since SDK 1.5.22.
  - `required_scopes` normalized to colon-form (`notes:read`, `notes:write`); `"*"` umbrella removed.
  - `note_save` scope: `notes.write` → `notes:write` (canonical colon-form).
- **`Extension(...)` capabilities** — now declares `capabilities=["notes:read", "notes:write"]` explicitly at construction time.
- **Pydantic models extracted** — all `BaseModel` params pulled out of `handlers_notes.py` into new `models_notes.py`. Keeps `handlers_notes.py` focused on `@chat.function` logic and safely under the 300-line cap (283 lines post-refactor).
- **`system_prompt.txt` hardening:**
  - Anti-refusal denylist extended with `"недоступна в контексте"`, `"в контексте выполнения"`, `"в контексте цепочки"`, `"chain context"`, `"execution context"`, `"функция не найдена"` — covers the hallucination pattern observed when the platform returned misrouted tool errors. (These Russian phrases are LLM negative-training corpus, intentional.)
  - NEW `PAGINATION HONESTY` block forbidding "searched all notes" claims unless `has_more=false` AND `total_count` is populated. Instructs the LLM to paginate via `next_offset` for exhaustive requests.
  - Routing updated to prefer `resolve_folder` over `list_folders`+match for single-folder lookups.
- **SDK pin** — `imperal-sdk>=1.5.26,<1.6` (from `v1.5.24` git URL). Absorbs narration guardrail, `@ext.skeleton` polish, structural contradiction guard, `check_write_arg_bleed`.

### Known limitations / deferred

- **Server-side bulk delete** — `delete_notes_by_filter(tags, folder_id, title_prefix)` deferred pending a backend `/notes/bulk-delete` endpoint. For now the LLM must loop `list_notes(tags=[...]) + delete_note(note_id)`; the `system_prompt.txt` CAPABILITY HONESTY block instructs it to do exactly that instead of silently claiming success.
- **Backend `total_count` on list/search** — `list_notes` / `search_notes` pagination prefers a DB-wide `total_count` from the backend when provided; falls back to a full-page heuristic otherwise. Pending a backend patch to surface the true count.
- **`ActionResult.error(error_code=...)` not yet adopted.** SDK 1.5.26's signature is `(error: str, retryable: bool = False)`. Same limitation as sql-db 1.3.0. Deferred pending SDK API expansion.

### Why this release matters

The AI session of 2026-04-23 produced three visible failure modes: (a) "delete notes tagged X" ended with a polite acknowledgement and nothing happened; (b) a search said "3 exact matches" then "0 exact matches" on the very next turn; (c) a folder listing reported a shrinking-then-zero count across multi-step operations. This release closes every extension-side contribution:

- **(a)** feature gap — no `tags` filter, no bulk op — now has the filter, the prompt tells the assistant to loop, and the extension will no longer pretend to succeed.
- **(b)** search hidden-cap — now has `has_more`/`total_count`, the prompt forbids false coverage claims.
- **(c)** silent empty-user scoping — now raises loudly via `require_user_id`, so a dropped user identity becomes a visible `ActionResult.error` instead of an empty list.

Platform-side bugs (user-identity propagation in multi-step operations, misrouted tool errors producing AI-synthesised refusals) are tracked separately and not in scope for this release.

---

## [2.4.0] — 2026-04-13

### Added
- `@ext.panel("editor")` — center overlay editor with `ui.RichEditor`, auto-save on change
- `@ext.panel("sidebar")` — left panel with folder tree, note list, trash view, drag & drop
- `note_save` handler — panel-specific save for title, content, pin toggle
- `@ext.health_check` — health probe for platform monitoring
- `@ext.on_install` lifecycle hook
- `panels_editor.py` split from `panels.py` (V1 file structure compliance)
- Markdown → HTML conversion in editor (`_prepare_content`)
- Folder counts in sidebar (notes per folder)
- Auto-open most recent note when no note is active

### Changed
- V1 file split: `main.py` → `app.py` + `handlers_notes.py` + `handlers_folders.py` + `handlers_panel_actions.py` + `skeleton.py` + `panels.py` + `panels_editor.py`
- All `@chat.function` params migrated to Pydantic `BaseModel` with `Field(description=...)`
- System prompt externalized to `system_prompt.txt`
- Version bump 2.3.0 → 2.4.0

---

## [2.3.0] — 2026-04-11

### Added
- `get_panel_data` — Declarative UI via `/call` endpoint (tabs: All Notes, folders, Unfiled)
- `panels.py` with `@ext.panel("sidebar")` initial implementation
- `handlers_panel_actions.py` — panel action handlers separated from chat handlers
- `imperal.json` auto-generated manifest

### Changed
- Extension split into V1 multi-file structure
- `panels.py` introduced as separate file

---

## [2.2.0] — 2026-04-08

### Added
- `move_note` — move note to folder or root
- Context strip fix in `NotesAIChat.tsx` (robust string-based approach)
- 2-Step Confirmation exact-category matching support

### Fixed
- `stripNoteContext()` regex failure due to encoding — replaced with string-based parser

---

## [2.1.0] — 2026-04-05

### Added
- Trash / Recycle Bin — soft-delete pattern
- `list_trash`, `restore_note`, `empty_trash` functions
- `permanent_delete_note` — permanent delete with disk cleanup
- Folder restore validation (folder existence check on restore)

---

## [2.0.0] — 2026-03-28

### Added
- `ChatExtension` pattern — single `tool_notes_chat` entry point
- LLM internal routing via tool_use (replaces manual dispatch)
- `create_note`, `update_note`, `delete_note`, `search_notes`
- `list_folders`, `create_folder`, `delete_folder`
- `skeleton_refresh_notes` — background stats (total, pinned, trash count, recent)
- `skeleton_alert_notes` — alert stub
- Tags support on notes
- Pin/unpin via `update_note(is_pinned=...)`

### Changed
- Full rewrite from raw `@ext.tool` to `ChatExtension` pattern
- Notes API moved to a dedicated hosted backend service (FastAPI + MySQL-compatible DB)

---

## [1.0.0] — 2026-03-01

### Added
- Initial release
- Basic note CRUD via `@ext.tool`
- Folder support
- Fulltext search (MySQL MATCH/AGAINST)
- Attachment upload and serving
- Panel UI: NotesSidebar + NoteEditor + NotesAIChat (React/Next.js)
