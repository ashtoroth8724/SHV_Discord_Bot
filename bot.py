import os
import logging
import discord
from discord import app_commands
from discord.ext import commands

# bot.py - Discord bot template with slash (application) commands
# Requires: discord.py 2.0+ (pip install -U "discord.py")
# Usage:
#   set environment variable DISCORD_TOKEN to your bot token
#   optionally set GUILD_ID to a single guild id for fast command registration during development


logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # optional: set to a number (string) for guild-scoped commands

intents = discord.Intents.default()

bot = commands.Bot(command_prefix="!", intents=intents)  # prefix not used for slash commands but kept for convenience

# Helper: get guild object for fast development sync (if provided)
dev_guild = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None


@bot.event
async def on_ready():
    """Called when the bot is ready. Syncs application commands."""
    if dev_guild:
        # Sync commands to a single guild (fast). Useful during development.
        await bot.tree.sync(guild=dev_guild)
        logging.info(f"Synced slash commands to guild {GUILD_ID}")
    else:
        # Global sync (can take up to an hour to propagate)
        await bot.tree.sync()
        logging.info("Synced global slash commands")
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")


# Simple slash command: /ping
@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! {latency_ms}ms")


# Slash command with a string parameter: /echo
@bot.tree.command(name="echo", description="Echo back your message")
@app_commands.describe(message="The message to echo")
async def echo(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(message)


# Slash command with typed options: /add a b
@bot.tree.command(name="add", description="Add two integers")
@app_commands.describe(a="First integer", b="Second integer")
async def add(interaction: discord.Interaction, a: int, b: int):
    await interaction.response.send_message(f"{a} + {b} = {a + b}")


# Example of a command group (subcommands): /math multiply
math = app_commands.Group(name="math", description="Math utilities")


@math.command(name="multiply", description="Multiply two numbers")
@app_commands.describe(a="First number", b="Second number")
async def multiply(interaction: discord.Interaction, a: float, b: float):
    await interaction.response.send_message(f"{a} * {b} = {a * b}")


bot.tree.add_command(math)  # register the group


# Global error handler for app commands
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # If an interaction hasn't been responded to, respond with an ephemeral message.
    try:
        await interaction.response.send_message(f"Error: {error}", ephemeral=True)
    except Exception:
        # If response already sent, follow up instead.
        await interaction.followup.send(f"Error: {error}", ephemeral=True)
    logging.exception("Error handling an application command")


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Environment variable DISCORD_TOKEN is required to run the bot.")
    bot.run(TOKEN)