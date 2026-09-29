"""
approval_engine.py
------------------
This is where the two backends meet.

From the `hackathon` backend: `find_approvals()` - given a project, work out
which government approvals apply to it by matching the project's sector and
headcount against an approvals catalogue.

From the `nirman` backend: the multi-level approval chain - an application
moves through an ordered list of stages, each of which must be cleared before
the next one unlocks, and a rejection at any stage rejects the whole thing.

The two are joined by `create_application()`: a matched approval from the
catalogue becomes an application, and that application gets a chain of stages.
"""

from database import (
    applications_table,
    approval_steps_table,
    catalog_table,
    documents_table,
    projects_table,
    next_sequence,
    now_iso,
)

# Stage keys in the order an application travels through them. These line up
# with the timeline on tracking.html.
STAGE_SUBMITTED = "submitted"
STAGE_DOCUMENTS = "document_verification"
STAGE_REVIEW = "under_review"
STAGE_INSPECTION = "inspection"
STAGE_DECISION = "decision"

STAGE_LABELS = {
    STAGE_SUBMITTED: "Application Submitted",
    STAGE_DOCUMENTS: "Document Verification",
    STAGE_REVIEW: "Department Review",
    STAGE_INSPECTION: "Site Inspection",
    STAGE_DECISION: "Final Decision",
}

STAGE_DESCRIPTIONS = {
    STAGE_SUBMITTED: "Your application and required documents have been submitted successfully.",
    STAGE_DOCUMENTS: "Submitted documents are being checked by the department.",
    STAGE_REVIEW: "The department is reviewing your application.",
    STAGE_INSPECTION: "A site inspection is part of this approval.",
    STAGE_DECISION: "The final decision on your application.",
}

# Application-level statuses
STATUS_DRAFT = "draft"
STATUS_SUBMITTED = "submitted"
STATUS_UNDER_REVIEW = "under_review"
STATUS_QUERY = "query"
STATUS_INSPECTION = "inspection_scheduled"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

OPEN_STATUSES = (
    STATUS_DRAFT, STATUS_SUBMITTED, STATUS_UNDER_REVIEW,
    STATUS_QUERY, STATUS_INSPECTION,
)


class ApprovalError(Exception):
    pass


# ------------------------------------------------------------------ catalogue

def normalise_sector(value: str) -> str:
    """
    The frontend <select> uses values like "food-processing"; the hackathon
    catalogue uses "food_processing". Normalise both to the same key.
    """
    return (value or "").strip().lower().replace("-", "_").replace(" ", "_")


def get_catalog():
    return sorted(catalog_table.all(), key=lambda a: a.get("order", 99))


def get_approval(slug: str):
    """Look an approval up by its slug, e.g. "factory"."""
    return catalog_table.find_one(slug=slug)


def find_approvals(project: dict, approvals=None):
    """
    Straight from the hackathon backend's services/approval_engine.py, widened
    a little: an approval applies when the project's sector is covered and the
    project meets the minimum headcount and investment thresholds.

    Returns the matching catalogue entries, most important first.
    """
    approvals = approvals if approvals is not None else get_catalog()
    sector = normalise_sector(project.get("sector"))
    employees = int(project.get("employees") or 0)
    investment = float(project.get("investment") or 0)

    required = []
    for approval in approvals:
        sectors = [normalise_sector(s) for s in approval.get("applicable_sectors", [])]
        sector_match = ("*" in sectors) or (sector in sectors)
        employee_match = employees >= int(approval.get("minimum_employees", 0) or 0)
        investment_match = investment >= float(approval.get("minimum_investment", 0) or 0)

        if sector_match and employee_match and investment_match:
            required.append(approval)

    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    required.sort(key=lambda a: (priority_order.get(a.get("priority", "LOW"), 3),
                                 a.get("order", 99)))
    return required


