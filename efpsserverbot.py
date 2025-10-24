# Use Python 3.10.8

import discord
from discord import app_commands
import os
import asyncio
import aiohttp
from dotenv import load_dotenv
from typing import List, Dict, Set

# Load env variables
load_dotenv()
TOKEN = os.getenv("token")
API_URL = os.getenv("api")
STEAM_API_KEY = os.getenv("steam_api")  # optional fallback

# Discord setup
intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Constants
FIELD_VALUE_MAX = 1024
EMBED_TOTAL_MAX = 6000

async def fetch_server_data(api_url: str) -> List[dict]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=10) as resp:
                if resp.status == 200:
                    return await resp.json()
                return []
    except Exception:
        return []

async def resolve_steam_names(steam_ids: Set[str]) -> Dict[str, str]:
    """Fetch persona names for given Steam IDs."""
    if not STEAM_API_KEY or not steam_ids:
        return {}

    ids = list(steam_ids)
    mapping: Dict[str, str] = {}
    CHUNK = 100
    async with aiohttp.ClientSession() as session:
        for i in range(0, len(ids), CHUNK):
            chunk = ids[i:i + CHUNK]
            url = (
                "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
                f"?key={STEAM_API_KEY}&steamids={','.join(chunk)}"
            )
            try:
                async with session.get(url, timeout=10) as resp:
                    if resp.status != 200:
                        continue
                    j = await resp.json()
                    players = j.get("response", {}).get("players", [])
                    for p in players:
                        sid = p.get("steamid")
                        name = p.get("personaname")
                        if sid and name:
                            mapping[sid] = name
            except Exception:
                continue
    return mapping

def choose_player_name(p: dict, steam_map: Dict[str, str]) -> str:
    """Pick the best player name available."""
    for key in ("name", "playerName", "nick", "username", "displayName", "persona", "personaname"):
        if p.get(key):
            return str(p[key])

    steamid = str(p.get("steamId") or p.get("steam_id") or "")
    if steamid:
        return steam_map.get(steamid, f"steam:{steamid[-8:]}")
    if "userId" in p:
        return f"#{p['userId']}"
    return "Unknown"

def compact_player_line(p: dict, name: str) -> str:
    team = p.get("teamIdx", "n/a")
    hp = p.get("health", "n/a")
    armor = p.get("armor", "n/a")
    kills = p.get("kills", "n/a")
    deaths = p.get("deaths", "n/a")
    ping = p.get("ping", "n/a")
    weapon = p.get("weapon") or "none"

    team_map = {"0": "Free For All", "1": "Free For All", "2": "Rebel", "3": "Combine"}
    team = team_map.get(str(team), team)
    return f"**{name}** — {team} — {hp}HP/{armor}AR — {kills}K/{deaths}D — {ping}ms — {weapon}"

def make_one_big_embed(all_data: List[dict], steam_map: Dict[str, str]) -> discord.Embed:
    embed = discord.Embed(
        title="SF Servers",
        description="Live stats for SF HL2DM servers.",
        timestamp=discord.utils.utcnow(),
        color=discord.Color.red()
    )

    # Attach an icon
    embed.set_author(name="SF Server Bot", icon_url="attachment://icon.png")
    embed.set_thumbnail(url="attachment://icon.png")

    total_chars = len(embed.title or "") + len(embed.description or "")
    servers_truncated = 0

    for entry in all_data:
        info = entry.get("serverInfo", {})
        name = info.get("name", "unnamed")
        version = info.get("version", "unknown")

        players = entry.get("players") or []
        if not players:
            field_value = f"Players: 0 • version `{version}`"
        else:
            lines = [f"Players: {len(players)} • version `{version}`"]
            for p in players:
                pname = choose_player_name(p, steam_map)
                line = compact_player_line(p, pname)
                lines.append(line)

            joined = "\n".join(lines)
            if len(joined) > FIELD_VALUE_MAX:
                joined = joined[:FIELD_VALUE_MAX - 30] + "\n... (truncated)"
            field_value = joined

        if total_chars + len(name) + len(field_value) + 10 > EMBED_TOTAL_MAX:
            servers_truncated += 1
            continue

        embed.add_field(name=name[:256], value=field_value, inline=False)
        total_chars += len(name) + len(field_value)

    if servers_truncated:
        embed.add_field(
            name="Notice",
            value=f"Truncated: {servers_truncated} server(s) omitted.",
            inline=False,
        )

    embed.set_footer(text=f"Server list • {len(all_data)} total (showing {len(embed.fields)}).")
    return embed

# Slash command
@tree.command(name="servers", description="Fetch and show all SF servers.")
async def servers(interaction: discord.Interaction):
    await interaction.response.defer()
    data = await fetch_server_data(API_URL)
    if not data:
        await interaction.followup.send("No servers available or failed to fetch data.")
        return

    steam_ids = {
        str(p.get("steamId") or p.get("steam_id"))
        for entry in data for p in (entry.get("players") or [])
        if p.get("steamId") or p.get("steam_id")
    }

    steam_map = await resolve_steam_names(steam_ids) if steam_ids else {}

    embed = make_one_big_embed(data, steam_map)
    file = discord.File("icon.png", filename="icon.png")

    approx_len = len(embed.title or "") + len(embed.description or "") + sum(len(f.name) + len(f.value) for f in embed.fields)
    if approx_len > EMBED_TOTAL_MAX:
        await interaction.followup.send("Result too large for a single embed.")
        return

    await interaction.followup.send(embed=embed, file=file)

@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user}")

bot.run(TOKEN)
