"""
scheme_matcher.py
-----------------
From the `nirman` backend, re-pointed at the industrial project shape that
IndustryEase uses (sector / investment / employees instead of category /
budget / location_type).

Given a project, work out which government schemes it is eligible for and
rank them by how well they fit.

A scheme record looks like:
{
  "id": "scheme-msme",
  "slug": "msme",
  "name": "MSME Business Support",
  "category": "msme finance",
  "eligibility_criteria": {
      "sectors": ["manufacturing", "food_processing", "textile"],
      "min_investment": 0,
      "max_investment": 500000000,
      "min_employees": 0,
      "max_employees": 250
  },
  "documents_required": [...]
}
"""

from database import schemes_table
from approval_engine import normalise_sector


def _matches_criteria(project: dict, criteria: dict):
    """Return (is_eligible, score) for one scheme's criteria."""
    if not criteria:
        return True, 1.0

    score = 0
    checks = 0

    allowed_sectors = [normalise_sector(s) for s in criteria.get("sectors", [])]
    if allowed_sectors:
        checks += 1
        if "*" in allowed_sectors or normalise_sector(project.get("sector")) in allowed_sectors:
            score += 1
        else:
            return False, 0.0

    investment = float(project.get("investment") or 0)
    employees = int(project.get("employees") or 0)

    numeric_checks = (
        ("min_investment", investment, lambda v, limit: v >= limit),
        ("max_investment", investment, lambda v, limit: v <= limit),
        ("min_employees", employees, lambda v, limit: v >= limit),
        ("max_employees", employees, lambda v, limit: v <= limit),
    )

    for key, value, passes in numeric_checks:
        limit = criteria.get(key)
        if limit is None:
            continue
        checks += 1
        if passes(value, limit):
            score += 1
        else:
            return False, 0.0

    return True, (1.0 if checks == 0 else score / checks)


def match_schemes(project: dict):
    """
    Return [{scheme, match_score, eligible}] for every scheme, best match
    first. Ineligible schemes are still returned (flagged `eligible: False`)
    so the schemes page can show the full catalogue rather than an empty grid.
    """
    matches = []
    for scheme in schemes_table.all():
        eligible, score = _matches_criteria(project, scheme.get("eligibility_criteria", {}))
        matches.append({
            "scheme": scheme,
            "match_score": round(score, 2),
            "eligible": eligible,
        })

    matches.sort(key=lambda m: (not m["eligible"], -m["match_score"], m["scheme"]["name"]))
    return matches


def eligible_schemes(project: dict):
    return [m for m in match_schemes(project) if m["eligible"]]


def best_scheme_for(project: dict):
    matches = eligible_schemes(project)
    return matches[0]["scheme"] if matches else None
