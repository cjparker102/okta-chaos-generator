"""
src/data/org_structure.py

Builds a realistic manager hierarchy for the org.

In a real company, every employee has a manager — except the CEO.
This creates a tree structure: CEO → VPs → Directors → Managers → ICs.

Why does this matter for IAM?
  - Orphaned accounts (no manager assigned) are a red flag — it often
    means the person left and nobody cleaned up their account.
  - Our chaos engine will deliberately remove managers from some accounts
    to create that signal.
  - When okta-access-reviewer sees a SUPER_ADMIN with no manager field,
    it should flag it immediately.
"""

import random
import math


# How the org hierarchy is structured as a percentage of total headcount.
# These are approximate ratios that mirror real mid-size companies.
HIERARCHY_RATIOS = {
    "executive": 0.03,   # ~3%  — CEO, VPs, C-suite
    "director":  0.07,   # ~7%  — Directors
    "manager":   0.12,   # ~12% — Managers
    "ic":        0.78,   # ~78% — Individual Contributors (everyone else)
}


def build_hierarchy(user_count: int) -> dict:
    """
    Calculates how many people belong at each level of the org chart,
    then assigns each level its manager from the level above.

    This returns a structure that user_generator.py uses to assign
    the correct seniority level and manager to each user.

    Args:
        user_count: Total number of users to generate.

    Returns:
        A dict with keys for each level ("executive", "director", "manager", "ic"),
        each containing:
            - count     (int)  how many people at this level
            - span      (int)  how many reports each person at this level manages
    """
    levels = {}

    for level, ratio in HIERARCHY_RATIOS.items():
        count = max(1, math.floor(user_count * ratio))
        levels[level] = {"count": count}

    # Ensure we have at least 1 executive (the CEO)
    levels["executive"]["count"] = max(1, levels["executive"]["count"])

    # Calculate management span — how many direct reports each manager has.
    # Span = (people at level below) / (people at this level)
    levels["executive"]["span"] = max(1, levels["director"]["count"] // levels["executive"]["count"])
    levels["director"]["span"]  = max(1, levels["manager"]["count"] // levels["director"]["count"])
    levels["manager"]["span"]   = max(1, levels["ic"]["count"] // levels["manager"]["count"])
    levels["ic"]["span"]        = 0  # ICs don't manage anyone

    return levels


def assign_org_level(
    index: int,
    total_users: int,
    hierarchy: dict,
) -> str:
    """
    Determines what org level a user belongs to based on their index
    in the overall user list.

    We fill the org from the top down — the first few users are executives,
    the next batch are directors, then managers, then the rest are ICs.

    Args:
        index:       The user's position in the full user list (0-based).
        total_users: Total number of users being generated.
        hierarchy:   The hierarchy dict returned by build_hierarchy().

    Returns:
        One of: "executive", "director", "manager", "ic"
    """
    exec_count = hierarchy["executive"]["count"]
    dir_count  = hierarchy["director"]["count"]
    mgr_count  = hierarchy["manager"]["count"]

    if index < exec_count:
        return "executive"
    elif index < exec_count + dir_count:
        return "director"
    elif index < exec_count + dir_count + mgr_count:
        return "manager"
    else:
        return "ic"


def assign_manager_login(
    org_level: str,
    index: int,
    hierarchy: dict,
    all_users: list[dict],
) -> str | None:
    """
    Assigns a manager's login to a user based on their org level.

    Executives report to the CEO (index 0).
    Directors report to a random executive.
    Managers report to a random director.
    ICs report to a random manager.

    This is called during user generation after enough users above the
    current level have already been created.

    Args:
        org_level:  The current user's org level ("executive", "director", etc.)
        index:      The current user's index in the full user list.
        hierarchy:  The hierarchy dict from build_hierarchy().
        all_users:  All users generated so far — we pick a manager from this list.

    Returns:
        The login (email) of the assigned manager, or None for the CEO.
    """
    exec_count = hierarchy["executive"]["count"]
    dir_count  = hierarchy["director"]["count"]
    mgr_count  = hierarchy["manager"]["count"]

    if org_level == "executive":
        # The first executive is the CEO — no manager
        if index == 0:
            return None
        # Other executives report to the CEO
        return all_users[0]["login"]

    elif org_level == "director":
        # Directors report to a random executive
        if not all_users[:exec_count]:
            return None
        manager = random.choice(all_users[:exec_count])
        return manager["login"]

    elif org_level == "manager":
        # Managers report to a random director
        directors = all_users[exec_count : exec_count + dir_count]
        if not directors:
            return None
        manager = random.choice(directors)
        return manager["login"]

    else:
        # ICs report to a random manager
        managers = all_users[exec_count + dir_count : exec_count + dir_count + mgr_count]
        if not managers:
            return None
        manager = random.choice(managers)
        return manager["login"]


def get_title_for_level(org_level: str, department: str, dept_config: dict) -> str:
    """
    Picks an appropriate job title for a user based on their org level
    and department.

    Executives and directors get senior titles. Managers get manager titles.
    ICs get regular titles. This ensures a VP in Engineering has a more
    senior-sounding title than a junior engineer.

    Args:
        org_level:   The user's org level.
        department:  The user's department name (e.g. "engineering").
        dept_config: The department's config dict from departments.yaml.

    Returns:
        A job title string.
    """
    titles = dept_config.get("titles", ["Employee"])

    if org_level == "executive":
        # Pick from the last third of the titles list (most senior)
        senior_titles = titles[len(titles) * 2 // 3:]
        return random.choice(senior_titles) if senior_titles else titles[-1]

    elif org_level == "director":
        # Pick from the middle/upper titles
        senior_titles = titles[len(titles) // 2:]
        return random.choice(senior_titles) if senior_titles else titles[-1]

    elif org_level == "manager":
        # Pick from the middle titles — look for "Manager" explicitly
        manager_titles = [t for t in titles if "Manager" in t or "Lead" in t]
        if manager_titles:
            return random.choice(manager_titles)
        return random.choice(titles[len(titles) // 3:])

    else:
        # ICs get the first half of titles (junior to mid)
        ic_titles = titles[:max(1, len(titles) * 2 // 3)]
        return random.choice(ic_titles)
