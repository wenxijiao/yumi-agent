"""Upload + file-tool security boundaries (review fixes)."""

import base64

import pytest
import yumi.tools.file_tools as file_tools
from fastapi import HTTPException
from yumi.core.features.uploads import service
from yumi.tools.file_tools import read_file


# ── #1: uploaded docs are readable; other ~/.yumi paths stay blocked ──
def test_read_file_allows_uploads_subtree_but_blocks_other_yumi(tmp_path, monkeypatch):
    uploads = tmp_path / ".yumi" / "uploads"
    monkeypatch.setattr(file_tools, "_uploads_root", lambda: uploads.resolve())

    doc = uploads / "tg_1" / "note.txt"
    doc.parent.mkdir(parents=True)
    doc.write_text("hello from an upload")
    assert "hello from an upload" in read_file(str(doc))

    cfg = tmp_path / ".yumi" / "config.json"
    cfg.write_text("{}")
    assert "refusing to read sensitive" in read_file(str(cfg))


# ── #2: session_id can't traverse out of the uploads dir ──
def test_safe_session_dir_rejects_dot_segments():
    for bad in (".", ".."):
        with pytest.raises(HTTPException):
            service._safe_session_dir(bad)
    assert service._safe_session_dir("tg_123") == "tg_123"


def test_save_rejects_destination_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "uploads_root", lambda: tmp_path)
    # a traversal owner segment must be caught by the containment assertion
    with pytest.raises(HTTPException):
        service.save_uploaded_file("s1", "x.txt", b"data", owner_user_id="..")


# ── #4: size capped before decode; base64 validated ──
def test_decode_rejects_oversize_before_decode(monkeypatch):
    monkeypatch.setattr(service, "MAX_UPLOAD_BYTES", 10)
    big = base64.b64encode(b"x" * 100).decode()  # decodes to 100 bytes > 10
    with pytest.raises(HTTPException) as ei:
        service.decode_upload_payload(big)
    assert ei.value.status_code == 413


def test_decode_rejects_invalid_base64():
    with pytest.raises(HTTPException) as ei:
        service.decode_upload_payload("not!!!valid$$$base64")
    assert ei.value.status_code == 400


def test_decode_accepts_valid_payload():
    assert service.decode_upload_payload(base64.b64encode(b"ok").decode()) == b"ok"
