import asyncio

import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
from dotenv import load_dotenv
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from gsheets_helper import (
    parse_shift_date,
    parse_time_range,
    resolve_full_shift,
    resolve_partial_shift,
    create_shift_thread,
    find_row_by_threadid,
)
from name_mappings  import get_assignee_name, set_assignee_name
from schedule_helper import build_daily_schedule_embed, write_daily_dynamic_schedule
import re
import os

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

SCHEDULE_CHANNEL_ID = os.getenv("SCHEDULE_CHANNEL_ID")
LOCAL_TZ = ZoneInfo("America/New_York")
DAILY_POST_TIME = dtime(hour=8, minute=0, tzinfo=LOCAL_TZ)

_schedule_message = None
_schedule_message_date = None

bot = commands.Bot(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    post_daily_schedule.start()
    # cleanup_threads.start()


# Task: posts the daily schedule embed to SCHEDULE_CHANNEL_ID once a day at
# DAILY_POST_TIME, and remembers the message so refresh_schedule_message()
# can edit it in place as coverage changes come in throughout the day.
@tasks.loop(time=DAILY_POST_TIME)
async def post_daily_schedule():
    global _schedule_message, _schedule_message_date
 
    if not SCHEDULE_CHANNEL_ID:
        print("SCHEDULE_CHANNEL_ID not set — skipping daily schedule post.")
        return
 
    channel = bot.get_channel(int(SCHEDULE_CHANNEL_ID))
    if channel is None:
        print(f"Couldn't find channel {SCHEDULE_CHANNEL_ID} for daily schedule post.")
        return
 
    today = datetime.now(LOCAL_TZ)
    embed = await asyncio.to_thread(build_daily_schedule_embed, today)
    _schedule_message = await channel.send(embed=embed)
    _schedule_message_date = today.date()
    await asyncio.to_thread(write_daily_dynamic_schedule, today)
 
@post_daily_schedule.before_loop
async def before_post_daily_schedule():
    await bot.wait_until_ready()
 
 
async def refresh_schedule_message():
    """
    If today's auto-posted schedule message is still live, edit it with a
    freshly built embed so coverage changes show up right away instead of
    waiting for tomorrow's post. No-ops if nothing's been posted yet today.
    """
    global _schedule_message, _schedule_message_date
 
    if _schedule_message is None or _schedule_message_date != datetime.now(LOCAL_TZ).date():
        return
 
    embed = await asyncio.to_thread(build_daily_schedule_embed, datetime.now(LOCAL_TZ))
    try:
        await _schedule_message.edit(embed=embed)
    except discord.NotFound:
        _schedule_message = None
        _schedule_message_date = None


async def sync_daily_schedule():
    """
    Single entry point for both dynamic-schedule outputs: rewrites the
    Coverage tab's row block (always), and refreshes the posted embed if
    today's is still up (via refresh_schedule_message's own check).
    Called after /coverage, /resolve, and as part of the daily post.
    """
    await asyncio.to_thread(write_daily_dynamic_schedule, datetime.now(LOCAL_TZ))
    await refresh_schedule_message()

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
    await sync_daily_schedule()
# Slash command to register your Discord account -> preferred name mapping.
# DM-only: this is a personal setting, not something that belongs in a
# server channel.
@bot.tree.command(name="register", description="DM only: set the name used for shift coverage credit")
@app_commands.describe(name="Your preferred name, as it should appear in the coverage sheet")
async def register(interaction: discord.Interaction, name: str):
    if interaction.guild is not None:
        await interaction.response.send_message(
            "❌ This command only works in a DM with me, not in a server. "
            "Send me a direct message and run `/register` there.",
            ephemeral=True,
        )
        return

    await asyncio.to_thread(set_assignee_name, interaction.user.id, name)
    await interaction.response.send_message(
        f"✅ Got it — you're registered as **{name}**. This is the name that'll show up when you cover a shift.",
        ephemeral=True,
    )




@bot.tree.command(name="schedule", description="DM only: view a day's shift schedule with live coverage status")
@app_commands.describe(date="Optional: MM/DD date to view (defaults to today)")
async def schedule(interaction: discord.Interaction, date: str = None):
    if interaction.guild is not None:
        await interaction.response.send_message(
            "❌ This command only works in a DM with me, not in a server. "
            "Send me a direct message and run `/schedule` there.",
            ephemeral=True,
        )
        return
 
    target_date = datetime.now(LOCAL_TZ)
    if date is not None:
        parsed = parse_shift_date(date)
        if parsed is None:
            await interaction.response.send_message(
                "❌ Invalid date format. Please use MM/DD (e.g., 09/15).", ephemeral=True
            )
            return
        target_date = target_date.replace(month=parsed.month, day=parsed.day)
 
    # Defer: building this reads two Sheets tabs, which can exceed
    # Discord's 3-second response window.
    await interaction.response.defer()
    await asyncio.to_thread(write_dynamic_schedule, target_date)
    embed = await asyncio.to_thread(
        build_daily_schedule_embed,
        target_date
    )
    await interaction.followup.send(embed=embed)
 


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

    assignee_id = get_assignee_name(interaction.user.id)
    if not assignee_id:
        await interaction.response.send_message(
            f"❌ {interaction.user.display_name} isn't registered yet. DM me `/register` to set your name.",
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

        await sync_daily_schedule()
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

@bot.tree.command(name="refresh_schedule", description="Manually rewrite today's dynamic schedule (Coverage tab rows 4-16)")
@app_commands.describe(date="Optional: MM/DD date to write (defaults to today)")
async def refresh_schedule(interaction: discord.Interaction, date: str = None):
    target_date = datetime.now(LOCAL_TZ)
    if date is not None:
        parsed = parse_shift_date(date)
        if parsed is None:
            await interaction.response.send_message(
                "❌ Invalid date format. Please use MM/DD (e.g., 09/15).", ephemeral=True
            )
            return
        target_date = target_date.replace(month=parsed.month, day=parsed.day)
 
    await interaction.response.defer(ephemeral=True)
    rows = await asyncio.to_thread(write_daily_dynamic_schedule, target_date)
    await interaction.followup.send(
        f"✅ Rewrote the dynamic schedule for {target_date.strftime('%m/%d')} — {len(rows)} row(s).",
        ephemeral=True,
    )



bot.run(token, log_handler=handler, log_level=logging.DEBUG)