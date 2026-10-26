# sixMans Command Reference

Every command in the `sixMans` cog. The cog in [sixMans/sixMans.py](../sixMans/sixMans.py) inherits
its commands from one module per area:

- Queue setup, joining and leaving, and helper queue commands:
  [sixMans/queues/commands.py](../sixMans/queues/commands.py)
- Queue bans: [sixMans/queues/bans.py](../sixMans/queues/bans.py)
- Score reports, cancels, lobby info and helper game commands:
  [sixMans/games/commands.py](../sixMans/games/commands.py)
- Leaderboards, ranks and `[p]rebuildPlayerTotals`:
  [sixMans/scoreboard/commands.py](../sixMans/scoreboard/commands.py)
- Guild-wide settings and data management:
  [sixMans/settings/commands.py](../sixMans/settings/commands.py)

## Conventions

- `[p]` is your bot's configured Red prefix.
- `<required>` / `[optional]` / `...` (accepts multiple values).
- **All commands are prefix (text) commands.** The cog registers no slash
  commands and no hybrid commands.
- **All commands are `guild_only`** — none work in DMs.
- **Command and alias names are case-sensitive.** The bot is not created with
  `case_insensitive=True`, so `[p]moreInfo` and `[p]moreinfo` work (both are
  registered) but `[p]MOREINFO` does not.
- An argument declared as *consume-rest* takes everything to the end of the
  message, so it does not need quoting. Other multi-word arguments (queue
  names, team-selection modes) must be quoted.

### Permission tiers

| Tier | Who passes | How it is enforced |
| --- | --- | --- |
| **Anyone** | Any guild member | no check |
| **Helper** | A member with the Discord **Manage Server** permission, **or** a member holding the configured 6 Mans helper role (`[p]setHelperRole`) | `has_perms()` inside the command body |
| **Red admin** | Bot owner, guild owner, or a member with a Red **admin role** (`[p]set addadminrole`) | `@checks.admin_or_permissions()` |
| **Red admin / Manage Server** | The Red admin tier, **or** a member with the Discord **Manage Server** permission | `@checks.admin_or_permissions(manage_guild=True)` |
| **Red admin / Kick Members** | The Red admin tier, **or** a member with the Discord **Kick Members** permission | `@checks.admin_or_permissions(kick_members=True)` |

Some commands stack a decorator check *and* an internal `has_perms()` check —
both must pass. Those are marked **Red admin + Helper**. Note that when the
internal check fails, the command returns silently with no reply.

### Team selection modes

`GameMode` values ([sixMans/enums.py](../sixMans/enums.py)) are matched by
**exact, case-sensitive string**:

| Value | Behaviour |
| --- | --- |
| `Random` | Teams split at random. Captains are then picked at random, one from each team. |
| `Captains` | Two random captains alternate picking players via buttons. |
| `Self Picking Teams` | Players place themselves on a team via buttons. See the captains caveat below. |
| `Balanced` | Teams built from stored player points to minimise the score gap, then a random one of the tied-best combinations is chosen. Captains are picked from the resulting teams. |
| `Vote` | Players vote by button for one of the four modes above. 15-minute vote timeout. |
| `Default` | Defer to the queue's own configured mode. |

`Vote` and `Default` are excluded from the vote buttons themselves.
`Self Picking Teams` contains spaces, so it must be quoted when passed as a
positional argument.

> **`Self Picking Teams` only gets captains via the vote path.** The vote
> handler assigns two random captains before starting self-picking, but reaching
> the mode directly — a queue configured as `Self Picking Teams`, or
> `[p]fts "Self Picking Teams"` — does not, and the self-picking view never sets
> them. Such a game has no captains, so `[p]scoreReport` rejects every player
> and the result must be recorded with `[p]forceResult`.

---

## Player commands

Available to **anyone**.

### `[p]queue`
Aliases: `q`

Add yourself to the queue attached to the current text channel. Fails if
queueing is disabled for the guild, if you are queue-banned, if you are already
in this queue, or if you are already in an active game. When the queue reaches
its max size it pops and a game is created.

