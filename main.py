import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
from dotenv import load_dotenv
from datetime import datetime
from gsheets_helper import (
    parse_shift_date,
    parse_time_range,
    resolve_full_shift,
    resolve_partial_shift,
    create_shift_thread,
    find_row_by_threadid,
)
from discord_to_sheets import DISCORD_TO_ASSIGNEE
import re
import os

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    # cleanup_threads.start()


# # Task to clean up old threads every 2 hours
# @tasks.loop(hours=2)
# async def cleanup_threads():
#     for guild in bot.guilds:
#         for channel in guild.text_channels:
#             for thread in channel.threads:
#                 try:
#                     parts = thread.name.split(" ")
#                     date_str = parts[1]
#                     month, day = map(int, date_str.split("/"))
#                     year = datetime.now().year
#                     thread_date = datetime(year, month, day)

#                     if datetime.now() > thread_date:
#                         await thread.send("This coverage shift has passed. Closing thread...", silent=True)
#                         await thread.delete()
#                 except Exception as e:
#                     print(f"Skipping thread '{thread.name}': {e}")


# @cleanup_threads.before_loop
# async def before_cleanup():
#     await bot.wait_until_ready()


# Slash command to create a coverage thread
# /coverage
@bot.tree.command(name="coverage", description="Create a coverage thread for an open shift")
@app_commands.describe(
    day="Day of the week (e.g., Monday)",
    date="Date in MM/DD format (e.g., 09/15)",
    time="Time range for the shift (e.g., 7-9pm)",
    location="Location: CSL or Hackerspace",
)
async def coverage(interaction: discord.Interaction, day: str, date: str, time: str, location: str):
    parsed_date = parse_shift_date(date)
    if day.lower() not in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
        await interaction.response.send_message(
            "Invalid day. Please use a valid weekday (e.g., Monday, Tuesday).", ephemeral=True
        )
        return
    elif parsed_date is None:
        await interaction.response.send_message(
            "Invalid date format. Please use MM/DD format (e.g., 09/15).", ephemeral=True
        )
        return
    elif location.lower() not in ["csl", "hackerspace"]:
        await interaction.response.send_message(
            "Invalid location. Please specify either 'CSL' or 'Hackerspace'.", ephemeral=True
        )
        return

    await interaction.response.send_message("Creating coverage thread...", ephemeral=True)
    await create_shift_thread(interaction.channel, day, date, time, location)


@bot.tree.command(name="resolve", description="Resolve a shift (fully or partially) and close the thread")
@app_commands.describe(time="Optional: only resolve part of the shift (e.g., 7-8pm). Leave blank to resolve fully.")
async def resolve(interaction: discord.Interaction, time: str = None):
    """
    /resolve            -> resolves the entire shift, closes thread
    /resolve time:7-8pm -> resolves only that portion, closes thread
    """
    if not isinstance(interaction.channel, discord.Thread):
        await interaction.response.send_message("This command can only be used inside a thread.", ephemeral=True)
        return

    assignee_id = DISCORD_TO_ASSIGNEE.get(interaction.user.id)
    if not assignee_id:
        await interaction.response.send_message(
            f"❌ {interaction.user.display_name} isn't mapped to a sheet assignee. Ask an admin to add you.",
            ephemeral=True,
        )
        return

    # Parse thread name: "{day} {date} {time} in {location}"
    match = re.match(r"^(\S+)\s+(\S+)\s+(.+?)\s+in\s+(.+)$", interaction.channel.name)
    if not match:
        await interaction.response.send_message("❌ Couldn't parse shift info from thread name.", ephemeral=True)
        return

    day, date, full_time, location = match.groups()
    parent_channel = interaction.channel.parent  # thread's parent text channel
    thread_id = interaction.channel.id

    try:
        if time is None:
            # FULL RESOLVE
            resolve_full_shift(thread_id, assignee_id=assignee_id)
            await interaction.response.send_message("✅ Shift fully covered! Closing thread...")
        else:
            # PARTIAL RESOLVE
            remainder_times = resolve_partial_shift(thread_id, day, date, full_time, time, location, assignee_id=assignee_id)
            for remainder_time in remainder_times:
                await create_shift_thread(parent_channel, day, date, remainder_time, location)
            await interaction.response.send_message(f"✅ {time} covered, remaining time still needs coverage. Closing thread...")

        await interaction.channel.delete()

    except ValueError as e:
        await interaction.response.send_message(f"❌ {e}", ephemeral=True)


# Slash command to clear the channel (for testing purposes)
# @bot.tree.command(name="clear", description="Purge up to 100 messages in this channel (testing only)")
# async def clear(interaction: discord.Interaction):
#     await interaction.response.defer(ephemeral=True)
#     await interaction.channel.purge(limit=100)
#     await interaction.followup.send("Channel cleared!", ephemeral=True)


# # Slash command to manually trigger cleanup (for testing purposes)
# @bot.tree.command(name="test_cleanup", description="Manually trigger the thread cleanup task (testing only)")
# async def test_cleanup(interaction: discord.Interaction):
#     await interaction.response.defer(ephemeral=True)
#     await cleanup_threads()
#     await interaction.followup.send("Cleanup ran!", ephemeral=True)


bot.run(token, log_handler=handler, log_level=logging.DEBUG)