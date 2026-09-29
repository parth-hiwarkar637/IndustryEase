"""
compliance.py
-------------
Post-approval obligations. Neither original backend covered this, but the
frontend has compliance.html and renewals.html, so the flow is completed here.

When an officer approves an application, the approval's catalogue entry says
which recurring compliance tasks it creates and how long the licence stays
valid. Both are generated automatically at that point.
"""

from datetime import datetime, timedelta, timezone

from database import (
    applications_table,
    compliance_table,
    renewals_table,
    projects_table,
    next_sequence,
    now_iso,
)
import approval_engine

DUE_SOON_DAYS = 30


# ------------------------------------------------------------------ helpers

def _today():
    return datetime.now(timezone.utc).date()


def _parse_date(value):
    """Accept ISO datetimes and plain YYYY-MM-DD dates."""
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def days_until(value):
    target = _parse_date(value)
    if target is None:
        return None
    return (target - _today()).days


def _derive_status(due_date, completed: bool):
    if completed:
        return "completed"
    remaining = days_until(due_date)
    if remaining is None:
        return "pending"
    if remaining < 0:
        return "overdue"
    if remaining <= DUE_SOON_DAYS:
        return "due_soon"
    return "pending"


# --------------------------------------------------------------- generation

def generate_for_application(application_id: str):
    """
    Called by the officer decision flow once an application is approved.
    Creates the compliance tasks and the renewal record for that approval.
    Safe to call twice - it will not duplicate.
    """
    application = applications_table.get(application_id)
    if not application:
        return {"compliance": [], "renewal": None}

    approval = approval_engine.get_approval(application["approval_slug"]) or {}

    created = []
    for item in approval.get("compliance_items", []):
        already = compliance_table.find_one(
            application_id=application_id, title=item["title"]
        )
        if already:
            continue
        due = _today() + timedelta(days=int(item.get("due_in_days", 90)))
        created.append(compliance_table.insert({
            "application_id": application_id,
            "project_id": application["project_id"],
            "user_id": application["user_id"],
            "title": item["title"],
            "description": item.get("description", ""),
            "icon": item.get("icon", "📄"),
            "due_date": due.isoformat(),
            "completed": False,
            "completed_at": None,
        }))

    renewal = _generate_renewal(application, approval)
    return {"compliance": created, "renewal": renewal}


def _generate_renewal(application: dict, approval: dict):
    validity_months = int(approval.get("validity_months", 0) or 0)
    if validity_months <= 0:
        return None

    existing = renewals_table.find_one(application_id=application["id"])
    if existing:
        return existing

    issued = _parse_date(application.get("decided_at")) or _today()
    # Month arithmetic without dateutil: roll the month over by hand.
    month = issued.month - 1 + validity_months
    year = issued.year + month // 12
    month = month % 12 + 1
    day = min(issued.day, 28)  # 28 keeps every month valid
    expiry = issued.replace(year=year, month=month, day=day)

    prefix = approval.get("licence_prefix", "LIC")
    number = f"{prefix}-{issued.year}-{next_sequence('licence_no', start=125):05d}"

    return renewals_table.insert({
        "application_id": application["id"],
        "project_id": application["project_id"],
        "user_id": application["user_id"],
        "title": approval.get("name", application["approval_name"]),
        "icon": approval.get("icon", "📄"),
        "licence_number": number,
        "issued_on": issued.isoformat(),
        "expiry_date": expiry.isoformat(),
        "renewed_at": None,
    })


# ------------------------------------------------------------------- reads

def list_compliance(user_id: str, project_id: str = None):
    filters = {"user_id": user_id}
    if project_id:
        filters["project_id"] = project_id

    items = []
    for row in compliance_table.find(**filters):
        row = dict(row)
        row["status"] = _derive_status(row.get("due_date"), row.get("completed", False))
        row["days_remaining"] = days_until(row.get("due_date"))
        items.append(row)

    items.sort(key=lambda r: (r["completed"], r.get("due_date") or ""))
    return items


def compliance_summary(user_id: str, project_id: str = None):
    items = list_compliance(user_id, project_id)
    return {
        "total": len(items),
        "completed": sum(1 for i in items if i["status"] == "completed"),
        "pending": sum(1 for i in items if i["status"] == "pending"),
        "due_soon": sum(1 for i in items if i["status"] in ("due_soon", "overdue")),
        "items": items,
    }


def complete_compliance(item_id: str, user_id: str):
    item = compliance_table.get(item_id)
    if not item or item.get("user_id") != user_id:
        return None
    return compliance_table.update(item_id, {
        "completed": True,
        "completed_at": now_iso(),
    })


def list_renewals(user_id: str, project_id: str = None):
    filters = {"user_id": user_id}
    if project_id:
        filters["project_id"] = project_id

    items = []
    for row in renewals_table.find(**filters):
        row = dict(row)
        remaining = days_until(row.get("expiry_date"))
        row["days_remaining"] = remaining
        if remaining is None:
            row["status"] = "active"
        elif remaining < 0:
            row["status"] = "expired"
        elif remaining <= 90:
            row["status"] = "due_soon"
        else:
            row["status"] = "active"
        items.append(row)

    items.sort(key=lambda r: r.get("expiry_date") or "")
    return items


def renewals_summary(user_id: str, project_id: str = None):
    items = list_renewals(user_id, project_id)
    return {
        "total": len(items),
        "active": sum(1 for i in items if i["status"] == "active"),
        "due_soon": sum(1 for i in items if i["status"] == "due_soon"),
        "expired": sum(1 for i in items if i["status"] == "expired"),
        "items": items,
    }


def renew(renewal_id: str, user_id: str, months: int = 12):
    """
    Extend a licence. Used by the 'Renew Now' button.

    The new term runs from the current expiry date, or from today if the
    licence has already lapsed - renewing early should not throw away the
    validity that is left on the existing licence.
    """
    row = renewals_table.get(renewal_id)
    if not row or row.get("user_id") != user_id:
        return None

    current_expiry = _parse_date(row.get("expiry_date"))
    today = _today()
    start = max(current_expiry, today) if current_expiry else today
    month = start.month - 1 + months
    year = start.year + month // 12
    month = month % 12 + 1
    expiry = start.replace(year=year, month=month, day=min(start.day, 28))

    return renewals_table.update(renewal_id, {
        "issued_on": start.isoformat(),
        "expiry_date": expiry.isoformat(),
        "renewed_at": now_iso(),
    })


def project_ids_for_user(user_id: str):
    return [p["id"] for p in projects_table.find(user_id=user_id)]
