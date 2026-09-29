"""
seed.py
-------
Creates the demo accounts and a little sample data on first run, so every page
has something to show the moment the server starts.

The two demo logins are the ones the original login.html was hard-coded to
accept, so the credentials people already know still work:

    Entrepreneur   entrepreneur@demo.com / Entrepreneur@123
    Officer        OFF-1001             / Officer@123

This is idempotent: if the users table already has rows, nothing happens.
Run `python backend/seed.py --reset` to wipe the transactional data and
rebuild it from scratch.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import (  # noqa: E402
    applications_table,
    approval_steps_table,
    compliance_table,
    counters_table,
    documents_table,
    inspections_table,
    profiles_table,
    projects_table,
    queries_table,
    renewals_table,
    users_table,
)
import approval_engine  # noqa: E402
import auth  # noqa: E402
import compliance as compliance_module  # noqa: E402
import officer as officer_module  # noqa: E402
import workflow  # noqa: E402

DEMO_ENTREPRENEUR = {
    "name": "Demo Entrepreneur",
    "email": "entrepreneur@demo.com",
    "phone": "9876543210",
    "password": "Entrepreneur@123",
}

DEMO_OFFICER = {
    "name": "Demo Officer",
    "email": "officer@demo.com",
    "phone": "9876500000",
    "password": "Officer@123",
}


def reset():
    """Clear everything except the reference catalogues."""
    for table in (users_table, profiles_table, projects_table, applications_table,
                  approval_steps_table, documents_table, compliance_table,
                  renewals_table, inspections_table, queries_table, counters_table):
        table.replace_all([])
    print("Cleared transactional data.")


def seed(force: bool = False):
    if users_table.all() and not force:
        return False

    entrepreneur = auth.register_user(
        name=DEMO_ENTREPRENEUR["name"],
        email=DEMO_ENTREPRENEUR["email"],
        password=DEMO_ENTREPRENEUR["password"],
        phone=DEMO_ENTREPRENEUR["phone"],
        role=auth.ENTREPRENEUR,
    )
    officer = auth.register_user(
        name=DEMO_OFFICER["name"],
        email=DEMO_OFFICER["email"],
        password=DEMO_OFFICER["password"],
        phone=DEMO_OFFICER["phone"],
        role=auth.OFFICER,
    )

    workflow.save_profile(entrepreneur["id"], {
        "business_name": "ABC Industries",
        "business_type": "manufacturing",
        "industry": "food",
        "state": "mp",
        "employees": 15,
    })

    project = workflow.create_project(entrepreneur["id"], {
        "project_name": "ABC Food Processing Plant",
        "business_name": "ABC Industries",
        "sector": "food-processing",
        "location": "Korba",
        "investment": 2000000,
        "employees": 15,
        "description": "A food processing unit handling packaging and cold storage "
                       "of locally sourced produce.",
    })

    # One application that has been submitted and is waiting on the officer,
    # so officer-dashboard.html has a row to review straight away.
    _seed_application(entrepreneur, project, "business", submit=True)

    # One already approved, so compliance.html and renewals.html have content.
    approved = _seed_application(entrepreneur, project, "fire", submit=True)
    officer_module.record_decision(
        approved["id"], officer, "approved",
        remarks="All documents verified. Fire safety approval granted.",
    )

    # One still in draft, so documents.html has something to upload against.
    _seed_application(entrepreneur, project, "factory", submit=False)

    print("Seeded demo data.")
    print(f"  Entrepreneur : {DEMO_ENTREPRENEUR['email']} / {DEMO_ENTREPRENEUR['password']}")
    print(f"  Officer      : {officer['officer_id']} / {DEMO_OFFICER['password']}")
    return True


def _seed_application(user, project, slug, submit: bool):
    application = approval_engine.create_application(project["id"], slug, user["id"])

    if submit:
        # Attach a placeholder record for each required document so the
        # checklist reads as complete without shipping real files.
        approval = approval_engine.get_approval(slug) or {}
        for required in approval.get("documents", []):
            documents_table.insert({
                "application_id": application["id"],
                "project_id": project["id"],
                "user_id": user["id"],
                "doc_type": required["key"],
                "filename": f"{required['key']}-sample.pdf",
                "filepath": "",
                "size_bytes": 0,
                "status": "uploaded",
                "validation_notes": "Sample record created by the seeder.",
                "seeded": True,
            })
        approval_engine.submit_application(application["id"])

    return applications_table.get(application["id"])


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset()
        seed(force=True)
    elif not seed():
        print("Data already present - nothing to seed. Use --reset to rebuild.")