def approvals_for_project(project_id: str):
    """
    What the approvals.html page renders: every applicable approval for the
    project, annotated with the status of the user's application for it (if
    they have started one yet).
    """
    project = projects_table.get(project_id)
    if not project:
        raise ApprovalError("project not found")

    existing = {
        app.get("approval_slug"): app
        for app in applications_table.find(project_id=project_id)
    }

    results = []
    for approval in find_approvals(project):
        application = existing.get(approval["slug"])
        results.append({
            "slug": approval["slug"],
            "name": approval["name"],
            "department": approval["department"],
            "description": approval.get("description", ""),
            "priority": approval.get("priority", "MEDIUM"),
            "mandatory": approval.get("mandatory", True),
            "inspection_required": approval.get("inspection_required", False),
            "documents": approval.get("documents", []),
            "application_id": application.get("id") if application else None,
            "application_status": application.get("status") if application else None,
            "reference": application.get("reference") if application else None,
        })
    return results


# ---------------------------------------------------------------- applications

def _new_reference() -> str:
    from datetime import datetime, timezone
    year = datetime.now(timezone.utc).year
    return f"IND-{year}-{next_sequence('application_ref', start=125):05d}"


def create_application(project_id: str, approval_slug: str, user_id: str):
    """
    Open (or return) the application for one approval on one project.
    Starts life as a draft - documents are attached before it is submitted.
    """
    project = projects_table.get(project_id)
    if not project:
        raise ApprovalError("project not found")

    approval = get_approval(approval_slug)
    if not approval:
        raise ApprovalError(f"unknown approval type '{approval_slug}'")

    existing = applications_table.find_one(project_id=project_id,
                                           approval_slug=approval_slug)
    if existing:
        return existing

    return applications_table.insert({
        "reference": _new_reference(),
        "project_id": project_id,
        "user_id": user_id,
        "approval_slug": approval_slug,
        "approval_name": approval["name"],
        "department": approval["department"],
        "inspection_required": approval.get("inspection_required", False),
        "status": STATUS_DRAFT,
        "submitted_at": None,
        "decided_at": None,
        "remarks": "",
    })


def submit_application(application_id: str):
    """Move a draft application into the approval chain."""
    application = applications_table.get(application_id)
    if not application:
        raise ApprovalError("application not found")
    if application["status"] not in (STATUS_DRAFT, STATUS_QUERY):
        raise ApprovalError("this application has already been submitted")

    applications_table.update(application_id, {
        "status": STATUS_SUBMITTED,
        "submitted_at": now_iso(),
    })
    start_approval_chain(application_id)
    return applications_table.get(application_id)


# -------------------------------------------------------------- approval chain

def _stages_for(application: dict):
    stages = [STAGE_SUBMITTED, STAGE_DOCUMENTS, STAGE_REVIEW]
    if application.get("inspection_required"):
        stages.append(STAGE_INSPECTION)
    stages.append(STAGE_DECISION)
    return stages


def start_approval_chain(application_id: str, stages=None):
    """
    Create the ordered stage records for a freshly submitted application.
    The first stage (submission) is already done by definition; the second is
    unlocked and pending; everything after that is locked.
    """
    application = applications_table.get(application_id)
    if not application:
        raise ApprovalError("application not found")

    # Never build the chain twice.
    if approval_steps_table.find(application_id=application_id):
        return get_steps(application_id)

    stages = stages or _stages_for(application)
    created = []
    for i, stage in enumerate(stages):
        if i == 0:
            status = "completed"
        elif i == 1:
            status = "pending"
        else:
            status = "locked"

        created.append(approval_steps_table.insert({
            "application_id": application_id,
            "stage": stage,
            "label": STAGE_LABELS.get(stage, stage.replace("_", " ").title()),
            "description": STAGE_DESCRIPTIONS.get(stage, ""),
            "sequence": i,
            "status": status,
            "officer_id": None,
            "remarks": "",
            "decided_at": now_iso() if i == 0 else None,
        }))

    applications_table.update(application_id, {"status": STATUS_UNDER_REVIEW})
    return created


