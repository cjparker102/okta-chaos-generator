"""
src/chaos/profiles.py

Defines every chaos type — what it is, what tier it belongs to,
and most importantly: the mutation function that breaks a clean
user record to create that specific IAM problem.

Each chaos profile is a dict with:
  - id          unique name used in the manifest
  - tier        critical / high / medium / low
  - description what an IAM analyst would see when they find this
  - mutate()    a function that takes a user dict and breaks it

The mutation functions are where the real damage happens. They don't
create new users — they corrupt existing ones. A clean Sales user
can become a dormant executive with SUPER_ADMIN and crown jewel apps
just by having the right mutations applied.

This is the "engine room" of the whole project.
"""

import random
from datetime import datetime, timedelta, timezone
from src.data.timeline import NOW, format_okta_timestamp


# ---------------------------------------------------------------------------
# Helper functions used by multiple chaos mutations
# ---------------------------------------------------------------------------

def _make_stale(user: dict, months_min: int = 6, months_max: int = 18) -> None:
    """
    Sets the user's last login to a random date between months_min
    and months_max ago, making them look inactive.

    Args:
        user:       The user dict to mutate.
        months_min: Minimum months of inactivity.
        months_max: Maximum months of inactivity.
    """
    days_ago = random.randint(months_min * 30, months_max * 30)
    stale_date = NOW - timedelta(days=days_ago)
    user["credentials"]["last_login"]      = format_okta_timestamp(stale_date)
    user["credentials"]["_last_login_raw"] = stale_date
    user["credentials"]["_activity_level"] = "stale"


def _make_never_logged_in(user: dict) -> None:
    """
    Clears the user's last login, making it look like the account
    was created but never activated.

    Args:
        user: The user dict to mutate.
    """
    user["credentials"]["last_login"]      = None
    user["credentials"]["_last_login_raw"] = None
    user["credentials"]["_activity_level"] = "never"


def _add_admin_role(user: dict, role: str) -> None:
    """
    Adds an Okta admin role to a user if they don't already have it.

    Valid Okta admin role types:
      SUPER_ADMIN, ORG_ADMIN, APP_ADMIN, USER_ADMIN,
      HELP_DESK_ADMIN, READ_ONLY_ADMIN, REPORT_ADMIN

    Args:
        user: The user dict to mutate.
        role: The Okta role type string.
    """
    if role not in user["admin_roles"]:
        user["admin_roles"].append(role)


def _add_crown_jewel_apps(user: dict, count: int = 3) -> None:
    """
    Adds a random selection of crown jewel apps to a user.

    Crown jewels are the highest-risk apps in the org — AWS prod,
    Okta Admin, HR Admin, Finance Admin, PagerDuty, Datadog.
    A contractor or a stale user with these is a major red flag.

    Args:
        user:  The user dict to mutate.
        count: How many crown jewel apps to add.
    """
    crown_jewels = [
        "access-aws-prod",
        "access-okta-admin",
        "access-hr-admin",
        "access-finance-admin",
        "access-pagerduty",
        "access-datadog",
    ]
    picks = random.sample(crown_jewels, min(count, len(crown_jewels)))
    for app in picks:
        if app not in user["apps"]:
            user["apps"].append(app)


def _add_cross_dept_groups(user: dict, count: int = 3) -> None:
    """
    Adds groups from OTHER departments to simulate privilege creep —
    access that accumulated over time as the user changed roles.

    Args:
        user:  The user dict to mutate.
        count: How many extra cross-department groups to inject.
    """
    all_dept_groups = [
        "dept-engineering", "dept-sales", "dept-hr",
        "dept-finance", "dept-it", "dept-marketing", "dept-legal",
    ]
    # Remove the user's own dept group to avoid adding it twice
    user_dept_group = f"dept-{user['department']}"
    foreign_groups  = [g for g in all_dept_groups if g != user_dept_group]

    picks = random.sample(foreign_groups, min(count, len(foreign_groups)))
    for group in picks:
        if group not in user["groups"]:
            user["groups"].append(group)


# ---------------------------------------------------------------------------
# CHAOS PROFILES
# Each profile has: id, tier, description, and a mutate(user) function.
# ---------------------------------------------------------------------------

