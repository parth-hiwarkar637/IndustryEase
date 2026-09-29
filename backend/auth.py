"""
auth.py
-------
Registration, login and token-based authentication for IndustryEase.

From the `nirman` backend, extended so it fits the IndustryEase login page:
an entrepreneur signs in with their email address, a government officer
signs in with an officer ID (e.g. OFF-1001).

No external auth library is used, so the only dependencies are FastAPI and
pydantic. Passwords are salted + SHA-256 hashed (fine for a project of this
size; swap in bcrypt/passlib for production). Tokens are HMAC-signed so they
cannot be forged without the secret key, and they carry an expiry.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from database import users_table, profiles_table, next_sequence

# In a real deployment this must come from the environment.
SECRET_KEY = os.environ.get("INDUSTRYEASE_SECRET_KEY", "industryease-dev-secret-change-me")
TOKEN_TTL_SECONDS = 60 * 60 * 8  # 8 hour session

ENTREPRENEUR = "entrepreneur"
OFFICER = "officer"
ADMIN = "admin"
VALID_ROLES = (ENTREPRENEUR, OFFICER, ADMIN)


class AuthError(Exception):
    """`status_code` lets main.py map the failure to the right HTTP status."""

    def __init__(self, message, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------- passwords

def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def _make_salt() -> str:
    return secrets.token_hex(16)


# ---------------------------------------------------------------- register

def register_user(name: str, email: str, password: str, phone: str = "",
                  role: str = ENTREPRENEUR):
    """Create a new account. role: entrepreneur | officer | admin"""
    name = (name or "").strip()
    email = (email or "").strip().lower()
    role = (role or ENTREPRENEUR).strip().lower()

    if not name or not email or not password:
        raise AuthError("name, email and password are all required")
    if "@" not in email:
        raise AuthError("please enter a valid email address")
    if len(password) < 6:
        raise AuthError("password must be at least 6 characters long")
    if role not in VALID_ROLES:
        raise AuthError(f"role must be one of {VALID_ROLES}")

    if users_table.find_one(email=email):
        raise AuthError("an account with this email already exists")

    salt = _make_salt()
    officer_id = None
    if role == OFFICER:
        officer_id = f"OFF-{next_sequence('officer_id', start=1001)}"

    user = users_table.insert({
        "name": name,
        "email": email,
        "phone": phone or "",
        "officer_id": officer_id,
        "salt": salt,
        "password_hash": _hash_password(password, salt),
        "role": role,
    })
    return public_user(user)


# ---------------------------------------------------------------- login

def login_user(identifier: str, password: str, role: str = None):
    """
    `identifier` is an email address for entrepreneurs, or an officer ID
    (OFF-1001) for government officers. Matching is case-insensitive.
    """
    identifier = (identifier or "").strip()
    if not identifier or not password:
        raise AuthError("please enter both your login ID and password")

    user = _find_by_identifier(identifier)
    if not user:
        raise AuthError("invalid login ID or password")

    expected = _hash_password(password, user["salt"])
    if not hmac.compare_digest(expected, user["password_hash"]):
        raise AuthError("invalid login ID or password")

    # The login page has an Entrepreneur / Officer toggle. If the caller told
    # us which one they picked, make sure the account actually matches, so an
    # entrepreneur cannot land on the officer dashboard by flipping the radio.
    if role:
        role = role.strip().lower()
        if role in VALID_ROLES and user.get("role") != role:
            raise AuthError(f"this account is not registered as a {role}")

    return {"token": generate_token(user["id"]), "user": public_user(user)}


def _find_by_identifier(identifier: str):
    lowered = identifier.lower()
    for user in users_table.all():
        if (user.get("email") or "").lower() == lowered:
            return user
        if (user.get("officer_id") or "").lower() == lowered:
            return user
    return None


# ---------------------------------------------------------------- tokens

def public_user(user: dict) -> dict:
    """Strip anything sensitive before a user record leaves this module."""
    profile = profiles_table.find_one(user_id=user["id"]) or {}
    return {
        "id": user["id"],
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "phone": user.get("phone", ""),
        "officer_id": user.get("officer_id"),
        "role": user.get("role", ENTREPRENEUR),
        "business_name": profile.get("business_name", ""),
        "created_at": user.get("created_at"),
    }


def generate_token(user_id: str) -> str:
    payload = {"user_id": user_id, "exp": time.time() + TOKEN_TTL_SECONDS}
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload).encode("utf-8")
    ).decode("utf-8")
    signature = hmac.new(
        SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_token(token: str) -> dict:
    """Return the user record for a valid token, raise AuthError otherwise."""
    try:
        payload_b64, signature = token.split(".")
    except (ValueError, AttributeError):
        raise AuthError("malformed token")

    expected_sig = hmac.new(
        SECRET_KEY.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_sig, signature):
        raise AuthError("invalid token signature")

    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("utf-8")))
    except (ValueError, json.JSONDecodeError):
        raise AuthError("malformed token")

    if payload.get("exp", 0) < time.time():
        raise AuthError("your session has expired, please log in again")

    user = users_table.get(payload.get("user_id"))
    if not user:
        raise AuthError("user no longer exists")
    return public_user(user)


def require_role(user: dict, *allowed_roles):
    if user.get("role") not in allowed_roles:
        raise AuthError("you do not have permission to perform this action",
                        status_code=403)
    return True
