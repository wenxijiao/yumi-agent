"""Session-scoped file uploads stored under ``~/.yumi/uploads``."""

from __future__ import annotations

import base64
import binascii
import hashlib
import mimetypes
import re
from pathlib import Path

from fastapi import HTTPException
from yumi.core.platform.storage.sqlite_store import SQLiteStore, db_path_for_config_path

# Keep in sync with ``yumi.tools.file_tools`` supported types users typically upload.
_ALLOWED_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".txt",
        ".md",
        ".markdown",
        ".csv",
        ".json",
        ".log",
        ".rst",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
        ".html",
        ".htm",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".css",
        ".c",
        ".cpp",
        ".h",
        ".go",
        ".rs",
        ".java",
        ".sql",
        ".docx",
        # Image formats
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".svg",
        ".tiff",
        ".tif",
        ".ico",
    }
)

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".ico"})

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_SESSION_RE = re.compile(r"^[a-zA-Z0-9_.:-]{1,200}$")


def uploads_root() -> Path:
    root = Path.home() / ".yumi" / "uploads"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_session_dir(session_id: str) -> str:
    s = (session_id or "default").strip() or "default"
    if not _SESSION_RE.match(s):
        raise HTTPException(status_code=400, detail="Invalid session_id for upload.")
    # The regex permits dots, so reject the directory-traversal segments
    # explicitly — "." / ".." would escape the session's upload dir.
    if s in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid session_id for upload.")
    return s


def _safe_filename(original: str) -> str:
    base = Path(original or "").name.strip() or "upload.bin"
    base = re.sub(r"[^\w.\-]", "_", base, flags=re.ASCII)
    if not base or base in (".", ".."):
        base = "upload.bin"
    if len(base) > 200:
        stem, suf = Path(base).stem[:160], Path(base).suffix
        base = stem + suf
    ext = Path(base).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext or '(none)'}' is not allowed. Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
        )
    return base


def _unique_path(dir_path: Path, filename: str) -> Path:
    candidate = dir_path / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for n in range(1, 10_000):
        alt = dir_path / f"{stem}_{n}{suffix}"
        if not alt.exists():
            return alt
    raise HTTPException(status_code=500, detail="Could not allocate a unique filename.")


def decode_upload_payload(content_base64: str) -> bytes:
    raw = (content_base64 or "").strip()
    if "base64," in raw:
        raw = raw.split("base64,", 1)[1]
    raw = re.sub(r"\s+", "", raw)
    # Reject oversize payloads BEFORE allocating the decoded copy: base64 is ~4/3
    # the size of its bytes, so an encoded length past this can't fit the limit.
    if len(raw) > MAX_UPLOAD_BYTES * 4 // 3 + 4:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
        )
    try:
        # validate=True rejects non-alphabet characters instead of silently
        # dropping them. (Note: it's `b64decode`, not `standard_b64decode`, whose
        # `validate` keyword some 3.12 builds reject.)
        data = base64.b64decode(raw, validate=True)
    except binascii.Error as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 content.") from exc
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).",
        )
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    return data


def save_uploaded_file(
    session_id: str,
    original_filename: str,
    data: bytes,
    *,
    owner_user_id: str | None = None,
) -> dict:
    """Write bytes to disk and return a JSON-serializable result dict.

    When *owner_user_id* is provided by a caller with scoped storage needs, the
    file is stored under ``~/.yumi/uploads/<user_id>/<session>/...``.
    OSS single-user code passes ``None`` and gets the flat layout.
    """
    session_seg = _safe_session_dir(session_id)
    safe_name = _safe_filename(original_filename)
    root = uploads_root()
    if owner_user_id and owner_user_id != "_local":
        dest_dir = root / owner_user_id / session_seg
    else:
        dest_dir = root / session_seg
    # Defense in depth: the resolved destination must stay inside uploads_root.
    resolved_root = root.resolve()
    resolved_dest = dest_dir.resolve()
    if resolved_dest != resolved_root and resolved_root not in resolved_dest.parents:
        raise HTTPException(status_code=400, detail="Invalid upload destination.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique_path(dest_dir, safe_name)
    dest.write_bytes(data)
    resolved = str(dest.resolve())
    ext = Path(safe_name).suffix.lower()
    result = {
        "status": "success",
        "path": resolved,
        "saved_as": dest.name,
        "size_bytes": len(data),
        "is_image": ext in IMAGE_EXTENSIONS,
    }
    try:
        SQLiteStore(db_path_for_config_path(root.parent / "config.json")).record_file(
            session_id=session_id,
            original_name=original_filename,
            path=resolved,
            size_bytes=len(data),
            mime_type=mimetypes.guess_type(dest.name)[0] or "",
            sha256=hashlib.sha256(data).hexdigest(),
            metadata={"owner_user_id": owner_user_id or "_local", "saved_as": dest.name},
        )
    except Exception:
        pass
    return result
