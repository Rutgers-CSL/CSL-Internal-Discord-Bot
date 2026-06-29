import discord
from discord.ext import commands, tasks
import logging
from dotenv import load_dotenv
from datetime import datetime
from notion_client import Client
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
    await bot.load_extension("reminders") 
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


def create_notion_event(day, date, time, location):
    notion.pages.create(
        parent={"database_id": database_id},
        properties={
            "Name": {"title": [{"text": {"content": f"{day} {date} {time} in {location}"}}]},
            "Date": {"date": {"start": f"2026-{date.replace('/', '-')}"}},
            "Location": {"select": {"name": location}},
        }
    )



# Command to create a coverage thread
# !coverage 
@bot.command()
async def coverage(ctx, day: str, date: str, time: str, *, location: str):
    if day.lower() not in ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]:
        await ctx.send("Invalid day. Please use a valid weekday (e.g., Monday, Tuesday).")
        return
    elif date.count("/") != 1:
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
    await asyncio.to_thread(create_notion_event, day, date, time, location)
    await ctx.send("Event added to Notion calendar!", silent=True)

# Command to resolve a thread (close it)
@bot.command()
async def resolve(ctx):
    if isinstance(ctx.channel, discord.Thread):
        await ctx.send("Thread resolved! Closing...", silent=True)
        await ctx.channel.delete()
    else:
        await ctx.send("This command can only be used inside a thread.")

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

