"""
src/generator/user_generator.py

The core user factory. Combines names, timelines, org structure, and
department config to produce fully-formed Okta user records.

This is the biggest file in the generator layer. Think of it as an
assembly line — each function adds one more piece to the user record
until we have everything Okta needs to create the account.

At this stage, all users are CLEAN — no chaos has been injected yet.
The chaos engine in src/chaos/ will mutate these records afterward.
"""

import random
import yaml
import os
from faker import Faker

from src.data.names import (
    generate_name,
    generate_service_account_name,
    make_login_unique,
    generate_employee_number,
)
from src.data.timeline import (
    generate_hire_date,
    generate_last_login,
    generate_password_changed,
    format_okta_timestamp,
)
from src.data.org_structure import (
    build_hierarchy,
    assign_org_level,
    assign_manager_login,
    get_title_for_level,
)


# Faker instance for generating phone numbers, cities, states
_fake = Faker("en_US")

# Paths to config files — using os.path so this works regardless of
# where you run the script from
_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _load_config() -> tuple[dict, dict, dict]:
    """
    Loads all three YAML config files and returns them as dicts.

    Returns:
        A tuple of (settings, departments, apps) dicts.
    """
    with open(os.path.join(_CONFIG_DIR, "settings.yaml")) as f:
        settings = yaml.safe_load(f)

    with open(os.path.join(_CONFIG_DIR, "departments.yaml")) as f:
        departments = yaml.safe_load(f)

    with open(os.path.join(_CONFIG_DIR, "apps.yaml")) as f:
        apps = yaml.safe_load(f)

    return settings, departments, apps


def _pick_department(dept_weights: dict) -> str:
    """
    Picks a random department based on the weights in settings.yaml.

    Uses Python's random.choices() which supports weighted selection —
    departments with higher weights are picked more often, just like
    how Engineering might have 28% of the company but Legal only 6%.

    Args:
        dept_weights: Dict of {department_name: weight} from settings.yaml.

    Returns:
        A department name string, e.g. "engineering".
    """
    departments = list(dept_weights.keys())
    weights = list(dept_weights.values())
    return random.choices(departments, weights=weights, k=1)[0]


def _pick_employee_type(department: str) -> str:
    """
    Determines whether a user is a full-time employee, contractor,
    or service account based on their department.

    Contractors always come from the contractors department.
    Service accounts are rare (about 3% of non-contractor users).
    Everyone else is full-time.

    Args:
        department: The user's department name.

    Returns:
        One of: "full_time", "contractor", "service_account"
    """
    if department == "contractors":
        return "contractor"
    # ~3% chance of being a service account in any non-contractor dept
    if random.random() < 0.03:
        return "service_account"
    return "full_time"


def _build_profile(
    name_data: dict,
    title: str,
    department: str,
    manager_login: str | None,
    employee_type: str,
    org_level: str,
    settings: dict,
) -> dict:
    """
    Builds the full Okta user profile dict.

    Okta stores user identity data in a "profile" object. This function
    assembles all the fields that make a user look real and complete.
    Every field here maps directly to an Okta profile attribute.

    Args:
        name_data:     Dict from generate_name() with first/last/login/email.
        title:         The user's job title.
        department:    The user's department name.
        manager_login: The login of the user's manager, or None for the CEO.
        employee_type: "full_time", "contractor", or "service_account".
        org_level:     "executive", "director", "manager", or "ic".
        settings:      The settings dict from settings.yaml.

    Returns:
        A dict matching Okta's user profile schema.
    """
    prefix = settings["generation"]["resource_prefix"]

    # Add the resource prefix to the login so cleanup.py can identify
    # everything this tool created (e.g. "chaos-sarah.chen@acmecorp.com")
    prefixed_login = f"{prefix}{name_data['login'].split('@')[0]}@{name_data['login'].split('@')[1]}"
    prefixed_email = prefixed_login

    return {
        "login":          prefixed_login,
        "email":          prefixed_email,
        "firstName":      name_data["first_name"],
        "lastName":       name_data["last_name"],
        "displayName":    name_data["display_name"],
        "title":          title,
        "department":     department.title(),
        "organization":   "AcmeCorp",
        "employeeNumber": generate_employee_number(),
        "employeeType":   employee_type,
        "manager":        manager_login,
        "mobilePhone":    _fake.phone_number(),
        "city":           _fake.city(),
        "state":          _fake.state_abbr(),
        "costCenter":     f"CC-{department.upper()[:3]}-{random.randint(100, 999)}",
        "userType":       employee_type,
    }


