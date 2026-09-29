# IndustryEase

A single-window portal for industrial approvals. An entrepreneur enters their
project once, sees which government approvals apply to it, uploads the
documents each one needs, and tracks the application through to a decision.
A government officer reviews the queue from the other side: raise a query,
schedule a site inspection, approve or reject.

This project merges three separate codebases:

| Original | What it was | What was taken |
|---|---|---|
| `nirman-backend` | A FastAPI app for rural welfare schemes | The architecture: token auth, the JSON data layer, the multi-level approval chain, document validation, scheme matching |
| `hackathon` | Two terminal scripts (`main.py`, `government.py`) | The industrial domain: sector / investment / employees, the approvals catalogue, `find_approvals()`, and the officer approve / reject / query actions |
| `IndustrialEase` | 19 static HTML pages with hardcoded demo content | The entire user interface |

---

## Running it

```bash
pip install -r requirements.txt
python run.py
```

Then open **http://127.0.0.1:8000/**.

The API and the pages are served by the same process, so there is no second
server to start and nothing to configure.

### Demo logins

| Role | Login ID | Password |
|---|---|---|
| Entrepreneur | `entrepreneur@demo.com` | `Entrepreneur@123` |
| Government Officer | `OFF-1001` | `Officer@123` |

These are the credentials the original `login.html` was hardcoded to accept.
They still work, but they now authenticate against real seeded accounts
instead of an `if` statement in the browser. You can also register a new
entrepreneur account from the register page.

### Other commands

```bash
python run.py --reload          # restart on code changes
python run.py --port 9000       # different port
python run.py --reset           # wipe all data and re-seed
python tests/test_smoke.py      # full end-to-end check
```

---

## Walking through it

**As the entrepreneur**

1. Log in — you land on the dashboard with live counters.
2. **Project** — the project details form. Saving it drives everything else.
3. **Approvals** — the approvals that match your sector, investment and
   headcount, each with its department and priority. A food processing unit
   with 15 staff needs a factory licence; a 3-person IT firm does not.
4. **Start Application** on one, which takes you to **Documents**.
5. Upload each document on the checklist. The submit button stays disabled
   until the checklist is complete.
6. **Submit** — you land on **Tracking**, with a live timeline.
7. If the officer raises a query it appears on the tracking page with a reply box.
8. Once approved, **Compliance** and **Renewals** fill in automatically.

**As the officer** (log out, log back in with the officer toggle)

1. The dashboard shows live counts and the review queue.
2. **Review →** on an application shows the applicant, the project and the
   uploaded documents.
3. From there: **Raise Query**, **Request Inspection**, or **Proceed to
   Decision**. Approving an application is what creates the applicant's
   compliance tasks and licence renewal record.

---

## Layout

```
industryease/
├── run.py                     # start here
├── requirements.txt
├── backend/
│   ├── main.py                # FastAPI app: ~45 endpoints + serves the frontend
│   ├── database.py            # JSON-file data layer (from nirman)
│   ├── auth.py                # register / login / tokens (from nirman, extended)
│   ├── approval_engine.py     # THE MERGE: hackathon matching + nirman's chain
│   ├── document_validator.py  # file checks + per-approval checklists (from nirman)
│   ├── scheme_matcher.py      # scheme eligibility (from nirman)
│   ├── workflow.py            # the applicant journey end to end
│   ├── officer.py             # port of hackathon's government.py
│   ├── compliance.py          # compliance + renewals (new)
│   └── seed.py                # demo accounts and sample data
├── frontend/
│   ├── *.html                 # the 19 original pages, now data-driven
│   ├── css/                   # the original stylesheets + app.css
│   └── js/
│       ├── api.js             # fetch wrapper, session, guards, formatters
│       ├── auth.js            # landing / login / register
│       ├── applicant.js       # the 11 entrepreneur pages
│       └── officer.js         # the 5 officer pages
├── data/                      # JSON "tables"
├── uploads/                   # uploaded documents
└── tests/test_smoke.py
```

---

## How the two backends were joined

The interesting file is `backend/approval_engine.py`.

The hackathon backend decided which approvals a project needed:

```python
sector_match = project["sector"] in approval["applicable_sectors"]
employee_match = project["employees"] >= approval["minimum_employees"]
```

The nirman backend moved an application through ordered approval levels, each
unlocking the next, with any rejection ending the whole thing.

Neither was useful alone: the hackathon version had no notion of an
application that progresses, and the nirman version had no idea which
approvals an industrial project needs. They are joined by
`create_application()` — a matched approval from the catalogue becomes an
application, and that application gets a chain of stages
(`submitted → document_verification → under_review → inspection → decision`).
The inspection stage only exists for approvals whose catalogue entry sets
`inspection_required`, which is why a factory licence has five stages and a
trade licence has four.

## Gaps that had to be filled

Things the frontend showed but no backend implemented:

- **Compliance and renewals.** Both pages existed with hardcoded cards.
  `compliance.py` generates real obligations from the approval's catalogue
  entry when an officer approves it, and derives due-soon / overdue / expired
  from the actual dates.
- **Queries and inspections.** The officer pages had forms that went nowhere.
- **Business profiles.** The form had no backing store.
- **All frontend wiring.** `JS/script.js` was an empty file and no page
  referenced it. Every page's content was hardcoded — the dashboard counters
  were literal numbers, the approvals were four fixed cards, tracking read
  from `localStorage` only.

Smaller fixes along the way:

- Every page linked `css/style.css` but the folder was named `CSS/`, which
  breaks on any case-sensitive filesystem. The folder is now `css/`.
- `login.html` contained a commented-out duplicate copy of the whole page.
- The hackathon backend crashed on menu option 3: it wrote `project_id` as a
  string on creation but compared it against `int(input(...))` on lookup, so
  no project ever matched. The merged code uses generated IDs throughout.
- `datetime.utcnow()` is deprecated in Python 3.12; timestamps are now
  timezone-aware.
- Data files are written to a temp file and moved into place, so an
  interrupted write cannot truncate a table.

## Notes

Passwords are salted SHA-256 and tokens are HMAC-signed — fine for a project
of this size, but use bcrypt or Argon2 and a real session store in
production. Set `INDUSTRYEASE_SECRET_KEY` in the environment to override the
development signing key. Data lives in JSON files under `data/`, which is
simple to inspect and hand in, but a real deployment wants a database.
