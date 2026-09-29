"""
workflow.py
-----------
From the `nirman` backend. Ties scheme_matcher, document_validator and
approval_engine together into the single journey a project actually takes:

  1. Entrepreneur registers their business profile
  2. They create a project (sector, investment, location, headcount)
  3. approval_engine works out which approvals apply
  4. They open an application for an approval and upload its documents
  5. document_validator confirms the checklist is complete
  6. The application is submitted and enters the approval chain
  7. tracking reads the current position back for the dashboard
  8. On approval, compliance/renewal obligations are created
"""

from database import (
    applications_table,
    documents_table,
    profiles_table,
    projects_table,
)
import approval_engine
import compliance as compliance_module
import document_validator
import officer
import scheme_matcher


class WorkflowError(Exception):
    pass


# ---------------------------------------------------------- business profile

def save_profile(user_id: str, data: dict):
    """Create or update the business profile behind business-profile.html."""
    fields = {
        "user_id": user_id,
        "business_name": (data.get("business_name") or "").strip(),
        "business_type": data.get("business_type", ""),
        "industry": data.get("industry", ""),
        "state": data.get("state", ""),
        "employees": int(data.get("employees") or 0),
    }
    if not fields["business_name"]:
        raise WorkflowError("business name is required")

    existing = profiles_table.find_one(user_id=user_id)
    if existing:
        return profiles_table.update(existing["id"], fields)
    return profiles_table.insert(fields)


def get_profile(user_id: str):
    return profiles_table.find_one(user_id=user_id)


# ------------------------------------------------------------------ projects

REQUIRED_PROJECT_FIELDS = (
    ("project_name", "project name"),
    ("business_name", "business name"),
    ("sector", "industry type"),
    ("location", "project location"),
)


def create_project(user_id: str, data: dict):
    for key, label in REQUIRED_PROJECT_FIELDS:
        if not (data.get(key) or "").strip():
            raise WorkflowError(f"{label} is required")

    try:
        investment = float(data.get("investment") or 0)
        employees = int(data.get("employees") or 0)
    except (TypeError, ValueError):
        raise WorkflowError("investment and employee count must be numbers")

    if investment < 0 or employees < 0:
        raise WorkflowError("investment and employee count cannot be negative")

    return projects_table.insert({
        "user_id": user_id,
        "project_name": data["project_name"].strip(),
        "business_name": data["business_name"].strip(),
        "sector": approval_engine.normalise_sector(data["sector"]),
        "sector_label": data.get("sector_label") or _sector_label(data["sector"]),
        "location": data["location"].strip(),
        "investment": investment,
        "employees": employees,
        "description": (data.get("description") or "").strip(),
        "status": "active",
    })


def update_project(project_id: str, user_id: str, data: dict):
    project = get_owned_project(project_id, user_id)
    updates = {}

    for key in ("project_name", "business_name", "location", "description"):
        if data.get(key) is not None:
            updates[key] = str(data[key]).strip()
    if data.get("sector"):
        updates["sector"] = approval_engine.normalise_sector(data["sector"])
        updates["sector_label"] = data.get("sector_label") or _sector_label(data["sector"])
    if data.get("investment") is not None:
        updates["investment"] = float(data["investment"])
    if data.get("employees") is not None:
        updates["employees"] = int(data["employees"])

    return projects_table.update(project["id"], updates)


def _sector_label(sector: str) -> str:
    known = {
        "manufacturing": "Manufacturing",
        "food_processing": "Food Processing",
        "textile": "Textile",
        "pharmaceutical": "Pharmaceutical",
        "chemical": "Chemical",
        "it": "IT / Software",
        "other": "Other",
    }
    key = approval_engine.normalise_sector(sector)
    return known.get(key, key.replace("_", " ").title())


def list_projects(user_id: str):
    projects = projects_table.find(user_id=user_id)
    projects.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return projects


