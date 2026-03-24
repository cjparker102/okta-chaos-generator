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

from src.generator.user_generator import generate_users
from src.generator.group_generator import generate_groups
from src.chaos.chaos_engine import inject_chaos
from src.okta.provisioner import provision_all


console = Console()


async def main() -> None:
    """
    Orchestrates the full generation and provisioning pipeline.

    Steps:
      1. Generate clean users from config
      2. Build the group structure
      3. Inject chaos (silently — no output about what was corrupted)
      4. Push everything to Okta
    """
    console.print(Panel.fit(
        "[bold red]OKTA CHAOS GENERATOR[/bold red]\n"
        "[dim]Generating a broken org... good luck finding everything.[/dim]",
        border_style="red",
    ))

    # Step 1 — Generate clean users
    console.print("\n[bold]Step 1/4[/bold] — Generating users...")
    users = generate_users()
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
