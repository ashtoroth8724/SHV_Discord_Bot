import os
import logging
import discord
from discord import app_commands
from discord.ext import commands
from pathlib import Path
import json
import datetime

# bot.py - Discord bot template with slash (application) commands
# Requires: discord.py 2.0+ (pip install -U "discord.py")
# Usage:
#   set environment variable DISCORD_TOKEN to your bot token
#   optionally set GUILD_ID to a single guild id for fast command registration during development


logging.basicConfig(level=logging.INFO)

# Try token.cfg in the same folder as this file, fallback to DISCORD_TOKEN env var
token_file = Path(__file__).parent / "token.cfg"
TOKEN = None
if token_file.exists():
    try:
        with token_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    TOKEN = line
                    break
    except Exception:
        TOKEN = None
config_file = Path(__file__).parent / "config.json"
config = json.load(open(config_file))
if not config.get("WorkThreadCategoryID"):
    print("WorkThreadCategoryID not set in config.json")
    exit(1)
if not config.get("ServerID"):
    print("ServerID not set in config.json")
    exit(1)
if not config.get("Commitees") or not config.get("Places") or not config.get("event_types"):
    print("Commitees, Places or event_types not set in config.json")
    exit(1)
if not TOKEN:
    print("DISCORD_TOKEN not set in environment or token.cfg")
    exit(1)
GUILD_ID = config.get("ServerID")
intents = discord.Intents.default()

bot = commands.Bot(command_prefix="!", intents=intents)  # prefix not used for slash commands but kept for convenience

# Helper: get guild object for fast development sync (if provided)
dev_guild = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None


@bot.event
async def on_ready():
    """Called when the bot is ready. Syncs application commands."""
    if dev_guild:
        # Sync commands to a single guild (fast). Useful during development.
        bot.tree.clear_commands(guild=dev_guild)  # clear existing commands to avoid duplicates
        logging.info(f"Cleared existing commands in guild {GUILD_ID}")
        await bot.tree.sync(guild=dev_guild)
        logging.info(f"Synced slash commands to guild {GUILD_ID}")
    await bot.tree.sync()
    logging.info("Synced global slash commands")
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")


# Example of a command group (subcommands): /math multiply
event_group = app_commands.Group(name="events", description="Commands related to events")


# Helper check: only allow users with the SA role (name or ID) defined in config.json
async def _check_sa_role(interaction: discord.Interaction) -> bool:
    sa_value = config.get("SARoleID")
    if not sa_value:
        raise app_commands.CheckFailure("SA role not configured on the bot.")
    member = interaction.user
    if not isinstance(member, discord.Member):
        # not in a guild context
        raise app_commands.CheckFailure("This command can only be used in a server.")
    # try numeric id first, fallback to name
    allowed = False
    try:
        sa_id = int(sa_value)
        allowed = any(r.id == sa_id for r in member.roles)
    except Exception:
        allowed = any(r.name == str(sa_value) for r in member.roles)
    if not allowed:
        raise app_commands.CheckFailure("You must have the SA role to use this command.")
    return True


@event_group.command(name="create-event", description="Create a work thread")
@app_commands.check(_check_sa_role)
@app_commands.describe( 
    event_name = "Name of the event", 
    date="DD-MM-YYYY date of the event", 
    time="HH:MM-HH:MM time of the event", 
    comitee="Comitee hosting the event", 
    place="Place of the event", 
    event_type="Type of the event",
    create_work_thread="Whether to create a work thread for the event (default: true)",
    create_event = "Whether to create the event in calendar (default: true)")
@app_commands.choices(  
    comitee=[app_commands.Choice(name=c, value=c) for c in config["Commitees"]],
    place = [app_commands.Choice(name=p, value=p) for p in config["Places"]],
    event_type = [app_commands.Choice(name=e, value=e) for e in config["event_types"]])