def current_project(user_id: str):
    """The most recently created project - what the dashboard defaults to."""
    projects = list_projects(user_id)
    return projects[0] if projects else None


def get_owned_project(project_id: str, user_id: str):
    project = projects_table.get(project_id)
    if not project:
        raise WorkflowError("project not found")
    if project.get("user_id") != user_id:
        raise WorkflowError("this project belongs to another account")
    return project


def resolve_project(project_id, user_id):
    """Use the given project if there is one, else fall back to the latest."""
    if project_id:
        return get_owned_project(project_id, user_id)
    project = current_project(user_id)
    if not project:
        raise WorkflowError("please add your project details first")
    return project


# -------------------------------------------------------------- applications

def get_owned_application(application_id: str, user_id: str):
    application = applications_table.get(application_id)
    if not application:
        raise WorkflowError("application not found")
    if application.get("user_id") != user_id:
        raise WorkflowError("this application belongs to another account")
    return application


def start_application(project_id: str, approval_slug: str, user_id: str):
    get_owned_project(project_id, user_id)
    try:
        return approval_engine.create_application(project_id, approval_slug, user_id)
    except approval_engine.ApprovalError as e:
        raise WorkflowError(str(e))


def submit_application(application_id: str, user_id: str):
    """Step 5/6: the checklist has to be complete before this goes anywhere."""
    application = get_owned_application(application_id, user_id)

    missing = document_validator.missing_documents(
        application_id, application["approval_slug"]
    )
    if missing:
        raise WorkflowError("please upload: " + ", ".join(missing))

    try:
        return approval_engine.submit_application(application_id)
    except approval_engine.ApprovalError as e:
        raise WorkflowError(str(e))


def list_applications(user_id: str, project_id: str = None):
    filters = {"user_id": user_id}
    if project_id:
        filters["project_id"] = project_id

    applications = applications_table.find(**filters)
    applications.sort(key=lambda a: a.get("created_at") or "", reverse=True)

    enriched = []
    for app in applications:
        enriched.append({
            **app,
            "documents_uploaded": len(documents_table.find(application_id=app["id"])),
            "documents_required": len(
                document_validator.required_documents(app["approval_slug"])
            ),
        })
    return enriched


def track_application(application_id: str, user_id: str):
    """Everything tracking.html needs, in one call."""
    application = get_owned_application(application_id, user_id)
    status = approval_engine.get_approval_status(application_id)

    return {
        "application": status["application"],
        "project": projects_table.get(application["project_id"]),
        "steps": status["steps"],
        "documents": status["documents"],
        "queries": officer.list_queries(application_id=application_id),
        "inspections": officer.list_inspections(application_id=application_id),
    }


# --------------------------------------------------------------- aggregation

def dashboard_summary(user_id: str):
    """The four counters and headline info on dashboard.html."""
    project = current_project(user_id)
    applications = applications_table.find(user_id=user_id)

    required_approvals = 0
    if project:
        required_approvals = len(approval_engine.find_approvals(project))

    in_progress = sum(
        1 for a in applications if a.get("status") in approval_engine.OPEN_STATUSES
    )
    compliance_stats = compliance_module.compliance_summary(user_id)
    renewal_stats = compliance_module.renewals_summary(user_id)

    return {
        "project": project,
        "approvals": required_approvals,
        "applications_in_progress": in_progress,
        "applications_total": len(applications),
        "approved": sum(1 for a in applications
                        if a.get("status") == approval_engine.STATUS_APPROVED),
        "compliance_pending": compliance_stats["pending"] + compliance_stats["due_soon"],
        "renewals_due": renewal_stats["due_soon"] + renewal_stats["expired"],
        "open_queries": sum(1 for q in officer.list_queries(user_id=user_id)
                            if q.get("status") == "open"),
    }


def suggest_schemes(project_id: str, user_id: str):
    project = get_owned_project(project_id, user_id)
    return scheme_matcher.match_schemes(project)
