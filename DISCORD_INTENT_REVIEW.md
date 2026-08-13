# Discord Privileged Intent Review — Submission Answers

_Prepared August 2026 for app **RSC 6Mans <3 Null** (`962033647672754216`)._

## Context

Discord notified us that the app crossed the 10,000-user threshold under the June 2026 policy change,
giving 29 days to submit a privileged intent review or lose the intents. This document contains
ready-to-paste answers, grounded in an audit of what the code in this repo actually does.

The app is a Rocket League 6-mans (3v3) matchmaking system for the Rocket Soccar Confederation
community.

**Key finding from the code audit:** the cog never reads presence data. Requesting Presence we don't
use is one of Discord's stated rejection reasons, so that intent should be switched off before
submitting.

Note that the 2026 policy introduces an **annual re-application requirement** — this will come around
again next year, which is why this document lives in the repo.

---

## Do these three things BEFORE submitting

1. **Disable the Presence Intent** in the Developer Portal → Bot → Privileged Gateway Intents.
   Verified by audit: zero references to `member.status`, `member.activity`, `member.activities`,
   or `on_presence_update` anywhere in [sixMans/](sixMans/). The only "status" hit is a command
   *alias* at [sixMans.py:1338](sixMans/sixMans.py#L1338). Submitting a request for an intent we
   demonstrably don't use invites scrutiny on the two we genuinely need.

2. **Record a short screen capture** (30–60s) of a queue popping. Discord's own guidance says
   evidence "is especially valuable." Suggested take: six people type `q` → queue pops → private
   text channel + three voice channels appear → team-selection buttons → players auto-moved into
   Blue/Orange VCs → `sr` reports the score → channels clean up. This single clip demonstrates both
   intents at once.

3. **Do NOT mention Red-DiscordBot** anywhere in the submission. Describe the app's features in the
   first person ("my app does X"). Framing an application as "I run a Red instance" reads as a
   generic framework request rather than a specific use case, and is widely reported to draw denials.

---

## Answer 1 — What does your app do?

> RSC 6Mans is a matchmaking and match-management app for competitive Rocket League communities. It
> runs the full lifecycle of an informal "6 mans" (3v3) pickup match inside Discord.
>
> Players join a queue by command in a designated channel. When six players have queued, the app
> automatically:
>
> 1. Creates a private text channel and three voice channels (General, Blue Team, Orange Team) for
>    that specific match, visible and joinable only to the six players in it.
> 2. Runs a team-selection process chosen by player vote — random split, captains drafting,
>    self-picking teams, or a balanced split computed from players' historical win rates.
> 3. Moves each player into their assigned team's voice channel.
> 4. Generates and posts the Rocket League private-match lobby name and password so players can meet
>    in-game.
> 5. Collects the match result, requiring agreement from both teams before it is recorded.
> 6. Awards points, updates each player's win/loss record, returns players to the main lobby voice
>    channel, and deletes the match channels.
>
> The app also provides leaderboards and individual player-stat cards filterable by day, week, month,
> year, or all time, plus moderation tools for community staff: removing a player from a queue,
> temporarily banning a disruptive player from queueing, force-cancelling a stuck match, and
> force-setting a result in a dispute.
>
> The app is used by Rocket League league and pickup communities, primarily the Rocket Soccar
> Confederation.

---

## Answer 2 — Server Members Intent justification

This is the strongest of the two requests. It is not a userinfo/serverinfo feature; the app performs
real member-object operations that have no non-privileged equivalent.

> My app requires the Server Members intent for five distinct core functions. None of them are
> informational lookups — each performs an action on member objects.
>
> **1. Restoring in-progress matches after a restart.**
> Active match state is persisted to disk as Discord user IDs so that a bot restart does not destroy
> a match that six people are in the middle of playing. On startup the app must resolve those stored
> IDs back to guild members in order to rebuild the match — its rosters, its team assignments, and
> its captains. Without the member cache this resolution returns nothing, every in-progress match is
> silently lost on restart, and six players are left in a private channel the app no longer
> recognises. This happens at `models/game.py` (`get_player_members`, `get_blue_members`,
> `get_orange_members`, `get_captain_members`), called during startup restore.
>
> **2. Creating per-match private channels with per-member permissions.**
> When a queue fills, the app creates a text channel and three voice channels and denies access to
> `@everyone`, then grants read access to each of the six players individually as a permission
> overwrite on that member object. After teams are picked it rewrites voice permissions per member so
> that Blue players can connect to the Blue voice channel and not the Orange one, and vice versa.
> This requires resolved member objects, not user IDs. Without it, match channels cannot be made
> private and any server member could join or spectate another team's voice comms — which in a
> competitive context means being able to listen to the opposing team.
>
> **3. Moving players between voice channels.**
> Once teams are set, the app moves each player into their team's voice channel, and when the match
> ends it reads the membership of the match voice channels and moves everyone back to the community
> lobby voice channel before deleting the match channels. Both reading voice channel membership and
> moving members require member data.
>
> **4. Resolving members named in moderation commands, and role-based permission checks.**
> Staff commands take a member as an argument — removing a player from a queue, temporarily banning a
> player from queueing, looking up another player's stat card. Resolving a name, nickname, or mention
> to the correct member requires member lookup. Separately, the app gates every moderation command
> behind a check of whether the invoking member holds the community's configured helper role, which
> requires reading that member's roles.
>
> **5. Removing players who leave the server from an active queue.**
> Players wait in a matchmaking queue for up to thirty minutes. If someone leaves, is kicked, or is
> banned while waiting, they can no longer be granted permissions on the private channels the app
> creates, and a match built around them fails outright. My app listens for `GUILD_MEMBER_REMOVE` for
> this single purpose: to drop a departing player from any queue they are waiting in so the next
> match is not formed around someone who is no longer in the server, and to warn the remaining
> players if the departure happened mid-match.
>
> For clarity about scope: `GUILD_MEMBER_REMOVE` is the only member event my app listens for, and it
> is used solely for the queue cleanup described above. My app does not listen for `GUILD_MEMBER_ADD`
> or `GUILD_MEMBER_UPDATE`, does not enumerate the full guild member list, does not assign or remove
> roles, and does not edit nicknames. It reads member data only for the players actively using it.

### Supporting code references

| Claim | Location |
|---|---|
| Restore matches from persisted IDs | [models/game.py:26-64](sixMans/models/game.py#L26-L64), called at [sixMans.py:2317-2320](sixMans/sixMans.py#L2317-L2320) |
| Private channel creation + per-member overwrites | [game.py:119-148](sixMans/game.py#L119-L148) |
| Per-team voice permission rewrite | [game.py:591-611](sixMans/game.py#L591-L611) |
| Voice moves | [game.py:602](sixMans/game.py#L602), [sixMans.py:812-814](sixMans/sixMans.py#L812-L814), [sixMans.py:1750-1751](sixMans/sixMans.py#L1750-L1751), [sixMans.py:1791-1792](sixMans/sixMans.py#L1791-L1792) |
| Queue cleanup on member departure (`on_member_remove`) | [sixMans.py:131-155](sixMans/sixMans.py#L131-L155) |
| Pop-time validation that queued players are still members | [sixMans.py:1930-1947](sixMans/sixMans.py#L1930-L1947) |
| Helper-role permission gate (`member.roles`) | [sixMans.py:1612-1623](sixMans/sixMans.py#L1612-L1623) |
| `discord.Member` command arguments | [sixMans.py:458](sixMans/sixMans.py#L458), [:513](sixMans/sixMans.py#L513), [:571](sixMans/sixMans.py#L571), [:590](sixMans/sixMans.py#L590) |

---

## Answer 3 — Message Content Intent justification

**Read the risk note below before submitting this one.** It is the weaker of the two requests, because
Discord's documented top rejection reason is a use case "achievable through slash commands or
interactions instead." Be honest and specific; do not overstate.

> My app's entire command interface is text-prefix commands — approximately fifty of them, including
> the commands players use constantly during a session: joining a queue, leaving a queue, checking who
> is queued, requesting a move to their team's voice channel, reporting a match result, and starting a
> vote to cancel a match. Staff and setup commands (creating and configuring queues, queue bans,
> force-cancel, force-result, leaderboards) are also text commands, several of which take free-text
> arguments such as a queue name or a ban reason.
>
> Without the Message Content intent, the app receives empty content on incoming messages and
> therefore cannot recognise that a command was issued at all. Every function of the app becomes
> unreachable — not degraded, but completely inoperable.
>
> The app does not register an `on_message` listener, does not scan, log, filter, or analyse message
> content, and does not store message bodies. Message content is used solely by the command parser to
> identify the invoked command and its arguments, and is discarded immediately after parsing. The only
> message field the app itself reads is the message timestamp, used to enforce a five-minute minimum
> match duration before a result can be reported (an anti-abuse measure against instantly-reported
> fake wins).
>
> Where interactive input is needed mid-match, the app already uses Discord UI components rather than
> message parsing: team-selection voting, captain drafting, self-picking teams, score-report
> confirmation, and cancel votes are all button-driven interactions.

### Risk note — read this

The button-based flows are genuinely in our favour: they show we already use interactions where they
fit, so the message-content request is not laziness across the board. But a reviewer can reasonably
respond that `q`, `dq`, and `sr` could be `/q`, `/dq`, and `/sr`, and that would be a correct
observation. There are no slash or hybrid commands in the cog at all — every one of the ~50 commands
is a `@commands.command()` / `@commands.group()` in [sixMans.py](sixMans/sixMans.py).

Realistic options:

- **Submit as written.** Prefix-command bots do get approved, and the Members justification is strong
  enough to carry weight. Low-effort path, probably succeeds.
- **Strengthen it first (recommended if there's time).** Converting the commands to
  `commands.hybrid_command` registers them as both prefix and slash commands with a fairly mechanical
  change. Doing this before submitting gives a much better story: "slash commands are available, and
  message content preserves the muscle-memory workflow for a community that has typed `q` for years."
  It also means a denial is survivable rather than fatal.

Honest read: option 2 materially de-risks this. Option 1 is defensible if time is short. Note that
`ctx.prefix` is persisted into match state and rendered into user-facing help strings
([game.py:665](sixMans/game.py#L665), [strings.py:34-35](sixMans/strings.py#L34-L35)), so a hybrid
migration needs those paths handled — it is not purely a decorator swap.

---

## Answer 4 — Data practices / storage and retention

Discord asks whether we store intent-derived data. The audit confirms this is a genuinely clean story.

> **Message content: not stored.** Message content is parsed for command dispatch and discarded. No
> message bodies are written to disk or retained in memory beyond the request. The one exception is
> that when a staff member issues a queue-ban command, the free-text ban reason they type is stored
> alongside the ban so it can be shown to the banned player and to other staff; this is
> moderator-authored text about a moderation action, not captured user conversation.
>
> **Member data: minimal, ID-only.** The app stores Discord user IDs and nothing else that identifies
> a person. Against each user ID it stores only gameplay statistics: points, games played, and wins,
> plus an append-only per-match history row recording match ID, queue ID, win flag, points, and
> timestamp. Active-match state stores user IDs for rosters, teams, and captains, along with channel
> IDs and the generated in-game lobby credentials.
>
> The app does not store usernames, display names, nicknames, avatars, email addresses, or any
> presence or activity data. Display names are read from the member cache and rendered into embeds at
> the moment they are shown, and are never persisted.
>
> **Storage and security.** All data is stored locally on the server that hosts the app, in per-guild
> scoped storage. Nothing is transmitted to any third-party service, sold, or shared. Match state is
> retained for the duration of a match and cleared when it completes; player statistics are retained
> to power leaderboards and player ranking, which is a core feature; queue bans expire automatically
> at their set duration.
>
> **Deletion.** Server administrators can wipe all stored data for their guild with a single command.

### Supporting code references

| Stored structure | Contents | Location |
|---|---|---|
| `Players` | `{user_id: {Points, GamesPlayed, Wins}}` | [types.py:22-25](sixMans/types.py#L22-L25) |
| `Scores` | append-only `{Game, Queue, Player, Win, Points, DateTime}` | [types.py:13-19](sixMans/types.py#L13-L19) |
| `QueueBans` | `{user_id: {expires, banned_by, reason}}` — `reason` is staff-typed text | [types.py:28-31](sixMans/types.py#L28-L31) |
| `Games` | rosters/teams/captains as `list[int]` user IDs | [game.py:656-675](sixMans/game.py#L656-L675) |
| Guild-scoped config only | `register_guild` only; no user/global scope | [sixMans.py:62-63](sixMans/sixMans.py#L62-L63) |
| Wipe-all-guild-data command | `clearSixMansData` | [sixMans.py:136-153](sixMans/sixMans.py#L136-L153) |

---

## Gaps worth closing (not blocking)

1. **No privacy policy or terms of service.** There is none in the repo and none found on the RSC
   sites. The Developer Portal has fields for these URLs, and a populated privacy policy URL is a
   cheap credibility signal for a data-practices review. A short page stating exactly what Answer 4
   says would suffice.
2. **No per-user data deletion path.** The only deletion is `clearSixMansData`, which wipes an entire
   guild. Since `Players`, `Scores`, and `QueueBans` are all keyed by Discord user ID, there is no way
   to honour an individual "delete my data" request. Worth adding independently of this review.
3. **No `info.json`** in the repo — unrelated to the intent review, but noted during the audit.

---

## Pre-submission checklist

- [ ] Presence intent toggled **off** in the Developer Portal.
- [ ] Confirm the app still functions with Presence off — restart and run a full queue-to-score-report
      cycle in a test guild. The audit says nothing uses it, so this should be a no-op, but verify
      rather than assume.
- [ ] Screen recording captured showing queue pop → private channels → team selection → voice moves →
      score report.
- [ ] Answers pasted with no mention of the underlying bot framework.
- [ ] Decide on the hybrid-command question above before submitting, since it changes Answer 3.

---

## References

- [Getting Started with Privileged Intent Review](https://docs.discord.com/developers/gateway/getting-started-with-privileged-intent-review)
- [Changes to Privileged Intent Access for Discord Apps](https://support-dev.discord.com/hc/en-us/articles/40281523410967-Changes-to-Privileged-Intent-Access-for-Discord-Apps)
- [Gateway: Privileged Intents](https://docs.discord.com/developers/topics/gateway#privileged-intents)
