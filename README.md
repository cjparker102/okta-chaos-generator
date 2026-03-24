# okta-chaos-generator

A CTF-style IAM chaos platform that generates 100–200 randomized users and pushes them to a real Okta org — with a secret number of intentionally broken accounts scattered throughout. Use it to practice finding and remediating real IAM security issues.

Pairs with [okta-access-reviewer](https://github.com/cjparker102/okta-access-reviewer) for a full generate → audit → reveal workflow.

---

## How It Works

1. **Generate** — Creates 100–200 realistic users across 8 departments with a full org hierarchy (CEO → VP → Director → Manager → IC), diverse names, realistic hire dates, and proper group/app assignments
2. **Chaos** — Secretly injects IAM security problems into a random 15–40% of users. You never know how many were corrupted
3. **Provision** — Pushes everything to your Okta developer org via API
4. **Audit** — Run your access review tools against the org and try to find all the bad accounts
5. **Reveal** — Run `reveal.py` to see the answer key and check your score
6. **Cleanup** — Wipe everything and start fresh

---

## Chaos Types

17 IAM problems across 4 severity tiers — randomly injected, randomly stacked:

| Tier | Type | What it looks like |
|---|---|---|
| 🔴 Critical | `sleeping_super_admin` | SUPER_ADMIN inactive 6–18 months |
| 🔴 Critical | `departed_employee` | Active account, clearly left 2–4 years ago |
| 🔴 Critical | `admin_without_mfa` | ORG/SUPER_ADMIN with MFA never enrolled |
| 🔴 Critical | `contractor_with_crown_jewels` | Contractor with AWS prod + Okta Admin access |
| 🟡 High | `privilege_creep` | Changed departments, kept all old group memberships |
| 🟡 High | `orphaned_admin` | Admin role, no manager, no department |
| 🟡 High | `dormant_executive` | Executives + SUPER_ADMIN + inactive 9–14 months |
| 🟡 High | `contractor_overstay` | Contractor inactive 12–24 months past contract end |
| 🔵 Medium | `ghost_account` | Created 3–8 months ago, never logged in |
| 🔵 Medium | `service_account_gone_rogue` | `svc.*` account in human groups with crown jewel apps |
| 🔵 Medium | `duplicate_identity` | Two active accounts for the same person |
| 🔵 Medium | `app_hoarder` | 15–25 app assignments across unrelated departments |
| 🔵 Medium | `password_never_rotated` | 3+ year old account, password never changed |
| ⚪ Low | `wrong_department_groups` | User in groups that don't match their department |
| ⚪ Low | `missing_manager` | No manager or cost center assigned |
| ⚪ Low | `stale_contractor_access` | Contractor in permanent employee groups |
| ⚪ Low | `incomplete_profile` | Missing phone, city, state, cost center |

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/cjparker102/okta-chaos-generator.git
cd okta-chaos-generator
pip install -r requirements.txt
```

### 2. Get a free Okta developer org

Sign up at [developer.okta.com](https://developer.okta.com/signup/) — it's free and takes 2 minutes.

### 3. Generate an API token

In your Okta Admin Console: **Security → API → Tokens → Create Token**

The token needs **Super Administrator** access to create users, groups, and assign admin roles.

### 4. Configure your environment

```bash
cp .env.example .env
```

Edit `.env`:
```
OKTA_DOMAIN=dev-12345678.okta.com
OKTA_API_TOKEN=your-token-here
```

---

## Usage

```bash
# Preview the full plan before touching Okta (chaos is revealed here)
python dry_run.py

# Generate and push everything to Okta (chaos is hidden)
python main.py

# See the answer key — which users were corrupted and how
python reveal.py

# Delete everything and reset for the next round
python cleanup.py
```

---

## The Workflow

```
python dry_run.py     →  see the plan (optional)
python main.py        →  generate + push to Okta
                         ↓
                      run okta-access-reviewer or your own audit tools
                         ↓
python reveal.py      →  check your score
python cleanup.py     →  wipe everything, start fresh
```

### Scoring

- **Full marks** — found every corrupted account
- **Good** — caught all Critical + High issues
- **Needs work** — missed any Critical issues

---

## Project Structure

```
├── src/
│   ├── data/
│   │   ├── names.py            — diverse multi-locale name generation
│   │   ├── timeline.py         — realistic hire dates and login history
│   │   └── org_structure.py    — CEO → VP → Director → Manager → IC hierarchy
│   ├── generator/
│   │   ├── user_generator.py   — assembles full Okta user records
│   │   ├── group_generator.py  — 3-tier group structure (dept, access, role)
│   │   └── app_generator.py    — assigns apps by department and seniority
│   ├── chaos/
│   │   ├── profiles.py         — 17 chaos type definitions and mutation functions
│   │   └── chaos_engine.py     — picks victims, applies mutations, writes manifest
│   └── okta/
│       ├── client.py           — Okta SDK wrapper with rate limiting and retry
│       ├── session.py          — tracks created resource IDs for reliable cleanup
│       ├── provisioner.py      — pushes everything to Okta in dependency order
│       └── cleanup.py          — deletes all generated resources safely
├── config/
│   ├── settings.yaml           — user count, chaos density, dept weights
│   ├── departments.yaml        — titles, groups, and apps per department
│   └── apps.yaml               — full app catalog with access tiers
├── dry_run.py                  — preview mode, no Okta calls
├── main.py                     — full pipeline entry point
├── reveal.py                   — chaos answer key
└── cleanup.py                  — wipe generated resources
```

---

## Tech Stack

- Python 3.10+
- [Okta Python SDK](https://github.com/okta/okta-sdk-python)
- [Faker](https://faker.readthedocs.io/) — realistic name and profile generation
- [Rich](https://rich.readthedocs.io/) — terminal UI with progress bars
- PyYAML · python-dotenv