PROFILES = [

    # =========================================================================
    # TIER: CRITICAL
    # =========================================================================

    {
        "id":          "sleeping_super_admin",
        "tier":        "critical",
        "description": "Active SUPER_ADMIN account that hasn't logged in for 6–18 months. "
                       "Full unrestricted control over the Okta tenant sitting dormant.",
        "mutate": lambda user: (
            _add_admin_role(user, "SUPER_ADMIN"),
            _make_stale(user, months_min=6, months_max=18),
        ),
    },

    {
        "id":          "departed_employee",
        "tier":        "critical",
        "description": "Account created 2–4 years ago with a very old last login. "
                       "Looks like the person left but was never offboarded. "
                       "Still ACTIVE with full app access.",
        "mutate": lambda user: (
            # Set hire date 2–4 years ago
            user["credentials"].update({
                "created": format_okta_timestamp(
                    NOW - timedelta(days=random.randint(730, 1460))
                ),
            }),
            # Last login 12–30 months ago
            _make_stale(user, months_min=12, months_max=30),
        ),
    },

    {
        "id":          "admin_without_mfa",
        "tier":        "critical",
        "description": "ORG_ADMIN or SUPER_ADMIN account with MFA never enrolled. "
                       "An admin account with no second factor is a trivially hijackable backdoor.",
        "mutate": lambda user: (
            _add_admin_role(user, random.choice(["SUPER_ADMIN", "ORG_ADMIN"])),
            user["profile"].update({"mfaEnrolled": False}),
        ),
    },

    {
        "id":          "contractor_with_crown_jewels",
        "tier":        "critical",
        "description": "A contractor (non-employee) with access to AWS prod, Okta Admin, "
                       "or other critical systems. Contractors should never have this.",
        "mutate": lambda user: (
            user["profile"].update({
                "employeeType": "contractor",
                "userType":     "contractor",
            }),
            user.__setitem__("employee_type", "contractor"),
            user["groups"].append("role-contractors")
            if "role-contractors" not in user["groups"] else None,
            _add_crown_jewel_apps(user, count=random.randint(2, 4)),
        ),
    },

    # =========================================================================
    # TIER: HIGH
    # =========================================================================

    {
        "id":          "privilege_creep",
        "tier":        "high",
        "description": "User changed departments 2–3 times and kept ALL their old access. "
                       "Now in 6+ unrelated groups across Engineering, Finance, HR, and Sales.",
        "mutate": lambda user: (
            _add_cross_dept_groups(user, count=random.randint(3, 5)),
            # Also add some access groups from other depts
            [user["groups"].append(g) for g in random.sample([
                "access-salesforce", "access-hr-systems",
                "access-finance-systems", "access-aws-dev",
                "access-github", "access-workday",
            ], k=random.randint(2, 4)) if g not in user["groups"]],
        ),
    },

    {
        "id":          "orphaned_admin",
        "tier":        "high",
        "description": "Has an admin role but no manager, no department, no cost center. "
                       "Completely unattached to the org structure — a ghost with power.",
        "mutate": lambda user: (
            _add_admin_role(user, random.choice(["ORG_ADMIN", "APP_ADMIN", "USER_ADMIN"])),
            user["profile"].update({
                "manager":    None,
                "department": None,
                "costCenter": None,
                "title":      None,
            }),
        ),
    },

    {
        "id":          "dormant_executive",
        "tier":        "high",
        "description": "In the Executives group with SUPER_ADMIN, inactive for 9–14 months. "
                       "Highest privilege + longest inactivity = worst possible combo.",
        "mutate": lambda user: (
            _add_admin_role(user, "SUPER_ADMIN"),
            user["groups"].append("role-executives")
            if "role-executives" not in user["groups"] else None,
            user["profile"].update({"title": random.choice([
                "CEO", "CTO", "COO", "CFO", "CISO", "VP of Engineering",
            ])}),
            _make_stale(user, months_min=9, months_max=14),
        ),
    },

    {
        "id":          "contractor_overstay",
        "tier":        "high",
        "description": "Contractor whose engagement clearly ended 12–24 months ago. "
                       "Still ACTIVE, still provisioned. Contract expiry was never enforced.",
        "mutate": lambda user: (
            user["profile"].update({
                "employeeType": "contractor",
                "userType":     "contractor",
            }),
            user.__setitem__("employee_type", "contractor"),
            # Set hire date 18–36 months ago (well past any contract window)
            user["credentials"].update({
                "created": format_okta_timestamp(
                    NOW - timedelta(days=random.randint(540, 1080))
                ),
            }),
            _make_stale(user, months_min=12, months_max=24),
            user["groups"].append("role-contractors")
            if "role-contractors" not in user["groups"] else None,
        ),
    },

    # =========================================================================
    # TIER: MEDIUM
    # =========================================================================

    {
        "id":          "ghost_account",
        "tier":        "medium",
        "description": "Account created 3–8 months ago but never logged in. "
                       "Fully provisioned with apps and groups. Onboarding failure "
                       "or the person left before starting.",
        "mutate": lambda user: (
            user["credentials"].update({
                "created": format_okta_timestamp(
                    NOW - timedelta(days=random.randint(90, 240))
                ),
            }),
            _make_never_logged_in(user),
        ),
    },

    {
        "id":          "service_account_gone_rogue",
        "tier":        "medium",
        "description": "A svc.* service account that ended up in human-facing groups "
                       "with broad app access. Service accounts should be tightly scoped.",
        "mutate": lambda user: (
            # Force this user to look like a service account
            user["profile"].update({
                "login":       f"svc.{user['profile']['firstName'].lower()}"
                               f"-{random.randint(100,999)}"
                               f"@{user['profile']['login'].split('@')[1]}",
                "displayName": f"SVC - {user['profile']['firstName'].title()}",
                "employeeType":"service_account",
                "userType":    "service_account",
                "manager":     None,
            }),
            user.__setitem__("employee_type", "service_account"),
            # Add it to human groups it shouldn't be in
            _add_cross_dept_groups(user, count=2),
            _add_crown_jewel_apps(user, count=random.randint(1, 3)),
            user["groups"].append("role-executives")
            if random.random() < 0.3 else None,
        ),
    },

    {
        "id":          "duplicate_identity",
        "tier":        "medium",
        "description": "Two active accounts exist for the same person. "
                       "The old account was never disabled when the new one was created — "
                       "a common offboarding/rehire failure.",
        "mutate": lambda user: (
            # We flag this user as one half of a duplicate pair.
            # The chaos engine will handle creating the second account.
            user["chaos_tags"].append("_is_duplicate_primary"),
            _make_stale(user, months_min=4, months_max=12),
        ),
    },

    {
        "id":          "app_hoarder",
        "tier":        "medium",
        "description": "User has 15–25 app assignments spanning multiple unrelated "
                       "departments. Classic sign of access that was added over time "
                       "and never cleaned up.",
        "mutate": lambda user: (
            _add_crown_jewel_apps(user, count=2),
            # Add a wide variety of apps from all over the org
            [user["apps"].append(app) for app in [
                "access-salesforce", "access-hr-systems", "access-workday",
                "access-finance-systems", "access-github", "access-aws-dev",
                "access-pagerduty", "access-datadog", "access-zoom",
                "access-docusign", "access-okta-readonly",
            ] if app not in user["apps"]],
        ),
    },

    {
        "id":          "password_never_rotated",
        "tier":        "medium",
        "description": "Account is 3+ years old and the password has never been changed. "
                       "A long-lived credential is an easy target for credential stuffing.",
        "mutate": lambda user: (
            # Set hire date at least 3 years ago
            user["credentials"].update({
                "created":          format_okta_timestamp(
                    NOW - timedelta(days=random.randint(1095, 2555))
                ),
                "password_changed": None,
            }),
        ),
    },

    # =========================================================================
    # TIER: LOW
    # =========================================================================

    {
        "id":          "wrong_department_groups",
        "tier":        "low",
        "description": "User is in groups that don't match their department. "
                       "An Engineering user in dept-finance and dept-hr stands out.",
        "mutate": lambda user: (
            _add_cross_dept_groups(user, count=random.randint(1, 2)),
        ),
    },

    {
        "id":          "missing_manager",
        "tier":        "low",
        "description": "No manager or cost center assigned. "
                       "Orphaned in the org chart — usually means the person left "
                       "and their manager was removed without cleanup.",
        "mutate": lambda user: (
            user["profile"].update({
                "manager":    None,
                "costCenter": None,
            }),
        ),
    },

    {
        "id":          "stale_contractor_access",
        "tier":        "low",
        "description": "A contractor who is a member of permanent employee groups "
                       "like dept-engineering or role-managers. Contractors should "
                       "only be in the contractors group.",
        "mutate": lambda user: (
            user["profile"].update({
                "employeeType": "contractor",
                "userType":     "contractor",
            }),
            user.__setitem__("employee_type", "contractor"),
            # Keep them in full-time employee groups (the mistake)
            user["groups"].append("role-managers")
            if "role-managers" not in user["groups"] else None,
        ),
    },

    {
        "id":          "incomplete_profile",
        "tier":        "low",
        "description": "Missing required profile fields — no phone, city, state, "
                       "or cost center. Looks like an account provisioned in a hurry "
                       "or imported from a legacy system.",
        "mutate": lambda user: (
            user["profile"].update({
                "mobilePhone": None,
                "city":        None,
                "state":       None,
                "costCenter":  None,
            }),
        ),
    },
]


# Build a lookup dict by ID for fast access
PROFILES_BY_ID: dict[str, dict] = {p["id"]: p for p in PROFILES}

# Group profiles by tier for weighted selection in chaos_engine.py
PROFILES_BY_TIER: dict[str, list[dict]] = {
    "critical": [p for p in PROFILES if p["tier"] == "critical"],
    "high":     [p for p in PROFILES if p["tier"] == "high"],
    "medium":   [p for p in PROFILES if p["tier"] == "medium"],
    "low":      [p for p in PROFILES if p["tier"] == "low"],
}
