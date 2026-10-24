# claim-bot

A Discord bot for claiming the next migration number **before** you create the file, so two people
never pick the same one. It also checks that a repo's Alembic migration chain isn't broken.

The bot reads committed migrations from GitHub and adds the numbers claimed in Discord but not
pushed yet, so the next free number is always right. A claim disappears on its own once its file is
pushed.

## Commands

| Command | What it does |
|---|---|
| `/next project` | Shows the next free number without claiming it |
| `/claim project desc [number]` | Claims the next free number, or a specific one. Refused if that number is already claimed or committed |
| `/claims [project]` | Lists open claims |
| `/release project number` | Drops a claim by hand |
| `/check project` | Checks the migration chain: more than one head, links to missing revisions, duplicate revisions or numbers, cycles |
| `/addproject name repo path numbered` | Adds a repo or updates an existing one. Claims are posted to the channel where you run it. Needs the **Manage Server** permission |

`numbered` is `True` when files start with a number (`0067_add_x.py`) and `False` for Alembic's
random ids (`a1b2c3d4e5f6_add_x.py`). Repos that aren't numbered only get `/check`.

## Setup

You need Python 3.11 or newer.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # on Linux/macOS: .venv/bin/python
cp .env.example .env                                      # then fill in both tokens
python bot.py
```

### Tokens (`.env`)

**`DISCORD_TOKEN`**
1. In the [Discord Developer Portal](https://discord.com/developers/applications), click New
   Application, open the **Bot** tab and click **Reset Token**. Copy the token.
2. Invite the bot: **OAuth2 → URL Generator**.
   - Scopes: `bot` and `applications.commands`.
   - Bot permissions: **View Channels** and **Send Messages**.

**`GITHUB_TOKEN`**
1. In GitHub, go to Settings → Developer settings → **Fine-grained tokens** and generate a new token.
2. Resource owner: the org that owns the repos, not your personal account.
3. Repository access: only the repos the bot tracks.
4. Permissions: **Contents: Read-only**.

Variables already set in the environment take priority over `.env`.

### Projects (`projects.json`)

Add projects with `/addproject`, or edit the file by hand:

```json
{
  "eduvia-server": {
    "repo": "EduVia-Org/EduVia-Server",
    "path": "migrations/versions",
    "pattern": "^(\\d{4})_",
    "guild_id": 123456789012345678,
    "channel_id": 123456789012345678
  }
}
```

To get the IDs, turn on Discord **Developer Mode** (User Settings → Advanced), then right-click the
server or channel and choose **Copy ID**.

## Deploy (Wispbyte or any Pterodactyl panel)

1. Upload `bot.py`, `projects.json`, `requirements.txt` and `.env`.
2. Set the startup script to:
   ```
   pip install --user -r requirements.txt && python bot.py
   ```
3. Run **one** copy only. A local copy and a hosted copy would keep separate claim lists.
4. When you redeploy, upload only `bot.py` (and `requirements.txt` if it changed). The bot writes
   `projects.json` and `claims.json` itself, so re-uploading them erases its data.
5. Log in to the Wispbyte panel about every 14 days, or the free server stops.

## Test

```bash
python test_next.py
```

This checks the next-number logic and the chain check with made-up data. It doesn't need Discord or
GitHub.
