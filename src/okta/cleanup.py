"""
src/okta/cleanup.py

Deletes everything created by a previous generation run.

Two modes:
  1. Session cleanup — reads .session.json for exact Okta IDs (fast, precise)
  2. Purge mode — searches Okta directly for all resources matching the
     prefix when no session file exists (catches orphans from crashed runs)

Both modes delete in the correct reverse dependency order:
  1. Remove admin roles first (can't delete a user with an active role)
  2. Deactivate and delete users
  3. Delete groups

We also do a safety check: we only delete resources whose names
start with the resource_prefix from settings.yaml. This prevents
accidentally deleting real Okta users if someone points this tool
at the wrong org.
"""

import asyncio
import yaml
import os
from rich.console import Console
from rich.prompt import Confirm
from rich.progress import (
    Progress, SpinnerColumn, BarColumn,
    TextColumn, TaskProgressColumn, TimeElapsedColumn,
)

from src.okta.client import build_client, safe_api_call
from src.okta.session import load_session, delete_session, session_exists


console = Console()

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "config")


def _load_settings() -> dict:
    """Loads settings.yaml."""
    with open(os.path.join(_CONFIG_DIR, "settings.yaml")) as f:
        return yaml.safe_load(f)


async def run_cleanup() -> None:
    """
    Main cleanup function. Deletes all resources tracked in .session.json.

    This is what cleanup.py (the entry point) calls. It:
      1. Checks a session file exists
      2. Verifies the resource prefix matches settings
      3. Removes admin roles, deletes users, deletes groups
      4. Deletes the session file on success

    If no session file exists, offers to run purge mode instead.
    """
    if not session_exists():
        console.print(
            "\n[yellow]No session file found (.session.json).[/yellow]"
        )
        console.print(
            "[dim]This can happen if a previous run crashed before "
            "finishing.[/dim]\n"
        )
        if Confirm.ask(
            "[bold]Search Okta directly for orphaned resources to clean up?[/bold]",
            default=True,
        ):
            await run_purge()
        return

    settings = _load_settings()
    prefix   = settings["generation"]["resource_prefix"]
    session  = load_session()

    # Safety check — make sure the session matches the current prefix
    session_prefix = session.get("resource_prefix", "")
    if session_prefix and session_prefix != prefix:
        console.print(
            f"\n[red]Prefix mismatch![/red]"
            f"\n   Session prefix  : [red]{session_prefix}[/red]"
            f"\n   Settings prefix : [cyan]{prefix}[/cyan]"
            f"\n   Aborting — edit settings.yaml to match the session prefix first.\n"
        )
        return

    users       = session.get("users", [])
    groups      = session.get("groups", [])
    admin_roles = session.get("admin_roles", [])

    console.print(f"\n[bold red]Starting cleanup...[/bold red]")
    console.print(f"   Admin roles to remove : [cyan]{len(admin_roles)}[/cyan]")
    console.print(f"   Users to delete       : [cyan]{len(users)}[/cyan]")
    console.print(f"   Groups to delete      : [cyan]{len(groups)}[/cyan]\n")

    client = build_client()

    await _remove_admin_roles(client, admin_roles, prefix)
    await _delete_users(client, users, prefix)
    await _delete_groups(client, groups, prefix)

    delete_session()

    console.print(f"\n[bold green]Cleanup complete. Session file deleted.[/bold green]")

    # After session cleanup, check for any orphans left behind
    console.print(f"\n[dim]Checking for orphaned resources...[/dim]")
    await _check_and_purge_orphans(client, prefix)

    console.print(f"   Ready for a fresh generation run.\n")


