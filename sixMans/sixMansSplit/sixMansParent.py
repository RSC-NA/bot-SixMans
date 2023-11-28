import asyncio
import discord

from sys import exc_info, maxsize
from typing import Dict, List

#redbot imports
from redbot.core import Config, commands

#sixmans imports
from sixMans.sixMansSplit.functions import *
from sixMans.game import Game
from sixMans.queue import SixMansQueue


#Class that will hold all of the variables that are needed for the sixmans cog
class SixMansParent(commands.Cog):
    def __init__(self, bot):
        """
        Initializes the SixMans class.

        Args:
            bot (discord.ext.commands.Bot): The bot instance.

        Attributes:
            bot (discord.ext.commands.Bot): The bot instance.
            config (Config): The configuration object.
            queues (dict[dict[SixMansQueue]]]): A nested dictionary of queues.
            games (dict[list[Game]]): A dictionary of games.
            queueMaxSize (dict[int]): A dictionary of maximum queue sizes.
            player_timeout_time (dict[int]): A dictionary of player timeout times.
            queues_enabled (dict[bool]): A dictionary of queue enable statuses.
            timeout_tasks (dict): A dictionary of timeout tasks.
            observers (set): A set of observers.
        """
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=1234567896, force_registration=True
        )
        self.config.register_guild(**defaults)
        self.queues: dict[dict[SixMansQueue]] = {} # [guild_id][channel_id] will give the SixMansQueue
        self.games: dict[dict[Game]] = {} # [guild_id][channel_id] will give the Game
        self.queueMaxSize: dict[int] = {}
        self.player_timeout_time: dict[int] = {}
        self.queues_enabled: dict[bool] = {}

        asyncio.create_task(self._pre_load_data())
        self.timeout_tasks = {}