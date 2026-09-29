"""
test_smoke.py
-------------
End-to-end check of the whole stack. Run it after installing the
requirements:

    pip install -r requirements.txt
    python tests/test_smoke.py

It walks the full journey - register, create a project, match approvals,
upload documents, submit, officer review, decision, compliance - against a
throwaway data directory, so your real data is never touched.
"""

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Point the app at a temporary data directory before anything imports it.
TMP_DATA = tempfile.mkdtemp(prefix="industryease-test-")
for reference in ("approvals_catalog.json", "schemes.json"):
    shutil.copy(os.path.join(ROOT, "data", reference), TMP_DATA)
os.environ["INDUSTRYEASE_DATA_DIR"] = TMP_DATA
os.environ["INDUSTRYEASE_UPLOAD_DIR"] = tempfile.mkdtemp(prefix="industryease-up-")

sys.path.insert(0, os.path.join(ROOT, "backend"))

try:
    from fastapi.testclient import TestClient
except ImportError:
    print("This test needs the project requirements installed:")
    print("    pip install -r requirements.txt")
    sys.exit(1)

import main  # noqa: E402

passed = []
failed = []


def ok(label, condition, detail=""):
    if condition:
        passed.append(label)
    else:
        failed.append((label, detail))


def run():
    client = TestClient(main.app)

    # ---------------------------------------------------------------- health
    r = client.get("/api/health")
    ok("health endpoint", r.status_code == 200 and r.json()["status"] == "ok", r.text)

    # --------------------------------------------------------------- the demo
    r = client.post("/api/auth/login", json={
        "identifier": "entrepreneur@demo.com",
        "password": "Entrepreneur@123",
        "role": "entrepreneur",
    })
    ok("demo entrepreneur can log in", r.status_code == 200, r.text)
    applicant = {"Authorization": "Bearer " + r.json()["token"]}

    r = client.post("/api/auth/login", json={
        "identifier": "OFF-1001", "password": "Officer@123", "role": "officer",
    })
    ok("demo officer can log in", r.status_code == 200, r.text)
    officer = {"Authorization": "Bearer " + r.json()["token"]}

    r = client.post("/api/auth/login", json={
        "identifier": "entrepreneur@demo.com", "password": "nope", "role": "",
    })
    ok("wrong password rejected", r.status_code == 400, r.text)

    r = client.get("/api/dashboard")
    ok("unauthenticated request rejected", r.status_code == 401, r.text)

    # ------------------------------------------------------------ new account
    r = client.post("/api/auth/register", json={
        "name": "Test User", "email": "test@example.com",
        "password": "Testing123", "phone": "9000000000", "role": "entrepreneur",
    })
    ok("register works", r.status_code == 200, r.text)
    fresh = {"Authorization": "Bearer " + r.json()["token"]}

    # --------------------------------------------------------------- project
    r = client.post("/api/projects", headers=fresh, json={
        "project_name": "Test Textile Unit", "business_name": "Test Weavers",
        "sector": "textile", "location": "Indore",
        "investment": 4000000, "employees": 25,
        "description": "Weaving and dyeing unit", "sector_label": "Textile",
    })
    ok("create project", r.status_code == 200, r.text)
    project = r.json()
    ok("sector normalised", project["sector"] == "textile", project["sector"])

    r = client.get("/api/approvals", headers=fresh)
    ok("approvals matched", r.status_code == 200, r.text)
    slugs = [a["slug"] for a in r.json()["approvals"]]
    ok("textile unit needs a factory licence", "factory" in slugs, str(slugs))
    ok("textile unit needs pollution consent", "pollution" in slugs, str(slugs))

    # ----------------------------------------------------------- application
    r = client.post("/api/applications", headers=fresh, json={
        "project_id": project["id"], "approval_slug": "factory",
    })
    ok("start application", r.status_code == 200, r.text)
    application = r.json()
    ok("reference generated", application["reference"].startswith("IND-"),
       application["reference"])

    r = client.post("/api/applications/%s/submit" % application["id"], headers=fresh)
    ok("submit blocked while documents missing", r.status_code == 400, r.text)

    # ------------------------------------------------------------- documents
    r = client.get("/api/applications/%s/documents" % application["id"], headers=fresh)
    checklist = r.json()["documents"]
    ok("checklist returned", len(checklist) == 5, str(len(checklist)))

    r = client.post("/api/documents/upload", headers=fresh,
                    data={"application_id": application["id"], "doc_type": "identity_proof"},
                    files={"file": ("id.exe", b"nope", "application/octet-stream")})
    ok("bad file type rejected", r.status_code == 400, r.text)

    for item in checklist:
        r = client.post("/api/documents/upload", headers=fresh,
                        data={"application_id": application["id"], "doc_type": item["key"]},
                        files={"file": (item["key"] + ".pdf", b"%PDF-1.4 test",
                                        "application/pdf")})
        ok("upload " + item["key"], r.status_code == 200, r.text)

    r = client.get("/api/applications/%s/documents" % application["id"], headers=fresh)
    ok("checklist complete", r.json()["complete"] is True, r.text)

    r = client.post("/api/applications/%s/submit" % application["id"], headers=fresh)
    ok("submit succeeds", r.status_code == 200, r.text)
    ok("status is under review", r.json()["status"] == "under_review", r.text)

    # -------------------------------------------------------------- tracking
    r = client.get("/api/applications/%s/tracking" % application["id"], headers=fresh)
    steps = r.json()["steps"]
    ok("chain has an inspection stage",
       any(s["stage"] == "inspection" for s in steps), str([s["stage"] for s in steps]))

    # --------------------------------------------------------------- officer
    r = client.get("/api/officer/stats", headers=applicant)
    ok("entrepreneur blocked from officer routes", r.status_code == 403, r.text)

    r = client.get("/api/officer/applications", headers=officer)
    ok("officer sees the queue", r.status_code == 200 and len(r.json()) >= 1, r.text)
    ok("drafts hidden from officer",
       all(a["status"] != "draft" for a in r.json()), r.text)

    r = client.post("/api/officer/applications/%s/query" % application["id"],
                    headers=officer,
                    json={"query_type": "document",
                          "message": "Please send a clearer site plan.",
                          "respond_by": "2026-10-01"})
    ok("officer can raise a query", r.status_code == 200, r.text)

    r = client.get("/api/queries", headers=fresh)
    ok("applicant sees the query", len(r.json()) == 1, r.text)
    query_id = r.json()[0]["id"]

    r = client.post("/api/queries/%s/respond" % query_id, headers=fresh,
                    json={"response": "Revised plan uploaded."})
    ok("applicant can respond", r.status_code == 200, r.text)

    r = client.post("/api/officer/applications/%s/inspection" % application["id"],
                    headers=officer,
                    json={"inspection_date": "2026-10-05", "inspection_time": "11:00",
                          "location": "Indore", "purpose": "Site check",
                          "officer_name": "Demo Officer", "notes": ""})
    ok("officer can schedule an inspection", r.status_code == 200, r.text)

    r = client.post("/api/officer/applications/%s/decision" % application["id"],
                    headers=officer,
                    json={"decision": "approved", "remarks": "Approved.",
                          "decision_date": "2026-09-20"})
    ok("officer can approve", r.status_code == 200, r.text)
    ok("application approved",
       r.json()["application"]["status"] == "approved", r.text)

    # ------------------------------------------------------ post-approval work
    r = client.get("/api/compliance", headers=fresh)
    ok("compliance generated on approval", r.json()["total"] >= 1, r.text)

    r = client.get("/api/renewals", headers=fresh)
    ok("licence issued on approval", r.json()["total"] >= 1, r.text)
    ok("licence number formatted",
       r.json()["items"][0]["licence_number"].startswith("FL-"), r.text)

    # --------------------------------------------------------------- schemes
    r = client.get("/api/schemes", headers=fresh)
    ok("schemes returned", len(r.json()) == 4, r.text)

    r = client.get("/api/schemes/msme")
    ok("scheme detail", r.status_code == 200 and r.json()["slug"] == "msme", r.text)

    # -------------------------------------------------------------- frontend
    r = client.get("/")
    ok("landing page served", r.status_code == 200 and "IndustryEase" in r.text, "")

    for page in ("login.html", "dashboard.html", "officer-dashboard.html",
                 "js/api.js", "css/app.css"):
        r = client.get("/" + page)
        ok("serves " + page, r.status_code == 200, str(r.status_code))


try:
    run()
finally:
    shutil.rmtree(TMP_DATA, ignore_errors=True)

print()
for label, detail in failed:
    print("FAILED: %s -> %s" % (label, detail[:200]))
print("passed %d, failed %d" % (len(passed), len(failed)))
sys.exit(1 if failed else 0)
