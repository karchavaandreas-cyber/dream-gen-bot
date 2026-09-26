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

LOG_CHANNEL_ID = 1551981969502511224           # Salon #restock
FREE_GEN_CHANNEL_ID = 1551949049178103941      # Salon #free-gen
PREMIUM_GEN_CHANNEL_ID = 1551949049178103943   # Salon #premium-gen

VIP_ROLE_ID = 1551996352643211345              # Rôle VIP requis pour le premium

GUILD_ID = 1551949048221536288
BANNER_URL = "https://i.imgur.com/WevuFGx.gif"

COOLDOWN_SECONDS = 60

# === COULEURS DES PANELS ===
PANEL_COLORS = {
    "free": 0x2B2D31,
    "premium": 0x2B2D31,
}

# === SERVICES ===
DEFAULT_SERVICES = {
    "steam":       {"emoji": "<:steam:1551985805327736934>",       "color": 0x1B2838, "category": "free"},
    "microsoft":   {"emoji": "<:microsoft:1551986128859693096>",   "color": 0x00A4EF, "category": "free"},
    "crunchyroll": {"emoji": "<:crunchyroll:1551986256332726312>", "color": 0xF47521, "category": "free"},
    "deezer":      {"emoji": "<:deezer:1552016366154948689>",      "color": 0xA238FF, "category": "free"},
    "sfr":         {"emoji": "",                                    "color": 0xE30613, "category": "free"},
    "netflix":     {"emoji": "<:netflix:1551985544882294834>",     "color": 0xE50914, "category": "premium"},
    "minecraft":   {"emoji": "<:minecraft:1551985978942554132>",   "color": 0x44BD32, "category": "premium"},
    "spotify":     {"emoji": "",                                    "color": 0x1DB954, "category": "premium"},
}

# === LOAD / SAVE ===
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

# === BOT ===
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# === PANEL EMBED ===
def build_panel_embed(category: str):
    color = PANEL_COLORS.get(category, 0x2B2D31)

    if category == "free":
        title = "Account Generator"
        desc = "Click a button to receive your free account in DM."
    else:
        title = "Premium Generator"
        desc = "Click a button to receive your premium account in DM.\n**VIP role required.**"

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

# === COOLDOWN ===
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

# === GEN BUTTON ===
class GenButton(discord.ui.Button):
    def __init__(self, service: str, emoji: str):
        emoji_obj = emoji if emoji else None
        has_stock = service in stock and len(stock.get(service, [])) > 0

        super().__init__(
            label=service.capitalize(),
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

        # === CHECK VIP POUR PREMIUM ===
        if category == "premium":
            if not is_owner(interaction.user) and not has_vip(interaction.user):
                await interaction.followup.send(
                    "You need the **VIP** role to generate premium accounts.",
                    ephemeral=True
                )
                return

        # === CHECK COOLDOWN ===
        if not is_owner(interaction.user):
            remaining = get_remaining_cooldown(interaction.user.id)
            if remaining > 0:
                await interaction.followup.send(
                    f"Wait **{remaining}s** before generating again.", ephemeral=True
                )
                return

        # === CHECK STOCK ===
        if service not in stock or not stock[service]:
            await interaction.followup.send(
                f"No stock left for **{service}**.", ephemeral=True
            )
            return

        compte = stock[service].pop(0)
        save_json(STOCK_FILE, stock)

        dm_embed = discord.Embed(
            title=f"{service.capitalize()}",
            description=f"```{compte}```",
            color=SERVICES[service]["color"]
        )
        dm_embed.set_footer(text="DREAM GEN • Break The Grind")

        try:
            await interaction.user.send(embed=dm_embed)

            if not is_owner(interaction.user):
                set_cooldown(interaction.user.id)

            await interaction.followup.send("Account sent in DM.", ephemeral=True)

            # === MESSAGE DE GEN DANS LE BON SALON ===
            if category == "premium":
                gen_channel_id = PREMIUM_GEN_CHANNEL_ID
            else:
                gen_channel_id = FREE_GEN_CHANNEL_ID

            if gen_channel_id:
                gen_channel = bot.get_channel(gen_channel_id)
                if gen_channel:
                    msg = await gen_channel.send(
                        f"{interaction.user.mention} generated a **{service.capitalize()}** account"
                    )
                    await asyncio.sleep(3)
                    try:
                        await msg.delete()
                    except discord.NotFound:
                        pass

            await refresh_all_panels()

        except discord.Forbidden:
            stock[service].insert(0, compte)
            save_json(STOCK_FILE, stock)
            await interaction.followup.send("Enable your DMs to receive the account.", ephemeral=True)

# === VIEW ===
class GenView(discord.ui.View):
    def __init__(self, category: str):
        super().__init__(timeout=None)
        for service, data in SERVICES.items():
            if data.get("category") == category:
                self.add_item(GenButton(service, data["emoji"]))

# === /panel ===
@bot.tree.command(name="panel", description="Show the FREE panel")
@app_commands.default_permissions(administrator=True)
async def panel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    msg = await interaction.channel.send(embed=build_panel_embed("free"), view=GenView("free"))
    panel_data["free"] = {"channel_id": msg.channel.id, "message_id": msg.id}
    save_json(PANEL_FILE, panel_data)
    await interaction.followup.send("FREE panel sent.", ephemeral=True)

# === /panel2 ===
@bot.tree.command(name="panel2", description="Show the PREMIUM panel")
@app_commands.default_permissions(administrator=True)
async def panel2(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    msg = await interaction.channel.send(embed=build_panel_embed("premium"), view=GenView("premium"))
    panel_data["premium"] = {"channel_id": msg.channel.id, "message_id": msg.id}
    save_json(PANEL_FILE, panel_data)
    await interaction.followup.send("PREMIUM panel sent.", ephemeral=True)

# === HELPER ADD SERVICE ===
async def _add_service_common(interaction, nom, emoji, categorie, couleur):
    nom = nom.lower().strip()

    if nom in SERVICES:
        await interaction.followup.send(f"Service **{nom}** already exists.", ephemeral=True)
        return

    if emoji and emoji.isdigit():
        emoji = f"<:emoji:{emoji}>"

    if emoji and not emoji.startswith("<"):
        await interaction.followup.send(
            "Invalid emoji format. Use `<:name:ID>`, a raw ID, or leave empty.", ephemeral=True
        )
        return

    try:
        color_int = int(couleur.replace("0x", "").replace("#", ""), 16)
    except ValueError:
        color_int = 0x2B2D31

    SERVICES[nom] = {"emoji": emoji, "color": color_int, "category": categorie}
    save_json(SERVICES_FILE, SERVICES)

    await interaction.followup.send(
        f"Service **{nom}** added as **{categorie}**. Run `/panel` or `/panel2` to see it.",
        ephemeral=True
    )
    await refresh_all_panels()

# === /addservice (FREE) ===
@bot.tree.command(name="addservice", description="Add a FREE service")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    nom="Service name",
    emoji="Custom emoji (ex: <:sfr:123456>) or leave empty",
    couleur="Hex color (ex: E30613) - optional"
)
async def addservice(interaction: discord.Interaction, nom: str, emoji: str, couleur: str = "2B2D31"):
    await interaction.response.defer(ephemeral=True)
    await _add_service_common(interaction, nom, emoji, "free", couleur)

# === /addservice2 (PREMIUM) ===
@bot.tree.command(name="addservice2", description="Add a PREMIUM service")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    nom="Service name",
    emoji="Custom emoji (ex: <:spotify:123456>) or leave empty",
    couleur="Hex color (ex: 1DB954) - optional"
)
async def addservice2(interaction: discord.Interaction, nom: str, emoji: str, couleur: str = "2B2D31"):
    await interaction.response.defer(ephemeral=True)
    await _add_service_common(interaction, nom, emoji, "premium", couleur)

