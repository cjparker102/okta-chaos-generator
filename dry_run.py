"""
dry_run.py

Generates the full user and group dataset, injects chaos, and prints
a complete plan — without touching Okta at all.

Use this to:
  - Preview exactly what would be created before committing to a real run
  - See the chaos manifest upfront (the ONLY script that shows it before reveal.py)
  - Verify your config looks right (user counts, dept distribution, etc.)
  - Debug generation issues without burning Okta API calls

Run with:
    python dry_run.py
"""

from rich.console import Console
from rich.panel import Panel

from src.generator.user_generator import generate_users
from src.generator.group_generator import generate_groups
from src.chaos.chaos_engine import inject_chaos
from src.okta.provisioner import provision_all

console = Console()


def main() -> None:
    """
    Runs the full generation and chaos pipeline in dry-run mode.
    Prints everything — including the chaos manifest — to the terminal.
    """
    console.print(Panel.fit(
        "[bold cyan]OKTA CHAOS GENERATOR[/bold cyan]\n"
        "[dim]Dry Run Mode — Okta will not be touched[/dim]",
        border_style="cyan",
    ))

    # Step 1: Generate clean users
    console.print("\n[bold]Step 1/3[/bold] — Generating users...")
    users = generate_users()
    console.print(f"  ✓ Generated [cyan]{len(users)}[/cyan] clean users\n")

    # Step 2: Generate groups
    console.print("[bold]Step 2/3[/bold] — Building group structure...")
    groups = generate_groups()
    console.print(f"  ✓ Built [cyan]{len(groups)}[/cyan] groups\n")

    # Step 3: Inject chaos — dry_run=True reveals the manifest in the terminal
    console.print("[bold]Step 3/3[/bold] — Injecting chaos...")
    inject_chaos(users, dry_run=True)

    # Print the full provisioning plan (no API calls)
    provision_all(users, groups, dry_run=True)

    console.print(
        "\n[dim]This was a dry run. To push to Okta, run:[/dim] "
        "[bold]python main.py[/bold]\n"
    )


if __name__ == "__main__":
    main()
