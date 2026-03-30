"""
src/chaos/chaos_engine.py

The chaos engine. Secretly picks how many users to corrupt,
which chaos profiles to apply, and which users become victims.

This is the file that makes the org unpredictable. You'll never
know how many bad accounts are in there until you run reveal.py.

Design decisions:
  - Chaos density is random between min/max from settings.yaml
  - Tier weights control the MIX of chaos (more medium than critical)
  - Users can be stacked with up to max_stack chaos types
  - The manifest records everything — but stays hidden until reveal.py
  - Service accounts are excluded from most chaos (they have their own profile)
"""

import copy
import random
import json
import os
import yaml
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.chaos.profiles import PROFILES_BY_TIER, PROFILES_BY_ID, PROFILES
from src.data.names import make_login_unique
from src.data.timeline import NOW, format_okta_timestamp, generate_hire_date
from src.generator.app_generator import assign_apps


console = Console()

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "config")
_MANIFEST_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", ".chaos_manifest.json"
)


def _load_settings() -> dict:
    """
    Loads settings.yaml.

    Returns:
        The settings dict.
    """
    with open(os.path.join(_CONFIG_DIR, "settings.yaml")) as f:
        return yaml.safe_load(f)


def _pick_chaos_profile(tier_weights: dict) -> dict:
    """
    Picks a random chaos profile using weighted tier selection.

    First picks a tier (e.g. "medium") based on weights, then
    picks a random profile from that tier.

    Args:
        tier_weights: Dict of {tier: weight} from settings.yaml.

    Returns:
        A chaos profile dict from profiles.py.
    """
    tiers   = list(tier_weights.keys())
    weights = list(tier_weights.values())

    chosen_tier = random.choices(tiers, weights=weights, k=1)[0]
    tier_profiles = PROFILES_BY_TIER.get(chosen_tier, [])

    if not tier_profiles:
        # Fallback to any profile if the tier is somehow empty
        return random.choice(PROFILES)

    return random.choice(tier_profiles)


def _pick_victims(users: list[dict], density: float) -> list[int]:
    """
    Randomly selects which users will receive chaos injections.

    We avoid picking the very first few users (executives) for the
    worst chaos — this keeps at least some leadership looking clean.
    We also avoid service accounts — they have their own chaos profile.

    Args:
        users:   The full list of clean users.
        density: Fraction of users to corrupt (0.15 to 0.40).

    Returns:
        A list of indices into the users list.
    """
    # Exclude the first 3 users (CEO and top VPs) and pure service accounts
    # from the general chaos pool
    eligible_indices = [
        i for i, u in enumerate(users)
        if i >= 3 and u["employee_type"] != "service_account"
    ]

    chaos_count = max(1, int(len(eligible_indices) * density))
    return random.sample(eligible_indices, min(chaos_count, len(eligible_indices)))


def inject_chaos(users: list[dict], dry_run: bool = False) -> dict:
    """
    The main function. Applies chaos mutations to a random subset of users.

    This function:
      1. Picks a random chaos density from settings
      2. Selects victim user indices
      3. For each victim, picks 1 or 2 chaos profiles and applies them
      4. Assigns final apps to all users (after chaos may have changed groups)
      5. Writes the secret manifest to .chaos_manifest.json
      6. Returns the manifest (revealed only in dry_run mode or reveal.py)

    Args:
        users:    The clean user list from user_generator.generate_users().
        dry_run:  If True, prints chaos details to the console. If False, stays silent.

    Returns:
        The chaos manifest dict — what was injected into whom.
    """
    settings    = _load_settings()
    chaos_cfg   = settings["chaos"]
    gen_cfg     = settings["generation"]

    # Pick random density — this is the secret
    density = random.uniform(
        gen_cfg["chaos_density"]["min"],
        gen_cfg["chaos_density"]["max"],
    )

    tier_weights = chaos_cfg["tier_weights"]
    max_stack    = chaos_cfg["max_stack"]

    victim_indices = _pick_victims(users, density)

    manifest = {
        "total_users":    len(users),
        "chaos_count":    len(victim_indices),
        "chaos_density":  round(density, 3),
        "victims":        [],
    }

    if dry_run:
        console.print(f"\n[bold red]🔥 CHAOS ENGINE[/bold red]")
        console.print(f"   Density : [yellow]{round(density * 100, 1)}%[/yellow]")
        console.print(f"   Victims : [yellow]{len(victim_indices)} of {len(users)} users[/yellow]\n")

    for idx in victim_indices:
        user = users[idx]

        # How many chaos profiles to stack on this user?
        stack_count = random.randint(1, max_stack)

        # Pick unique profiles (no duplicates on same user)
        chosen_profiles = []
        used_ids: set[str] = set()

        for _ in range(stack_count):
            profile = _pick_chaos_profile(tier_weights)
            # Try up to 5 times to get a non-duplicate profile
            for _ in range(5):
                if profile["id"] not in used_ids:
                    break
                profile = _pick_chaos_profile(tier_weights)

            if profile["id"] not in used_ids:
                chosen_profiles.append(profile)
                used_ids.add(profile["id"])

        # Apply each mutation
        for profile in chosen_profiles:
            try:
                profile["mutate"](user)
            except Exception as e:
                # Never let a chaos mutation crash the whole run
                if dry_run:
                    console.print(f"   [dim]Warning: mutation {profile['id']} failed: {e}[/dim]")

            # Tag the user so reveal.py can find them
            if profile["id"] not in user["chaos_tags"]:
                user["chaos_tags"].append(profile["id"])

        victim_entry = {
            "index":        idx,
            "login":        user["profile"]["login"],
            "chaos_types":  [p["id"] for p in chosen_profiles],
            "tiers":        [p["tier"] for p in chosen_profiles],
        }
        manifest["victims"].append(victim_entry)

        if dry_run:
            tiers_str   = " + ".join(p["tier"].upper() for p in chosen_profiles)
            types_str   = ", ".join(p["id"] for p in chosen_profiles)
            color       = "red" if "critical" in [p["tier"] for p in chosen_profiles] else "yellow"
            console.print(
                f"   [{color}]{tiers_str}[/{color}] "
                f"[bold]{user['profile']['login']}[/bold] → {types_str}"
            )

    # Create duplicate accounts for users tagged by the duplicate_identity profile.
    # The original is the stale "old" account. The clone is a fresh "new" account
    # with the same name but a different login — mimicking a rehire where the
    # old account was never disabled.
    dupes_created = _create_duplicate_accounts(users, manifest, dry_run)

    # After all chaos is applied, assign final apps to every user.
    # We do this AFTER chaos because some mutations change employee_type
    # or groups, which affects app eligibility.
    for user in users:
        user["apps"] = assign_apps(user)

    # Write the secret manifest — hidden from main.py output
    _write_manifest(manifest)

    if dry_run:
        console.print(f"\n[dim]Manifest written to .chaos_manifest.json[/dim]")

    return manifest


