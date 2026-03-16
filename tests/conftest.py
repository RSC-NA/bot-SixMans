"""Shared fixtures for six mans tests.

Provides mock Discord objects (Members, TextChannels, Interactions, etc.)
and lightweight fake Game/Queue objects for testing views in isolation.
"""

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import discord
import pytest


# ---------------------------------------------------------------------------
# Discord mock helpers
# ---------------------------------------------------------------------------


def make_member(name: str, id: int) -> MagicMock:
    """Create a mock discord.Member with the given name and id."""
    member = MagicMock(spec=discord.Member)
    member.name = name
    member.id = id
    member.mention = f"<@{id}>"
    member.display_name = name
    # Make it hashable so it can be used as dict key / in sets
    member.__hash__ = lambda self: hash(id)
    member.__eq__ = lambda self, other: getattr(other, "id", None) == id
    return member


def make_interaction(user: MagicMock, data: dict | None = None) -> MagicMock:
    """Create a mock discord.Interaction for a given user."""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = user
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.response = AsyncMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.data = data or {}
    return interaction


def make_text_channel() -> MagicMock:
    """Create a mock discord.TextChannel."""
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    channel.name = "test-6mans-channel"
    msg = MagicMock(spec=discord.Message)
    msg.edit = AsyncMock()
    channel.send.return_value = msg
    return channel


# ---------------------------------------------------------------------------
# Fake game / queue for view tests
# ---------------------------------------------------------------------------


class FakeQueue:
    """Minimal queue-like object for view tests."""

    def __init__(self, guild=None):
        self.guild = guild or MagicMock(spec=discord.Guild)
        self.guild.icon = None
        self.players = {}
        self.gamesPlayed = 0
        self.name = "Test Queue"


class FakeGame:
    """Minimal game-like object that views expect."""

    def __init__(self, players: list[MagicMock], captains: list[MagicMock] | None = None):
        self.players = set(players)
        self.captains = captains or list(players[:2])
        self.textChannel = make_text_channel()
        self.helper_role = None
        self.queue = FakeQueue()
        self.id = "test-game-id"


# ---------------------------------------------------------------------------
# Reusable fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def players():
    """Six mock players for a standard 6-mans game."""
    return [make_member(f"Player{i}", i) for i in range(1, 7)]


@pytest.fixture
def captains(players):
    """First two players as captains."""
    return [players[0], players[1]]


@pytest.fixture
def game(players, captains):
    """A FakeGame with 6 players and 2 captains."""
    return FakeGame(players=players, captains=captains)
