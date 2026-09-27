"""End-to-end authentication smoke test (Phase 7.1).

Drives the real application — real routes, real database, real scrypt hashing,
real server-side session rows — through the complete sign-in journey and reports
exactly what happened. This is the tool that reproduced the reported login error
(``GET /login`` answered 405) and it now guards against that regression.

    python scripts/check_auth_flow.py                 # throwaway SQLite database
    python scripts/check_auth_flow.py path/to.db      # copy of an existing DB

Relative SQLite URLs resolve to the Flask instance folder, so production data is
never modified: pass a copy, never the live file. Exit code 0 means every check
passed. No secret value is ever printed.
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API_DIR = REPO / "apps" / "api"
sys.path.insert(0, str(API_DIR))

CONTACT = "auth.smoke@example.com"
PASSWORD = "auth-smoke-password-1"

_results: list[tuple[bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    _results.append((bool(condition), label))
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {label}{(' — ' + detail) if detail else ''}")


def first_csrf(client, path: str = "/login") -> str:
    """Read the CSRF token exactly as a browser receives it with the form."""
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]*)"', html)
    return match.group(1) if match else ""


def build_database(source: str | None) -> tuple[str, Path]:
    tmpdir = Path(tempfile.mkdtemp(prefix="agriq_auth_smoke_"))
    target = tmpdir / "smoke.db"
    if source:
        shutil.copy2(Path(source), target)
        print(f"using a copy of {source} (the original is untouched)")
    else:
        print("using a throwaway SQLite database (nothing persisted)")
    return f"sqlite:///{target.as_posix()}", target


def main() -> int:
    os.environ["DATABASE_URL"], db_path = build_database(
        sys.argv[1] if len(sys.argv) > 1 else None
    )
    os.environ.setdefault("AGRIQ_ENV", "development")
    os.environ["AGRIQ_COOKIE_SECURE"] = "0"
    os.environ.setdefault("RATELIMIT_STORAGE_URI", "memory://")

    from agriq import create_app  # imported after DATABASE_URL is set

    app = create_app()
    client = app.test_client()

    # --- the reported login error -----------------------------------------
    response = client.get("/login")
    check("GET /login serves the login page", response.status_code == 200,
          f"status {response.status_code}")

    # --- registration ------------------------------------------------------
    response = client.post("/login", data={
        "csrf_token": first_csrf(client),
        "user_contact": CONTACT,
        "password": PASSWORD,
        "password_confirm": PASSWORD,
        "auth_action": "register",
    })
    body = response.get_data(as_text=True)
    registered = "Registration successful" in body or "may already be registered" in body
    check("registration creates a real account (or reports a conflict)",
          response.status_code == 200 and registered)

    # --- sign in -----------------------------------------------------------
    response = client.post("/login", data={
        "csrf_token": first_csrf(client),
        "user_contact": CONTACT,
        "password": PASSWORD,
    }, follow_redirects=False)
    check("valid credentials start a session (302 to /choose)",
          response.status_code == 302 and response.headers.get("Location", "").endswith("/choose"),
          f"status {response.status_code}")

    with client.session_transaction() as session:
        raw_token = session.get("session_token", "")
    check("the cookie carries an opaque session token", bool(raw_token))

    with app.app_context():
        from agriq.repositories.session_repository import SessionRepository

        resolved = SessionRepository.resolve(raw_token)
        check("the token matches a live server-side session row", resolved is not None)
        row_id = resolved[1].id if resolved else None

    response = client.get("/dashboard", follow_redirects=False)
    check("the protected dashboard renders for the session", response.status_code == 200)

    # --- wrong password / enumeration -------------------------------------
    other = app.test_client()
    response = other.post("/login", data={
        "csrf_token": first_csrf(other),
        "user_contact": CONTACT,
        "password": "definitely-the-wrong-password",
    })
    check("a wrong password is refused with one generic message",
          response.status_code == 200 and "Invalid contact or password" in response.get_data(as_text=True))

    response = other.post("/login", data={"user_contact": CONTACT, "password": PASSWORD})
    check("a POST without the form's CSRF token is refused", response.status_code == 400)

    # --- recovery without a provider --------------------------------------
    recovery = app.test_client()
    response = recovery.post("/forgot-password", data={
        "csrf_token": first_csrf(recovery, "/forgot-password"),
        "user_contact": CONTACT,
    })
    recovery_body = response.get_data(as_text=True)
    check("recovery reports an honest unavailable state, not a fake send",
          "not available on this deployment" in recovery_body)

    # --- logout revokes the row -------------------------------------------
    response = client.post("/logout", data={"csrf_token": first_csrf(client, "/choose")})
    check("logout redirects to the login page", response.status_code == 302)
    with app.app_context():
        from agriq.extensions import db
        from agriq.models.user_session import UserSession

        row = db.session.get(UserSession, row_id) if row_id else None
        check("logout revokes the session row server-side",
              row is not None and row.revoked_at is not None and row.revoked_reason == "logout")

    response = client.get("/dashboard", follow_redirects=False)
    check("the protected dashboard is blocked after logout", response.status_code == 302)
    api = client.get("/api/profile")
    check("the API answers 401 AUTH_UNAUTHORIZED after logout",
          api.status_code == 401 and (api.get_json() or {}).get("code") == "AUTH_UNAUTHORIZED")

    # --- stored credential form -------------------------------------------
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        row = con.execute(
            "SELECT password_hash FROM users WHERE contact = ?", (CONTACT,)
        ).fetchone()
    check("the stored password is a scrypt hash, never plaintext",
          bool(row) and row[0].startswith("scrypt:") and PASSWORD not in row[0])

    failures = [label for ok, label in _results if not ok]
    print()
    if failures:
        print(f"AUTH FLOW CHECK FAILED ({len(failures)} of {len(_results)} checks)")
        return 1
    print(f"AUTH FLOW CHECK PASSED ({len(_results)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
