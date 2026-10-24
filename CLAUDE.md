# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

Implemented in `bot.py`. [CONTEXT.md](CONTEXT.md) holds the full spec, hosting choice, and setup
checklist. Its "Decisions already made" section is
settled; do not re-litigate (always-on host, GitHub API instead of a local clone, generic counter).

## What it is

Discord bot for claiming the next number in a shared sequential counter (mainly Alembic migration
numbers for EduVia-Server) *before* the file is pushed. Standalone tool: never commit anything into
the EduVia repos.

## Architecture

- `bot.py` (Python 3.11+, `discord.py` v2 slash commands, `requests`) + two JSON files. No DB,
  no framework, no other deps.
- `projects.json`: per-project config — `repo`, `path`, `pattern` (regex capturing the number from
  filenames), `guild_id`, `channel_id`. Zero-pad width inferred from committed files (default 4).
- `claims.json`: bot-owned state of open (claimed, not yet pushed) numbers per project.
- Core rule: **next = max(committed numbers via `GET /repos/{repo}/contents/{path}`, open claims) + 1**.
  Git alone is wrong because claimed numbers aren't pushed yet. Any claim whose number now appears
  in the repo is auto-pruned.
- Commands: `/next`, `/claim` (refuse if number already claimed or committed), `/claims`, `/release`,
  `/check` (migration chain), `/addproject` (Manage Server only; writes `projects.json`, takes guild
  and channel from where it's run).
- `numbered: false` projects (Alembic hash ids) only support `/check`; missing key means numbered.
- `/check` reads all migration sources in one GraphQL call (`fetch_sources`), parses
  `revision`/`down_revision` with `ast` (`parse_revision`), and `chain_problems` flags multiple
  heads/bases, dangling down_revisions, duplicate revisions, duplicate numbers, cycles.
- All claims.json read-modify-writes happen under one `asyncio.Lock`, so concurrent `/claim`s can't
  get the same number. Commands sync per guild (from `projects.json` `guild_id`s), else globally.

## Commands

- Setup: `python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt`
- Run: `python bot.py` with `DISCORD_TOKEN` and `GITHUB_TOKEN` (fine-grained, read-only
  Contents) set as env vars or in `.env` (see `.env.example`; real env vars take precedence).
- Test: `python test_next.py` — asserts on the pure functions (`parse_numbers`, `next_free`,
  `prune`, `parse_revision`, `chain_problems`) in `bot.py`. No live services.
- Live GitHub read without Discord: `GITHUB_TOKEN=$(gh auth token) python -c "import bot; ..."`
  calling `bot.fetch_names`.

## Constraints

- No GitHub Actions (org out of free minutes).
- Deployed on Wispbyte free tier (512 MB; panel login ~every 14 days to keep it alive). Panel
  startup script: `pip install --user -r requirements.txt && python bot.py`. Tokens in `.env`
  uploaded next to `bot.py`; `claims.json` and `projects.json` are written by the bot on the host,
  so don't overwrite them on redeploy.
  Only run one instance (local + host = two separate claim lists).
- `gh` CLI on this machine: `/c/Program Files/GitHub CLI/gh.exe`.
