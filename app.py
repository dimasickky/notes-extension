"""Notes · Shared state & extension setup."""
import logging
import os
import re

from pydantic import BaseModel

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def _bad_id(note_id: str) -> str | None:
    """Return error message if note_id is not a valid UUID4, else None."""
    if not note_id or not note_id.strip():
        return "note_id is required. Call list_notes() or search_notes() first to get real IDs."
    if not _UUID_RE.match(note_id.strip()):
        return (
            f"'{note_id}' is not a valid note ID. Note IDs are UUID4 strings "
            "(e.g. '3f2504e0-4f89-11d3-9a0c-0305e82c3301'). "
            "Call list_notes() or search_notes() first to get real IDs — never guess them."
        )
    return None

from imperal_sdk import Extension
from imperal_sdk.chat import ChatExtension, ActionResult  # noqa: F401 — re-exported

log = logging.getLogger("notes")

NOTES_API_URL = os.environ["NOTES_API_URL"]



# ─── Backend error ────────────────────────────────────────────────────────── #

class NotesAPIError(Exception):
    """HTTP error from the backend backend."""

    def __init__(self, status_code: int, detail: str, path: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"the backend {status_code} on {path}: {detail}")


# ─── HTTP helpers (ctx-scoped, per-request, no shared state) ─────────────── #

def _url(path: str) -> str:
    return f"{NOTES_API_URL.rstrip('/')}{path}"


async def _auth(ctx) -> dict:
    # App-scope secret from Vault (Developer Portal → Secrets). No value in code.
    key = (await ctx.secrets.get("notes_api_key")) or ""
    return {"x-api-key": key} if key else {}


def _raise_from(resp, path: str) -> None:
    """Raise NotesAPIError when the SDK HTTPResponse indicates failure."""
    if resp.ok:
        return
    body = resp.body
    if isinstance(body, dict):
        detail = body.get("detail") or str(body)
    elif isinstance(body, str):
        detail = body
    else:
        detail = f"HTTP {resp.status_code}"
    raise NotesAPIError(resp.status_code, detail, path)


async def _api_get(ctx, path: str, params: dict | None = None) -> dict:
    r = await ctx.http.get(_url(path), params=params or {}, headers=await _auth(ctx))
    _raise_from(r, path)
    body = r.body
    return body if isinstance(body, dict) else {}


async def _api_post(ctx, path: str, data: dict | None = None, params: dict | None = None) -> dict:
    r = await ctx.http.post(_url(path), json=data, params=params, headers=await _auth(ctx))
    _raise_from(r, path)
    body = r.body
    return body if isinstance(body, dict) else {}


async def _api_patch(ctx, path: str, params: dict, data: dict) -> dict:
    r = await ctx.http.patch(_url(path), params=params, json=data, headers=await _auth(ctx))
    _raise_from(r, path)
    body = r.body
    return body if isinstance(body, dict) else {}


async def _api_delete(ctx, path: str, params: dict) -> dict:
    r = await ctx.http.delete(_url(path), params=params, headers=await _auth(ctx))
    _raise_from(r, path)
    body = r.body
    return body if isinstance(body, dict) else {}


async def _api_upload(ctx, path: str, params: dict, filename: str,
                      data: bytes, content_type: str) -> dict:
    r = await ctx.http.post(
        _url(path),
        params=params,
        headers=await _auth(ctx),
        files={"file": (filename, data, content_type)},
    )
    _raise_from(r, path)
    body = r.body
    return body if isinstance(body, dict) else {}


# ─── Identity helpers ─────────────────────────────────────────────────────── #

def _user_id(ctx) -> str:
    """Return user ID or '' for anonymous contexts (panels, skeletons)."""
    return ctx.user.imperal_id if hasattr(ctx, "user") and ctx.user else ""


def require_user_id(ctx) -> str:
    """Return user ID or raise. Every @chat.function handler must call this."""
    uid = _user_id(ctx)
    if not uid:
        raise RuntimeError(
            "No authenticated user on context. Refusing to query the backend "
            "with an empty user_id (would silently return no data)."
        )
    return uid


def _tenant_id(ctx) -> str:
    if hasattr(ctx, "user") and ctx.user:
        return getattr(ctx.user, "tenant_id", None) or "default"
    return "default"


# ─── Folder name resolver (shared by delete handlers) ────────────────────── #

async def _resolve_folder_id_or_name(ctx, value: str) -> str:
    """Accept a folder UUID or display name. Returns UUID or '' if not found."""
    v = value.strip()
    if not v:
        return ""
    if _UUID_RE.match(v):
        return v
    return await _resolve_folder_name(ctx, v) or ""


def _match_folder_name(folders: list, name: str) -> str | None:
    """Pick the folder matching `name` out of an ALREADY-FETCHED list.

    Pure and local, so the matching precedence — exact, then prefix, then
    contains — lives in exactly one place and cannot drift between the
    single-name and batch resolvers below.
    """
    target = (name or "").strip().lower()
    if not target:
        return None
    exact = next((f for f in folders if f["name"].strip().lower() == target), None)
    if exact:
        return exact["id"]
    prefix = next((f for f in folders if f["name"].strip().lower().startswith(target)), None)
    if prefix:
        return prefix["id"]
    contain = next((f for f in folders if target in f["name"].strip().lower()), None)
    return contain["id"] if contain else None


async def _fetch_folders(ctx) -> list:
    """Fetch this user's folder list once. Empty list on failure (callers treat
    that as 'nothing matched', which is what the old per-name resolver did)."""
    try:
        return (await _api_get(ctx, "/folders", {
            "user_id": _user_id(ctx), "tenant_id": _tenant_id(ctx),
        })).get("folders", [])
    except Exception as e:
        log.warning("_fetch_folders: API error during lookup: %s", e)
        return []


