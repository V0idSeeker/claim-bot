"""Discord bot: claim the next number in a shared sequential counter (e.g. Alembic migrations)."""
import ast
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import discord
import requests
from discord import app_commands

HERE = Path(__file__).parent
if (HERE / ".env").exists():  # KEY=value lines; real env vars win
    for line in (HERE / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))
PROJECTS_FILE = HERE / "projects.json"
PROJECTS = json.loads(PROJECTS_FILE.read_text())
CLAIMS_FILE = HERE / "claims.json"
lock = asyncio.Lock()  # one projects.json / claims.json read-modify-write at a time


# --- pure logic (tested in test_next.py) ---

def parse_numbers(names, pattern):
    """Committed numbers from filenames, plus zero-pad width taken from the highest one (default 4)."""
    found = [m.group(1) for n in names if (m := re.match(pattern, n))]
    width = len(max(found, key=int)) if found else 4
    return {int(s) for s in found}, width


def next_free(committed, claimed):
    return max(committed | claimed, default=0) + 1


def prune(open_claims, committed):
    """Drop claims whose number has since been pushed."""
    return {k: v for k, v in open_claims.items() if int(k) not in committed}


def parse_revision(text):
    """(revision, [down_revisions]) from an Alembic file's source; revision is None if absent."""
    rev, down = None, []
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        name = getattr(target, "id", None)
        if name == "revision":
            rev = ast.literal_eval(value)
        elif name == "down_revision":
            d = ast.literal_eval(value)
            down = [] if d is None else [d] if isinstance(d, str) else list(d)
    return rev, down


def chain_problems(files, pattern=None):
    """Problems in the migration graph of {filename: source}, plus its heads.
    `pattern` (numbered projects only) also flags two files sharing a number."""
    problems, revs = [], {}  # revision -> (filename, down_revisions)
    for name in sorted(files):
        try:
            rev, downs = parse_revision(files[name])
        except (SyntaxError, ValueError) as e:
            problems.append(f"`{name}`: can't read it ({e})")
            continue
        if rev is None:
            problems.append(f"`{name}`: no `revision`")
        elif rev in revs:
            problems.append(f"revision `{rev}` is in both `{revs[rev][0]}` and `{name}`")
        else:
            revs[rev] = (name, downs)
    for name, downs in revs.values():
        problems += [f"`{name}`: down_revision `{d}` doesn't exist" for d in downs if d not in revs]
    bases = [n for n, downs in revs.values() if not downs]
    if len(bases) > 1:
        problems.append(f"{len(bases)} base migrations (down_revision = None): {', '.join(f'`{b}`' for b in bases)}")
    heads = sorted(set(revs) - {d for _, downs in revs.values() for d in downs})
    if len(heads) > 1:
        problems.append(f"{len(heads)} heads: {', '.join(f'`{h}`' for h in heads)} → `alembic merge heads`")
    elif revs and not heads:
        problems.append("no head: the revisions form a cycle")
    if pattern:
        seen = {}
        for name in sorted(files):
            if m := re.match(pattern, name):
                if (n := int(m.group(1))) in seen:
                    problems.append(f"number {m.group(1)} is used by `{seen[n]}` and `{name}`")
                seen[n] = name
    return problems, heads


# --- I/O ---

def gh_headers():
    return {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json"}


def fetch_names(repo, path):
    r = requests.get(f"https://api.github.com/repos/{repo}/contents/{path}", headers=gh_headers(), timeout=15)
    if r.status_code == 404:
        raise RuntimeError(f"`{repo}/{path}` not found, or GITHUB_TOKEN can't read that repo")
    r.raise_for_status()
    if not isinstance(r.json(), list):
        raise RuntimeError(f"`{path}` is a file, not a folder")
    return [e["name"] for e in r.json()]


def fetch_sources(repo, path):
    """{filename: source} of every migration .py in the folder, in one GraphQL request."""
    owner, name = repo.split("/")
    query = """query($o: String!, $n: String!, $e: String!) { repository(owner: $o, name: $n) {
        object(expression: $e) { ... on Tree { entries { name object { ... on Blob { text } } } } } } }"""
    r = requests.post("https://api.github.com/graphql", headers=gh_headers(), timeout=30,
                      json={"query": query, "variables": {"o": owner, "n": name, "e": f"HEAD:{path}"}})
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise RuntimeError(body["errors"][0]["message"])
    tree = (body["data"]["repository"] or {}).get("object")
    if not tree:
        raise RuntimeError(f"`{repo}/{path}` not found, or GITHUB_TOKEN can't read that repo")
    return {e["name"]: e["object"]["text"] for e in tree["entries"]
            if e["name"].endswith(".py") and not e["name"].startswith("_")
            and e["object"] and e["object"].get("text") is not None}


def load_claims():
    return json.loads(CLAIMS_FILE.read_text()) if CLAIMS_FILE.exists() else {}


def save_json(file, data):
    tmp = file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, file)