def get_steps(application_id: str):
    steps = approval_steps_table.find(application_id=application_id)
    return sorted(steps, key=lambda s: s["sequence"])


def current_step(application_id: str):
    for step in get_steps(application_id):
        if step["status"] == "pending":
            return step
    return None


def get_approval_status(application_id: str):
    """Everything the tracking page needs about one application."""
    application = applications_table.get(application_id)
    if not application:
        raise ApprovalError("application not found")
    return {
        "application": application,
        "steps": get_steps(application_id),
        "documents": documents_table.find(application_id=application_id),
    }


def advance_step(application_id: str, officer_id: str, remarks: str = "",
                 stage: str = None):
    """
    Mark the current pending stage as completed and unlock the next one.
    If `stage` is given, only advance when that is the stage we are sitting on
    (so scheduling an inspection cannot accidentally clear a document check).
    """
    step = current_step(application_id)
    if not step:
        raise ApprovalError("there is no pending stage on this application")
    if stage and step["stage"] != stage:
        return step

    approval_steps_table.update(step["id"], {
        "status": "completed",
        "officer_id": officer_id,
        "remarks": remarks,
        "decided_at": now_iso(),
    })

    steps = get_steps(application_id)
    following = next((s for s in steps if s["sequence"] == step["sequence"] + 1), None)
    if following:
        approval_steps_table.update(following["id"], {"status": "pending"})
        new_status = (STATUS_INSPECTION if following["stage"] == STAGE_INSPECTION
                      else STATUS_UNDER_REVIEW)
        applications_table.update(application_id, {"status": new_status})

    return approval_steps_table.get(step["id"])


def decide(application_id: str, officer_id: str, approved: bool, remarks: str = "",
           decision_date: str = None):
    """
    Final officer decision. Completes every outstanding stage on approval, or
    marks the current stage rejected and closes the application on rejection.
    """
    application = applications_table.get(application_id)
    if not application:
        raise ApprovalError("application not found")
    if application["status"] in (STATUS_APPROVED, STATUS_REJECTED):
        raise ApprovalError("a decision has already been recorded for this application")

    steps = get_steps(application_id)
    if not steps:
        raise ApprovalError("this application has not been submitted yet")

    decided_at = decision_date or now_iso()

    if approved:
        for step in steps:
            if step["status"] in ("pending", "locked"):
                approval_steps_table.update(step["id"], {
                    "status": "completed",
                    "officer_id": officer_id,
                    "remarks": remarks if step["stage"] == STAGE_DECISION else "",
                    "decided_at": decided_at,
                })
        applications_table.update(application_id, {
            "status": STATUS_APPROVED,
            "remarks": remarks,
            "decided_at": decided_at,
        })
    else:
        target = current_step(application_id) or steps[-1]
        approval_steps_table.update(target["id"], {
            "status": "rejected",
            "officer_id": officer_id,
            "remarks": remarks,
            "decided_at": decided_at,
        })
        for step in steps:
            if step["status"] == "locked":
                approval_steps_table.update(step["id"], {"status": "cancelled"})
        applications_table.update(application_id, {
            "status": STATUS_REJECTED,
            "remarks": remarks,
            "decided_at": decided_at,
        })

    return get_approval_status(application_id)


def mark_query_raised(application_id: str, remarks: str = ""):
    applications_table.update(application_id, {
        "status": STATUS_QUERY,
        "remarks": remarks,
    })
    return applications_table.get(application_id)


def mark_inspection_scheduled(application_id: str):
    applications_table.update(application_id, {"status": STATUS_INSPECTION})
    step = current_step(application_id)
    # If the chain is still on review, push it forward to the inspection stage.
    if step and step["stage"] == STAGE_REVIEW:
        advance_step(application_id, officer_id=None,
                     remarks="Inspection scheduled", stage=STAGE_REVIEW)
    return applications_table.get(application_id)
