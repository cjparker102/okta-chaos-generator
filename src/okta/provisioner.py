"""
src/okta/provisioner.py

Pushes everything to Okta in the correct dependency order:
  1. Create all groups first
  2. Create all users
  3. Assign users to their groups
  4. Assign admin roles to chaos users

The ordering matters — Okta will reject a group assignment if the
group doesn't exist yet, and reject a user creation if the login
already exists. We handle all of that here.

This file uses Rich for all terminal output — progress bars and
colored status so you can watch the run in real time.
"""

import asyncio
import yaml
import os
from rich.console import Console
from rich.progress import (
    Progress, SpinnerColumn, BarColumn,
    TextColumn, TaskProgressColumn, TimeElapsedColumn,
)
from rich.table import Table

from src.okta.client import build_client, safe_api_call
from src.okta.session import (
    init_session, record_group, record_user,
    record_admin_role, session_exists,
)


console = Console()

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _load_settings() -> dict:
    """Loads settings.yaml."""
    with open(os.path.join(_CONFIG_DIR, "settings.yaml")) as f:
        return yaml.safe_load(f)


async def provision_all(
    users: list[dict],
    groups: list[dict],
    dry_run: bool = False,
) -> None:
    """
    The main provisioning function. Pushes users and groups to Okta.

    This is what main.py calls after generation and chaos injection
    are complete. It handles the full lifecycle: groups → users →
    group memberships → admin roles.

    Args:
        users:   The chaos-injected user list.
        groups:  The group list from group_generator.
        dry_run: If True, prints what WOULD happen without calling Okta.
    """
    settings = _load_settings()
    prefix   = settings["generation"]["resource_prefix"]

    if dry_run:
        _print_dry_run_summary(users, groups, prefix)
        return

    if session_exists():
        console.print(
            "\n[yellow]⚠️  A previous session exists (.session.json).[/yellow]"
            "\nRun [bold]python cleanup.py[/bold] before generating a new org.\n"
        )
        return

    client = build_client()
    init_session(prefix)

    console.print(f"\n[bold green]🚀 Starting provisioning...[/bold green]")
    console.print(f"   Groups to create : [cyan]{len(groups)}[/cyan]")
    console.print(f"   Users to create  : [cyan]{len(users)}[/cyan]\n")

    # Step 1 — Create groups
    group_id_map = await _provision_groups(client, groups)

    # Step 2 — Create users
    user_id_map = await _provision_users(client, users)

    # Step 3 — Assign users to groups
    await _assign_group_memberships(client, users, group_id_map, user_id_map, prefix)

    # Step 4 — Assign admin roles
    await _assign_admin_roles(client, users, user_id_map)

    console.print(f"\n[bold green]✅ Provisioning complete![/bold green]")
    console.print(f"   {len(group_id_map)} groups created")
    console.print(f"   {len(user_id_map)} users created")
    console.print(
        f"\n[dim]Run [bold]python reveal.py[/bold] to see what chaos was injected.[/dim]"
        f"\n[dim]Run [bold]python cleanup.py[/bold] to delete everything.[/dim]\n"
    )


async def _provision_groups(
    client,
    groups: list[dict],
) -> dict[str, str]:
    """
    Creates all groups in Okta and returns a name→ID mapping.

    Groups must exist before users can be assigned to them.

    Args:
        client: Authenticated OktaClient.
        groups: Group list from group_generator.generate_groups().

    Returns:
        Dict of {group_name: okta_group_id}.
    """
    group_id_map: dict[str, str] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Creating groups[/bold blue]"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("groups", total=len(groups))

        for group in groups:
            group_body = {
                "profile": {
                    "name":        group["name"],
                    "description": group["description"],
                }
            }

            result = await safe_api_call(
                lambda: client.create_group(group_body),
                description=f"create group {group['name']}",
            )

            created_group, _, err = result
            if err:
                console.print(f"   [red]Failed to create group {group['name']}: {err}[/red]")
            else:
                group_id_map[group["name"]] = created_group.id
                record_group(created_group.id, group["name"])

            progress.advance(task)

    return group_id_map


async def _provision_users(
    client,
    users: list[dict],
) -> dict[str, str]:
    """
    Creates all users in Okta and returns a login→ID mapping.

    Each user is created with ACTIVE status and a temporary password.
    In a real org you'd send an activation email — here we activate
    directly so the accounts exist in a queryable state.

    Args:
        client: Authenticated OktaClient.
        users:  The chaos-injected user list.

    Returns:
        Dict of {login: okta_user_id}.
    """
    user_id_map: dict[str, str] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Creating users[/bold blue] "),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("users", total=len(users))

        for user in users:
            profile  = user["profile"]
            creds    = user["credentials"]

            user_body = {
                "profile": {
                    "login":          profile["login"],
                    "email":          profile["email"],
                    "firstName":      profile["firstName"],
                    "lastName":       profile["lastName"],
                    "displayName":    profile.get("displayName", ""),
                    "title":          profile.get("title", ""),
                    "department":     profile.get("department", ""),
                    "organization":   profile.get("organization", "AcmeCorp"),
                    "employeeNumber": profile.get("employeeNumber", ""),
                    "mobilePhone":    profile.get("mobilePhone"),
                    "city":           profile.get("city"),
                    "userType":       profile.get("userType", "full_time"),
                },
                "credentials": {
                    "password": {
                        # Temporary password — meets Okta's complexity requirements
                        "value": "Ch@os2024!"
                    }
                },
            }

            # activate=True creates the user in ACTIVE status immediately
            result = await safe_api_call(
                lambda: client.create_user(user_body, {"activate": "true"}),
                description=f"create user {profile['login']}",
            )

            created_user, _, err = result
            if err:
                err_str = str(err)
                # If the user already exists (e.g. from a partial previous run),
                # look them up by login and record them so group assignments work.
                if "already exists" in err_str:
                    login = profile["login"]
                    lookup = await safe_api_call(
                        lambda l=login: client.get_user(l),
                        description=f"lookup existing user {login}",
                    )
                    existing_user, _, lookup_err = lookup
                    if not lookup_err and existing_user:
                        user_id_map[login] = existing_user.id
                        record_user(existing_user.id, login)
                        console.print(f"   [yellow]User {login} already exists — reusing[/yellow]")
                    else:
                        console.print(f"   [red]Failed to create or find {login}: {err}[/red]")
                else:
                    console.print(f"   [red]Failed to create {profile['login']}: {err}[/red]")
            else:
                user_id_map[profile["login"]] = created_user.id
                record_user(created_user.id, profile["login"])

            progress.advance(task)

    return user_id_map


