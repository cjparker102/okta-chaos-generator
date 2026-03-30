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

import asyncio
from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt

from src.generator.user_generator import generate_users
from src.generator.group_generator import generate_groups
from src.chaos.chaos_engine import inject_chaos
from src.okta.provisioner import provision_all

console = Console()


def prompt_user_count() -> int:
    """
    Asks the user how many users to generate for the dry run.

    Returns:
        The chosen user count.
    """
    console.print()
    console.print("[bold cyan]How many users do you want to generate?[/bold cyan]\n")
    console.print("  [dim]Recommended ranges:[/dim]")
    console.print("    [green]25–75[/green]   — small run, good for quick tests")
    console.print("    [yellow]75–150[/yellow]  — medium run, realistic org feel")
    console.print("    [red]150–300[/red] — large run, full-scale chaos\n")
    console.print(
        "  [bold yellow]TIP:[/bold yellow] Okta [bold]developer orgs[/bold] "
        "have a [bold]100-user limit[/bold]."
    )
    console.print(
        "  If you plan to push this to a dev org, keep it under "
        "[bold green]95[/bold green].\n"
    )

    user_count = IntPrompt.ask(
        "  [bold]Enter user count[/bold]",
        default=80,
    )

    if user_count < 10:
        console.print("  [yellow]Minimum is 10 users — setting to 10.[/yellow]")
        user_count = 10
    elif user_count > 500:
        console.print("  [yellow]Maximum is 500 users — setting to 500.[/yellow]")
        user_count = 500

    return user_count


async def main() -> None:
    """
    Runs the full generation and chaos pipeline in dry-run mode.
    Prints everything — including the chaos manifest — to the terminal.
    """
    console.print(Panel.fit(
        "[bold cyan]OKTA CHAOS GENERATOR[/bold cyan]\n"
        "[dim]Dry Run Mode — Okta will not be touched[/dim]",
        border_style="cyan",
    ))

    # Ask how many users
    user_count = prompt_user_count()

    # Step 1: Generate clean users
    console.print(f"\n[bold]Step 1/3[/bold] — Generating {user_count} users...")
    users = generate_users(user_count=user_count)
    console.print(f"  ✓ Generated [cyan]{len(users)}[/cyan] clean users\n")

    # Step 2: Generate groups
    console.print("[bold]Step 2/3[/bold] — Building group structure...")
    groups = generate_groups()
    console.print(f"  ✓ Built [cyan]{len(groups)}[/cyan] groups\n")

    # Step 3: Inject chaos — dry_run=True reveals the manifest in the terminal
    console.print("[bold]Step 3/3[/bold] — Injecting chaos...")
    inject_chaos(users, dry_run=True)

    # Print the full provisioning plan (no API calls)
    await provision_all(users, groups, dry_run=True)

    console.print(
        "\n[dim]This was a dry run. To push to Okta, run:[/dim] "
        "[bold]python main.py[/bold]\n"
    )


if __name__ == "__main__":
    asyncio.run(main())
