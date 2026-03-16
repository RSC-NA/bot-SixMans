# RSCBot: sixMans

The `sixMans` cog allows members of the guild to queue to play in a Team vs Team series. The cog enables you to set up one or more queues in a guild. When a queue pops, it creates a text channel

## Installation

The `sixMans` cog has no other cog dependencies.

```
<p>cog install RSCBot sixMans
<p>load sixMans
```

<br>

# Setup

### Add a New Queue

The `<p>addNewQueue` command can be used to add a new queue.

```
<p>addNewQueue "<Queue Name>" <points for playing> <points for winning> <channel(s)>
```

### Set Category

The `<p>setCategory` can be used to set the category that contains the 6 mans text and voice channels.

```
<p>setCategory <cateory id>
```

### Set Queue Timeout

The `<p>setQueueTimeout` can be used to declare how long in minutes a player may wait in a queue before being timed out (Default: 240). This value will apply to all queues set up in the guild.

```
<p>setQueueTimeout <minutes>
```

### Set Queue Sizes

The `<p>setQueueMaxSize` can be used to declare how many players must be in a queue for it to pop (Default: 6). This value will apply to all queues set up in the guild.

```
<p>setQueueMaxSize <max_size>
```

### Set Helper Role

Sets the role that will be assigned to individuals to resolve issues with 6 mans queues and games.

```
<p>setHelperRole <role>
```

<br>

# Regular Use

#### Common Commands:

#### `<p>q` - Queue for a 6 mans series

#### `<p>dq` - De-Queue from a 6 mans series

#### `<p>sr <winner>` - Report winner of a 6 mans series (Blue/Orange)

#### `<p>cg` - Cancel Game

#### Information:

#### `<p>status` - Shows all players who are in the queue

#### `<p>qi` - Shows all "Queue Info"

#### `<p>qlb <timeframe> [queue_name]` - Gets a leaderboard for a timeframe ~~and queue if specified~~

#### `<p>rank [timeframe]` - Enables a player to get a player card of their 6mans rating and overall win statistics

<br>

# Helper Commands

#### `<p>enableQueues` - "Enable Queues" - Enables queueing for players (default)
#### `<p>disableQueues` - "Disable Queues" - Disables queueing for players. This is particularly helpful for maintenance.

#### `<p>cag` - "Check Active Games" - Lists all ongoing 6 mans series

#### `<p>getQueueNames` - Lists names of available queues

#### `<p>fts <team selection> [Queue ID]` - Force team selection for a popped queue game

#### `<p>fr <winner>` - Forces result of 6 mans series (Blue/Orange)

#### `<p>fcg` - Force cancel game

#### `<p>kq <member>` - Kicks a member from a 6 mans queue

# Queue Commands

- `<p>moveMe` - Move me to my voice channel
- `<p>queue` - Queue for a game
- `<p>dequeue` - Dequeue from game
- `<p>moveMe` -

# Game Commands
- `<p>lobbyInfo` - Display lobby information
- `<p>cancelGame` - Vote to cancel a game
- `<p>scoreReport` - Report the game result
- `<p>moreInfo` - Detailed information on game
- `<p>voteRandom` - Vote for random team selection
- `<p>voteCaptains` - Vote for captains team selection
- `<p>voteBalanced` - Vote for balanced team selection
- `<p>voteSelfPickingTeams` - Vote self picking team selection

# Admin Commands

- `<p>clearSixMansData` - Clear **ALL** data for guild **(CAUTION)**
- `<p>preLoadData` -  Load all data (called at cog_load)
- `<p>addNewQueue, <ppg> <ppw> <*channels>` - Add new queue
- `<p>editQueue <name> <new_name> <ppg> <ppw> <*channels>` - Edit an existing queue
- `<p>setQueueTS <*name> <team_selection>` - Set team selection mode for queue
- `<p>getQueueTS <name>` - Get team selection mode for queue
- `<p>setQueueTimeout <minutes>` - Set queue timeout in minutes
- `<p>getQueueTimeout` - Get current queue timeout
- `<p>setDefaultQueueMaxSize <size>` - Set default size of queues
- `<p>getDefaultQueueMaxSize` - Get default max size of queues
- `<p>getQueueMaxSize <name>` - Get max size of specific queue
- `<p>removeQueue` - Delete a queue
- `<p>queueMultiple <*discord.Member>` - Force queue of multiple players
- `<p>kickQueue <discord.Member>` - Kick a player from the queue
- `<p>clearQueue` - Clear queued players from queue
- `<p>enableQueues` - Enable all queues
- `<p>disableQueues` - Disable all queues
- `<p>forceTeamSelection <mode>` - Force a games team selection mode
- `<p>forceCancelGame` - Force cancel a game
- `<p>forceResult` - Force the result of a game

*ppw: Points per Win*
*ppg: Points per Game/Play*
