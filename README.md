# RSCBot: sixMans

The `sixMans` cog allows members of the guild to queue to play in a Team vs Team
series. The cog enables you to set up one or more queues in a guild. When a
queue pops, it creates a text channel and a pair of team voice channels, runs
team selection, and tears the channels down once the result is reported.

## Installation

The `sixMans` cog has no other cog dependencies.

```
[p]cog install RSCBot sixMans
[p]load sixMans
```

## Command reference

**➡️ See [docs/COMMANDS.md](docs/COMMANDS.md)** for every command, its aliases,
its arguments, and who is allowed to run it.

## Quick setup

`[p]` is your bot's configured Red prefix.

1. **Set the game channel category.** Game channels are not created until this
   is set.

   ```
   [p]setCategory <category>
   ```

2. **Add a queue**, giving it a name, its points per series played, its points
   per series win, and the text channel(s) players queue in.

   ```
   [p]addNewQueue "<queue name>" <points_per_play> <points_per_win> <channel(s)>
   ```

3. **Optional — set a helper role.** Holders can see every game channel and can
   run the helper-tier commands (kick from queue, force cancel, force result).

   ```
   [p]setHelperRole <role>
   ```

4. **Optional — set a lobby voice channel.** Players are returned here when a
   game's voice channels are deleted.

   ```
   [p]setQueueLobby <voice channel>
   ```

5. **Optional — adjust defaults** for new queues and for queue timeouts.

   ```
   [p]setDefaultQueueMaxSize <size>          # default 6, must be even and > 2
   [p]setDefaultTeamSelection <mode>         # default "Vote"
   [p]setQueueTimeout <minutes>              # default 30
   ```

Use `[p]getQueueInfo` (`[p]qi`) to check a queue's configuration at any time.

## Most-used commands

| Command | Aliases | Purpose |
| --- | --- | --- |
| `[p]queue` | `q` | Join this channel's queue |
| `[p]dequeue` | `dq`, `uq`, … | Leave the queue |
| `[p]checkQueue` | `cq`, `status` | See who is waiting |
| `[p]scoreReport` | `sr` | Report the winner (captains only) |
| `[p]cancelGame` | `cg` | Vote to cancel a game |
| `[p]lobbyInfo` | `li`, `gi` | Re-post the lobby name/password |
| `[p]queueLeaderBoard` | `qlb` | Leaderboards |
| `[p]rank` | `rnk`, `pc` | Your player card |

Full alias lists are in [docs/COMMANDS.md](docs/COMMANDS.md).

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) and
[DevSetup-VSCode.md](DevSetup-VSCode.md).
