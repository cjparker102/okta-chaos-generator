"""
src/data/timeline.py

Generates realistic dates for user accounts — when they were created,
when they last logged in, and when they last changed their password.

Dates are one of the most important signals in an access review.
A SUPER_ADMIN who hasn't logged in for 14 months looks very different
from one who logged in yesterday. This module makes those dates feel real.
"""

import random
from datetime import datetime, timedelta, timezone


# The "present" moment all dates are calculated relative to.
# Using a fixed reference date makes dry runs consistent.
NOW = datetime(2026, 3, 24, tzinfo=timezone.utc)


def _random_date_between(start: datetime, end: datetime) -> datetime:
    """
    Returns a random datetime between two datetimes.

    Args:
        start: Earliest possible date.
        end:   Latest possible date.

    Returns:
        A random datetime between start and end.
    """
    delta = end - start
    random_seconds = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=random_seconds)


def generate_hire_date(employee_type: str = "full_time") -> datetime:
    """
    Generates a realistic hire date based on employee type.

    Full-time employees tend to have a wide range of tenure — some are
    brand new, some have been there for years. Contractors are typically
    more recent. Executives tend to have been around longer.

    The distribution is weighted toward more recent hires (the last
    2 years) with a long tail going back up to 8 years. This mirrors
    how real orgs grow — faster recently than in the past.

    Args:
        employee_type: One of "full_time", "contractor", "service_account".

    Returns:
        A datetime representing when the account was created in Okta.
    """
    if employee_type == "contractor":
        # Contractors are typically more recent — 1 month to 2 years ago
        start = NOW - timedelta(days=730)
        end = NOW - timedelta(days=30)

    elif employee_type == "service_account":
        # Service accounts can be very old — up to 6 years
        start = NOW - timedelta(days=365 * 6)
        end = NOW - timedelta(days=90)

    else:
        # Full-time: 2 weeks to 8 years ago, weighted toward recent
        # We use a random choice between "recent" (70%) and "veteran" (30%)
        if random.random() < 0.70:
            # Recent hire: 2 weeks to 2 years ago
            start = NOW - timedelta(days=730)
            end = NOW - timedelta(days=14)
        else:
            # Veteran: 2 to 8 years ago
            start = NOW - timedelta(days=365 * 8)
            end = NOW - timedelta(days=730)

    return _random_date_between(start, end)


def generate_last_login(
    hire_date: datetime,
    activity_level: str = "normal",
) -> datetime | None:
    """
    Generates a realistic last login date based on how active the user is.

    Activity level controls how recently the user logged in:
      - "active"    → logged in within the last 14 days (regular user)
      - "normal"    → logged in within the last 90 days
      - "infrequent"→ logged in 90–180 days ago (busy or occasional user)
      - "stale"     → logged in 6–18 months ago (this is the chaos zone)
      - "never"     → returns None — account was created but never used

    Args:
        hire_date:      When the account was created — last login can't be before this.
        activity_level: How recently the user logs in.

    Returns:
        A datetime of the last login, or None if the user never logged in.
    """
    if activity_level == "never":
        return None

    if activity_level == "active":
        start = NOW - timedelta(days=14)
        end = NOW - timedelta(hours=1)

    elif activity_level == "normal":
        start = NOW - timedelta(days=90)
        end = NOW - timedelta(days=1)

    elif activity_level == "infrequent":
        start = NOW - timedelta(days=180)
        end = NOW - timedelta(days=90)

    elif activity_level == "stale":
        # 6 to 18 months ago — this is what triggers IAM alerts
        start = NOW - timedelta(days=540)
        end = NOW - timedelta(days=180)

    else:
        # Default: treat as normal
        start = NOW - timedelta(days=90)
        end = NOW - timedelta(days=1)

    # Last login can't be before the account was created
    if start < hire_date:
        start = hire_date + timedelta(days=1)

    # If there's no valid window (account too new), return None
    if start >= end:
        return None

    return _random_date_between(start, end)


def generate_password_changed(
    hire_date: datetime,
    last_login: datetime | None,
    never_changed: bool = False,
) -> datetime | None:
    """
    Generates a realistic password last-changed date.

    In a healthy org, users reset their password periodically — typically
    every 90–180 days per policy. In a broken org (ours), some users have
    never changed their password since the account was created.

    Args:
        hire_date:     When the account was created.
        last_login:    When the user last logged in (used as a ceiling).
        never_changed: If True, returns None — password has never been rotated.

    Returns:
        A datetime of the last password change, or None if never changed.
    """
    if never_changed:
        return None

    # Password was changed somewhere between hire date and last login
    # (or between hire date and now if they've never logged in)
    ceiling = last_login if last_login else NOW

    # Make sure there's a valid window
    if hire_date >= ceiling:
        return None

    return _random_date_between(hire_date, ceiling)


def format_okta_timestamp(dt: datetime | None) -> str | None:
    """
    Formats a datetime into the ISO 8601 format Okta expects.

    Okta's API uses timestamps like "2024-03-15T14:22:00.000Z".

    Args:
        dt: A datetime object, or None.

    Returns:
        An ISO 8601 string, or None if the input was None.
    """
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def days_since(dt: datetime | None) -> int | None:
    """
    Returns how many days ago a datetime was, relative to NOW.

    Useful for generating human-readable summaries and for chaos
    profiles that need to check "has this user been inactive for X days?"

    Args:
        dt: A datetime object, or None.

    Returns:
        Number of days since dt, or None if dt is None.
    """
    if dt is None:
        return None
    return (NOW - dt).days