async def refresh(project):
    """Read the repo, prune pushed claims, save. Call with `lock` held."""
    cfg = PROJECTS[project]
    names = await asyncio.to_thread(fetch_names, cfg["repo"], cfg["path"])
    committed, width = parse_numbers(names, cfg["pattern"])
    claims = load_claims()
    claims[project] = prune(claims.get(project, {}), committed)
    save_json(CLAIMS_FILE, claims)
    return committed, width, claims


def numbered(project):
    return PROJECTS[project].get("numbered", True)


# --- Discord ---

class Bot(discord.Client):
    async def setup_hook(self):
        guilds = {p["guild_id"] for p in PROJECTS.values() if p.get("guild_id")}
        for g in guilds:
            tree.copy_global_to(guild=discord.Object(g))
            await tree.sync(guild=discord.Object(g))
        if not guilds:
            await tree.sync()  # global sync can take up to an hour to show up


client = Bot(intents=discord.Intents.default())
tree = app_commands.CommandTree(client)


async def project_ac(interaction, current):
    return [app_commands.Choice(name=p, value=p) for p in PROJECTS if current.lower() in p.lower()][:25]


async def check_project(interaction, project, need_numbers=False):
    if project not in PROJECTS:
        await interaction.followup.send(f"Unknown project `{project}`. Known: {', '.join(PROJECTS)}")
        return False
    if need_numbers and not numbered(project):
        await interaction.followup.send(f"**{project}** isn't numbered, so there's nothing to claim. Use `/check`.")
        return False
    return True


@tree.command(name="next", description="Show the next free number (does not claim it)")
@app_commands.autocomplete(project=project_ac)
async def next_cmd(interaction: discord.Interaction, project: str):
    await interaction.response.defer()
    if not await check_project(interaction, project, need_numbers=True):
        return
    async with lock:
        committed, width, claims = await refresh(project)
    n = next_free(committed, {int(k) for k in claims[project]})
    await interaction.followup.send(f"Next free for **{project}**: `{n:0{width}d}`")


