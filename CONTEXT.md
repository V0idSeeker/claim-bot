# Claim Bot — context & spec (for a fresh session)

A Discord bot that lets a team **claim the next number in a shared sequential counter**
(primarily Alembic migration numbers) *before* creating the file, so two people don't pick the
same number. Replaces the manual "I claim migration 00XX" message in the team channel.

This folder is a **standalone tool**, deliberately separate from the EduVia repos and the EduVia
Claude session. Nothing here gets committed into EduVia-Server / EduVia-Client.

## Why it exists

On EduVia, migration numbers are claimed by hand in the team Discord before the file is pushed.
The claimed number is therefore **not in git yet** — so "next = highest file + 1" is wrong (it
hands out a number someone already claimed but hasn't pushed). The claim channel is the real
source of truth. This bot makes claiming one command and computes the next free number correctly.

GitHub Actions is **not** an option (the org ran out of free Actions minutes — see EduVia TASKS.md).

## Decisions already made (do not re-litigate)

1. **Always-on host** (team uses it anytime via Discord), not local-only.
2. **Reads the repo's migration files over the GitHub API** (no local clone on the host) and
   combines that with open claims to compute the next free number.
3. **Generic sequential counter**, configured per project — works for Alembic (`0067_*.py`) and
   any other numbered resource, across old and new projects.

## Hosting — picked: Wispbyte (free)

Compared for free / no credit card / 24/7 / Python:

| Host | Free RAM | Renewal | Notes |
|---|---|---|---|
| **Wispbyte** (chosen) | 512 MB | login ~every 14 days | Python/discord.py, no card; 1 bot per server; some downtime reports |
| Bot-Hosting.net | 256 MB | **every 4 days** (annoying) | Python/discord.py, no card |
| Pella | 100 MB, 0.1 CPU | "Available Once" (unclear) | GitHub import; 100 MB tight once deps load; downtime reports |
| Railway free | n/a | — | $5 one-time trial then $1/mo credit — **won't run 24/7** without Hobby ($5/mo, card) |

A claim bot is tiny and tolerates brief downtime (worst case: host down → claim by hand that
day), so Wispbyte's 512 MB + 14-day login is the best free fit. Confirm current limits in the
panel before relying on them. Alt long-term home: the Icosnet VPS once it exists (free, 24/7).

## Design sketch

**Stack:** Python 3.11+, `discord.py` v2 (slash/app commands), `requests` for the GitHub API.
Keep it one small bot file + two JSON files. No framework, no database.

**`projects.json`** (one entry per project the bot serves):
```json
{
  "eduvia-server": {
    "repo": "EduVia-Org/EduVia-Server",
    "path": "migrations/versions",
    "pattern": "^(\\d{4})_",
    "guild_id": 000000000000000000,
    "channel_id": 000000000000000000
  }
}
```
`pattern` captures the number from each filename in `path`; zero-pad width inferred from the
committed files (default 4). This is what makes it a generic counter, not Alembic-only.

**`claims.json`** — the bot's own state of open (claimed-but-not-pushed) numbers:
```json
{ "eduvia-server": { "0067": {"who": "Younes", "desc": "regle_attribution", "at": "2026-10-..."} } }
```

**Next free number** = `max( committed numbers from GitHub API, open claim numbers ) + 1`.
Auto-prune: any open claim whose number now appears in the repo is dropped (it was pushed).

**Slash commands:**
- `/next project:<name>` — show the next free number (no claim).
- `/claim project:<name> desc:<text> [number:<n>]` — claim next (or an explicit number); refuse
  if that number is already claimed or already committed in the repo; record + post confirmation.
- `/claims [project:<name>]` — list open claims.
- `/release project:<name> number:<n>` — drop a claim by hand (normally auto-pruned once pushed).

**GitHub read:** `GET /repos/{repo}/contents/{path}` with a token → filenames → extract numbers.

## Setup checklist (for whoever builds it)

- [ ] Create a Discord application + bot; enable the bot; invite to the server with **Send
      Messages** and **Use Application Commands** (slash commands need no privileged intents).
- [ ] `DISCORD_TOKEN` env var (bot token). Never commit it.
- [ ] Fine-grained **GitHub token**, read-only **Contents** on the private repos, as
      `GITHUB_TOKEN` env var.
- [ ] Fill `projects.json` with real repo paths, `guild_id`, `channel_id`.
- [ ] Deploy on Wispbyte: upload code, set the Python startup command, set the two env vars,
      start. Remember the ~14-day login to keep it alive.
- [ ] Leave ONE runnable self-check for the next-free math (e.g. a `test_next.py` that feeds a
      fake committed set + claims and asserts the computed number) — no live Discord/GitHub needed.

## EduVia specifics (the first project it serves)

- Repo `EduVia-Org/EduVia-Server`, migrations in `migrations/versions`, files `NNNN_name.py`.
- As of 24 Oct 2026: highest **pushed** = `0066_regle_attribution.py`. Numbers **0047 and 0067**
  were claimed in chat (unpushed at various points) — exactly the case git alone can't see, which
  is why the bot tracks open claims on top of the committed files.
- `gh` CLI path on this machine: `/c/Program Files/GitHub CLI/gh.exe` (for manual checks).

## Constraints / non-goals

- No GitHub Actions (billing).
- Don't commit anything into the EduVia repos; this tool lives in its own repo/folder.
- Keep it minimal: stdlib + discord.py + requests. No DB, no web dashboard, no multi-tenant auth.
