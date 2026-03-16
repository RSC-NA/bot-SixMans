import logging

import discord

log = logging.getLogger("red.sixMans.embeds")


class EmbedLimits:
    Total = 6000
    Title = 256
    Description = 4096
    Fields = 25

    class Field:
        Name = 256
        Value = 1024

    class Footer:
        Text = 2048

    class Author:
        Name = 256


class BetterEmbed(discord.Embed):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def valid_fields(self) -> bool:
        c = 0
        for field in self.fields:
            # Name
            if field.name:
                c += len(field.name)
                if len(field.name) > EmbedLimits.Field.Name:
                    return False

            # Value
            if field.value:
                c += len(field.value)
                if len(field.value) > EmbedLimits.Field.Value:
                    return False

        if c > EmbedLimits.Total:
            return False
        return True

    def total_field_chars(self) -> int:
        c = 0
        for f in self.fields:
            if f.name:
                c += len(f.name)
            if f.value:
                c += len(f.value)
        return c

    def exceeds_limits(self) -> bool:
        total_chars = 0

        # Title
        if self.title:
            total_chars += len(self.title)
            if len(self.title) > EmbedLimits.Title:
                return True

        # Description
        if self.description:
            total_chars += len(self.description)
            if len(self.description) > EmbedLimits.Description:
                return True

        # Field Count
        if len(self.fields) > EmbedLimits.Fields:
            return True

        # Fields
        for field in self.fields:
            # Name
            if field.name:
                total_chars += len(field.name)
                if len(field.name) > EmbedLimits.Field.Name:
                    return True

            # Value
            if field.value:
                total_chars += len(field.value)
                if len(field.value) > EmbedLimits.Field.Value:
                    return True

        # Footer
        if self.footer and self.footer.text:
            total_chars += len(self.footer.text)
            if len(self.footer.text) > EmbedLimits.Footer.Text:
                return True

        # Author
        if self.author and self.author.name:
            total_chars += len(self.author.name)
            if len(self.author.name) > EmbedLimits.Author.Name:
                return True

        # Total Characters
        if total_chars > EmbedLimits.Total:
            return True

        return False


class BlueEmbed(BetterEmbed):
    """Generic Blue Embed"""

    def __init__(self, **kwargs):
        super().__init__(color=discord.Color.blue(), **kwargs)


class YellowEmbed(BetterEmbed):
    """Generic Yellow Embed"""

    def __init__(self, **kwargs):
        super().__init__(color=discord.Color.yellow(), **kwargs)


class OrangeEmbed(BetterEmbed):
    """Generic Orange Embed"""

    def __init__(self, **kwargs):
        super().__init__(color=discord.Color.orange(), **kwargs)


class RedEmbed(BetterEmbed):
    """Generic Red Embed"""

    def __init__(self, **kwargs):
        super().__init__(color=discord.Color.red(), **kwargs)


class GreenEmbed(BetterEmbed):
    """Generic Green Embed"""

    def __init__(self, **kwargs):
        super().__init__(color=discord.Color.green(), **kwargs)


class LoadingEmbed(YellowEmbed):
    """Generic Loading Embed"""

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "Processing")
        super().__init__(title=title, description="Working on your request. Please wait...", **kwargs)


class SuccessEmbed(GreenEmbed):
    """Generic Success Embed"""

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "Success")
        super().__init__(title=title, **kwargs)


class ErrorEmbed(RedEmbed):
    """Generic Error Embed"""

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "Error")
        super().__init__(title=title, **kwargs)


class WarningEmbed(OrangeEmbed):
    """Generic Warning Embed"""

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "Error")
        super().__init__(title=title, **kwargs)


class CooldownEmbed(YellowEmbed):
    """Generic Cooldown Embed"""

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "Error")
        desc = kwargs.pop(
            "description",
            "This command has a cool down period. Please wait a bit before trying again...",
        )
        super().__init__(title=title, description=desc, **kwargs)


class QueueNotFoundEmbed(ErrorEmbed):
    def __init__(self, name: str, **kwargs):
        title = kwargs.pop("title", "Error")
        desc = f"No queue found with name: **{name}**"
        super().__init__(title=title, description=desc, **kwargs)


class ExceptionErrorEmbed(RedEmbed):
    """Generic Error Embed"""

    def __init__(self, exc_message: str, **kwargs):
        title = kwargs.pop("title", "Error")
        super().__init__(title=title, description=exc_message, **kwargs)


class NotImplementedEmbed(RedEmbed):
    def __init__(self, **kwargs):
        super().__init__(
            title="Not Implemented",
            description="Command has not been implemented yet.",
            **kwargs,
        )
