# Automatic shift reminders using Google Sheets schedule
import discord 
from discord.ext import commands, tasks
from datetime import datetime
from schedule import get_current_shift, get_current_hackerspace_shift

# Role IDs for each location 
CSL_ON_SHIFT_ROLE_ID = 1529576268310515867      
HACKERSPACE_ON_SHIFT_ROLE_ID = 1542189739837493258

# Maps names from Google Sheet to Discord IDs
NAME_TO_DISCORD = {       
    "Mymuna": 723224915528122448, #temp for now, should make it so people can input it through discord command 
    "Martin": 588546731088805902, 
}

# Shift transition times (includes 23:00 for closing checks)
CHECK_TIMES = ["10:00", "11:30", "13:00", "15:00", "17:00", "19:00", "21:00", "23:00"]
HACKERSPACE_START_TIMES = ["13:00", "15:00"]

class Reminders(commands.Cog): 
    def __init__(self, bot):
        self.bot = bot
        self.on_shift = {}
        self.current_csl_users = []
        self.current_hackerspace_user = None
        self.check_shifts.start()

    def cog_unload(self):
        self.check_shifts.cancel()

    @tasks.loop(minutes=1)
    async def check_shifts(self):
        now = datetime.now()
        # Only run Monday-Friday
        if now.weekday() >= 5:
            return
        
        current_time = now.strftime("%H:%M")

        if current_time not in CHECK_TIMES:
            return

        channel = discord.utils.get(self.bot.get_all_channels(), name="bot-testing")
        if not channel:
            return

        guild = channel.guild
        csl_role = guild.get_role(CSL_ON_SHIFT_ROLE_ID)
        hs_role = guild.get_role(HACKERSPACE_ON_SHIFT_ROLE_ID)

        # -------------------------------------------------------------
        # CSL SHIFT HANDLING
        # -------------------------------------------------------------
        csl_names = get_current_shift()  # Fetch people on shift right now

        # Track if the previous slot had active workers
        was_empty = len(self.current_csl_users) == 0

        # 1. Handle Outgoing Shift (End of Shift / Closing)
        if self.current_csl_users:
            prev_mentions = " ".join([f"<@{uid}>" for uid in self.current_csl_users])
            
            # Remove on-shift role from outgoing members
            for prev_user_id in self.current_csl_users:
                prev_member = guild.get_member(prev_user_id)
                if prev_member and csl_role:
                    await prev_member.remove_roles(csl_role)

            # If nobody is scheduled now (or if it's closing time), run closing check
            if not csl_names or current_time == "23:00" or (now.weekday() == 4 and current_time == "17:00"):
                await channel.send(
                    f"{prev_mentions} Your CSL shift has ended! "
                    f"Please submit your **final headcount update** and do a **closing check on the iLab machines**."
                )
            else:
                # Regular shift end
                await channel.send(
                    f"{prev_mentions} Your CSL shift has ended! Please submit your **headcount update** before leaving."
                )

        # Reset stored user IDs
        self.current_csl_users = []
        pings = []

        # 2. Handle Incoming Shift (Start of Shift / Opening)
        if current_time != "23:00" and csl_names:
            for name in csl_names:
                user_id = NAME_TO_DISCORD.get(name)
                if user_id:
                    member = guild.get_member(user_id)
                    if member and csl_role:
                        await member.add_roles(csl_role)
                    self.current_csl_users.append(user_id)
                    pings.append(f"<@{user_id}>")

            if pings:
                mentions = " ".join(pings)
                # Opening if 10:00 AM or if no one was on shift in the previous slot
                is_opening = (current_time == "10:00") or was_empty

                if is_opening:
                    await channel.send(
                        f"{mentions} Welcome! Your CSL opening shift has started. "
                        f"Please perform a **room check** and **check the iLab machines**."
                    )
                else:
                    await channel.send(
                        f"{mentions} Your CSL shift has started! Please perform a **room check**."
                    )

        # -------------------------------------------------------------
        # HACKERSPACE SHIFT HANDLING
        # -------------------------------------------------------------
        if current_time in HACKERSPACE_START_TIMES or current_time == "17:00":
            hs_name = get_current_hackerspace_shift()

            # End of previous Hackerspace shift
            if self.current_hackerspace_user:
                prev_member = guild.get_member(self.current_hackerspace_user)
                if prev_member and hs_role:
                    await prev_member.remove_roles(hs_role)
                await channel.send(f"<@{self.current_hackerspace_user}> Your Hackerspace shift has ended!")
                self.current_hackerspace_user = None

            # Start of new Hackerspace shift
            if hs_name and current_time in HACKERSPACE_START_TIMES:
                user_id = NAME_TO_DISCORD.get(hs_name)
                if user_id:
                    member = guild.get_member(user_id)
                    if member and hs_role:
                        await member.add_roles(hs_role)
                    self.current_hackerspace_user = user_id
                    await channel.send(f"<@{user_id}> Your Hackerspace shift has started!")

    @check_shifts.before_loop
    async def before_check_shifts(self):
        await self.bot.wait_until_ready()

    @commands.command()
    async def onshift(self, ctx): 
        self.on_shift["current"] = ctx.author.id
        role = ctx.guild.get_role(CSL_ON_SHIFT_ROLE_ID)
        if role:
            await ctx.author.add_roles(role)
        await ctx.send(f"{ctx.author.mention} is now on shift.")
        await self.send_roomcheck_ping(ctx.channel)

    @commands.command()
    async def offshift(self, ctx):
        if self.on_shift.get("current") == ctx.author.id:
            await self.send_headcount_ping(ctx.channel)
            role = ctx.guild.get_role(CSL_ON_SHIFT_ROLE_ID)
            if role:
                await ctx.author.remove_roles(role)
            self.on_shift.pop("current")
            await ctx.send(f"{ctx.author.mention} has ended their shift.")
        else:
            await ctx.send(f"{ctx.author.mention} is not currently on shift.")

    async def get_current_shift_users(self):
        names = get_current_shift()
        user_ids = []
        for name in names:
            uid = NAME_TO_DISCORD.get(name)
            if uid:
                user_ids.append(uid)
        return user_ids

    async def send_headcount_ping(self, channel):
        user_ids = await self.get_current_shift_users()
        if user_ids: 
            mentions = " ".join([f"<@{uid}>" for uid in user_ids])
            await channel.send(f"{mentions} Please submit your headcount update.")
    
    async def send_roomcheck_ping(self, channel):
        user_ids = await self.get_current_shift_users()
        if user_ids:
            mentions = " ".join([f"<@{uid}>" for uid in user_ids])
            await channel.send(f"{mentions} Please perform a room check.")

async def setup(bot): 
    await bot.add_cog(Reminders(bot))