async def run_purge() -> None:
    """
    Searches Okta directly for ALL resources matching the prefix and
    deletes them. Catches orphans that aren't tracked in .session.json.

    This runs when:
      - No session file exists (crashed run left orphans)
      - After a normal cleanup to sweep up anything the session missed
    """
    settings = _load_settings()
    prefix = settings["generation"]["resource_prefix"]
    client = build_client()

    console.print(f"\n[bold yellow]Scanning Okta for resources with prefix "
                  f"[cyan]{prefix}[/cyan]...[/bold yellow]\n")

    users_to_delete, groups_to_delete = await _scan_okta(client, prefix)

    if not users_to_delete and not groups_to_delete:
        console.print("[green]Nothing found — your Okta org is clean.[/green]\n")
        return

    console.print(f"  Found [bold yellow]{len(users_to_delete)}[/bold yellow] users")
    console.print(f"  Found [bold yellow]{len(groups_to_delete)}[/bold yellow] groups\n")

    if not Confirm.ask("[bold red]Delete all of these?[/bold red]", default=False):
        console.print("[dim]Aborted.[/dim]\n")
        return

    await _purge_users(client, users_to_delete)
    await _purge_groups(client, groups_to_delete)

    if session_exists():
        delete_session()

    console.print(f"\n[bold green]Purge complete.[/bold green]")
    console.print(f"  {len(users_to_delete)} users deleted")
    console.print(f"  {len(groups_to_delete)} groups deleted")
    console.print(f"  Your Okta org is clean. Ready for a fresh run.\n")


async def _scan_okta(
    client,
    prefix: str,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """
    Searches Okta for all users and groups matching the resource prefix.
    Also finds svc.* users created by the service_account_gone_rogue
    chaos profile.

    Args:
        client: Authenticated OktaClient.
        prefix: The resource prefix to search for.

    Returns:
        Tuple of (users_to_delete, groups_to_delete) where each is a
        list of (id, name/login) tuples.
    """
    # Find prefixed users
    users_to_delete = []
    result = await safe_api_call(
        lambda: client.list_users({"search": f'profile.login sw "{prefix}"', "limit": 200}),
        description="search users by prefix",
    )
    found_users, _, err = result
    if not err and found_users:
        users_to_delete = [(u.id, u.profile.login) for u in found_users]

    # Find svc.* users (chaos renames some logins)
    svc_result = await safe_api_call(
        lambda: client.list_users({"search": 'profile.login sw "svc."', "limit": 200}),
        description="search svc users",
    )
    svc_users, _, svc_err = svc_result
    if not svc_err and svc_users:
        existing_ids = {uid for uid, _ in users_to_delete}
        for u in svc_users:
            if u.id not in existing_ids:
                users_to_delete.append((u.id, u.profile.login))

    # Find prefixed groups
    groups_to_delete = []
    result = await safe_api_call(
        lambda: client.list_groups({"q": prefix, "limit": 200}),
        description="search groups by prefix",
    )
    found_groups, _, err = result
    if not err and found_groups:
        groups_to_delete = [
            (g.id, g.profile.name) for g in found_groups
            if g.profile.name.startswith(prefix)
        ]

    return users_to_delete, groups_to_delete


async def _check_and_purge_orphans(client, prefix: str) -> None:
    """
    After a normal session cleanup, scans Okta for any leftover resources
    the session didn't track. Silently cleans them up if found.

    Args:
        client: Authenticated OktaClient.
        prefix: The resource prefix to search for.
    """
    users_to_delete, groups_to_delete = await _scan_okta(client, prefix)

    if not users_to_delete and not groups_to_delete:
        console.print(f"   [green]No orphans found.[/green]")
        return

    console.print(
        f"   [yellow]Found {len(users_to_delete)} orphaned users "
        f"and {len(groups_to_delete)} orphaned groups — cleaning up...[/yellow]"
    )
    await _purge_users(client, users_to_delete)
    await _purge_groups(client, groups_to_delete)
    console.print(f"   [green]Orphans cleaned up.[/green]")


async def _purge_users(client, users: list[tuple[str, str]]) -> None:
    """
    Deactivates and deletes a list of users found by scanning Okta.

    Args:
        client: Authenticated OktaClient.
        users:  List of (user_id, login) tuples.
    """
    if not users:
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold red]Purging users[/bold red]        "),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("users", total=len(users))

        for user_id, login in users:
            await safe_api_call(
                lambda uid=user_id: client.deactivate_user(uid),
                description=f"deactivate {login}",
            )
            await safe_api_call(
                lambda uid=user_id: client.deactivate_or_delete_user(uid),
                description=f"delete {login}",
            )
            progress.advance(task)


