# === MINI SERVEUR WEB POUR FLY.IO ===
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'DREAM GEN is alive')
    def log_message(self, format, *args):
        pass

def run_web_server():
    server = HTTPServer(('0.0.0.0', 8080), HealthHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()
# =====================================

import fix_ssl

import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import re
import asyncio
import time
import sqlite3
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# === CONFIGURATION ===
DB_FILE = "dreamgen.db"
SERVICES_FILE = "services.json"
PANEL_FILE = "panel.json"
COOLDOWN_FILE = "cooldowns.json"

LOG_CHANNEL_ID = 1551981969502511224
FREE_GEN_CHANNEL_ID = 1551949049178103941
PREMIUM_GEN_CHANNEL_ID = 1553802370494890147

VIP_ROLE_ID = 1551996352643211345

GUILD_ID = 1551949048221536288

BANNER_URL = "https://i.imgur.com/20MxNVU.gif"

COOLDOWN_SECONDS = 120

ELDO_YELLOW = 0xFFC72C
ELDO_GOLD = 0xFFAC33
EPIC_BLUE = 0x0078F2

ELDO_EMOJI = "<:eldo:1553801485488365729>"
EPIC_EMOJI = "<:epic:1554199484777369610>"

# === SERVICES (EPIC UNIQUEMENT EN VIP) ===
DEFAULT_SERVICES = {
    "eldorado-free": {"label": "ELDORADO", "emoji": ELDO_EMOJI, "color": ELDO_YELLOW, "category": "free"},
    "epic-vip":      {"label": "EPIC GAMES", "emoji": EPIC_EMOJI, "color": EPIC_BLUE, "category": "premium"},
}

# === BASE DE DONNÉES SQLITE ===
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        service TEXT NOT NULL,
        account TEXT NOT NULL
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_service ON accounts(service)')
    conn.commit()
    conn.close()

def add_accounts_db(service: str, accounts: list) -> int:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.executemany(
        "INSERT INTO accounts (service, account) VALUES (?, ?)",
        [(service, acc) for acc in accounts]
    )
    conn.commit()
    count = c.rowcount
    conn.close()
    return count

def pop_account_db(service: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, account FROM accounts WHERE service = ? LIMIT 1", (service,))
    row = c.fetchone()
    if row:
        c.execute("DELETE FROM accounts WHERE id = ?", (row[0],))
        conn.commit()
        conn.close()
        return row[1]
    conn.close()
    return None

def count_accounts_db(service: str) -> int:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM accounts WHERE service = ?", (service,))
    count = c.fetchone()[0]
    conn.close()
    return count

def clear_service_db(service: str) -> int:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM accounts WHERE service = ?", (service,))
    conn.commit()
    count = c.rowcount
    conn.close()
    return count

def clear_all_db() -> int:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM accounts")
    conn.commit()
    count = c.rowcount
    conn.close()
    return count

# === SERVICES / PANELS / COOLDOWNS (JSON) ===
def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

SERVICES = load_json(SERVICES_FILE, DEFAULT_SERVICES)
panel_data = load_json(PANEL_FILE, {"free": {"channel_id": None, "message_id": None}, "premium": {"channel_id": None, "message_id": None}})
cooldowns = load_json(COOLDOWN_FILE, {})

# === BOT ===
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

init_db()

def build_panel_embed(category: str):
    if category == "free":
        color = ELDO_YELLOW
        title = "FREE GENERATOR"
        desc = "Click a button below to receive your free account in DM."
    else:
        color = ELDO_GOLD
        title = "VIP GENERATOR"
        desc = "Click a button below to receive your VIP account in DM."
    embed = discord.Embed(title=title, description=desc, color=color)
    embed.set_image(url=BANNER_URL)
    return embed

async def refresh_panel(category: str):
    data = panel_data.get(category)
    if not data or not data["channel_id"] or not data["message_id"]:
        return
    try:
        channel = bot.get_channel(data["channel_id"])
        if not channel:
            return
        message = await channel.fetch_message(data["message_id"])
        await message.edit(embed=build_panel_embed(category), view=GenView(category))
    except Exception as e:
        print(f"⚠️ Refresh panel {category} : {e}")

async def refresh_all_panels():
    await refresh_panel("free")
    await refresh_panel("premium")

def is_owner(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or member.id == member.guild.owner_id

def has_vip(member: discord.Member) -> bool:
    return any(role.id == VIP_ROLE_ID for role in member.roles)

def get_remaining_cooldown(user_id: int) -> int:
    if str(user_id) not in cooldowns:
        return 0
    elapsed = time.time() - cooldowns[str(user_id)]
    remaining = COOLDOWN_SECONDS - elapsed
    return max(0, int(remaining))

def set_cooldown(user_id: int):
    cooldowns[str(user_id)] = time.time()
    save_json(COOLDOWN_FILE, cooldowns)

class GenButton(discord.ui.Button):
    def __init__(self, service: str, label: str, emoji: str):
        emoji_obj = emoji if emoji else None
        count = count_accounts_db(service)
        has_stock = count > 0
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            emoji=emoji_obj,
            custom_id=f"gen_{service}",
            disabled=not has_stock
        )
        self.service = service

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        service = self.service
        category = SERVICES[service].get("category", "free")

        if category == "premium":
            if not is_owner(interaction.user) and not has_vip(interaction.user):
                await interaction.followup.send("You need the **VIP** role.", ephemeral=True)
                return

        if not is_owner(interaction.user):
            remaining = get_remaining_cooldown(interaction.user.id)
            if remaining > 0:
                await interaction.followup.send(f"Wait **{remaining}s** before generating again.", ephemeral=True)
                return

        compte = pop_account_db(service)
        if not compte:
            await interaction.followup.send("No stock left.", ephemeral=True)
            return

        dm_embed = discord.Embed(
            title=SERVICES[service]["label"],
            description=f"```{compte}```",
            color=SERVICES[service]["color"]
        )
        dm_embed.set_footer(text="DREAM GEN")

        try:
            await interaction.user.send(embed=dm_embed)
            if not is_owner(interaction.user):
                set_cooldown(interaction.user.id)
            await interaction.followup.send("Sent in DM.", ephemeral=True)

            gen_channel_id = PREMIUM_GEN_CHANNEL_ID if category == "premium" else FREE_GEN_CHANNEL_ID
            if gen_channel_id:
                gen_channel = bot.get_channel(gen_channel_id)
                if gen_channel:
                    msg = await gen_channel.send(f"{interaction.user.mention} generated a **{SERVICES[service]['label']}** account")
                    await asyncio.sleep(3)
                    try:
                        await msg.delete()
                    except discord.NotFound:
                        pass

            await refresh_all_panels()
        except discord.Forbidden:
            add_accounts_db(service, [compte])
            await interaction.followup.send("Enable your DMs.", ephemeral=True)

class GenView(discord.ui.View):
    def __init__(self, category: str):
        super().__init__(timeout=None)
        for service, data in SERVICES.items():
            if data.get("category") == category:
                label = data.get("label", service.capitalize())
                self.add_item(GenButton(service, label, data["emoji"]))

@bot.tree.command(name="panel", description="Show the FREE panel")
@app_commands.default_permissions(administrator=True)
async def panel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    msg = await interaction.channel.send(embed=build_panel_embed("free"), view=GenView("free"))
    panel_data["free"] = {"channel_id": msg.channel.id, "message_id": msg.id}
    save_json(PANEL_FILE, panel_data)
    await interaction.followup.send("Panel FREE sent.", ephemeral=True)

@bot.tree.command(name="panel2", description="Show the VIP panel")
@app_commands.default_permissions(administrator=True)
async def panel2(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    msg = await interaction.channel.send(embed=build_panel_embed("premium"), view=GenView("premium"))
    panel_data["premium"] = {"channel_id": msg.channel.id, "message_id": msg.id}
    save_json(PANEL_FILE, panel_data)
    await interaction.followup.send("Panel VIP sent.", ephemeral=True)

@bot.tree.command(name="addservice", description="Add a FREE service")
@app_commands.default_permissions(administrator=True)
async def addservice(interaction: discord.Interaction, nom: str, label: str, emoji: str = "", couleur: str = "FFC72C"):
    await interaction.response.defer(ephemeral=True)
    nom = nom.lower().strip()
    if nom in SERVICES:
        await interaction.followup.send(f"Service **{nom}** already exists.", ephemeral=True)
        return
    try:
        color_int = int(couleur.replace("0x", "").replace("#", ""), 16)
    except ValueError:
        color_int = ELDO_YELLOW
    SERVICES[nom] = {"label": label, "emoji": emoji, "color": color_int, "category": "free"}
    save_json(SERVICES_FILE, SERVICES)
    await interaction.followup.send(f"Service **{nom}** added as **free**.", ephemeral=True)
    await refresh_all_panels()

@bot.tree.command(name="addservice2", description="Add a VIP service")
@app_commands.default_permissions(administrator=True)
async def addservice2(interaction: discord.Interaction, nom: str, label: str, emoji: str = "", couleur: str = "FFAC33"):
    await interaction.response.defer(ephemeral=True)
    nom = nom.lower().strip()
    if nom in SERVICES:
        await interaction.followup.send(f"Service **{nom}** already exists.", ephemeral=True)
        return
    try:
        color_int = int(couleur.replace("0x", "").replace("#", ""), 16)
    except ValueError:
        color_int = ELDO_GOLD
    SERVICES[nom] = {"label": label, "emoji": emoji, "color": color_int, "category": "premium"}
    save_json(SERVICES_FILE, SERVICES)
    await interaction.followup.send(f"Service **{nom}** added as **VIP**.", ephemeral=True)
    await refresh_all_panels()

# === /addstock (SQLite - supporte 1M+ comptes) ===
@bot.tree.command(name="addstock", description="Add accounts to stock (text or .txt file)")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    service="The service",
    comptes="Accounts (optional if file provided)",
    fichier="Optional .txt file (one account per line)"
)
async def addstock(
    interaction: discord.Interaction,
    service: str,
    comptes: str = "",
    fichier: discord.Attachment = None
):
    await interaction.response.defer(ephemeral=True)
    service = service.lower()

    if service not in SERVICES:
        await interaction.followup.send("Unknown service.", ephemeral=True)
        return

    all_accounts = []

    if comptes:
        all_accounts.extend([c.strip() for c in re.split(r"[,\n;]+", comptes) if c.strip()])

    if fichier:
        if not fichier.filename.endswith(".txt"):
            await interaction.followup.send("File must be .txt", ephemeral=True)
            return
        try:
            content = await fichier.read()
            all_accounts.extend([c.strip() for c in content.decode("utf-8", errors="ignore").splitlines() if c.strip()])
        except Exception as e:
            await interaction.followup.send(f"Error reading file: {e}", ephemeral=True)
            return

    if not all_accounts:
        await interaction.followup.send("No account provided.", ephemeral=True)
        return

    all_accounts = list(set(all_accounts))
    added = add_accounts_db(service, all_accounts)
    total = count_accounts_db(service)

    await interaction.followup.send(
        f"**{added}** account(s) added to **{SERVICES[service]['label']}**. Total: `{total}`",
        ephemeral=True
    )

    await refresh_all_panels()

    if LOG_CHANNEL_ID:
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"**{added}** {SERVICES[service]['label']} account(s) restocked.")

@addstock.autocomplete("service")
async def service_autocomplete(interaction: discord.Interaction, current: str):
    # Dédupliqué automatiquement
    seen = set()
    choices = []
    for s in SERVICES.keys():
        if s not in seen and current.lower() in s.lower():
            choices.append(app_commands.Choice(name=s.capitalize(), value=s))
            seen.add(s)
    return choices

# === /resetstock (vider un service) ===
@bot.tree.command(name="resetstock", description="Clear all accounts from a service")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(service="Service to clear (or 'all' to clear everything)")
async def resetstock(interaction: discord.Interaction, service: str):
    await interaction.response.defer(ephemeral=True)
    service = service.lower()

    if service == "all":
        count = clear_all_db()
        await interaction.followup.send(f"Cleared **{count}** accounts from all services.", ephemeral=True)
    elif service in SERVICES:
        count = clear_service_db(service)
        await interaction.followup.send(f"Cleared **{count}** accounts from **{SERVICES[service]['label']}**.", ephemeral=True)
    else:
        await interaction.followup.send(f"Unknown service. Use 'all' or a valid service.", ephemeral=True)
        return

    await refresh_all_panels()

@resetstock.autocomplete("service")
async def resetstock_autocomplete(interaction: discord.Interaction, current: str):
    choices = [app_commands.Choice(name="ALL SERVICES", value="all")]
    choices += [app_commands.Choice(name=s.capitalize(), value=s) for s in SERVICES.keys() if current.lower() in s.lower()]
    return choices

@bot.tree.command(name="removeservice", description="Remove a service")
@app_commands.default_permissions(administrator=True)
async def removeservice(interaction: discord.Interaction, nom: str):
    await interaction.response.defer(ephemeral=True)
    nom = nom.lower().strip()
    if nom not in SERVICES:
        await interaction.followup.send(f"Service **{nom}** does not exist.", ephemeral=True)
        return
    del SERVICES[nom]
    save_json(SERVICES_FILE, SERVICES)
    clear_service_db(nom)
    await interaction.followup.send(f"Service **{nom}** removed (and its stock).", ephemeral=True)
    await refresh_all_panels()

@removeservice.autocomplete("nom")
async def removeservice_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=s.capitalize(), value=s) for s in SERVICES.keys() if current.lower() in s.lower()]

