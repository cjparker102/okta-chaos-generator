"""
main.py

The full pipeline. Generates users and groups, secretly injects chaos,
and pushes everything to your Okta org.

The chaos count is NEVER printed here — you won't know how many bad
accounts were created until you run reveal.py. That's the point.

Run with:
    python main.py

Recommended workflow:
    1. python dry_run.py      — preview the plan first
    2. python main.py         — push to Okta (chaos is hidden)
    3. (run your access review tools against the org)
    4. python reveal.py       — check your score
    5. python cleanup.py      — wipe everything, start fresh
"""

import asyncio
from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt, Confirm

from src.generator.user_generator import generate_users
from src.generator.group_generator import generate_groups
from src.chaos.chaos_engine import inject_chaos
from src.okta.provisioner import provision_all


console = Console()


def prompt_user_count() -> int:
    """
    Asks the user how many users to generate, with guidance
    about Okta org limits and recommended ranges.

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
        "  [bold yellow]WARNING:[/bold yellow] Okta [bold]developer orgs[/bold] "
        "have a [bold]100-user limit[/bold] (including your admin account)."
    )
    console.print(
        "  If you're on a dev org, keep it under [bold green]95[/bold green] "
        "to stay safe.\n"
    )

    user_count = IntPrompt.ask(
        "  [bold]Enter user count[/bold]",
        default=80,
    )

    # Guard against unreasonable values
    if user_count < 10:
        console.print("  [yellow]Minimum is 10 users — setting to 10.[/yellow]")
        user_count = 10
    elif user_count > 500:
        console.print("  [yellow]Maximum is 500 users — setting to 500.[/yellow]")
        user_count = 500

    # Warn if they're likely on a dev org and going over the limit
    if user_count > 95:
        console.print(
            f"\n  [bold yellow]Heads up:[/bold yellow] You chose [bold]{user_count}[/bold] users. "
            "Okta dev orgs cap at ~100 total users."
        )
        if not Confirm.ask("  [bold]Continue anyway?[/bold]", default=False):
            console.print("  [dim]Aborting. Adjust your count and re-run.[/dim]\n")
            raise SystemExit(0)

    return user_count


async def main() -> None:
    """
    Orchestrates the full generation and provisioning pipeline.

    Steps:
      1. Ask the user how many users to generate
      2. Generate clean users from config
      3. Build the group structure
      4. Inject chaos (silently — no output about what was corrupted)
      5. Push everything to Okta
    """
    console.print(Panel.fit(
        "[bold red]OKTA CHAOS GENERATOR[/bold red]\n"
        "[dim]Generating a broken org... good luck finding everything.[/dim]",
        border_style="red",
    ))

    # Step 0 — Ask how many users
    user_count = prompt_user_count()

    # Step 1 — Generate clean users
    console.print(f"\n[bold]Step 1/4[/bold] — Generating {user_count} users...")
    users = generate_users(user_count=user_count)
    console.print(f"  ✓ [cyan]{len(users)}[/cyan] users generated\n")

    # Step 2 — Build groups
    console.print("[bold]Step 2/4[/bold] — Building groups...")
    groups = generate_groups()
    console.print(f"  ✓ [cyan]{len(groups)}[/cyan] groups ready\n")

    # Step 3 — Inject chaos silently
    # dry_run=False means nothing is printed about what was corrupted.
    # The manifest is written to .chaos_manifest.json (gitignored).
    console.print("[bold]Step 3/4[/bold] — Applying configuration...")
    inject_chaos(users, dry_run=False)
    console.print("  ✓ Configuration applied\n")

    # Step 4 — Push to Okta
    console.print("[bold]Step 4/4[/bold] — Provisioning to Okta...")
    await provision_all(users, groups, dry_run=False)


if __name__ == "__main__":
    asyncio.run(main())
