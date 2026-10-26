DEBUG = False
MINIMUM_GAME_TIME = 300  # Seconds (5 Minutes)
PLAYER_TIMEOUT_TIME = 10 if DEBUG else 1800  # How long players can be in a queue in seconds (4 Hours)
CHANNEL_SLEEP_TIME = 5 if DEBUG else 30  # How long channels will persist after a game's score has been reported (seconds)
CONFIRM_TIMEOUT = 60  # How long an admin has to confirm a destructive command (seconds)