# === /addstock ===
@bot.tree.command(name="addstock", description="Add accounts to stock")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(service="The service", comptes="Accounts separated by commas or newlines")
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

    await interaction.followup.send(
        f"**{len(liste)}** account(s) added for **{service}**. Stock: `{len(stock[service])}`",
        ephemeral=True
    )

    await refresh_all_panels()

    # === LOG RESTOCK ===
    if LOG_CHANNEL_ID:
        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            cat = SERVICES[service].get("category", "free").upper()

            embed = discord.Embed(
                title=f"NEW RESTOCK • {cat}",
                description=f"**{len(liste)}** new account(s) added to the stock!",
                color=SERVICES[service]["color"]
            )
            embed.add_field(name="Service", value=service.capitalize(), inline=True)
            embed.add_field(name="Added", value=f"`+{len(liste)}`", inline=True)
            embed.add_field(name="Total stock", value=f"`{len(stock[service])}`", inline=True)
            embed.add_field(name="Category", value=cat, inline=True)
            embed.set_thumbnail(url=bot.user.display_avatar.url)
            embed.set_footer(text=f"Restocked by {interaction.user} • DREAM GEN", icon_url=interaction.user.display_avatar.url)
            embed.timestamp = discord.utils.utcnow()
            await log_channel.send(embed=embed)

@addstock.autocomplete("service")
async def service_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=s.capitalize(), value=s) for s in SERVICES.keys() if current.lower() in s.lower()]

# === /removeservice ===
@bot.tree.command(name="removeservice", description="Remove a service")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(nom="Name of the service to remove")
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

# === /stock ===
@bot.tree.command(name="stock", description="View current stock")
async def stock_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not stock:
        await interaction.followup.send("Stock is empty.", ephemeral=True)
        return
    free_msg = "**FREE:**\n"
    premium_msg = "\n**PREMIUM:**\n"
    for service, comptes in stock.items():
        emoji = SERVICES.get(service, {}).get("emoji", "")
        cat = SERVICES.get(service, {}).get("category", "free")
        line = f"{emoji} **{service.capitalize()}** : `{len(comptes)}`\n"
        if cat == "premium":
            premium_msg += line
        else:
            free_msg += line
    await interaction.followup.send(free_msg + premium_msg, ephemeral=True)

# === /resetcooldown ===
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
