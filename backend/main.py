"""
main.py
-------
FastAPI entrypoint for IndustryEase.

Wires auth, workflow, approval_engine, document_validator, scheme_matcher,
compliance and officer together behind one REST API, and serves the HTML
frontend from the same origin so there is nothing to configure and no CORS
problem to trip over.

Run from the project root with:
    python run.py
or directly:
    uvicorn main:app --reload --port 8000 --app-dir backend
"""

import os
import shutil
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import approval_engine
import auth
import compliance as compliance_module
import document_validator
import officer as officer_module
import scheme_matcher
import seed
import workflow
from database import documents_table

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
UPLOAD_DIR = os.environ.get("INDUSTRYEASE_UPLOAD_DIR", os.path.join(BASE_DIR, "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="IndustryEase API", version="1.0.0")

# The frontend is served from this same app, so CORS is not strictly needed.
# It stays open anyway so the pages can also be opened from a separate static
# server (e.g. VS Code Live Server) during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    seed.seed()


# --------------------------------------------------------------- error handling

def _error_handler(status_code: int):
    async def handler(request: Request, exc: Exception):
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})
    return handler


async def _auth_error_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=getattr(exc, "status_code", 400),
        content={"detail": str(exc)},
    )


app.add_exception_handler(auth.AuthError, _auth_error_handler)
app.add_exception_handler(workflow.WorkflowError, _error_handler(400))
app.add_exception_handler(approval_engine.ApprovalError, _error_handler(400))
app.add_exception_handler(document_validator.DocumentValidationError, _error_handler(400))
app.add_exception_handler(officer_module.OfficerError, _error_handler(400))


# ----------------------------------------------------------------- dependencies

def get_current_user(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="please log in to continue")
    token = authorization[len("Bearer "):].strip()
    try:
        return auth.verify_token(token)
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))


def get_current_officer(user=Depends(get_current_user)):
    auth.require_role(user, auth.OFFICER, auth.ADMIN)
    return user


# --------------------------------------------------------------- request bodies

class RegisterBody(BaseModel):
    name: str
    email: str
    password: str
    phone: str = ""
    role: str = auth.ENTREPRENEUR


class LoginBody(BaseModel):
    identifier: str
    password: str
    role: str = ""


class ProfileBody(BaseModel):
    business_name: str
    business_type: str = ""
    industry: str = ""
    state: str = ""
    employees: int = 0


class ProjectBody(BaseModel):
    project_name: str
    business_name: str
    sector: str
    location: str
    investment: float = 0
    employees: int = 0
    description: str = ""
    sector_label: str = ""


class ApplicationBody(BaseModel):
    project_id: str
    approval_slug: str


class DecisionBody(BaseModel):
    decision: str
    remarks: str = ""
    decision_date: str = ""


class QueryBody(BaseModel):
    query_type: str = "other"
    message: str
    respond_by: str = ""


class QueryResponseBody(BaseModel):
    response: str


class InspectionBody(BaseModel):
    inspection_date: str
    inspection_time: str
    location: str
    purpose: str
    officer_name: str = ""
    notes: str = ""


# ------------------------------------------------------------------------ auth

@app.post("/api/auth/register")
def register(body: RegisterBody):
    user = auth.register_user(
        name=body.name, email=body.email, password=body.password,
        phone=body.phone, role=body.role,
    )
    # Log them straight in so registration can go directly to the dashboard.
    session = auth.login_user(body.email, body.password)
    return {"user": user, "token": session["token"]}


@app.post("/api/auth/login")
def login(body: LoginBody):
    return auth.login_user(body.identifier, body.password, body.role)


@app.get("/api/auth/me")
def me(user=Depends(get_current_user)):
    return user


# --------------------------------------------------------------------- profile

@app.get("/api/profile")
def read_profile(user=Depends(get_current_user)):
    return workflow.get_profile(user["id"]) or {}


@app.put("/api/profile")
def write_profile(body: ProfileBody, user=Depends(get_current_user)):
    return workflow.save_profile(user["id"], body.model_dump())


# -------------------------------------------------------------------- projects

@app.post("/api/projects")
def create_project(body: ProjectBody, user=Depends(get_current_user)):
    return workflow.create_project(user["id"], body.model_dump())