async def _purge_groups(client, groups: list[tuple[str, str]]) -> None:
    """
    Deletes a list of groups found by scanning Okta.

    Args:
        client: Authenticated OktaClient.
        groups: List of (group_id, name) tuples.
    """
    if not groups:
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold red]Purging groups[/bold red]       "),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("groups", total=len(groups))

        for group_id, name in groups:
            await safe_api_call(
                lambda gid=group_id: client.delete_group(gid),
                description=f"delete group {name}",
            )
            progress.advance(task)


async def _remove_admin_roles(
    client,
    admin_roles: list[dict],
    prefix: str,
) -> None:
    """
    Removes all admin role assignments tracked in the session.

    Admin roles must be removed before the user can be deleted.
    Trying to delete a user who still has an admin role will fail.

    Args:
        client:      Authenticated OktaClient.
        admin_roles: List of {user_id, role_type, role_id} dicts from session.
        prefix:      Resource prefix for safety verification (logged only).
    """
    if not admin_roles:
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold red]Removing admin roles[/bold red]  "),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("roles", total=len(admin_roles))

        for entry in admin_roles:
            await safe_api_call(
                lambda uid=entry["user_id"], rid=entry["role_id"]: client.remove_role_from_user(uid, rid),
                description=f"remove {entry['role_type']} from {entry['user_id']}",
            )
            progress.advance(task)


async def _delete_users(
    client,
    users: list[dict],
    prefix: str,
) -> None:
    """
    Deactivates and permanently deletes all users tracked in the session.

    In Okta, deleting a user requires two steps:
      1. Deactivate the user (status → DEPROVISIONED)
      2. Delete the deprovisioned user

    We do both here. The safety check ensures we only delete users
    whose login starts with the resource prefix.

    Args:
        client: Authenticated OktaClient.
        users:  List of {id, login} dicts from session.
        prefix: Resource prefix — any user not starting with this is skipped.
    """
    if not users:
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold red]Deleting users[/bold red]       "),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("users", total=len(users))

        for entry in users:
            # Safety check — only delete resources we created
            if not entry["login"].startswith(prefix):
                console.print(
                    f"   [yellow]Skipping {entry['login']} "
                    f"— does not match prefix '{prefix}'[/yellow]"
                )
                progress.advance(task)
                continue

            # Step 1: Deactivate
            await safe_api_call(
                lambda uid=entry["id"]: client.deactivate_user(uid),
                description=f"deactivate {entry['login']}",
            )

            # Step 2: Delete
            await safe_api_call(
                lambda uid=entry["id"]: client.deactivate_or_delete_user(uid),
                description=f"delete {entry['login']}",
            )

            progress.advance(task)


async def _delete_groups(
    client,
    groups: list[dict],
    prefix: str,
) -> None:
    """
    Deletes all groups tracked in the session.

    Groups can only be deleted after all their members have been
    removed or deleted, which is why users are deleted first.

    Args:
        client: Authenticated OktaClient.
        groups: List of {id, name} dicts from session.
        prefix: Resource prefix — any group not starting with this is skipped.
    """
    if not groups:
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold red]Deleting groups[/bold red]      "),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("groups", total=len(groups))

        for entry in groups:
            # Safety check
            if not entry["name"].startswith(prefix):
                console.print(
                    f"   [yellow]Skipping group {entry['name']} "
                    f"— does not match prefix '{prefix}'[/yellow]"
                )
                progress.advance(task)
                continue

            await safe_api_call(
                lambda gid=entry["id"]: client.delete_group(gid),
                description=f"delete group {entry['name']}",
            )
            progress.advance(task)
