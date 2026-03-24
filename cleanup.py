"""
cleanup.py

Deletes everything created by the last generation run.

Reads .session.json to find the exact Okta IDs of every resource
created, then removes them in safe order:
  1. Admin role assignments
  2. Users (deactivate then delete)
  3. Groups

Safe to run multiple times — if a resource was already deleted,
the error is caught and the run continues.

Run with:
    python cleanup.py
"""

import asyncio
from rich.console import Console
from rich.panel import Panel

from src.okta.cleanup import run_cleanup


console = Console()


def main() -> None:
    """
    Entry point for cleanup. Calls the async cleanup runner.
    """
    console.print(Panel.fit(
        "[bold red]OKTA CHAOS GENERATOR[/bold red]\n"
        "[dim]Cleanup Mode — deleting all generated resources[/dim]",
        border_style="red",
    ))

    asyncio.run(run_cleanup())


if __name__ == "__main__":
    main()
