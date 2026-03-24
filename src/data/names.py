"""
src/data/names.py

Generates realistic, diverse names for fake users and builds their
Okta login/email from those names.

We use Faker with multiple locales so the org doesn't look like
everyone is from the same country — a real company of 150 people
will have names from many backgrounds.
"""

import random
import re
from faker import Faker


# Multiple locales give us diverse name pools.
# Each locale contributes names from a different cultural background.
_LOCALES = [
    "en_US",   # American English
    "en_GB",   # British English
    "es_MX",   # Mexican Spanish
    "pt_BR",   # Brazilian Portuguese
    "zh_CN",   # Chinese
    "ja_JP",   # Japanese
    "de_DE",   # German
    "fr_FR",   # French
    "hi_IN",   # Hindi / Indian
    "ko_KR",   # Korean
]

# Build one Faker instance per locale, stored in a dict
_FAKERS: dict[str, Faker] = {locale: Faker(locale) for locale in _LOCALES}

# The company domain used for all generated email addresses
COMPANY_DOMAIN = "acmecorp.com"


def _clean_for_login(name: str) -> str:
    """
    Converts a name string into something safe to use in an email login.

    Real names can have accents, spaces, apostrophes, and other characters
    that break email addresses. This strips them down to plain ASCII letters.

    Examples:
        "José"     → "jose"
        "O'Brien"  → "obrien"
        "van der Berg" → "vandenberg"  (after joining with dot)

    Args:
        name: A raw name string.

    Returns:
        A lowercase ASCII-safe version of the name.
    """
    # Normalize unicode characters (é → e, ñ → n, etc.)
    import unicodedata
    normalized = unicodedata.normalize("NFKD", name)
    # Keep only ASCII characters
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    # Remove anything that isn't a letter, number, space, or hyphen
    cleaned = re.sub(r"[^a-zA-Z0-9 \-]", "", ascii_only)
    # Lowercase and strip whitespace
    return cleaned.strip().lower()


def generate_name(seed: int | None = None) -> dict:
    """
    Generates a single realistic person's name using a randomly chosen locale.

    Picks a locale at random, generates a first and last name from it,
    then builds a display name, login, and email address.

    Args:
        seed: Optional random seed for reproducible output. If None, truly random.

    Returns:
        A dict with keys:
            - first_name    (str) e.g. "Sarah"
            - last_name     (str) e.g. "Chen"
            - display_name  (str) e.g. "Sarah Chen"
            - login         (str) e.g. "sarah.chen@acmecorp.com"
            - email         (str) same as login for regular users
    """
    if seed is not None:
        random.seed(seed)

    # Pick a random locale and use its Faker instance
    locale = random.choice(_LOCALES)
    fake = _FAKERS[locale]

    first = fake.first_name()
    last = fake.last_name()

    # Clean both parts for use in an email
    first_clean = _clean_for_login(first)
    last_clean = _clean_for_login(last)

    # Handle edge case: if cleaning removes everything (rare with some locales),
    # fall back to the en_US faker
    if not first_clean or not last_clean:
        fallback = _FAKERS["en_US"]
        first = fallback.first_name()
        last = fallback.last_name()
        first_clean = _clean_for_login(first)
        last_clean = _clean_for_login(last)

    login = f"{first_clean}.{last_clean}@{COMPANY_DOMAIN}"

    return {
        "first_name": first,
        "last_name": last,
        "display_name": f"{first} {last}",
        "login": login,
        "email": login,
    }


def generate_service_account_name(purpose: str) -> dict:
    """
    Generates a service account identity with the svc. naming convention.

    Service accounts are non-human identities used by systems and scripts.
    Real orgs use naming patterns like svc.deploy, svc.monitoring, svc.backup.
    In our chaos org, some service accounts will be "gone rogue" — they'll
    end up with human-level access they shouldn't have.

    Args:
        purpose: What the service account is for, e.g. "deploy", "monitoring".

    Returns:
        A dict with the same keys as generate_name(), but with svc. prefix.
    """
    login = f"svc.{purpose.lower().replace(' ', '-')}@{COMPANY_DOMAIN}"

    return {
        "first_name": "svc",
        "last_name": purpose,
        "display_name": f"SVC - {purpose.title()}",
        "login": login,
        "email": login,
    }


def make_login_unique(login: str, existing_logins: set[str]) -> str:
    """
    Ensures a login is unique by appending a number if it already exists.

    In a real org (and in ours), two people can share the same name.
    John Smith #1 gets john.smith@acmecorp.com, John Smith #2 gets
    john.smith2@acmecorp.com, and so on.

    Args:
        login:           The desired login (e.g. "john.smith@acmecorp.com").
        existing_logins: Set of logins already taken.

    Returns:
        A unique login string, with a number appended if needed.
    """
    if login not in existing_logins:
        return login

    # Split at @ to insert the number before the domain
    local, domain = login.split("@")
    counter = 2
    while f"{local}{counter}@{domain}" in existing_logins:
        counter += 1

    return f"{local}{counter}@{domain}"


def generate_employee_number() -> str:
    """
    Generates a realistic employee ID number.

    Real orgs use sequential or random numeric IDs to identify employees
    in HR systems. We prefix with EMP- to make it obvious what it is.

    Returns:
        A string like "EMP-004821".
    """
    return f"EMP-{random.randint(1000, 9999)}"