### `[p]dequeue`
Aliases: `dq`, `lq`, `leaveq`, `leaveQ`, `unqueue`, `unq`, `uq`

Remove yourself from the queue attached to the current text channel.

### `[p]checkQueue`
Aliases: `cq`, `status`

Show the players currently waiting in this channel's queue, and the count out of
the queue's max size.

### `[p]getQueueNames`
Aliases: `qn`

List the names of every queue configured in the guild.

### `[p]getQueueInfo [queue_name]`
Aliases: `qi`

Show a queue's team-selection mode, attached channels, max size, lobby VC,
games played, all-time unique players, and its points-per-play /
points-per-win breakdown. `queue_name` is consume-rest (no quoting needed);
without it, the queue attached to the current channel is used.

### `[p]getQueueTimeout`
Aliases: `getQTO`, `gqto`, `qto`

Show, in minutes, how long a player may sit in a queue before being timed out.

### `[p]moveMe`
Aliases: `smMove`, `moveme`

Move yourself into your team's voice channel. Must be run in the game's text
channel, which must sit under the configured 6 Mans category, and you must
already be connected to a voice channel.

### `[p]lobbyInfo`
Aliases: `li`, `gameInfo`, `gi`

Re-post the lobby info (name/password) for the game in this channel. The channel
must sit under the configured 6 Mans category.

### `[p]moreInfo`
Aliases: `moreinfo`, `mi`

Post more detailed information about the series in this game channel.

### `[p]cancelGame`
Aliases: `cg`

Vote to cancel the game in this channel. Posts a **Cancel** / **Play Out**
button pair that only players in the game can use, with a 60-second timeout.
Required votes are half the player count (3 of 6 in a standard game; 2 if the
game has exactly 2 players, 1 if fewer). Whichever side reaches that count first
decides the outcome. A cancelled game awards no points, players may queue again,
and the game's channels are deleted after 30 seconds.

Limited to one concurrent invocation per channel.

### `[p]scoreReport`
Aliases: `sr`, `reportScore`

Report the winner of the game in this channel. **Only the game's two captains
may run it**, and only after at least **5 minutes** have passed since the game
channel was created. Posts **Blue** / **Orange** / **Cancel** buttons usable
only by the captains, with a 120-second timeout; both captains must pick the
same winner. On success, points are awarded and the game's channels are deleted
after 30 seconds. If a result was already recorded, the command reports that
instead.

Limited to one concurrent invocation per channel.

---

## Leaderboards

`[p]queueLeaderBoard` (alias `qlb`) is a command group. Invoking it with no
subcommand sends the group's help. All subcommands are open to **anyone** and
take an optional consume-rest `queue_name`; without it, stats span all queues in
the guild. Each ranks players by points (ties broken by wins) and shows the top
ten, with the caller's own row appended if they aren't among them. Rows show
points, wins, games played, and win percentage.

| Command | Aliases | Window |
| --- | --- | --- |
| `[p]qlb overall [queue_name]` | `all-time`, `alltime` | All time |
| `[p]qlb day [queue_name]` | `daily` | Last 24 hours |
| `[p]qlb week [queue_name]` | `weekly`, `wk` | Last 7 days |
| `[p]qlb month [queue_name]` | `monthly`, `mnth` | Last 30 days |
| `[p]qlb year [queue_name]` | `yearly`, `yr` | Last 365 days |

Note that `overall` reads the running per-player totals, while the other four
replay the stored score history and filter by date. Players who have left the
server are skipped but keep their rank number, so the list can jump (for example
from 9 to 11). A `queue_name` that matches no queue is ignored and the
guild-wide board is shown instead.

---

## Player ranks

`[p]rank` (aliases `rnk`, `playerCard`, `pc`) is a command group. Invoking it
with no subcommand sends the group's help. All subcommands are open to
**anyone** and take `[player] [queue_name]` — `player` defaults to the caller,
and `queue_name` is consume-rest and defaults to all queues. Because `player` is
optional, `[p]rank alltime SomeQueue` is read as a queue name. As with
leaderboards, a `queue_name` that matches no queue falls back to all queues.

