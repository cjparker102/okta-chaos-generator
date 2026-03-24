"""
src/generator/group_generator.py

Builds the full list of Okta groups that need to be created before
any users can be assigned to them.

In Okta, groups must exist before you can add members — you can't
assign someone to a group that doesn't exist yet. So provisioner.py
creates all groups first, then creates users and assigns them.

We organize groups into 3 tiers, each with a clear purpose:
  Tier 1 — Department groups  (who you work with)
  Tier 2 — Access groups      (what systems you can reach)
  Tier 3 — Role groups        (your seniority or function)
"""

import os
import yaml


_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _load_config() -> tuple[dict, dict]:
    """
    Loads settings.yaml and departments.yaml.

    Returns:
        A tuple of (settings, departments) dicts.
    """
    with open(os.path.join(_CONFIG_DIR, "settings.yaml")) as f:
        settings = yaml.safe_load(f)

    with open(os.path.join(_CONFIG_DIR, "departments.yaml")) as f:
        departments = yaml.safe_load(f)

    return settings, departments


def generate_groups() -> list[dict]:
    """
    Generates the complete list of groups to create in Okta.

    Each group dict contains everything Okta needs to create it,
    plus metadata we use internally for assigning users correctly.

    Returns:
        A list of group dicts, each with:
            - name        (str)  the Okta group name
            - description (str)  what the group is for
            - tier        (str)  "department", "access", or "role"
            - department  (str | None) which dept this group belongs to, if any
    """
    settings, departments = _load_config()
    prefix = settings["generation"]["resource_prefix"]

    groups = []
    seen_names: set[str] = set()

    # --- TIER 1: Department Groups ---
    # One group per department. Every user gets their dept group.
    for dept_name, dept_config in departments.items():
        if dept_name == "executive_titles":
            continue  # not a real department entry

        groups_config = dept_config.get("groups", {})
        dept_group_name = groups_config.get("department")

        if dept_group_name and dept_group_name not in seen_names:
            groups.append({
                "name":        f"{prefix}{dept_group_name}",
                "description": f"All {dept_name.title()} department employees",
                "tier":        "department",
                "department":  dept_name,
            })
            seen_names.add(dept_group_name)

    # --- TIER 2: Access Groups ---
    # Collected from all departments — deduplicated so we don't create
    # the same group twice (e.g. access-vpn appears in many departments)
    for dept_name, dept_config in departments.items():
        if dept_name == "executive_titles":
            continue

        groups_config = dept_config.get("groups", {})

        for group_name in groups_config.get("access", []):
            if group_name not in seen_names:
                groups.append({
                    "name":        f"{prefix}{group_name}",
                    "description": _access_group_description(group_name),
                    "tier":        "access",
                    "department":  None,
                })
                seen_names.add(group_name)

        for group_name in groups_config.get("lead_groups", []):
            if group_name not in seen_names:
                groups.append({
                    "name":        f"{prefix}{group_name}",
                    "description": _role_group_description(group_name),
                    "tier":        "role",
                    "department":  None,
                })
                seen_names.add(group_name)

    # --- TIER 3: Role Groups (hardcoded — these apply org-wide) ---
    role_groups = [
        ("role-executives",      "C-suite and VP-level leadership"),
        ("role-managers",        "People managers across all departments"),
        ("role-engineers-lead",  "Senior and lead engineers"),
        ("role-contractors",     "External contractors and temporary workers"),
        ("role-service-accounts","Non-human service account identities"),
    ]

    for name, description in role_groups:
        if name not in seen_names:
            groups.append({
                "name":        f"{prefix}{name}",
                "description": description,
                "tier":        "role",
                "department":  None,
            })
            seen_names.add(name)

    return groups


def _access_group_description(group_name: str) -> str:
    """
    Returns a human-readable description for an access group based on its name.

    Args:
        group_name: The group name slug, e.g. "access-aws-prod".

    Returns:
        A description string.
    """
    descriptions = {
        "access-github":           "GitHub organization access — source code and CI/CD",
        "access-aws-dev":          "AWS Console access for non-production environments",
        "access-aws-prod":         "AWS Console access for production environments",
        "access-okta-readonly":    "Read-only access to Okta admin console",
        "access-okta-admin":       "Full Okta administration rights",
        "access-salesforce":       "Salesforce CRM access",
        "access-salesforce-admin": "Salesforce administration rights",
        "access-hr-systems":       "HR platform access — employee records",
        "access-hr-admin":         "HR platform administration rights",
        "access-workday":          "Workday HR and finance platform",
        "access-finance-systems":  "Financial reporting and accounting systems",
        "access-finance-admin":    "Finance platform administration rights",
        "access-pagerduty":        "PagerDuty incident management and on-call",
        "access-datadog":          "Datadog monitoring and observability",
        "access-vpn":              "Corporate VPN access",
        "access-zoom":             "Zoom video conferencing",
        "access-docusign":         "DocuSign contract signing",
        "access-slack":            "Slack workspace access",
        "access-google-workspace": "Google Workspace (email, docs, calendar)",
    }
    return descriptions.get(group_name, f"Access group: {group_name}")


def _role_group_description(group_name: str) -> str:
    """
    Returns a human-readable description for a role group.

    Args:
        group_name: The group name slug.

    Returns:
        A description string.
    """
    descriptions = {
        "role-executives":       "C-suite and VP-level leadership",
        "role-managers":         "People managers across all departments",
        "role-engineers-lead":   "Senior and lead engineers",
        "role-contractors":      "External contractors and temporary workers",
        "role-service-accounts": "Non-human service account identities",
    }
    return descriptions.get(group_name, f"Role group: {group_name}")


def get_group_names(groups: list[dict]) -> set[str]:
    """
    Returns a set of all group names from the generated groups list.

    Used by the provisioner to quickly check if a group exists.

    Args:
        groups: The list returned by generate_groups().

    Returns:
        A set of group name strings.
    """
    return {g["name"] for g in groups}