async def _resolve_folder_name(ctx, name: str) -> str | None:
    """Return folder UUID for a given display name (case-insensitive, fuzzy). None if not found."""
    target = (name or "").strip()
    if not target:
        return None
    return _match_folder_name(await _fetch_folders(ctx), target)


async def _resolve_folder_names(ctx, names: list) -> tuple[list, list]:
    """Resolve MANY folder names with ONE backend call. Returns (ids, not_found).

    The bulk delete path used to call _resolve_folder_name per name, and that
    function fetches the whole folder list every time — so deleting 10 folders
    by name meant 10 identical requests for the same unchanging list. The folder
    set cannot change between those calls (nothing here mutates it), so the
    repeats bought nothing but latency.

    This mirrors what the notes bulk path already does one file over: fetch the
    pool once, then match every name against it in memory. Order of `ids`
    follows the order of `names`, and duplicates collapse — a user naming the
    same folder twice should not get it counted twice.
    """
    cleaned = [(n or "").strip() for n in (names or [])]
    cleaned = [n for n in cleaned if n]
    if not cleaned:
        return [], []

    folders = await _fetch_folders(ctx)
    ids: list = []
    seen: set = set()
    not_found: list = []
    for name in cleaned:
        resolved = _match_folder_name(folders, name)
        if not resolved:
            not_found.append(name)
        elif resolved not in seen:
            seen.add(resolved)
            ids.append(resolved)
    return ids, not_found


# ─── Extension ───────────────────────────────────────────────────────────── #

ext = Extension(
    "notes",
    version="3.22.0",
    capabilities=["notes:read", "notes:write"],
    display_name="Notes",
    description=(
        "Personal notes with folders, tags, full-text search, "
        "and trash management for your workspace."
    ),
    icon="icon.svg",
    actions_explicit=True,
)


# ─── Semantic Omnisearch Provider (SDK 5.15+) ─────────────────────────────── #

from imperal_sdk.search import SearchEntityResult


@ext.search_provider("notes", description="Search personal notes by title, tags, or content")
async def search_provider_notes(ctx, query: str) -> list[SearchEntityResult]:
    """Provide search results for global Cmd+K omnisearch."""
    uid, tid = _user_id(ctx), _tenant_id(ctx)
    if not query or not query.strip():
        return []
    try:
        data = await _api_get(ctx, "/notes/search", {
            "user_id": uid,
            "tenant_id": tid,
            "query": query.strip(),
            "limit": 10,
        }) or {}
        notes = data.get("notes", [])
        results = []
        for n in notes:
            nid = n.get("id", "")
            title = n.get("title", "Untitled")
            body = n.get("content_text", "")
            snippet = body[:120] if body else ""
            results.append(SearchEntityResult(
                id=nid,
                title=title,
                type="note",
                snippet=snippet,
                url=f"/workspace/notes?note_id={nid}",
                metadata={"tags": n.get("tags", []), "folder_id": n.get("folder_id")},
            ))
        return results
    except Exception as exc:
        log.warning("search_provider_notes failed: %s", exc)
        return []


# ─── Cache models (SDK 4.0 ctx.cache, Pydantic-typed, per-user TTL) ───────── #

@ext.cache_model("folders_list")
class FoldersCacheEntry(BaseModel):
    folders: list[dict]


@ext.cache_model("tags_list")
class TagsCacheEntry(BaseModel):
    tags: list[str]


@ext.cache_model("folder_stats")
class FolderStatsCacheEntry(BaseModel):
    counts: dict


# ─── Emitted events (UEB manifest §M7, SDK 3.6+) ─────────────────────────── #

@ext.emits("notes.created")
@ext.emits("notes.updated")
@ext.emits("notes.deleted")
@ext.emits("notes.permanently_deleted")
@ext.emits("notes.moved")
@ext.emits("notes.restored")
@ext.emits("notes.emptied")
@ext.emits("notes.bulk_deleted")
@ext.emits("notes.folder_created")
@ext.emits("notes.folder_renamed")
@ext.emits("notes.folder_deleted")
@ext.emits("notes.folder_with_contents_deleted")
async def _declare_events() -> None:  # pragma: no cover
    pass


# ─── ChatExtension ────────────────────────────────────────────────────────── #

chat = ChatExtension(
    ext=ext,
    tool_name="tool_notes_chat",
    description=(
        "Personal notes assistant — create, read, update, delete, search, "
        "organize notes with folders and tags, move notes, manage trash"
    ),
)


# ─── Secrets (app-scope: one developer-owned key, shared by all users) ────── #

ext.secret(
    name="notes_api_key",
    description=(
        "API key the notes backend authenticates with. Shared across all "
        "users; set once in Developer Portal → Secrets."
    ),
    scope="app",
    required=True,
    max_bytes=256,
)(lambda: None)


# ─── Lifecycle ────────────────────────────────────────────────────────────── #

@ext.health_check
async def health(ctx) -> dict:
    try:
        r = await ctx.http.get(_url("/health"), headers=await _auth(ctx))
        if not r.ok:
            return {"status": "degraded", "version": ext.version, "api": "unreachable"}
        return {"status": "ok", "version": ext.version, "api": "reachable"}
    except Exception as exc:
        log.warning("notes health check failed: %s", exc)
        return {"status": "degraded", "version": ext.version, "api": "unreachable"}


@ext.on_install
async def on_install(ctx) -> None:
    log.info("notes installed for user %s", _user_id(ctx) or "system")
