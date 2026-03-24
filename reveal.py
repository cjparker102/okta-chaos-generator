"""
reveal.py

The answer key. Reads .chaos_manifest.json and displays exactly
what chaos was injected — which users were corrupted, what types
were applied, and how many you should have found.

Run this AFTER you've done your access review to check your score:
    1. python main.py            (generate + push to Okta)
    2. python okta-access-reviewer/main.py  (run your audit)
    3. python reveal.py          (see how many you caught)
    4. python cleanup.py         (wipe the org, start fresh)

Run with:
    python reveal.py
"""

import json
import os
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()

_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), ".chaos_manifest.json")

# Color per chaos tier
_TIER_COLORS = {
    "critical": "bold red",
    "high":     "yellow",
    "medium":   "cyan",
    "low":      "dim",
}

# Description of each chaos type for the reveal screen
_CHAOS_DESCRIPTIONS = {
    "sleeping_super_admin":         "SUPER_ADMIN inactive 6–18 months",
    "departed_employee":            "Active account, clearly left 2–4 years ago",
    "admin_without_mfa":            "ORG/SUPER_ADMIN with MFA never enrolled",
    "contractor_with_crown_jewels": "Contractor with AWS prod / Okta Admin access",
    "privilege_creep":              "Changed depts, kept all old group memberships",
    "orphaned_admin":               "Admin role, no manager, no dept, no cost center",
    "dormant_executive":            "Executives group + SUPER_ADMIN + inactive 9–14mo",
    "contractor_overstay":          "Contractor inactive 12–24 months past contract end",
    "ghost_account":                "Created 3–8 months ago, never logged in",
    "service_account_gone_rogue":   "svc.* account in human groups with crown jewel apps",
    "duplicate_identity":           "Two active accounts for the same person",
    "app_hoarder":                  "15–25 app assignments across unrelated departments",
    "password_never_rotated":       "3+ year old account, password never changed",
    "wrong_department_groups":      "User in groups that don't match their department",
    "missing_manager":              "No manager or cost center assigned",
    "stale_contractor_access":      "Contractor in permanent employee groups",
    "incomplete_profile":           "Missing phone, city, state, cost center",
}


def main() -> None:
    """
    Reads the chaos manifest and displays a formatted answer key.
    """
    if not os.path.exists(_MANIFEST_PATH):
        console.print(Panel.fit(
            "[red]No chaos manifest found.[/red]\n\n"
            "Run [bold]python main.py[/bold] or [bold]python dry_run.py[/bold] first\n"
            "to generate the org and create the manifest.",
            title="reveal.py",
            border_style="red",
        ))
        return

    with open(_MANIFEST_PATH) as f:
        manifest = json.load(f)

    total_users  = manifest["total_users"]
    chaos_count  = manifest["chaos_count"]
    density      = manifest["chaos_density"]
    victims      = manifest["victims"]

    # --- Header panel ---
    console.print(Panel.fit(
        f"[bold red]🔥 CHAOS MANIFEST — ANSWER KEY[/bold red]\n\n"
        f"  Total users   : [cyan]{total_users}[/cyan]\n"
        f"  Chaos count   : [red]{chaos_count}[/red] users corrupted\n"
        f"  Chaos density : [red]{round(density * 100, 1)}%[/red] of eligible users\n\n"
        f"[dim]How many did your audit catch?[/dim]",
        border_style="red",
        box=box.DOUBLE,
    ))

    # --- Breakdown by tier ---
    tier_counts: dict[str, int] = {}
    for victim in victims:
        for tier in victim.get("tiers", []):
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

    tier_table = Table(title="Chaos by Tier", show_header=True, box=box.SIMPLE)
    tier_table.add_column("Tier",   style="bold")
    tier_table.add_column("Count",  justify="right")
    tier_table.add_column("What it means")

    tier_info = {
        "critical": "Immediate action required — active security exposure",
        "high":     "Needs review this week — elevated risk",
        "medium":   "Should be investigated — policy violation",
        "low":      "Cleanup item — hygiene issue",
    }

    for tier in ["critical", "high", "medium", "low"]:
        count = tier_counts.get(tier, 0)
        if count > 0:
            color = _TIER_COLORS[tier]
            tier_table.add_row(
                f"[{color}]{tier.upper()}[/{color}]",
                f"[{color}]{count}[/{color}]",
                tier_info[tier],
            )

    console.print(tier_table)

    # --- Full victim list ---
    console.print(f"\n[bold]All {chaos_count} corrupted accounts:[/bold]\n")

    victim_table = Table(show_header=True, box=box.SIMPLE_HEAVY)
    victim_table.add_column("#",           justify="right", style="dim", width=4)
    victim_table.add_column("Login",       style="bold white")
    victim_table.add_column("Chaos Types", style="white")
    victim_table.add_column("Tier(s)",     style="white")

    for i, victim in enumerate(victims, 1):
        tiers      = victim.get("tiers", [])
        top_tier   = tiers[0] if tiers else "low"
        color      = _TIER_COLORS.get(top_tier, "white")

        types_desc = "\n".join(
            f"[{color}]{ct}[/{color}] — "
            f"[dim]{_CHAOS_DESCRIPTIONS.get(ct, ct)}[/dim]"
            for ct in victim["chaos_types"]
        )

        tiers_str = " + ".join(
            f"[{_TIER_COLORS.get(t, 'white')}]{t.upper()}[/{_TIER_COLORS.get(t, 'white')}]"
            for t in tiers
        )

        victim_table.add_row(str(i), victim["login"], types_desc, tiers_str)

    console.print(victim_table)

    # --- Scoring prompt ---
    console.print(Panel(
        "[bold]Scoring guide:[/bold]\n\n"
        f"  Full marks   = found all [red]{chaos_count}[/red] corrupted accounts\n"
        f"  Good         = found all [red]{tier_counts.get('critical', 0) + tier_counts.get('high', 0)}[/red] critical + high issues\n"
        f"  Needs work   = missed any critical issues\n\n"
        "[dim]Run [bold]python cleanup.py[/bold] to wipe the org and try again.[/dim]",
        border_style="dim",
    ))


if __name__ == "__main__":
    main()
