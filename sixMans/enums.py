from enum import StrEnum


class Winner(StrEnum):
    ORANGE = "orange"
    BLUE = "blue"
    PENDING = "pending"


class GameState(StrEnum):
    NEW = "New"
    SELECTION = "Selection"
    ONGOING = "Ongoing"
    CANCELLED = "Cancelled"
    COMPLETE = "Complete"


class GameMode(StrEnum):
    RANDOM = "Random"
    CAPTAINS = "Captains"
    SELF_PICK = "Self Picking Teams"
    BALANCED = "Balanced"
    VOTE = "Vote"
    DEFAULT = "Default"

    @staticmethod
    def to_options():
        opts = []
        for mode in GameMode:
            if mode == GameMode.VOTE or mode == GameMode.DEFAULT:
                continue
            opts.append(mode.value)
        return opts

    @staticmethod
    def to_dict():
        # Return dictionary used to track votes for each mode
        d = {}
        for mode in GameMode:
            if mode == GameMode.VOTE or mode == GameMode.DEFAULT:
                continue
            d[mode] = 0
        return d
