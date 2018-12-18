import discord
import os.path
import os

from .utils.dataIO import dataIO
from discord.ext import commands

class Test:
    """My custom cog that does stuff!"""

    transactionLog = {}

    def __init__(self, bot):
        self.bot = bot
        self.check_configs()
        

    async def on_ready(self):
        global transactionLog
        try:
            with open('transactionLog.json') as f:
                transactionLog = json.load(f)
        except:
            transactionLog = {}
        

    @commands.command()
    async def mycom(self):
        """This does stuff!"""

        #Your code will go here
        await self.bot.say("I can do stuff!")

    @commands.command()
    async def punch(self, user : discord.Member):
        """I will punch anyone! >.<"""

        await self.bot.say("ONE PUNCH! And " + user.mention + " is out! ლ(ಠ益ಠლ)")

    @commands.command(pass_context=True)
    async def draft(self, ctx, user : discord.Member, teamRole : discord.Role):
        await self.bot.add_roles(user, teamRole)
        server = ctx.message.server
        channel = transactionLog[server.id]
        await self.bot.say(server.get_channel(channel), user.mention + " was drafted onto the " + teamRole)

    @commands.command(pass_context=True)
    async def setTransactionLogChannel(self, ctx, tlog:discord.Channel):
        """Sets transaction-log channel"""
        transactionLog[ctx.message.server.id] = tlog.id
        await self.bot.say("Transaction Log channel set")
        with open('transactionLog.json', 'w+') as f:
            json.dump(transactionLog, f)

def setup(bot):
    bot.add_cog(Test(bot))