import discord
from discord.ext import commands, tasks
import logging
from dotenv import load_dotenv
from datetime import datetime
from notion_client import Client
from notion_helper import get_data_source_id, get_calendar_entries
from notion_helper import get_shifts_needing_coverage, get_todays_shifts
from notion_helper import create_notion_event, parse_time_range, resolve_partial_shift
from discord_to_notion import DISCORD_TO_NOTION
import re
import asyncio
import os

load_dotenv()
token = os.getenv('DISCORD_TOKEN')
notion = Client(auth=os.getenv("NOTION_TOKEN"))
database_id = os.getenv('NOTION_DATABASE_ID')

handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
intents = discord.Intents.default()
intents.message_content = True
intents.members = True



bot = commands.Bot(command_prefix='!', intents=intents)
#hello
@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')
    cleanup_threads.start()

# Task to clean up old threads every 2 hours
@tasks.loop(hours=2)
async def cleanup_threads():
    for guild in bot.guilds:
        for channel in guild.text_channels:
            for thread in channel.threads:
                try:
                    parts = thread.name.split(" ")
                    date_str = parts[1]
                    month, day = map(int, date_str.split("/"))
                    year = datetime.now().year
                    thread_date = datetime(year, month, day)

                    if datetime.now() > thread_date:
                        await thread.send("This coverage shift has passed. Closing thread...", silent=True)
                        await thread.delete()
                except Exception as e:
                    print(f"Skipping thread '{thread.name}': {e}")

@cleanup_threads.before_loop
async def before_cleanup():
    await bot.wait_until_ready()


#helper function to parse date
def parse_shift_date(date: str):
    """Returns a datetime.date if valid MM/DD, else None."""
    try:
        # %m/%d parses month/day; year defaults to 1900 but we don't care about it here
        parsed = datetime.strptime(date, "%m/%d")
        return parsed
    except ValueError:
        return None
    
# Command to create a coverage thread
# !coverage 
@bot.command()
async def coverage(ctx, day: str, date: str, time: str, *, location: str):
    parsed_date = parse_shift_date(date)
    if day.lower() not in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
        await ctx.send("Invalid day. Please use a valid weekday (e.g., Monday, Tuesday).")
        return
    elif parsed_date is None:
        await ctx.send("Invalid date format. Please use MM/DD format (e.g., 09/15).")
        return
    elif location.lower() not in ["csl", "hackerspace"]:
        await ctx.send("Invalid location. Please specify either 'CSL' or 'Hackerspace'.")
        return
    

    thread_name = f"{day} {date} {time} in {location}"
    thread = await ctx.channel.create_thread(
        name=thread_name,
        type=discord.ChannelType.public_thread
    )
    await ctx.message.delete()  # delete the original command message for cleanliness
    await asyncio.to_thread(create_notion_event, day, date, time, location)


@bot.command(name="resolve")
async def resolve(ctx, time: str = None):
    """
    !resolve            -> resolves the entire shift, closes thread
    !resolve 7-8pm      -> resolves only that portion, closes thread
    """
    if not isinstance(ctx.channel, discord.Thread):
        await ctx.send("This command can only be used inside a thread.")
        return
    
    notion_user_id = DISCORD_TO_NOTION.get(ctx.author.id)
    if not notion_user_id:
        await ctx.send(f"❌ {ctx.author.display_name} isn't mapped to a Notion account. Ask an admin to add you.")
        return

    # Parse thread name: "{day} {date} {time} in {location}"
    match = re.match(r"^(\S+)\s+(\S+)\s+(.+?)\s+in\s+(.+)$", ctx.channel.name)
    if not match:
        await ctx.send("❌ Couldn't parse shift info from thread name.")
        return

    day, date, full_time, location = match.groups()
    parent_channel = ctx.channel.parent  # thread's parent text channel

    # Find the matching Notion page for this shift
    entries = get_calendar_entries()
    target_entry = None
    for entry in entries:
        name = entry["properties"]["Name"]["title"][0]["text"]["content"]
        if name == ctx.channel.name:
            target_entry = entry
            break

    if not target_entry:
        await ctx.send("❌ Couldn't find matching shift in Notion.")
        return

    page_id = target_entry["id"]

    try:
        if time is None:
            # FULL RESOLVE
            notion.pages.update(page_id=page_id, archived=True)
            create_notion_event(day, date, full_time, location, status="Covered", assignee_id=notion_user_id)
            await ctx.send("✅ Shift fully covered! Closing thread...", silent=True)
        else:
            remainder_times = resolve_partial_shift(page_id, day, date, full_time, time, location, assignee_id=notion_user_id)
            # PARTIAL RESOLVE
            
            for remainder_time in remainder_times:
                print(f"Remainder times after resolving {time}: {remainder_times}")
                new_thread_name = f"{day} {date} {remainder_time} in {location}"
                await parent_channel.create_thread(
                    name=new_thread_name,
                    type=discord.ChannelType.public_thread
                )
            await ctx.send(f"✅ {time} covered, remaining time still needs coverage. Closing thread...", silent=True)

        await ctx.channel.delete()

    except ValueError as e:
        await ctx.send(f"❌ {e}")

# Command to clear the channel (for testing purposes)
@bot.command()
async def clear(ctx):
    await ctx.channel.purge(limit=100)
# Command to manually trigger cleanup (for testing purposes)
@bot.command()
async def test_cleanup(ctx):
    await cleanup_threads()
    await ctx.send("Cleanup ran!")

bot.run(token, log_handler=handler, log_level=logging.DEBUG)

