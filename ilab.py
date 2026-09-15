import requests 
from bs4 import BeautifulSoup
from discord.ext import commands 
import discord 

class Ilab(commands.Cog): 
    def __init__(self, bot): 
        self.bot = bot 


    # Fetches the Ilab machines page and checks for any machines that are down 
    @commands.command() 
    async def ilab(self, ctx): 
        # URLs for each room
        clusters = {
            "H248": "https://report.cs.rutgers.edu/cgi-bin/MachineStatus.pl?cluster=H248",
            "H252": "https://report.cs.rutgers.edu/cgi-bin/MachineStatus.pl?cluster=H252",
            "H254": "https://report.cs.rutgers.edu/cgi-bin/MachineStatus.pl?cluster=H254"
        }
        down_machines = {}

        for room, url in clusters.items():
            response = requests.get(url)
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Find all rows with criticalStatus in this table
            down_rows = soup.find_all("td", class_="criticalStatus")
            for row in down_rows:
                hostname = row.text.strip()
                if hostname and "." in hostname:
                    if room not in down_machines:
                        down_machines[room] = []
                    down_machines[room].append(hostname)
        
        # Format and send the message 
        if not down_machines: 
            await ctx.send("✅ All iLab machines are up and running!")
        else: 
            message = "🔴 Machines currently down:\n"
            for room, machines in down_machines.items():
                message += f"\n**{room}:**\n"
                for machine in machines: 
                    message += f"  • {machine}\n"
            await ctx.send(message)

async def setup(bot): 
    await bot.add_cog(Ilab(bot)) 