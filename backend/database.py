"""
database.py
-----------
JSON-file based data access layer for IndustryEase.

Originally from the `nirman` backend; extended here with the extra tables
the IndustryEase frontend needs (business profiles, compliance, renewals,
inspections, queries and the approvals catalogue).

There is no real database on purpose - everything lives under /data/*.json.
This module gives every other backend module one consistent, lock-guarded
way to read/write those files so nobody has to open() a JSON file directly.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone

# Base directory that holds all the *.json "tables"
DATA_DIR = os.environ.get(
    "INDUSTRYEASE_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
)

# One re-entrant lock per file name so concurrent requests don't corrupt a file.
_locks = {}
_locks_guard = threading.Lock()


def _lock_for(filename):
    with _locks_guard:
        if filename not in _locks:
            # RLock so a method that already holds the lock can call another one.
            _locks[filename] = threading.RLock()
        return _locks[filename]


def _path(filename):
    return os.path.join(DATA_DIR, filename)


def _ensure_file(filename):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = _path(filename)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)


def now_iso():
    """Timezone-aware UTC timestamp. `datetime.utcnow()` is deprecated in 3.12."""
    return datetime.now(timezone.utc).isoformat()


def new_id():
    return str(uuid.uuid4())


class Table:
    """
    Lightweight wrapper around one JSON file (e.g. "users.json").
    Each file holds a JSON array of objects, each with an "id".
    """

    def __init__(self, filename):
        self.filename = filename
        _ensure_file(filename)

    # ---------- internals ----------

    def _load(self):
        path = _path(self.filename)
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                return []
        return data if isinstance(data, list) else []

    def _save(self, records):
        # Write to a temp file first so a crash mid-write can't truncate the data.
        path = _path(self.filename)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, default=str)
        os.replace(tmp, path)

    # ---------- reads ----------

    def all(self):
        with _lock_for(self.filename):
            return self._load()

    def get(self, record_id):
        if record_id is None:
            return None
        for row in self.all():
            if row.get("id") == record_id:
                return row
        return None

    def find(self, **filters):
        """Return every row matching all of the keyword filters given."""
        return [
            row for row in self.all()
            if all(row.get(k) == v for k, v in filters.items())
        ]

    def find_one(self, **filters):
        results = self.find(**filters)
        return results[0] if results else None

    def count(self, **filters):
        return len(self.find(**filters)) if filters else len(self.all())

    # ---------- writes ----------

    def insert(self, record: dict):
        with _lock_for(self.filename):
            records = self._load()
            record = dict(record)
            record.setdefault("id", new_id())
            record.setdefault("created_at", now_iso())
            records.append(record)
            self._save(records)
            return record

    def update(self, record_id, updates: dict):
        with _lock_for(self.filename):
            records = self._load()
            updated = None
            for i, row in enumerate(records):
                if row.get("id") == record_id:
                    row.update(updates)
                    row["updated_at"] = now_iso()
                    records[i] = row
                    updated = row
                    break
            if updated is not None:
                self._save(records)
            return updated

    def delete(self, record_id):
        with _lock_for(self.filename):
            records = self._load()
            remaining = [r for r in records if r.get("id") != record_id]
            deleted = len(remaining) != len(records)
            if deleted:
                self._save(remaining)
            return deleted

    def replace_all(self, records):
        """Used by the seeder to reset a reference table."""
        with _lock_for(self.filename):
            self._save(list(records))
            return records


# Ready-to-import table handles, one per data file in /data
users_table = Table("users.json")
profiles_table = Table("business_profiles.json")
projects_table = Table("projects.json")
applications_table = Table("applications.json")
approval_steps_table = Table("approval_steps.json")
documents_table = Table("documents.json")
schemes_table = Table("schemes.json")
catalog_table = Table("approvals_catalog.json")
compliance_table = Table("compliance.json")
renewals_table = Table("renewals.json")
inspections_table = Table("inspections.json")
queries_table = Table("queries.json")
counters_table = Table("counters.json")


def next_sequence(name: str, start: int = 125) -> int:
    """
    Small sequence generator used for human-readable application references
    such as IND-2026-00125. Stored in counters.json so it survives restarts.
    """
    lock = _lock_for(counters_table.filename)
    with lock:
        row = counters_table.find_one(name=name)
        if row is None:
            row = counters_table.insert({"name": name, "value": start})
            return start
        value = int(row.get("value", start)) + 1
        counters_table.update(row["id"], {"value": value})
        return value