def _create_duplicate_accounts(
    users: list[dict],
    manifest: dict,
    dry_run: bool,
) -> int:
    """
    Scans for users tagged with _is_duplicate_primary and creates a
    second account for each — the "new" account that should have replaced
    the old one but didn't.

    The original (primary) account is already stale from the mutation.
    The clone gets:
      - Same firstName and lastName (how auditors spot duplicates)
      - A different login (e.g. john.smith2@acmecorp.com)
      - Recent hire date and active login (the "current" account)
      - Same department and groups (inherited the role)

    Args:
        users:    The user list — clones are appended in place.
        manifest: The chaos manifest — clones are added to the victim list.
        dry_run:  If True, prints details to the console.

    Returns:
        Number of duplicate accounts created.
    """
    # Collect all existing logins so we can ensure uniqueness
    existing_logins = {u["profile"]["login"] for u in users}
    dupes_created = 0

    # Find all primary-tagged users and their indices BEFORE we start appending
    primaries = [
        (i, u) for i, u in enumerate(users)
        if "_is_duplicate_primary" in u.get("chaos_tags", [])
    ]

    for original_idx, original in primaries:
        # Deep copy so we don't share mutable objects with the original
        clone = copy.deepcopy(original)

        # Build a new login — same name pattern but with a numeric suffix
        original_login = original["profile"]["login"]
        clone_login = make_login_unique(original_login, existing_logins)
        existing_logins.add(clone_login)

        clone["profile"]["login"] = clone_login
        clone["profile"]["email"] = clone_login

        # The clone is the "new" account — recent hire, active usage
        recent_hire = generate_hire_date("full_time")
        clone["credentials"]["created"] = format_okta_timestamp(recent_hire)
        clone["credentials"]["last_login"] = format_okta_timestamp(NOW)
        clone["credentials"]["_last_login_raw"] = NOW
        clone["credentials"]["_hire_date_raw"] = recent_hire
        clone["credentials"]["_activity_level"] = "active"
        clone["credentials"]["status"] = "ACTIVE"

        # Tag the clone so reveal.py can identify both halves
        clone["chaos_tags"] = ["duplicate_identity", "_is_duplicate_clone"]

        # Append the clone to the user list
        clone_idx = len(users)
        users.append(clone)
        dupes_created += 1

        # Add the clone to the manifest
        manifest["victims"].append({
            "index":       clone_idx,
            "login":       clone_login,
            "chaos_types": ["duplicate_identity"],
            "tiers":       ["medium"],
            "duplicate_of": original_login,
        })

        # Update the original's manifest entry to reference the clone
        for entry in manifest["victims"]:
            if entry["login"] == original_login and "duplicate_identity" in entry["chaos_types"]:
                entry["duplicate_of"] = clone_login
                break

        if dry_run:
            console.print(
                f"   [yellow]DUPLICATE[/yellow] "
                f"[bold]{clone_login}[/bold] ← clone of {original_login}"
            )

    # Update total user count in the manifest
    manifest["total_users"] = len(users)

    return dupes_created


def _write_manifest(manifest: dict) -> None:
    """
    Writes the chaos manifest to .chaos_manifest.json.

    This file is gitignored so it never gets committed. It's the
    "answer key" that reveal.py reads.

    Args:
        manifest: The chaos manifest dict.
    """
    with open(_MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