| Command | Aliases | Window |
| --- | --- | --- |
| `[p]rank alltime [player] [queue_name]` | `all-time`, `overall` | All time |
| `[p]rank daily [player] [queue_name]` | `day` | Last 24 hours |
| `[p]rank weekly [player] [queue_name]` | `week`, `wk` | Last 7 days |
| `[p]rank monthly [player] [queue_name]` | `month`, `mnth` | Last 30 days |
| `[p]rank yearly [player] [queue_name]` | `year`, `yr` | Last 365 days |

---

## Helper commands

These have no decorator check; they call `has_perms()` internally, so they
require **Manage Server** or the configured helper role. A member without either
gets no response at all.

### `[p]kickQueue <player>`
Aliases: `kq`, `fdq`

Remove another member from the queue attached to the current channel.

### `[p]clearQueue`
Aliases: `clrq`

Empty the queue attached to the current channel.

### `[p]enableQueues`
Aliases: `eq`

Enable queueing guild-wide. Enabled by default.

### `[p]disableQueues`
Aliases: `stopQueue`, `sq`

Disable queueing guild-wide. `[p]queue` then replies that queueing is disabled.
Useful for maintenance.

### `[p]checkActiveGames`
Aliases: `cag`

List every ongoing game in the guild, grouped by queue, with each game's ID and
players.

### `[p]forceTeamSelection <mode> [game_id]`
Aliases: `fts`

