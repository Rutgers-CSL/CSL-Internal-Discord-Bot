# Currently a temporary manual solution, will be replaced/connected with notion later 
import discord 
from discord.ext import commands, tasks 

ON_SHIFT_ROLE_ID = 1529576268310515867

# Cog = a way to organize bot commands in a separate file from main.py
# This connects to the bot defined in main.py via load_extension("reminders") 
class Reminders(commands.Cog): 
    # Runs automatically when the Cog is created
    # Sets up the bot and an empty dictionary to store who's on shift
    def __init__(self, bot):
        self.bot = bot
        self.on_shift = {}

    # Command: !onshift
    # Run by the person starting their shift to register themselves
    # Stores their Discord ID so the bot knows who to ping for reminders
    @commands.command()
    async def onshift(self, ctx): 
        self.on_shift["current"] = ctx.author.id
        
        # Add the On Shift role
        role = ctx.guild.get_role(ON_SHIFT_ROLE_ID)
        if role:
            await ctx.author.add_roles(role)

        await ctx.send(f"{ctx.author.mention} is now on shift.")
        await self.send_headcount_ping(ctx.channel) # Manual for now 
        await self.send_roomcheck_ping(ctx.channel) # Manual for now

    # Command: !offshift
    # Run by the person ending their shift to unregister themselves
    # Removes the On Shift role and clears current shift user
    @commands.command()
    async def offshift(self, ctx):
        if self.on_shift.get("current") == ctx.author.id:
            await self.send_headcount_ping(ctx.channel) # Manual for now 
            await self.send_roomcheck_ping(ctx.channel) # Manual for now
            
            # Remove the On Shift role
            role = ctx.guild.get_role(ON_SHIFT_ROLE_ID)
            if role:
                await ctx.author.remove_roles(role)

            self.on_shift.pop("current")
            await ctx.send(f"{ctx.author.mention} has ended their shift.")
        else:
            await ctx.send(f"{ctx.author.mention} is not currently on shift.")

    # Temporary: reads from manual command
    # Will be replaced with Notion later
    async def get_current_shift_user(self):
        return self.on_shift.get("current")
    
    # Sends the headcount reminder ping to the person currently on shift 
    async def send_headcount_ping(self, channel):
        user_id = await self.get_current_shift_user()
        if user_id: 
            await channel.send(f"<@{user_id}> Please provide a headcount update.")
    
    # Sends the room check reminder ping to the person currently on shift 
    async def send_roomcheck_ping(self, channel):
        user_id = await self.get_current_shift_user()
        if user_id:
            await channel.send(f"<@{user_id}> Please do a room check.")
    

# Required for main.py to load this file as an extension
async def setup(bot): 
    await bot.add_cog(Reminders(bot))

# TODO: Notion Automation
# The manual !onshift and !offshift commands are a temporary solution.
# In the future, this will be replaced with an automatic Notion integration.
#
# STEP 1: Replace get_current_shift_user() with a Notion query
#     async def get_current_shift_user(self):
#         # query Notion database for the person whose shift matches the current time
#         # return their Discord ID
#
# STEP 2: Replace !onshift and !offshift with a scheduled task that checks Notion
#
# NOTE: send_headcount_ping(), send_roomcheck_ping(), and get_current_shift_user() stay the same,
# only what triggers them changes (commands now, scheduled task later)
# This also applies to future ping tasks (tickets, vouchers, etc)