async def _assign_group_memberships(
    client,
    users: list[dict],
    group_id_map: dict[str, str],
    user_id_map: dict[str, str],
    prefix: str,
) -> None:
    """
    Assigns each user to their groups.

    We created groups with the resource_prefix (e.g. "chaos-dept-engineering").
    The user's groups list stores the unprefixed names (e.g. "dept-engineering").
    We add the prefix here when looking up the Okta group ID.

    Args:
        client:       Authenticated OktaClient.
        users:        The chaos-injected user list.
        group_id_map: Name→ID map from _provision_groups.
        user_id_map:  Login→ID map from _provision_users.
        prefix:       The resource prefix from settings.yaml.
    """
    # Count total assignments for the progress bar
    total_assignments = sum(len(u["groups"]) for u in users)

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Assigning groups[/bold blue]  "),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("memberships", total=total_assignments)

        for user in users:
            login   = user["profile"]["login"]
            user_id = user_id_map.get(login)

            if not user_id:
                progress.advance(task, advance=len(user["groups"]))
                continue

            for group_name in user["groups"]:
                # Look up both prefixed and unprefixed forms
                prefixed = f"{prefix}{group_name}"
                group_id = group_id_map.get(prefixed) or group_id_map.get(group_name)

                if not group_id:
                    progress.advance(task)
                    continue

                await safe_api_call(
                    lambda gid=group_id, uid=user_id: client.add_user_to_group(gid, uid),
                    description=f"add {login} to {group_name}",
                )
                progress.advance(task)


async def _assign_admin_roles(
    client,
    users: list[dict],
    user_id_map: dict[str, str],
) -> None:
    """
    Assigns Okta admin roles to any users who have them.

    Only chaos-injected users will have admin_roles populated.
    This step runs last because admin role assignment is the most
    sensitive operation — we want all users and groups created first.

    Args:
        client:      Authenticated OktaClient.
        users:       The chaos-injected user list.
        user_id_map: Login→ID map from _provision_users.
    """
    admin_users = [u for u in users if u.get("admin_roles")]

    if not admin_users:
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold red]Assigning admin roles[/bold red]"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        total = sum(len(u["admin_roles"]) for u in admin_users)
        task  = progress.add_task("roles", total=total)

        for user in admin_users:
            login   = user["profile"]["login"]
            user_id = user_id_map.get(login)

            if not user_id:
                progress.advance(task, advance=len(user["admin_roles"]))
                continue

            for role_type in user["admin_roles"]:
                role_body = {"type": role_type}

                result = await safe_api_call(
                    lambda uid=user_id, rb=role_body: client.assign_role_to_user(uid, rb),
                    description=f"assign {role_type} to {login}",
                )

                role_obj, _, err = result
                if err:
                    console.print(
                        f"   [red]Failed to assign {role_type} to {login}: {err}[/red]"
                    )
                else:
                    record_admin_role(user_id, role_type, role_obj.id)

                progress.advance(task)


def _print_dry_run_summary(
    users: list[dict],
    groups: list[dict],
    prefix: str,
) -> None:
    """
    Prints a detailed summary of what WOULD be created, without
    touching Okta. This is what dry_run.py displays.

    Args:
        users:  The chaos-injected user list.
        groups: The group list.
        prefix: The resource prefix.
    """
    console.print(f"\n[bold cyan]📋 DRY RUN SUMMARY[/bold cyan]")
    console.print(f"   Resource prefix : [cyan]{prefix}[/cyan]")
    console.print(f"   Groups          : [cyan]{len(groups)}[/cyan]")
    console.print(f"   Users           : [cyan]{len(users)}[/cyan]")

    # Department breakdown
    dept_counts: dict[str, int] = {}
    for user in users:
        dept = user["department"]
        dept_counts[dept] = dept_counts.get(dept, 0) + 1

    table = Table(title="Department Breakdown", show_header=True)
    table.add_column("Department", style="cyan")
    table.add_column("Users", justify="right")
    table.add_column("% of Org", justify="right")

    for dept, count in sorted(dept_counts.items(), key=lambda x: -x[1]):
        pct = round(count / len(users) * 100, 1)
        table.add_row(dept.title(), str(count), f"{pct}%")

    console.print(table)

    # Admin role summary
    admin_users = [u for u in users if u.get("admin_roles")]
    if admin_users:
        console.print(f"\n[bold red]Admin Roles ({len(admin_users)} users)[/bold red]")
        for u in admin_users:
            roles = ", ".join(u["admin_roles"])
            console.print(f"   {u['profile']['login']} → [red]{roles}[/red]")

    console.print(
        f"\n[dim]Run [bold]python main.py[/bold] to push this to Okta.[/dim]\n"
    )
