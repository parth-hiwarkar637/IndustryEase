"""
officer.py
----------
The government-officer side of the system. This is the port of the hackathon
backend's `government.py` (which was an interactive terminal menu) into
functions the officer-dashboard, application-review, queries, inspections and
decision pages call over HTTP.

The three officer actions from the original CLI - approve, reject, raise a
query - are all here, plus scheduling a site inspection, which the frontend
needs and the CLI did not have.
"""

from database import (
    applications_table,
    documents_table,
    inspections_table,
    profiles_table,
    projects_table,
    queries_table,
    users_table,
    now_iso,
)
import approval_engine
import compliance as compliance_module


class OfficerError(Exception):
    pass


# ------------------------------------------------------------------ queues

def _decorate(application: dict):
    """Attach the project and applicant details the officer pages display."""
    project = projects_table.get(application.get("project_id")) or {}
    user = users_table.get(application.get("user_id")) or {}
    profile = profiles_table.find_one(user_id=application.get("user_id")) or {}

    return {
        **application,
        "project": project,
        "applicant_name": user.get("name", ""),
        "applicant_email": user.get("email", ""),
        "applicant_phone": user.get("phone", ""),
        "business_name": (profile.get("business_name")
                          or project.get("business_name")
                          or user.get("name", "")),
    }


def list_applications(status: str = None, limit: int = None):
    """
    Every submitted application across all applicants, newest first. Drafts
    are hidden - an officer should not see an application nobody has sent yet.
    """
    applications = [
        app for app in applications_table.all()
        if app.get("status") != approval_engine.STATUS_DRAFT
    ]
    if status:
        applications = [a for a in applications if a.get("status") == status]

    applications.sort(key=lambda a: a.get("submitted_at") or a.get("created_at") or "",
                      reverse=True)
    if limit:
        applications = applications[:limit]
    return [_decorate(a) for a in applications]


def get_application(application_id: str):
    application = applications_table.get(application_id)
    if not application:
        raise OfficerError("application not found")

    detail = _decorate(application)
    detail["steps"] = approval_engine.get_steps(application_id)
    detail["documents"] = documents_table.find(application_id=application_id)
    detail["queries"] = list_queries(application_id=application_id)
    detail["inspections"] = list_inspections(application_id=application_id)
    return detail


def dashboard_stats():
    """The four counters at the top of officer-dashboard.html."""
    applications = [
        a for a in applications_table.all()
        if a.get("status") != approval_engine.STATUS_DRAFT
    ]
    counts = {
        "total": len(applications),
        "pending": 0,
        "approved": 0,
        "rejected": 0,
        "query": 0,
    }
    pending_states = (
        approval_engine.STATUS_SUBMITTED,
        approval_engine.STATUS_UNDER_REVIEW,
        approval_engine.STATUS_INSPECTION,
    )
    for app in applications:
        status = app.get("status")
        if status in pending_states:
            counts["pending"] += 1
        elif status == approval_engine.STATUS_APPROVED:
            counts["approved"] += 1
        elif status == approval_engine.STATUS_REJECTED:
            counts["rejected"] += 1
        elif status == approval_engine.STATUS_QUERY:
            counts["query"] += 1
    return counts


# ---------------------------------------------------------------- decisions

def record_decision(application_id: str, officer, decision: str,
                    remarks: str = "", decision_date: str = None):
    """
    The `review_application` action from government.py. `decision` is one of
    approved / rejected / information (the third re-opens the application as a
    query rather than closing it).
    """
    decision = (decision or "").strip().lower()
    application = applications_table.get(application_id)
    if not application:
        raise OfficerError("application not found")
    if not remarks.strip():
        raise OfficerError("please enter remarks explaining the decision")

    if decision == "approved":
        result = approval_engine.decide(
            application_id, officer["id"], approved=True,
            remarks=remarks, decision_date=decision_date,
        )
        # Approval is what creates the post-approval obligations.
        compliance_module.generate_for_application(application_id)
        return result

    if decision == "rejected":
        return approval_engine.decide(
            application_id, officer["id"], approved=False,
            remarks=remarks, decision_date=decision_date,
        )

    if decision in ("information", "query"):
        raise_query(
            application_id=application_id,
            officer=officer,
            query_type="information",
            message=remarks,
        )
        return approval_engine.get_approval_status(application_id)

    raise OfficerError("decision must be approved, rejected or information")