Restart team selection for a game using `mode` (a `GameMode` value — see
[Team selection modes](#team-selection-modes)). Without `game_id`, the game in
the current channel is used. Runs even if the game is already `Ongoing`.

Because `mode` is positional, `[p]fts "Self Picking Teams"` needs quotes.

### `[p]forceCancelGame [gameId]`
Aliases: `fcg`

Cancel a game with no points awarded, freeing its players to queue again.
Without `gameId`, the game in the current channel is used. Posts
**Confirm** / **Cancel** buttons that only the invoking member can use, with a
60-second timeout. Channels are deleted 30 seconds after confirmation.

Limited to one concurrent invocation per channel.

### `[p]forceResult`
Aliases: `fr`

Force the result of the game in the current channel. Posts **Blue** /
**Orange** / **Cancel** buttons usable only by the invoking member, with a
60-second timeout. Unlike `[p]scoreReport` there is no 5-minute wait, no captain
restriction, and no second confirmation — one click records the winner, awards
points, and tears the game down.

Limited to one concurrent invocation per channel.

---

## Testing helpers

### `[p]queueMultiple [members...]`
Aliases: `qm`, `queueAll`, `qa`, `forceQueue`, `fq` · **Red admin / Manage Server**

Force-add any number of members to the queue attached to the current channel.
Its docstring describes it as being for testing purposes. Members already in the
queue are skipped with a message, and the queue pops as soon as it fills. Unlike
`[p]queue`, this bypasses the queue-ban, queues-disabled, and already-in-a-game
checks.

---

## Queue bans

Require **Red admin / Kick Members** *and* pass `has_perms()`
(**Manage Server** or the helper role).

### `[p]queueBan <player> <duration_minutes> [reason]`
Aliases: `qban`

Ban a member from queueing for `duration_minutes` (must be greater than 0).
`reason` is consume-rest, defaults to `None provided.`, and is rejected over
1500 characters. The member is removed from every queue in the guild and is DM'd
the expiry and reason (silently skipped if their DMs are closed).

### `[p]queueUnban <player>`
Aliases: `qunban`

Lift a member's queue ban. Replies that they are not banned if no ban is active.

### `[p]listQueueBans`
Aliases: `qbans`

List all active queue bans with expiry and reason. Expired bans are purged
first.

---

## Queue configuration

### `[p]addNewQueue <name> <points_per_play> <points_per_win> [channels...]`
**Red admin / Manage Server**

Create a queue. Quote `name` if it contains spaces. `channels` are text channels
the queue listens on; a channel already attached to another queue is rejected,
as is a duplicate queue name. The new queue inherits the guild's default max
size, default team selection, and category.

### `[p]editQueue <current_name> <new_name> <points_per_play> <points_per_win> [channels...]`
**Red admin / Manage Server**

Rename a queue and replace its points and channel list. Channels attached to a
*different* queue are rejected. Note that the channel list is replaced, not
appended to — omitting channels leaves the queue with none.

### `[p]removeQueue <queue_name>`
**Red admin / Manage Server**

Delete a queue. `queue_name` is consume-rest. The queue's stats are kept, marked
as deleted under the queue's final name, and no longer appear anywhere.

### `[p]setQueueTS <queue_name> <team_selection>`
Aliases: `setQTS`, `setQueueTeamSelection`, `sqts` · **Red admin + Helper**

Set one queue's team-selection mode. `team_selection` is consume-rest, so
`[p]sqts MyQueue Self Picking Teams` works without quotes. Rejected for a queue
whose max size is 2.

### `[p]getQueueTS <queue_name>`
Aliases: `getQTS`, `getQueueTeamSelection`, `gqts` · **Red admin + Helper**

Show one queue's team-selection mode.

### `[p]setQueueMaxSize <queue_name> <max_size>`
Aliases: `setQueueSize`, `setQMaxSize`, `setQMS`, `sqms` · **Red admin**

Set one queue's max size. Odd values are rejected. `max_size` is consume-rest,
so `queue_name` comes first and needs quoting if it contains spaces. Setting it
to 2 also forces that queue's team selection to `Random`.

### `[p]getQueueMaxSize <queue_name>`
Aliases: `getQMaxSize`, `getQMS`, `gqms`, `qms` · **Red admin**

Show one queue's max size.

### `[p]setDefaultQueueMaxSize <max_size>`
Aliases: `setDefaultQueueSize`, `setDefaultQMaxSize`, `setDefaultQMS`, `setDQMS`, `sdqms` · **Red admin**

Set the max size applied to **newly created** queues. Existing queues are
unchanged. Values of 2 or less are rejected, and odd values are rejected, so the
effective minimum is 4. Default: 6.

### `[p]getDefaultQueueMaxSize`
Aliases: `getDQMaxSize`, `getDQMS`, `gdqms`, `dqms` · **Red admin**

Show the default queue max size.

### `[p]setQueueTimeout <minutes>`
Aliases: `setQTimeout`, `setQTO`, `sqto` · **Red admin**

Set how long a player may sit in a queue before being removed and DM'd a timeout
notice. Applies guild-wide. Default: 30 minutes.

---

## Guild configuration

All **Red admin / Manage Server** unless noted.

### `[p]setCategory <category_channel>`
Set the category under which game text and voice channels are created. Game
channels are not created while this is unset.

### `[p]getCategory`
Show the configured category.

### `[p]unsetCategory`
Clear the category, also removing the helper role's permission overwrite from
it.

### `[p]setHelperRole <helper_role>`
Set the 6 Mans helper role. The role is granted *Read Messages*, *Manage
Channels*, and *Connect* on the 6 Mans category, so its holders can see every
game channel. Holding this role also satisfies the **Helper** permission tier.
Replies that the category is not configured if it is unset.

### `[p]getHelperRole`
Show the configured helper role.

### `[p]unsetHelperRole`
Clear the helper role and remove its permission overwrite from the category.

### `[p]setQueueLobby <lobby_voice>`
Aliases: `setQLobby`, `setQVC`

Set the shared lobby voice channel. Players are moved back into it when a game's
voice channels are deleted, and (with AutoMove on) after a game is scored.

### `[p]clearQueueLobby`
Aliases: `unsetQueueLobby`, `unsetQLobby`, `clearQLobby`

Clear the lobby voice channel.

### `[p]setDefaultTeamSelection <team_selection_method>`
Aliases: `setTeamSelection`

Set the team-selection mode assigned to newly created queues. Accepts a
`GameMode` value, matched case-sensitively, and must be quoted if it contains
spaces. Rejected while the default queue max size is 2. Default: `Vote`.

### `[p]getDefaultTeamSelection`
Aliases: `getTeamSelection`

Show the default team-selection mode.

### `[p]toggleAutoMove`
Toggle whether the bot moves players into their team voice channel when a queue
pops, and back to the lobby VC after a game is scored. Default: off.

### `[p]toggleVoteMethod`
Aliases: `toggleReactToVote`, `tvm`, `trtv`

Toggles the stored `ReactToVote` flag between "reactions" and "commands" and
reports the change.

> **This setting currently has no effect.** Nothing outside this command reads
> `ReactToVote`; team-selection voting is always done with buttons
> ([sixMans/views/vote.py](../sixMans/views/vote.py)).

### `[p]preLoadData`
Reload all guild settings, queues, and games from config. This is the same work
done on `cog_load` and `on_ready`.

### `[p]clearSixMansData`
Erase **all** 6 Mans data for the guild. Prompts for a ✅/❌ reaction
confirmation first. This resets settings (category, helper role, AutoMove,
ReactToVote, lobby VC, default team selection, queue max size, player timeout)
and deletes all queues, games, player stats, and score history. Active queue
bans and the queues-enabled flag are **not** cleared. If the prompt isn't
answered within 60 seconds, nothing is cleared.

### `[p]rebuildPlayerTotals`
Restore all-time totals that a bug failed to record. From 2026-03-16 until the
fix shipped, a player's first game was saved to the score history but never
added to the stored all-time totals, so new players were missing from
`[p]qlb overall` and `[p]rank alltime`. The dated leaderboards and ranks broke
too, but they are recalculated from score history every time, so the fix alone
repaired them; only the stored all-time totals need this command.

The command rebuilds totals from score history only for players whose first game
(server-wide or in a given queue) came after the bug shipped, and only if their
stored totals are missing or show fewer games than their history. Nobody's
totals go down and nobody else is touched, including older players whose stored
totals differ from their history for unrelated reasons.

1. It lists how many players it will add or update, server-wide and per queue,
   and asks for a ✅/❌ reaction. It gives up after 60 seconds.
2. On ✅, it recalculates from current data, in case a game finished while it
   waited, and applies the changes.
3. It posts `player_totals_changes.json`, with the before and after totals for
   every changed player, which can be used to undo a change by hand.

Running it again once it has been applied finds nothing to change. Deleted
queues are skipped.

---

## Scoring

Points come from the queue's own `points_per_play` / `points_per_win` values,
set by `[p]addNewQueue` and `[p]editQueue`:

- Every player on both teams receives `points_per_play`.
- Winners additionally receive `points_per_win`.

Totals are tracked per queue and guild-wide, and each result is also appended to
a score history that the dated leaderboard and rank views replay. Leaderboards
count games by game, so queues of different sizes (Duels, Twos) report the right
number of games.

---

## Behavioural notes

These are facts about the current implementation that are easy to get wrong from
the command help text alone.

- **Queue ban messages are public.** `[p]queueBan`'s confirmation, which
  includes the reason, is posted in the channel the command was run in.
  `[p]queue`'s "you are banned" notice is posted in the queue channel; it leaves
  out the reason, but the fact of the ban and its expiry are visible to
  everyone. Only the banned member's notification, sent when the ban is issued,
  is a DM.
- **The 5-minute score-report gate is measured from the game channel's
  creation time.**
- **Game channels are deleted 30 seconds after a game ends** (cancelled or
  scored), for both the text channel and the two team voice channels.
- **Popping a queue removes its players from every other queue** in the guild.
- **A queue pop is aborted if any of the front players have left the server.**
  They are dropped from the queue and a warning is posted instead.
- **Deleting a queue's last text channel auto-clones it** and attaches the clone
  to the queue, pinging the helper role.
- **Members who leave the guild are removed from any queue they were in.** If
  they were in an active game, a warning suggesting `[p]fcg` is posted in the
  game channel instead.