async def create_event(
    interaction: discord.Interaction, 
    event_name: str, 
    date: str, 
    time: str, 
    comitee: app_commands.Choice[str], 
    place: app_commands.Choice[str], 
    event_type: app_commands.Choice[str],
    create_work_thread: bool = True,
    create_event: bool = True):
    """Creates a new event with the given parameters."""
    response = f"Creating event '{event_name}' on {date} at {time} hosted by {comitee.value} in {place.value} of type {event_type.value}."
    if create_work_thread:
        response += "\n A work thread will be created."
    if create_event:
        response += "\n The event will be added to the calendar."
    await interaction.response.send_message(response, ephemeral=True)

    # create a new work thread channel in the WorkThreadCategory with name event_name-DD-MM-YYYY
    if create_work_thread:
        category_id = config.get("WorkThreadCategoryID")
        # prefer interaction.guild, fallback to configured guild id
        guild_obj = interaction.guild or bot.get_guild(int(GUILD_ID)) if GUILD_ID else None
        if not guild_obj:
            await interaction.followup.send("Guild not available to create the work thread.", ephemeral=True)
        else:
            channel_name = f"workthread-{event_name}-{date}"
            # category may be an ID in config; get the CategoryChannel object if possible
            category_channel = None
            if category_id is not None:
                try:
                    category_channel = guild_obj.get_channel(int(category_id))
                except Exception:
                    category_channel = None
            thread_channel = await guild_obj.create_text_channel(channel_name, category=category_channel)
            await thread_channel.send(f"Work thread for event '{event_name}' on {date} at {time}.")
            await interaction.followup.send(f"Work thread created: {thread_channel.mention}", ephemeral=True)
    
    #create a discord event in the guild
    if create_event:

        # parse date and start/end time. time will be "HH:MM-HH:MM"
        start_dt = None
        end_dt = None
        date_str = date.strip()
        time_str = time.strip()

        # split start and end times (only first '-' splits to allow hyphens in other contexts)
        if "-" in time_str:
            start_part, end_part = [p.strip() for p in time_str.split("-", 1)]
        else:
            start_part = time_str
            end_part = None

        async def try_parse(dt_str: str) -> datetime.datetime:
            """Try to parse a time string in various formats."""
            # format is DD-MM-YYYY HH:MM, set to midnight if no time provided or if format is invalid,
            # and send a warning message saying to edit the event
            try:
                return datetime.datetime.strptime(dt_str, "%d-%m-%Y %H:%M")
            except ValueError:
                await interaction.followup.send("Time format invalid, set to default (00:00), edit the event to correct it.", ephemeral=True)
                return datetime.datetime.strptime(f"{date_str} 00:00", "%d-%m-%Y %H:%M")

        # try parse start
        start_dt = await try_parse(f"{date_str} {start_part}")

        # try parse end (use provided end_part if available, otherwise default to 1 hour after start)
        if end_part:
            end_dt = await try_parse(f"{date_str} {end_part}")
        else:
            end_dt = start_dt + datetime.timedelta(hours=1)

        # keep behavior compatible with downstream code that expects start_dt variable (timezone applied later)
        # start_dt and end_dt are naive datetimes here; later code will set tzinfo as needed
        # make timezone-aware UTC (Discord expects an aware datetime)
        start_dt = start_dt.replace(tzinfo=datetime.timezone.utc)
        end_dt = end_dt.replace(tzinfo=datetime.timezone.utc)

        # get guild object (prefer interaction.guild)
        guild_obj = interaction.guild or bot.get_guild(int(GUILD_ID)) if GUILD_ID else None
        if not guild_obj:
            await interaction.followup.send("Guild not available to create the event.", ephemeral=True)
        else:
            try:
                # Create a scheduled event. Use an external event (no voice/stage channel).
                event = await guild_obj.create_scheduled_event(
                    name=event_name,
                    start_time=start_dt,
                    end_time=end_dt,
                    description=f"{event_type.value} hosted by {comitee.value} at {place.value}",
                    location=place.value,
                    entity_type=discord.EntityType.external,
                    privacy_level=discord.PrivacyLevel.guild_only,
                )
                await interaction.followup.send(f"Discord event created: {event.name} (ID: {event.id})", ephemeral=True)
            except AttributeError:
                # guild.create_scheduled_event not available in this discord.py version
                await interaction.followup.send("This bot's discord.py version does not support creating scheduled events.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"Failed to create discord event: {e}", ephemeral=True)

@event_group.command(name="delete-work-thread", description="Delete the current channel if it is a work thread")
@app_commands.check(_check_sa_role)
async def delete_work_thread(interaction: discord.Interaction):
    "Delete the current channel if it is a work thread."
    channel = interaction.channel
    if channel and "workthread-" in channel.name:
        await channel.delete()
        await interaction.response.send_message(f"Work thread channel '{channel.name}' deleted.", ephemeral=True)

@event_group.command(name="delete-all-thread", description="Delete all work threads for events older than today")
@app_commands.check(_check_sa_role)
async def delete_all_work_threads(interaction: discord.Interaction):
    """Delete all work thread channels for events older than today."""
    guild_obj = interaction.guild or bot.get_guild(int(GUILD_ID)) if GUILD_ID else None
    if not guild_obj:
        await interaction.response.send_message("Guild not available to delete work threads.", ephemeral=True)
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    deleted_channels = []
    for channel in guild_obj.channels:
        if channel.name.startswith("workthread-"):
            # extract date from channel name
            parts = channel.name.split("-")
            date = parts[-3:]  # last three parts should be DD-MM-YYYY
            if len(date) == 3:
                date_str = "-".join(parts)
                try:
                    event_date = datetime.datetime.strptime(date_str, "%d-%m-%Y").replace(tzinfo=datetime.timezone.utc)
                    if event_date < now:
                        await channel.delete()
                        deleted_channels.append(channel.name)
                except ValueError:
                    print(f"Invalid date format in channel name: {channel.name}")
    await interaction.response.send_message(f"Deleted work thread channels:\n {',\n'.join(deleted_channels)}", ephemeral=True)

bot.tree.add_command(event_group)  # register the group

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