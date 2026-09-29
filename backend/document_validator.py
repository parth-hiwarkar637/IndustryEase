"""
document_validator.py
---------------------
From the `nirman` backend. Validates uploaded files (type + size) and checks
that an application has every document its approval requires before it is
allowed to move forward.
"""

import os

from database import documents_table, now_iso
import approval_engine

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".docx"}
MAX_FILE_SIZE_MB = 10


class DocumentValidationError(Exception):
    pass


def validate_file_basics(filename: str, size_bytes: int):
    """Check extension and size before the file is written to disk."""
    if not filename:
        raise DocumentValidationError("no file was selected")

    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(e.lstrip(".").upper() for e in ALLOWED_EXTENSIONS))
        raise DocumentValidationError(
            f"'{ext or 'unknown'}' files are not accepted. Allowed types: {allowed}"
        )

    if size_bytes <= 0:
        raise DocumentValidationError("the selected file is empty")

    size_mb = size_bytes / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise DocumentValidationError(
            f"file is {size_mb:.1f} MB, which is over the {MAX_FILE_SIZE_MB} MB limit"
        )
    return True


def required_documents(approval_slug: str):
    """The document checklist for an approval, straight from the catalogue."""
    approval = approval_engine.get_approval(approval_slug)
    if not approval:
        raise DocumentValidationError("unknown approval type")
    return approval.get("documents", [])


def register_document(application_id: str, project_id: str, user_id: str,
                      doc_type: str, filename: str, filepath: str, size_bytes: int = 0):
    """
    Record an uploaded document against an application. Re-uploading the same
    doc_type replaces the previous file rather than piling up duplicates.
    """
    previous = documents_table.find_one(application_id=application_id, doc_type=doc_type)
    if previous:
        documents_table.delete(previous["id"])
        _remove_file(previous.get("filepath"))

    return documents_table.insert({
        "application_id": application_id,
        "project_id": project_id,
        "user_id": user_id,
        "doc_type": doc_type,
        "filename": filename,
        "filepath": filepath,
        "size_bytes": size_bytes,
        "status": "uploaded",
        "validation_notes": "",
        "uploaded_at": now_iso(),
    })


def _remove_file(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        # A stale file on disk is not worth failing the request over.
        pass


def review_document(document_id: str, approved: bool, notes: str = ""):
    status = "verified" if approved else "rejected"
    return documents_table.update(document_id, {
        "status": status,
        "validation_notes": notes,
    })


def documents_for_application(application_id: str, approval_slug: str):
    """
    The checklist the documents.html page renders: every required document,
    each annotated with whether it has been uploaded yet.
    """
    uploaded = {d["doc_type"]: d for d in documents_table.find(application_id=application_id)}

    checklist = []
    for required in required_documents(approval_slug):
        doc = uploaded.get(required["key"])
        checklist.append({
            "key": required["key"],
            "name": required["name"],
            "hint": required.get("hint", ""),
            "uploaded": doc is not None,
            "document_id": doc["id"] if doc else None,
            "filename": doc["filename"] if doc else None,
            "status": doc["status"] if doc else "not_uploaded",
            "uploaded_at": doc.get("uploaded_at") if doc else None,
        })
    return checklist


def missing_documents(application_id: str, approval_slug: str):
    """Return the names of the documents still to be uploaded."""
    return [d["name"] for d in documents_for_application(application_id, approval_slug)
            if not d["uploaded"]]


def documents_ready(application_id: str, approval_slug: str) -> bool:
    return not missing_documents(application_id, approval_slug)