@app.get("/api/projects")
def list_projects(user=Depends(get_current_user)):
    return workflow.list_projects(user["id"])


# Declared before /api/projects/{project_id} so "current" is not read as an id.
@app.get("/api/projects/current")
def read_current_project(user=Depends(get_current_user)):
    return workflow.current_project(user["id"]) or {}


@app.get("/api/projects/{project_id}")
def read_project(project_id: str, user=Depends(get_current_user)):
    return workflow.get_owned_project(project_id, user["id"])


@app.put("/api/projects/{project_id}")
def edit_project(project_id: str, body: ProjectBody, user=Depends(get_current_user)):
    return workflow.update_project(project_id, user["id"], body.model_dump())


# ------------------------------------------------------------------- approvals

@app.get("/api/approvals/catalog")
def approvals_catalog():
    return approval_engine.get_catalog()


@app.get("/api/approvals/catalog/{slug}")
def approval_detail(slug: str):
    approval = approval_engine.get_approval(slug)
    if not approval:
        raise HTTPException(status_code=404, detail="unknown approval type")
    return approval


@app.get("/api/approvals")
def project_approvals(project_id: str = "", user=Depends(get_current_user)):
    project = workflow.resolve_project(project_id or None, user["id"])
    return {
        "project": project,
        "approvals": approval_engine.approvals_for_project(project["id"]),
    }


# ---------------------------------------------------------------- applications

@app.post("/api/applications")
def start_application(body: ApplicationBody, user=Depends(get_current_user)):
    return workflow.start_application(body.project_id, body.approval_slug, user["id"])


@app.get("/api/applications")
def list_applications(project_id: str = "", user=Depends(get_current_user)):
    return workflow.list_applications(user["id"], project_id or None)


@app.get("/api/applications/{application_id}")
def read_application(application_id: str, user=Depends(get_current_user)):
    application = workflow.get_owned_application(application_id, user["id"])
    approval = approval_engine.get_approval(application["approval_slug"]) or {}
    return {
        "application": application,
        "approval": approval,
        "project": workflow.get_owned_project(application["project_id"], user["id"]),
        "documents": document_validator.documents_for_application(
            application_id, application["approval_slug"]
        ),
    }


@app.get("/api/applications/{application_id}/documents")
def application_documents(application_id: str, user=Depends(get_current_user)):
    application = workflow.get_owned_application(application_id, user["id"])
    checklist = document_validator.documents_for_application(
        application_id, application["approval_slug"]
    )
    return {
        "application": application,
        "documents": checklist,
        "complete": all(d["uploaded"] for d in checklist),
    }


@app.post("/api/applications/{application_id}/submit")
def submit_application(application_id: str, user=Depends(get_current_user)):
    return workflow.submit_application(application_id, user["id"])


@app.get("/api/applications/{application_id}/tracking")
def track_application(application_id: str, user=Depends(get_current_user)):
    return workflow.track_application(application_id, user["id"])


# ------------------------------------------------------------------- documents

@app.post("/api/documents/upload")
def upload_document(
    application_id: str = Form(...),
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    application = workflow.get_owned_application(application_id, user["id"])

    contents = file.file.read()
    document_validator.validate_file_basics(file.filename, len(contents))

    ext = os.path.splitext(file.filename)[1].lower()
    stored_name = f"{uuid.uuid4().hex}{ext}"
    stored_path = os.path.join(UPLOAD_DIR, stored_name)
    with open(stored_path, "wb") as out:
        out.write(contents)

    return document_validator.register_document(
        application_id=application_id,
        project_id=application["project_id"],
        user_id=user["id"],
        doc_type=doc_type,
        filename=file.filename,
        filepath=stored_path,
        size_bytes=len(contents),
    )


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: str, user=Depends(get_current_user)):
    doc = documents_table.get(document_id)
    if not doc or doc.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="document not found")
    document_validator._remove_file(doc.get("filepath"))
    documents_table.delete(document_id)
    return {"deleted": True}


# --------------------------------------------------------------------- schemes

