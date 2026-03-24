"""
src/generator/app_generator.py

Assigns applications to users based on their department, org level,
and employee type.

In Okta, apps can be assigned directly to a user OR inherited through
a group. In a real org it's usually both. For simplicity, we track
app assignments at the user level — the chaos engine will add extra
apps to over-provisioned users later.

The goal here is to give every clean user a realistic, justified
set of apps — no more, no less than their job requires.
"""

import os
import yaml


_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _load_config() -> tuple[dict, dict]:
    """
    Loads departments.yaml and apps.yaml.

    Returns:
        A tuple of (departments, apps_config) dicts.
    """
    with open(os.path.join(_CONFIG_DIR, "departments.yaml")) as f:
        departments = yaml.safe_load(f)

    with open(os.path.join(_CONFIG_DIR, "apps.yaml")) as f:
        apps_config = yaml.safe_load(f)

    return departments, apps_config


def assign_apps(user: dict) -> list[str]:
    """
    Determines which apps a clean user should have based on their
    department, org level, and employee type.

    The logic mirrors how a real IT team would provision access:
      - Everyone gets Slack and Google Workspace (baseline)
      - VPN goes to everyone except service accounts
      - Department-specific apps come from departments.yaml group config
        (we use the group config as a proxy for app access)
      - Executives get a broader set
      - Contractors get the minimum needed, nothing extra
      - Service accounts get no user-facing apps

    Args:
        user: A user dict from user_generator.generate_users().

    Returns:
        A list of app ID strings from apps.yaml.
    """
    departments, apps_config = _load_config()

    department  = user["department"]
    org_level   = user["org_level"]
    emp_type    = user["employee_type"]

    # Service accounts get no user-facing apps
    if emp_type == "service_account":
        return []

    apps: set[str] = set()

    # --- Baseline apps everyone gets ---
    apps.add("access-slack")
    apps.add("access-google-workspace")

    # VPN for all humans
    apps.add("access-vpn")

    # --- Department-specific apps ---
    dept_config   = departments.get(department, {})
    groups_config = dept_config.get("groups", {})

    # Map access group names to app IDs
    # The access groups in departments.yaml use the same IDs as apps.yaml
    for group_name in groups_config.get("access", []):
        # Skip pure Okta/role groups, add actual app groups
        if group_name.startswith("access-"):
            apps.add(group_name)

    # Lead/management groups also imply additional app access
    if org_level in ("manager", "director", "executive"):
        for group_name in groups_config.get("lead_groups", []):
            if group_name.startswith("access-"):
                apps.add(group_name)

    # --- Contractors get a stripped-down set ---
    if emp_type == "contractor":
        # Contractors only keep low/medium tier apps — no critical systems
        allowed_for_contractors = _get_apps_below_tier(apps_config, "high")
        apps = apps.intersection(allowed_for_contractors)
        # Always keep baseline
        apps.add("access-slack")
        apps.add("access-google-workspace")
        apps.add("access-vpn")

    # --- Executives get Zoom and DocuSign ---
    if org_level == "executive":
        apps.add("access-zoom")
        apps.add("access-docusign")

    return sorted(list(apps))


def _get_apps_below_tier(apps_config: dict, max_tier: str) -> set[str]:
    """
    Returns the set of app IDs whose tier is below the given threshold.

    Tier order from lowest to highest: low → medium → high → critical.
    "Below high" means: low and medium.

    Used to restrict contractor app access to non-sensitive systems.

    Args:
        apps_config: The apps dict from apps.yaml.
        max_tier:    The tier threshold — apps AT or ABOVE this tier are excluded.

    Returns:
        A set of app ID strings.
    """
    tier_order = ["low", "medium", "high", "critical"]
    max_index  = tier_order.index(max_tier)

    allowed = set()
    for app in apps_config.get("apps", []):
        app_tier_index = tier_order.index(app["tier"])
        if app_tier_index < max_index:
            allowed.add(app["id"])

    return allowed


def get_crown_jewel_apps(apps_config: dict) -> list[str]:
    """
    Returns the list of crown jewel app IDs from apps.yaml.

    Crown jewel apps are the ones the chaos engine targets when creating
    over-provisioned or high-risk users. These are the apps that would
    cause the most damage if a bad actor got access to them.

    Args:
        apps_config: The apps dict loaded from apps.yaml.

    Returns:
        A list of app ID strings flagged as crown jewels.
    """
    return apps_config.get("crown_jewel_app_ids", [])
