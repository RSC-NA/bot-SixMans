import collections
import datetime
import logging
import uuid
import struct
from queue import Queue
from typing import List
from .strings import Strings
from .game import Game
import string
import random
import copy
from .strings import Strings
from .views import GameMode

log = logging.getLogger("red.RSC6Mans.sixMans.queue")

import discord

SELECTION_MODES = {
    0x1F3B2: Strings.RANDOM_TS,  # game_die
    0x1F1E8: Strings.CAPTAINS_TS,  # C
    0x0262F: Strings.BALANCED_TS,  # yin_yang
    0x1F530: Strings.SELF_PICKING_TS,  # beginner
    0x1F5F3: Strings.VOTE_TS,  # ballot_box
}


# JOB: When queue is full, create a game object and return it
# Reset the queue
# TODO: Logic of people joining. Could be implimented somewhere else. Need to investigate.
class SixMansQueue:
    def __init__(
        self,
        text_channel: discord.TextChannel,
        maxSize=6,
        helper_role: discord.Role = None,
        automove: bool = False,
        # Discord members have the same functionality as discord users, but with server specific information.
        # Only difference is the members avatar is the server specific avatar, while the users avatar is the global avatar.
    ):
        #Will move to game
        self.name = self.make_name()
        self.id = uuid.uuid4().int
        self.teamSelection: GameMode = GameMode.VOTE
        self.players: List[discord.Member] = []
        self.maxSize = maxSize
        self.helper_role = helper_role
        self.automove = automove
        self.text_channel: discord.TextChannel = text_channel
        self.points = 0

        #Wont bring to game
        self.guild = text_channel.guild
        self.gamesPlayed = 0
        self.category = text_channel.category
        

        self.activeJoinLog = {}
        # TODO: active join log could maintain queue during downtime

    def make_name(self):
        """
        Generates a random name from a predefined list of words.

        Returns:
            str: A randomly chosen name.
        """
        lAndD = [
            "apple",
            "book",
            "chair",
            "desk",
            "egg",
            "fish",
            "goat",
            "hand",
            "idea",
            "jump",
            "king",
            "lake",
            "moon",
            "nose",
            "open",
            "park",
            "queen",
            "rock",
            "star",
            "tree",
            "under",
            "vase",
            "wolf",
            "x-ray",
            "year",
            "zoo",
            "aunt",
            "bird",
            "cloud",
            "duck",
            "earth",
            "frog",
            "gift",
            "hill",
            "inch",
            "juice",
            "kite",
            "lion",
            "mango",
            "note",
            "owl",
            "peach",
            "quilt",
            "rain",
            "sun",
            "tiger",
            "umbra",
            "vest",
            "wind",
            "box",
            "cat",
            "dog",
            "eel",
            "fox",
            "gold",
            "hat",
            "ice",
            "joke",
            "key",
            "lamb",
            "mice",
            "nest",
            "oak",
            "pine",
            "queen",
            "rose",
            "seed",
            "tent",
            "urge",
            "vine",
            "wave",
            "xerox",
            "yoga",
            "zebra",
            "apple",
            "bear",
            "cake",
            "deer",
            "egg",
            "girl",
            "hat",
            "ink",
            "joke",
            "kite",
            "lamp",
            "moon",
            "nest",
            "oar",
            "park",
            "herp",
            "derp",
            "quilt",
        ]
        name = random.choice(lAndD)
        return name

    def _put(self, player):
        """
        Add a player to the queue.

        Args:
            player (Player): The player to be added to the queue.

        Returns:
            Game or None: If the queue is full after adding the player, returns a new Game object. Otherwise, returns None.
        """
        # we'll add a player then check if the queue is full. Will never add a player if the queue is full.
        self.players.append(player)
        # self.activeJoinLog[player.id] = datetime.datetime.now()
        if self._queue_full():
            game = Game(
                name = self.name,
                id = self.id,
                teamSelection = self.teamSelection,
                players = self.players,
                MaxSize = self.maxSize,
                helper_role = self.helper_role,
                automove = self.automove,
                text_channel = self.text_channel,
                points = self.points,
            )
            self.players.clear()
            return game
        else:
            return None

    def __str__(self):
        """
        Returns a string representation of the Queue object.

        The string contains the mentions of all the players in the queue, separated by commas.
        """
        return ", ".join(player.mention for player in self.players)

    def _get(self):
        """
        Retrieves and removes a player from the queue.

        Returns:
            Player: The player object that was removed from the queue.
        """
        player = self.players.pop(self.players.__len__ - 1)
        try:
            del self.activeJoinLog[player.id]
        except:
            pass
        return player

    def get_player_summary(self, player: discord.User):
        """
        Retrieves the player summary from the player database.

        Args:
            player (discord.User): The Discord user object representing the player.

        Returns:
            dict or None: The player summary if found in the database, None otherwise.
        """
        try:
            return self.player[str(player.id)]
        except:
            return None

    def _remove(self, player: discord.User):
        """
        Removes a player from the queue.

        Args:
            player (discord.User): The player to be removed.

        Returns:
            None
        """
        if player in self.players:
            self.players.remove(player)
        try:
            del self.activeJoinLog[player.id]
        except:
            pass

    def _queue_full(self):
        """
        Check if the queue is full.

        Returns:
            bool: True if the queue is full, False otherwise.
        """
        return self.players.__len__ >= self.maxSize

    async def send_message(self, message="", embed=None):
        """
        Sends a message to all the channels in the queue.

        Args:
            message (str): The message to send (default is an empty string).
            embed (discord.Embed): The embed to send (default is None).

        Returns:
            list: A list of messages sent to each channel.
        """
        messages = []
        for channel in self.channels:
            messages.append(await channel.send(message, embed=embed))
        return messages

    async def set_team_selection(self, team_selection):
        """
        Sets the team selection for the queue.

        Parameters:
        - team_selection (str): The team selection to be set.

        Returns:
        None
        """
        self.teamSelection = team_selection
        emoji = self.get_ts_emoji()
        if emoji:
            await self.send_message(
                f"Queue Team Selection has been set to {emoji} **{team_selection}**."
            )
        else:
            await self.send_message(
                f"Queue Team Selection has been set to **{team_selection}**."
            )

    def _get_pick_reaction(self, int_or_hex):
        """
        Converts an integer or hexadecimal value to a corresponding UTF-32LE encoded string.

        Args:
            int_or_hex (int or str): The integer or hexadecimal value to convert.

        Returns:
            str: The UTF-32LE encoded string representation of the input value, or None if conversion fails.
        """
        try:
            if type(int_or_hex) == int:
                return struct.pack("<I", int_or_hex).decode("utf-32le")
            if type(int_or_hex) == str:
                return struct.pack("<I", int(int_or_hex, base=16)).decode("utf-32le")
        except:
            return None

    def _to_dict(self):
        """
        Converting Name, Channels, Points, Players, GamesPlayed, TeamSelection, and MaxSize of the queue
            object into to a dictionary.

        Returns:
            dict: A dictionary representation of the queue object's Name, Channels, Points, Players, GamesPlayed, TeamSelection, and MaxSize.
        """
        q_data = {
            "Name": self.name,
            "Channels": [x.id for x in self.channels],
            "Points": self.points,
            "Players": self.players,
            "GamesPlayed": self.gamesPlayed,
            "TeamSelection": self.teamSelection,
            "MaxSize": self.maxSize,
        }
        if self.category:
            q_data["Category"] = self.category.id
        if self.lobby_vc:
            q_data["LobbyVC"] = self.lobby_vc.id

        return q_data

    def has_player(self, player):
        """
        Check if a player is in the queue.

        Args:
            player: The player to check.

        Returns:
            True if the player is in the queue, False otherwise.
        """
        return player in self.players

    def __contains__(self, player):
        """
        Check if a player is in the queue.

        Args:
            item: The player to check.

        Returns:
            True if the player is in the queue, False otherwise.
        """
        return player in self.players

    def __iter__(self):
        """
        Returns an iterator object that iterates over the elements in the queue.
        """
        return iter(self.players)

    def __len__(self):
        """
        Returns the length of the queue.
        """
        return len(self.players)

    def __eq__(self, sel):
        """
        Check if the queue is equal to another object.

        Args:
            sel: The object to compare with.

        Returns:
            True if the queue is equal to the other object, False otherwise.
        """
        return (
            (self.name == sel.name)
            and (self.channels == sel.channels)
            and (self.points == sel.points)
            and (self.players == sel.players)
            and (self.gamesPlayed == sel.gamesPlayed)
            and (self.teamSelection == sel.teamSelection)
            and (self.maxSize == sel.maxSize)
            and (self.category == sel.category)
            and (self.lobby_vc == sel.lobby_vc)
        )

    async def makeGame(self):
        """
        Creates a new game instance with the current queue information.

        Returns:
            Game: The newly created game instance.
        """
        return Game(
            self.name,
            self.id,
            self.players,
            self.playerDB,
            self.points,
            self.text_channel,
            self.teamSelection,
            self.maxSize,
        )

    async def makeGame(self):
        return Game(
            self.name,
            self.id,
            self.players,
            self.playerDB,
            self.points,
            self.text_channel,
            self.teamSelection,
            self.maxSize,
        )