@app.get("/api/schemes")
def list_schemes(project_id: str = "", user=Depends(get_current_user)):
    try:
        project = workflow.resolve_project(project_id or None, user["id"])
    except workflow.WorkflowError:
        # No project yet - still show the full catalogue, just unranked.
        from database import schemes_table
        return [{"scheme": s, "match_score": 0, "eligible": True}
                for s in schemes_table.all()]
    return scheme_matcher.match_schemes(project)


@app.get("/api/schemes/{slug}")
def read_scheme(slug: str):
    from database import schemes_table
    scheme = schemes_table.find_one(slug=slug) or schemes_table.get(slug)
    if not scheme:
        raise HTTPException(status_code=404, detail="scheme not found")
    return scheme


# --------------------------------------------------------- compliance & renewals

@app.get("/api/compliance")
def list_compliance(project_id: str = "", user=Depends(get_current_user)):
    return compliance_module.compliance_summary(user["id"], project_id or None)


@app.post("/api/compliance/{item_id}/complete")
def complete_compliance(item_id: str, user=Depends(get_current_user)):
    item = compliance_module.complete_compliance(item_id, user["id"])
    if not item:
        raise HTTPException(status_code=404, detail="compliance item not found")
    return item


@app.get("/api/renewals")
def list_renewals(project_id: str = "", user=Depends(get_current_user)):
    return compliance_module.renewals_summary(user["id"], project_id or None)


@app.post("/api/renewals/{renewal_id}/renew")
def renew_licence(renewal_id: str, user=Depends(get_current_user)):
    row = compliance_module.renew(renewal_id, user["id"])
    if not row:
        raise HTTPException(status_code=404, detail="renewal not found")
    return row


# --------------------------------------------------------- applicant-side queries

@app.get("/api/queries")
def my_queries(user=Depends(get_current_user)):
    return officer_module.list_queries(user_id=user["id"])


@app.post("/api/queries/{query_id}/respond")
def respond_query(query_id: str, body: QueryResponseBody, user=Depends(get_current_user)):
    return officer_module.respond_to_query(query_id, user["id"], body.response)


@app.get("/api/inspections")
def my_inspections(user=Depends(get_current_user)):
    return officer_module.list_inspections(user_id=user["id"])


# ------------------------------------------------------------------- dashboard

@app.get("/api/dashboard")
def dashboard(user=Depends(get_current_user)):
    return workflow.dashboard_summary(user["id"])


# --------------------------------------------------------------------- officer

@app.get("/api/officer/stats")
def officer_stats(user=Depends(get_current_officer)):
    return officer_module.dashboard_stats()


@app.get("/api/officer/applications")
def officer_applications(status: str = "", limit: int = 0,
                         user=Depends(get_current_officer)):
    return officer_module.list_applications(status or None, limit or None)


@app.get("/api/officer/applications/{application_id}")
def officer_application(application_id: str, user=Depends(get_current_officer)):
    return officer_module.get_application(application_id)


@app.post("/api/officer/applications/{application_id}/decision")
def officer_decision(application_id: str, body: DecisionBody,
                     user=Depends(get_current_officer)):
    return officer_module.record_decision(
        application_id, user, body.decision, body.remarks,
        body.decision_date or None,
    )


@app.post("/api/officer/applications/{application_id}/query")
def officer_query(application_id: str, body: QueryBody,
                  user=Depends(get_current_officer)):
    return officer_module.raise_query(
        application_id, user, body.query_type, body.message,
        body.respond_by or None,
    )


@app.post("/api/officer/applications/{application_id}/inspection")
def officer_inspection(application_id: str, body: InspectionBody,
                       user=Depends(get_current_officer)):
    return officer_module.schedule_inspection(
        application_id, user,
        inspection_date=body.inspection_date,
        inspection_time=body.inspection_time,
        location=body.location,
        purpose=body.purpose,
        officer_name=body.officer_name,
        notes=body.notes,
    )


@app.get("/api/officer/queries")
def officer_queries(user=Depends(get_current_officer)):
    return officer_module.list_queries()


@app.get("/api/officer/inspections")
def officer_inspections(user=Depends(get_current_officer)):
    return officer_module.list_inspections()


# ---------------------------------------------------------------------- health

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "industryease-api", "version": app.version}


# -------------------------------------------------------------- static frontend

@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# Mounted last so every /api route above takes precedence.
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