# ------------------------------------------------------------------ queries

def raise_query(application_id: str, officer, query_type: str, message: str,
                respond_by: str = None):
    application = applications_table.get(application_id)
    if not application:
        raise OfficerError("application not found")
    if not (message or "").strip():
        raise OfficerError("please enter the query message")

    query = queries_table.insert({
        "application_id": application_id,
        "project_id": application["project_id"],
        "user_id": application["user_id"],
        "officer_id": officer["id"],
        "officer_name": officer.get("name", "Reviewing Officer"),
        "query_type": query_type or "other",
        "message": message.strip(),
        "respond_by": respond_by,
        "status": "open",
        "response": "",
        "responded_at": None,
    })

    approval_engine.mark_query_raised(application_id, remarks=message.strip())
    return query


def list_queries(application_id: str = None, user_id: str = None):
    filters = {}
    if application_id:
        filters["application_id"] = application_id
    if user_id:
        filters["user_id"] = user_id

    rows = queries_table.find(**filters) if filters else queries_table.all()
    rows.sort(key=lambda q: q.get("created_at") or "", reverse=True)
    return rows


def respond_to_query(query_id: str, user_id: str, response: str):
    """The applicant answering an officer's query."""
    query = queries_table.get(query_id)
    if not query or query.get("user_id") != user_id:
        raise OfficerError("query not found")
    if not (response or "").strip():
        raise OfficerError("please enter your response")

    updated = queries_table.update(query_id, {
        "response": response.strip(),
        "status": "answered",
        "responded_at": now_iso(),
    })
    # Answering a query puts the application back in the review queue.
    applications_table.update(query["application_id"],
                              {"status": approval_engine.STATUS_UNDER_REVIEW})
    return updated


# -------------------------------------------------------------- inspections

def schedule_inspection(application_id: str, officer, inspection_date: str,
                        inspection_time: str, location: str, purpose: str,
                        officer_name: str = "", notes: str = ""):
    application = applications_table.get(application_id)
    if not application:
        raise OfficerError("application not found")

    missing = [label for label, value in (
        ("inspection date", inspection_date),
        ("inspection time", inspection_time),
        ("location", location),
        ("purpose", purpose),
    ) if not (value or "").strip()]
    if missing:
        raise OfficerError("please fill in the " + ", ".join(missing))

    inspection = inspections_table.insert({
        "application_id": application_id,
        "project_id": application["project_id"],
        "user_id": application["user_id"],
        "officer_id": officer["id"],
        "officer_name": officer_name.strip() or officer.get("name", "Inspecting Officer"),
        "inspection_date": inspection_date,
        "inspection_time": inspection_time,
        "location": location,
        "purpose": purpose,
        "notes": notes,
        "status": "scheduled",
    })

    approval_engine.mark_inspection_scheduled(application_id)
    return inspection


def list_inspections(application_id: str = None, user_id: str = None):
    filters = {}
    if application_id:
        filters["application_id"] = application_id
    if user_id:
        filters["user_id"] = user_id

    rows = inspections_table.find(**filters) if filters else inspections_table.all()
    rows.sort(key=lambda i: i.get("inspection_date") or "", reverse=True)
    return rows


def complete_inspection(inspection_id: str, officer, outcome: str = "completed",
                        notes: str = ""):
    inspection = inspections_table.get(inspection_id)
    if not inspection:
        raise OfficerError("inspection not found")

    updated = inspections_table.update(inspection_id, {
        "status": outcome,
        "notes": notes or inspection.get("notes", ""),
        "completed_at": now_iso(),
    })
    approval_engine.advance_step(
        inspection["application_id"], officer["id"],
        remarks=notes or "Inspection completed",
        stage=approval_engine.STAGE_INSPECTION,
    )
    return updated