def _build_credentials(
    hire_date,
    employee_type: str,
) -> dict:
    """
    Builds the credentials/lifecycle fields for a user.

    These are the time-based fields that IAM tools scrutinize most:
    when was the account created, when did they last log in, and
    when did they last change their password.

    Args:
        hire_date:     The datetime when the account was created.
        employee_type: Used to set appropriate activity patterns.

    Returns:
        A dict with created, last_login, and password_changed timestamps.
    """
    # Determine activity level — most users are normal, some are active,
    # a few are infrequent. Chaos will later override some to "stale"/"never".
    activity_roll = random.random()
    if activity_roll < 0.40:
        activity_level = "active"
    elif activity_roll < 0.85:
        activity_level = "normal"
    else:
        activity_level = "infrequent"

    last_login = generate_last_login(hire_date, activity_level)
    password_changed = generate_password_changed(hire_date, last_login)

    return {
        "created":          format_okta_timestamp(hire_date),
        "last_login":       format_okta_timestamp(last_login),
        "password_changed": format_okta_timestamp(password_changed),
        "status":           "ACTIVE",
        # Store raw datetime for chaos engine comparisons
        "_hire_date_raw":   hire_date,
        "_last_login_raw":  last_login,
        "_activity_level":  activity_level,
    }


def generate_users(seed: int | None = None, user_count: int | None = None) -> list[dict]:
    """
    The main function. Generates the full list of clean user records.

    This is what main.py calls to get the user dataset before chaos
    is applied. Each record in the returned list is a complete user
    ready to be mutated by the chaos engine and then pushed to Okta.

    Args:
        seed:       Optional random seed for reproducible generation.
        user_count: Optional override for total user count. If None,
                    picks randomly between min and max from settings.yaml.

    Returns:
        A list of user dicts, each containing:
            - profile       (dict) Okta profile fields
            - credentials   (dict) dates and status
            - groups        (list) group names the user belongs to
            - admin_roles   (list) Okta admin role types (empty for clean users)
            - apps          (list) app IDs assigned to this user
            - org_level     (str)  executive / director / manager / ic
            - department    (str)  department name
            - employee_type (str)  full_time / contractor / service_account
            - chaos_tags    (list) empty here — filled by chaos engine
    """
    if seed is not None:
        random.seed(seed)

    settings, departments, apps_config = _load_config()

    # Use provided count or pick randomly between min and max
    if user_count is None:
        user_count = random.randint(
            settings["generation"]["user_count"]["min"],
            settings["generation"]["user_count"]["max"],
        )

    # Build the org hierarchy so we know how many executives, directors, etc.
    hierarchy = build_hierarchy(user_count)

    dept_weights = settings["departments"]
    existing_logins: set[str] = set()
    users: list[dict] = []

    print(f"  Generating {user_count} users...")

    for i in range(user_count):
        # Determine this user's place in the org
        org_level  = assign_org_level(i, user_count, hierarchy)
        department = _pick_department(dept_weights)
        emp_type   = _pick_employee_type(department)

        # Get department config from departments.yaml
        dept_config = departments.get(department, departments["engineering"])

        # Generate identity
        if emp_type == "service_account":
            purposes = ["deploy", "monitoring", "backup", "ci-runner", "reporting", "integration"]
            name_data = generate_service_account_name(random.choice(purposes))
        else:
            name_data = generate_name()

        # Ensure login is unique across all generated users
        unique_login = make_login_unique(name_data["login"], existing_logins)
        name_data["login"] = unique_login
        name_data["email"] = unique_login
        existing_logins.add(unique_login)

        # Determine title based on org level and department
        title = get_title_for_level(org_level, department, dept_config)

        # Assign manager from users already created above this person in the list
        manager_login = assign_manager_login(org_level, i, hierarchy, users)

        # Generate dates
        hire_date   = generate_hire_date(emp_type)
        credentials = _build_credentials(hire_date, emp_type)

        # Build the full profile
        profile = _build_profile(
            name_data, title, department, manager_login,
            emp_type, org_level, settings,
        )

        # Determine groups based on department config
        groups = _assign_clean_groups(org_level, department, dept_config)

        users.append({
            "profile":       profile,
            "credentials":   credentials,
            "groups":        groups,
            "admin_roles":   [],           # empty — chaos engine adds these
            "apps":          [],           # filled by app_generator.py
            "org_level":     org_level,
            "department":    department,
            "employee_type": emp_type,
            "chaos_tags":    [],           # filled by chaos engine
        })

    return users


def _assign_clean_groups(
    org_level: str,
    department: str,
    dept_config: dict,
) -> list[str]:
    """
    Assigns the correct groups to a clean (pre-chaos) user.

    Every user gets their department group plus the standard access groups
    for their department. Leads and managers also get lead-level groups.
    Executives get the role-executives group.

    Args:
        org_level:   The user's position in the org hierarchy.
        department:  The user's department.
        dept_config: The department's entry from departments.yaml.

    Returns:
        A list of group name strings.
    """
    groups_config = dept_config.get("groups", {})
    groups = []

    # Everyone gets their department group
    dept_group = groups_config.get("department")
    if dept_group:
        groups.append(dept_group)

    # Everyone gets the standard access groups for their department
    access_groups = groups_config.get("access", [])
    groups.extend(access_groups)

    # Leads, managers, directors, and executives get extra groups
    if org_level in ("manager", "director", "executive"):
        lead_groups = groups_config.get("lead_groups", [])
        groups.extend(lead_groups)

    # Executives also get the global executives role group
    if org_level == "executive":
        if "role-executives" not in groups:
            groups.append("role-executives")

    # Contractors get the contractors role group
    if department == "contractors":
        groups.append("role-contractors")

    return list(set(groups))  # deduplicate