@tree.command(name="claim", description="Claim the next free number (or a specific one)")
@app_commands.autocomplete(project=project_ac)
async def claim_cmd(interaction: discord.Interaction, project: str, desc: str, number: int | None = None):
    await interaction.response.defer()
    if not await check_project(interaction, project, need_numbers=True):
        return
    async with lock:
        committed, width, claims = await refresh(project)
        open_ = claims[project]
        claimed = {int(k): v for k, v in open_.items()}
        n = number if number is not None else next_free(committed, set(claimed))
        if n in committed:
            return await interaction.followup.send(f"`{n:0{width}d}` is already committed in `{project}`.")
        if n in claimed:
            c = claimed[n]
            return await interaction.followup.send(
                f"`{n:0{width}d}` is already claimed by **{c['who']}** ({c['desc']}).")
        key = f"{n:0{width}d}"
        open_[key] = {"who": interaction.user.display_name, "desc": desc,
                      "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        save_json(CLAIMS_FILE, claims)
    msg = f"🔒 **{interaction.user.display_name}** claimed **{project}** `{key}` — {desc}"
    await interaction.followup.send(msg)
    channel_id = PROJECTS[project].get("channel_id")
    if channel_id and channel_id != interaction.channel_id and (ch := client.get_channel(channel_id)):
        await ch.send(msg)


@tree.command(name="claims", description="List open (claimed, not yet pushed) numbers")
@app_commands.autocomplete(project=project_ac)
async def claims_cmd(interaction: discord.Interaction, project: str | None = None):
    await interaction.response.defer()
    if project is not None and not await check_project(interaction, project, need_numbers=True):
        return
    lines = []
    async with lock:
        for p in [project] if project else [p for p in PROJECTS if numbered(p)]:
            _, _, claims = await refresh(p)
            lines += [f"**{p}** `{k}` — {v['who']}: {v['desc']} ({v['at'][:10]})"
                      for k, v in sorted(claims[p].items(), key=lambda kv: int(kv[0]))]
    await interaction.followup.send("\n".join(lines) or "No open claims.")


@tree.command(name="release", description="Drop a claim by hand")
@app_commands.autocomplete(project=project_ac)
async def release_cmd(interaction: discord.Interaction, project: str, number: int):
    await interaction.response.defer()
    if not await check_project(interaction, project, need_numbers=True):
        return
    async with lock:
        claims = load_claims()
        open_ = claims.get(project, {})
        key = next((k for k in open_ if int(k) == number), None)
        if key is None:
            return await interaction.followup.send(f"No open claim for `{number}` in **{project}**.")
        c = open_.pop(key)
        save_json(CLAIMS_FILE, claims)
    await interaction.followup.send(f"Released **{project}** `{key}` ({c['who']}: {c['desc']}).")


@tree.command(name="check", description="Check the migration chain: multiple heads, broken links, duplicates")
@app_commands.autocomplete(project=project_ac)
async def check_cmd(interaction: discord.Interaction, project: str):
    await interaction.response.defer()
    if not await check_project(interaction, project):
        return
    cfg = PROJECTS[project]
    files = await asyncio.to_thread(fetch_sources, cfg["repo"], cfg["path"])
    problems, heads = chain_problems(files, cfg["pattern"] if numbered(project) else None)
    if problems:
        msg = f"❌ **{project}**: {len(problems)} problem(s)\n" + "\n".join(f"• {p}" for p in problems)
    elif heads:
        msg = f"✅ **{project}**: {len(files)} migrations, one chain, head `{heads[0]}`"
    else:
        msg = f"**{project}**: no migration files in `{cfg['path']}`"
    await interaction.followup.send(msg[:1990])


@tree.command(name="addproject", description="Track a repo's migrations (or update it); claims post to this channel")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(
    name="Short name used in commands, e.g. eduvia-server",
    repo="GitHub owner/repo, e.g. EduVia-Org/EduVia-Server",
    path="Folder holding the migration files, e.g. migrations/versions or alembic/versions",
    numbered="True if files start with a number (0067_add_x.py); False for Alembic hash ids (a1b2c3d4e5f6_add_x.py)",
)
async def addproject_cmd(interaction: discord.Interaction, name: str, repo: str, path: str, numbered: bool):
    await interaction.response.defer()
    path = path.strip("/")
    names = await asyncio.to_thread(fetch_names, repo, path)  # fails here if the token can't read it
    cfg = {"repo": repo, "path": path, "numbered": numbered,
           "guild_id": interaction.guild_id, "channel_id": interaction.channel_id}
    if numbered:
        cfg["pattern"] = r"^(\d+)_"
    async with lock:
        PROJECTS[name] = cfg
        save_json(PROJECTS_FILE, PROJECTS)
    if numbered:
        committed, width = parse_numbers(names, cfg["pattern"])
        detail = f"{len(committed)} numbered files, next free `{next_free(committed, set()):0{width}d}`"
    else:
        detail = "not numbered: `/check` works, `/next` and `/claim` don't"
    await interaction.followup.send(f"Added **{name}** (`{repo}/{path}`): {detail}.")


@tree.error
async def on_error(interaction: discord.Interaction, error):
    send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
    await send(f"⚠️ {getattr(error, 'original', error)}")
    raise error


if __name__ == "__main__":
    client.run(os.environ["DISCORD_TOKEN"])
