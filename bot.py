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
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# === CONFIGURATION ===
STOCK_FILE = "stock.json"
SERVICES_FILE = "services.json"
PANEL_FILE = "panel.json"
COOLDOWN_FILE = "cooldowns.json"

LOG_CHANNEL_ID = 1551981969502511224
FREE_GEN_CHANNEL_ID = 1551949049178103941
PREMIUM_GEN_CHANNEL_ID = 1553802370494890147

VIP_ROLE_ID = 1551996352643211345
FREE_ROLE_ID = 1553847227900891216

GUILD_ID = 1551949048221536288

BANNER_URL = "https://i.imgur.com/JlkSP96.gif"

COOLDOWN_SECONDS = 120

ELDO_YELLOW = 0xFFC72C
ELDO_GOLD = 0xFFAC33

ELDO_EMOJI = "<:eldo:1553801485488365729>"

DEFAULT_SERVICES = {
    "eldorado-free": {"label": "ELDORADO", "emoji": ELDO_EMOJI, "color": ELDO_YELLOW, "category": "free"},
    "eldorado-vip":  {"label": "ELDORADO", "emoji": ELDO_EMOJI, "color": ELDO_GOLD,   "category": "premium"},
}

def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

stock = load_json(STOCK_FILE, {})
SERVICES = load_json(SERVICES_FILE, DEFAULT_SERVICES)
panel_data = load_json(PANEL_FILE, {"free": {"channel_id": None, "message_id": None}, "premium": {"channel_id": None, "message_id": None}})
cooldowns = load_json(COOLDOWN_FILE, {})

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

def build_panel_embed(category: str):
    if category == "free":
        color = ELDO_YELLOW
        title = "ELDORADO • FREE"
        desc = "Click the button below to receive your free Eldorado account."
    else:
        color = ELDO_GOLD
        title = "ELDORADO • VIP"
        desc = "Click the button below to receive your VIP Eldorado account."
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

def has_free(member: discord.Member) -> bool:
    return any(role.id == FREE_ROLE_ID for role in member.roles)

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
        has_stock = service in stock and len(stock.get(service, [])) > 0
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

        if category == "free":
            if not is_owner(interaction.user) and not has_free(interaction.user):
                await interaction.followup.send(
                    "You need the **Free Access** role. Go to <#1553847227900891216> to get it.",
                    ephemeral=True
                )
                return

        if not is_owner(interaction.user):
            remaining = get_remaining_cooldown(interaction.user.id)
            if remaining > 0:
                await interaction.followup.send(f"Wait **{remaining}s** before generating again.", ephemeral=True)
                return

        if service not in stock or not stock[service]:
            await interaction.followup.send("No stock left.", ephemeral=True)
            return

        compte = stock[service].pop(0)
        save_json(STOCK_FILE, stock)

        dm_embed = discord.Embed(
            title="ELDORADO",
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
                    msg = await gen_channel.send(f"{interaction.user.mention} generated an Eldorado account")
                    await asyncio.sleep(3)
                    try:
                        await msg.delete()
                    except discord.NotFound:
                        pass

            await refresh_all_panels()
        except discord.Forbidden:
            stock[service].insert(0, compte)
            save_json(STOCK_FILE, stock)
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

# === /rolepanel ===
@bot.tree.command(name="rolepanel", description="Send the role panel")
@app_commands.default_permissions(administrator=True)
async def rolepanel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(
        title="GET FREE ACCESS",
        description=(
            "React with 🟡 below to get the **Free Access** role.\n\n"
            "This role allows you to generate **free Eldorado accounts**."
        ),
        color=ELDO_YELLOW
    )
    embed.set_footer(text="DREAM GEN x ELDORADO")
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("🟡")
    await interaction.followup.send("Role panel sent.", ephemeral=True)

@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id:
        return
    if str(payload.emoji) != "🟡":
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    member = guild.get_member(payload.user_id)
    if not member:
        return
    role = guild.get_role(FREE_ROLE_ID)
    if not role:
        return
    try:
        await member.add_roles(role)
        try:
            await member.send("You received the **Free Access** role on DREAM GEN!")
        except:
            pass
    except Exception as e:
        print(f"⚠️ Error adding role: {e}")

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

@bot.tree.command(name="addstock", description="Add accounts to stock")
@app_commands.default_permissions(administrator=True)
async def addstock(interaction: discord.Interaction, service: str, comptes: str):
    await interaction.response.defer(ephemeral=True)
    service = service.lower()
    if service not in SERVICES:
        await interaction.followup.send("Unknown service.", ephemeral=True)
        return
    liste = [c.strip() for c in re.split(r"[,\n;]+", comptes) if c.strip()]
    if not liste:
        await interaction.followup.send("No valid account found.", ephemeral=True)
        return
    stock.setdefault(service, []).extend(liste)
    save_json(STOCK_FILE, stock)
    await interaction.followup.send(f"**{len(liste)}** account(s) added. Stock: `{len(stock[service])}`", ephemeral=True)
    await refresh_all_panels()
    if LOG_CHANNEL_ID:
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"**{len(liste)}** Eldorado account(s) restocked.")

@addstock.autocomplete("service")
async def service_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=s.capitalize(), value=s) for s in SERVICES.keys() if current.lower() in s.lower()]

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
    if nom in stock:
        del stock[nom]
        save_json(STOCK_FILE, stock)
    await interaction.followup.send(f"Service **{nom}** removed.", ephemeral=True)
    await refresh_all_panels()

@removeservice.autocomplete("nom")
async def removeservice_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=s.capitalize(), value=s) for s in SERVICES.keys() if current.lower() in s.lower()]

@bot.tree.command(name="stock", description="View current stock")
async def stock_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not stock:
        await interaction.followup.send("Stock is empty.", ephemeral=True)
        return
    free_msg = "**FREE:**\n"
    premium_msg = "\n**VIP:**\n"
    for service, comptes in stock.items():
        cat = SERVICES.get(service, {}).get("category", "free")
        line = f"**{service.capitalize()}** : `{len(comptes)}`\n"
        if cat == "premium":
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
