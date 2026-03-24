"""
src/okta/cleanup.py

Deletes everything created by a previous generation run.

Reads .session.json to get the exact Okta IDs of every resource
we created — users, groups, and admin role assignments — and
deletes them all in the correct reverse order:

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
    """
    if not session_exists():
        console.print(
            "\n[yellow]No session file found (.session.json).[/yellow]"
            "\nNothing to clean up.\n"
        )
        return

    settings = _load_settings()
    prefix   = settings["generation"]["resource_prefix"]
    session  = load_session()

    # Safety check — make sure the session matches the current prefix
    session_prefix = session.get("resource_prefix", "")
    if session_prefix and session_prefix != prefix:
        console.print(
            f"\n[red]⚠️  Prefix mismatch![/red]"
            f"\n   Session prefix  : [red]{session_prefix}[/red]"
            f"\n   Settings prefix : [cyan]{prefix}[/cyan]"
            f"\n   Aborting — edit settings.yaml to match the session prefix first.\n"
        )
        return

    users       = session.get("users", [])
    groups      = session.get("groups", [])
    admin_roles = session.get("admin_roles", [])

    console.print(f"\n[bold red]🗑️  Starting cleanup...[/bold red]")
    console.print(f"   Admin roles to remove : [cyan]{len(admin_roles)}[/cyan]")
    console.print(f"   Users to delete       : [cyan]{len(users)}[/cyan]")
    console.print(f"   Groups to delete      : [cyan]{len(groups)}[/cyan]\n")

    client = build_client()

    await _remove_admin_roles(client, admin_roles, prefix)
    await _delete_users(client, users, prefix)
    await _delete_groups(client, groups, prefix)

    delete_session()

    console.print(f"\n[bold green]✅ Cleanup complete. Session file deleted.[/bold green]")
    console.print(f"   Ready for a fresh generation run.\n")


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
                client.remove_role_from_user(entry["user_id"], entry["role_id"]),
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
                client.deactivate_user(entry["id"]),
                description=f"deactivate {entry['login']}",
            )

            # Step 2: Delete
            await safe_api_call(
                client.deactivate_or_delete_user(entry["id"]),
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
                client.delete_group(entry["id"]),
                description=f"delete group {entry['name']}",
            )
            progress.advance(task)