@bot.tree.command(name="stock", description="View current stock")
async def stock_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    free_msg = "**FREE:**\n"
    premium_msg = "\n**VIP:**\n"
    for service, data in SERVICES.items():
        count = count_accounts_db(service)
        label = data.get("label", service)
        line = f"**{label}** : `{count}`\n"
        if data.get("category") == "premium":
            premium_msg += line
        else:
            free_msg += line
    await interaction.followup.send(free_msg + premium_msg, ephemeral=True)

@bot.tree.command(name="resetcooldown", description="Reset a member's cooldown")
@app_commands.default_permissions(administrator=True)
async def resetcooldown(interaction: discord.Interaction, membre: discord.Member):
    await interaction.response.defer(ephemeral=True)
    if str(membre.id) in cooldowns:
        del cooldowns[str(membre.id)]
        save_json(COOLDOWN_FILE, cooldowns)
        await interaction.followup.send(f"Cooldown of {membre.mention} reset.", ephemeral=True)
    else:
        await interaction.followup.send(f"{membre.mention} has no cooldown.", ephemeral=True)

@bot.event
async def on_ready():
    await bot.tree.sync()
    guild = discord.Object(id=GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)
    print(f"✅ {len(synced)} commands synced")
    print(f"✅ Connected as : {bot.user}")

bot.run(TOKEN)
