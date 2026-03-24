"""
src/okta/session.py

Tracks every Okta resource created during a generation run so that
cleanup.py can reliably delete everything later.

Why is this necessary?
  When we create 150 users and 40 groups in Okta, each one gets a
  unique ID assigned by Okta (e.g. "00u1ab2cd3EF4gh5Hi6"). These IDs
  are the only reliable way to delete resources later — names can
  change, but IDs never do.

  Without tracking IDs, cleanup would have to search for resources
  by name (fragile) or delete everything in the org (dangerous).

  The session file is written to .session.json (gitignored) and
  updated incrementally — if the run crashes halfway through,
  cleanup.py can still delete everything created so far.
"""

import json
import os
from datetime import datetime, timezone


_SESSION_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", ".session.json"
)


def _empty_session() -> dict:
    """
    Returns a fresh empty session structure.

    Returns:
        A dict with empty lists for each resource type.
    """
    return {
        "created_at":  datetime.now(timezone.utc).isoformat(),
        "resource_prefix": None,
        "groups":      [],   # list of {id, name}
        "users":       [],   # list of {id, login}
        "admin_roles": [],   # list of {user_id, role_type, role_id}
    }


def init_session(resource_prefix: str) -> None:
    """
    Creates a fresh session file, overwriting any previous one.

    Call this at the start of a new generation run. If you're
    resuming a partial run, use load_session() instead.

    Args:
        resource_prefix: The prefix used for all created resources
                         (from settings.yaml). Used by cleanup to
                         double-check it's only deleting our stuff.
    """
    session = _empty_session()
    session["resource_prefix"] = resource_prefix
    _write(session)


def load_session() -> dict:
    """
    Loads the existing session from .session.json.

    Returns:
        The session dict, or an empty session if no file exists.
    """
    if not os.path.exists(_SESSION_PATH):
        return _empty_session()

    with open(_SESSION_PATH) as f:
        return json.load(f)


def record_group(group_id: str, group_name: str) -> None:
    """
    Records a successfully created Okta group.

    Args:
        group_id:   The Okta-assigned group ID (e.g. "00g1ab2cd3EF").
        group_name: The group's display name.
    """
    session = load_session()
    session["groups"].append({"id": group_id, "name": group_name})
    _write(session)


def record_user(user_id: str, login: str) -> None:
    """
    Records a successfully created Okta user.

    Args:
        user_id: The Okta-assigned user ID (e.g. "00u1ab2cd3EF").
        login:   The user's login/email.
    """
    session = load_session()
    session["users"].append({"id": user_id, "login": login})
    _write(session)


def record_admin_role(user_id: str, role_type: str, role_id: str) -> None:
    """
    Records a successfully assigned admin role.

    Admin roles need their own IDs for deletion — you can't just
    remove "SUPER_ADMIN" by name, you need the role assignment ID.

    Args:
        user_id:   The Okta user ID the role was assigned to.
        role_type: The role type string (e.g. "SUPER_ADMIN").
        role_id:   The Okta-assigned role assignment ID.
    """
    session = load_session()
    session["admin_roles"].append({
        "user_id":   user_id,
        "role_type": role_type,
        "role_id":   role_id,
    })
    _write(session)


def session_exists() -> bool:
    """
    Checks whether a session file exists from a previous run.

    Used by cleanup.py and main.py to determine whether there's
    anything to clean up or whether a previous run needs finishing.

    Returns:
        True if .session.json exists, False otherwise.
    """
    return os.path.exists(_SESSION_PATH)


def delete_session() -> None:
    """
    Deletes the session file after a successful cleanup.

    This is called at the end of cleanup.py once all resources
    have been successfully deleted from Okta. A clean slate.
    """
    if os.path.exists(_SESSION_PATH):
        os.remove(_SESSION_PATH)


def get_summary() -> dict:
    """
    Returns a summary of what's currently tracked in the session.

    Used by dry_run.py and main.py to show progress stats.

    Returns:
        A dict with counts of each resource type.
    """
    session = load_session()
    return {
        "groups":      len(session.get("groups", [])),
        "users":       len(session.get("users", [])),
        "admin_roles": len(session.get("admin_roles", [])),
        "created_at":  session.get("created_at"),
        "prefix":      session.get("resource_prefix"),
    }


def _write(session: dict) -> None:
    """
    Writes the session dict to .session.json.

    We write immediately after every resource creation so that if
    the run crashes, we still have an accurate record of what was
    created and can clean it up.

    Args:
        session: The full session dict to write.
    """
    with open(_SESSION_PATH, "w") as f:
        json.dump(session, f, indent=2)
