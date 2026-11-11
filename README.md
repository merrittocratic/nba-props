# nba-props

Daily raw snapshots of NBA player prop lines and prediction-market prices, kept
so a model can be graded against them later. Capture only: nothing is cleaned or
joined here.

## Sources

| Source | What | Cost |
|---|---|---|
| The Odds API | `player_points`, `player_rebounds`, `player_assists`, `player_threes`, `player_points_rebounds_assists`, `player_points_rebounds`; regions `us` and `us_dfs` | `/events` free; each event's odds up to 6 markets x 2 regions = 12 credits |
| Kalshi | series `KXNBAPTS`, `KXNBAREB`, `KXNBAAST`, `KXNBA3PT`, `KXNBAPRA`, `KXNBAPR`, `KXNBAPA`, `KXNBARA` (open markets) plus batch order books | free, no auth |
| Polymarket | Gamma `/events/keyset?tag_slug=nba` pages, plus CLOB `/books` for player-prop markets (points, rebounds, assists, threes) tipping off in the window | free, no auth |

## Snapshots

Each game gets three Odds API snapshots, defined in `src/nbaprops/snapshots.py` and
shared by the live capture and the historical backfill:

| Snapshot | When |
|---|---|
| `open` | the first time prop lines are posted (books post them the evening before) |
| `morning` | 11:00 ET on game day; skipped when tip-off is under two hours later (noon games) |
| `close` | one hour before tip-off |

The capture runs every 15 minutes and looks at games tipping off in the next 30 hours
(`--hours-ahead`). For each game it takes the snapshot that is due, if it isn't already
in the manifest. Weekend afternoon games and the Christmas slate need nothing special:
each game's snapshots follow its own tip-off. An `open` check finds nothing until lines
are posted. It costs 0 credits and isn't saved. Each snapshot costs up to 12 credits, so
a 15-game night costs up to 540.

**Intraday snapshots.** Once a game's `open` is in the manifest, the capture also takes a
points-only snapshot (`player_points`, region `us`, 1 credit) every 2 hours until 2 hours
before tip-off, labeled `pts_t28` .. `pts_t02` by the hours left. They follow how one
book's line and price move together through the day (EDA catalog entry A5). That's about
10 a game, roughly 2,100 credits a month in season. They queue after the full
snapshots in each run, so the daily cap can't starve a `close`.

Kalshi and Polymarket are pulled only on runs that took a `morning` or `close`
snapshot (about 30 MB per pull, mostly Polymarket), not on `open`-only runs.

## Credit guard

Before every Odds API request the run checks:

- a daily cap of **810 credits**: three full snapshots on a 15-game night (540, rounded
  up to 600) plus up to 14 intraday snapshots per game (today's spend is summed from
  `data/manifest.csv` plus each response's `x-requests-last`), and
- a floor of **2,000 remaining credits** on the plan (from `x-requests-remaining`). The
  live in-game capture uses the same floor.

If a request could cross either limit, the run logs it, writes a `skipped` manifest
row and stops calling the Odds API. Kalshi and Polymarket are not capped.

## Output

- `data/raw/<source>/<YYYY-MM-DD>/<UTC timestamp>.json`: response bodies byte for byte.
  Files are opened in exclusive-create mode, so nothing is ever overwritten.
- `data/manifest.csv`: one row per request: `source, fetched_at, status, row_count,
  request_cost, request, path`.

`data/` and `.env` are gitignored.

## Running

The package reads the key from the `ODDS_API_KEY` environment variable only. How it
gets there depends on the machine, same as shadow-leaderboard:

**Laptop (dev):** 1Password. `.env.template` holds only the `op://` reference, so it
is committed; `op run` resolves it into the process at launch.

```sh
uv sync
op run --env-file=.env.template -- uv run python -m nbaprops.capture --dry-run   # free calls only, writes nothing
op run --env-file=.env.template -- uv run python -m nbaprops.capture             # real run
```

**Mac Mini (Earnest):** Keychain. `scripts/with-secrets.sh` reads `ODDS_API_KEY` from the
`autopilot` service (account `ODDS_API_KEY`) and execs the command.

```sh
scripts/with-secrets.sh uv run python -m nbaprops.capture --dry-run
scripts/with-secrets.sh uv run python -m nbaprops.capture
```

## Scheduling

**Mac Mini (launchd):** every 15 minutes (`StartInterval` 900); each run takes only the
snapshots due. If you change the plist, `bootout` and install it again. The LaunchAgent is `deploy/launchd/com.merritt.nba-props.capture.plist`. launchd does
not expand `~` or `$HOME`, so install it from the repo root with the paths filled in:

```sh
mkdir -p data/logs   # launchd won't create the log dir
sed -e "s|__REPO__|$PWD|g" -e "s|__HOME__|$HOME|g" \
    deploy/launchd/com.merritt.nba-props.capture.plist \
    > ~/Library/LaunchAgents/com.merritt.nba-props.capture.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.merritt.nba-props.capture.plist
```

Check it with `launchctl print gui/$(id -u)/com.merritt.nba-props.capture`, run it now
with `launchctl kickstart gui/$(id -u)/com.merritt.nba-props.capture`, and unload it with
`launchctl bootout gui/$(id -u)/com.merritt.nba-props.capture`. Output goes to
`data/logs/capture.log`. A run missed while the Mini sleeps fires on wake. Don't use
cron on the Mini: it needs Full Disk Access and can't reliably reach the Keychain.

**Live in-game (launchd):** `deploy/launchd/com.merritt.nba-props.live.plist` runs
`python -m nbaprops.live` at :00, :05, ... :55 (`StartCalendarInterval`). Each run lists
games that tipped off in the last 4 hours (free) and takes one `player_points` snapshot
(region `us`, 1 credit) per game in progress, labeled `inplay_MMM` like the historical
in-game backfill. It follows a game to minute 210, or until two checks in a row past minute
90 find no lines. Empty snapshots are saved, since the stop rule reads them from the
manifest; listings with no game on are not, so idle hours leave nothing. Spend goes under
`odds_api_live`, with its own daily cap of 800 (about 30 credits a game, roughly 6K a month
in season), apart from the pregame capture's 810. Install it the same way:

```sh
sed -e "s|__REPO__|$PWD|g" -e "s|__HOME__|$HOME|g" \
    deploy/launchd/com.merritt.nba-props.live.plist \
    > ~/Library/LaunchAgents/com.merritt.nba-props.live.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.merritt.nba-props.live.plist
```

Output goes to `data/logs/live.log`. Check, test-fire and unload it with `launchctl print`,
`kickstart` and `bootout` on `gui/$(id -u)/com.merritt.nba-props.live`.

Prefer the Mac Mini over the laptop: Keychain needs no unlocked 1Password session, and
`data/manifest.csv` accumulates there, which the daily credit cap reads.

**GitHub Actions:** `.github/workflows/capture.yml` runs on manual dispatch only
(dry run by default). It reads the key from the repository secret `ODDS_API_KEY`
and uploads `data/` as a 90-day artifact. To schedule it, uncomment the `schedule`
lines. Each runner starts with an empty `data/`, so there the daily cap only applies
within a single run, and snapshots already taken on the Mini are fetched again.

## Historical backfill

`python -m nbaprops.backfill` pulls the same three snapshots for past games from the
Odds API historical endpoints, newest day first, back to 2023-05-03 (the first day with
historical props). Costs:

- each day's event listing: 1 credit
- finding `open`: a binary search on a 15-minute grid with a cheap probe
  (`player_points`, region `us`), 10 credits when lines exist, 0 when not, about 40 per game
- each full snapshot: up to 10 x 6 markets x 2 regions = 120 credits

That's about 400 credits per game, roughly 1.6M for the ~4,000 games since May 2023.
Spend goes under the manifest source `odds_api_hist`, so it never counts against the live
daily cap. It has its own cap, `--daily-cap` (default 500,000 per UTC day), and stops
before the plan drops below `--floor` (default 50,000), which leaves room for the live
capture. It's resumable: snapshots already in the manifest are skipped, so rerun the same
command after a stop. A test day (11 games, 33 snapshots) took about a minute and 1.7 MB,
so the whole backfill is roughly 6 hours and 600 MB under `data/raw/odds_api_hist/`.

```sh
scripts/with-secrets.sh uv run python -m nbaprops.backfill --dry-run   # listings only, 1 credit/day
caffeinate -i scripts/with-secrets.sh uv run python -m nbaprops.backfill \
    >> data/logs/backfill.log 2>&1
```

Use `--start`/`--end` (YYYY-MM-DD) to limit the range. DFS lines (`us_dfs`) appear only
from about the 2024-25 season. The daily cap is this repo's own guard, not an API limit;
raise it with `--daily-cap` when the whole backfill must finish sooner.

`--markets`, `--regions` and `--source` pull other markets at the same three times, each
source with its own resume state and cap. `--alternates` is the shortcut for the
alternate-line ladders (`player_{points,rebounds,assists,threes}_alternate`, region `us`,
source `odds_api_alt_hist`), which start on 2023-12-08 (1-2 books that month, 5-6 from
January 2024). Most books post ladder Over prices only (FanDuel has both sides) and post
them after the main lines, so `open` is often empty. A test day (2025-01-15, 11 games)
cost 1,761 credits, so every game since December 2023 is ~615K.

```sh
caffeinate -i op run --env-file=.env.template -- uv run python -m nbaprops.backfill \
    --alternates >> data/logs/alt.log 2>&1
```

## Intraday backfill

`python -m nbaprops.intraday` pulls the intraday snapshots (see Snapshots) for past games:
`player_points`, region `us`, every 2 hours from 30 hours before tip-off to 2 hours before,
labeled `pts_t28` .. `pts_t02` like the live capture. Each slot is fetched 5 minutes after
it opens, as the 15-minute capture would. Snapshots with no lines (props not posted yet)
and the 404 before an event is listed cost nothing and aren't saved. Each snapshot with
lines costs 10 credits, about 10 a game.

Spend goes under the manifest source `odds_api_intraday_hist`, with its own `--daily-cap`
(default 1,000,000) and the same `--floor` (50,000). Six games run at once (`--workers`).
It's resumable. A test day (2025-01-15, 11 games) saved 104 snapshots for 1,041 credits in
32 seconds and 1.1 MB, so all ~4,080 games since May 2023 are roughly 3.5 hours, 390K
credits and 400 MB. Run it while the 5M plan lasts (through 2026-11-25).

```sh
caffeinate -i op run --env-file=.env.template -- uv run python -m nbaprops.intraday \
    >> data/logs/intraday.log 2>&1
```

The full run (finished 2026-11-02) saved 41,136 snapshots for 4,094 games: ~413K credits,
722 MB.

`--near-tip` fills the last 2 hours, which the 2-hourly slots leave to `close`: every 15
minutes from 2 hours to 15 minutes before tip-off, labeled `pts_m120` .. `pts_m015` by
minutes left. That's when injury and lineup news lands. It goes under its own source,
`odds_api_neartip_hist`, and costs about 80 credits a game (~330K for every game since
May 2023).

```sh
caffeinate -i op run --env-file=.env.template -- uv run python -m nbaprops.intraday \
    --near-tip >> data/logs/neartip.log 2>&1
```

## In-game backfill

`python -m nbaprops.inplay` pulls historical in-game `player_points` lines (region `us`):
a snapshot every 5 minutes from tip-off, labeled `inplay_000`, `inplay_005`, ... by minutes
after tip. It stops when lines are gone twice in a row after minute 90, or at minute 210.
Snapshots with no lines, and the 404 the API returns once a game has left the feed, cost
nothing and aren't saved. Each snapshot with lines costs 10 credits, about 300 per game.

Spend goes under the manifest source `odds_api_inplay`, with its own `--daily-cap`
(default 2,000,000) and the same `--floor` (50,000). Six games run at once (`--workers`).
It's resumable, like the backfill. A test day (11 games) took 37 seconds and 3.1 MB, so
all ~4,000 games since May 2023 are roughly 4 hours, 1.2M credits and 1.1 GB. Live books
re-price during games and drop out late, and some late lines are stale (still posted after
the player has passed them), so check snapshot times against play-by-play before using them.

```sh
op run --env-file=.env.template -- uv run python -m nbaprops.inplay --dry-run   # listings only
caffeinate -i op run --env-file=.env.template -- uv run python -m nbaprops.inplay \
    --data-dir data/inplay >> data/inplay/inplay.log 2>&1
```

The laptop run writes to `data/inplay/`, not `data/mini/`, because each pull from the Mini
replaces `data/mini/manifest.csv`.

## Game-lines backfill

`python -m nbaprops.gamelines` pulls historical moneyline, spread and total (`h2h`,
`spreads`, `totals`, region `us`) for pace, game-script and blowout features. One
historical `/odds` call returns every game on the board at that moment, so each day takes
a few slate-wide snapshots: `morning` (11:00 ET) and a `close` one hour before each
distinct tip-off time. Each costs 30 credits, plus 1 for the day's listing. A test day
(11 games, 8 snapshots) cost 241 credits, so the whole range since May 2023 is roughly
150-220K. Spend goes under `odds_api_gamelines` (default cap 200,000 a day, floor 50,000),
and it's resumable.

```sh
caffeinate -i op run --env-file=.env.template -- uv run python -m nbaprops.gamelines \
    --data-dir data/gamelines >> data/gamelines/gamelines.log 2>&1
```

ESPN summaries carry DraftKings spread and total in `pickcenter`, but only from 2025-26 on,
so this backfill is the source for earlier seasons.

## Outcomes (actual results)

`python -m nbaprops.outcomes` pulls ESPN's public site API: no key, plain requests, a
0.3 s pause between calls. It fetches one scoreboard per US date, then the game summary
(box score plus play-by-play with UTC `wallclock` times) for each final game, back to
2023-05-03 by default, newest first. Raw responses go to `data/raw/espn/`, about 380 KB
per game, so ~1.5 GB for every game since May 2023. It's resumable, like the backfill.

ESPN's API is unofficial and could change. Two cautions:
- In historical summaries, `injuries` is today's injury list, not the game's. Never
  use it as a feature (it leaks).
- `reason` is filled in for players who played too. Only DNP rows keep it.

## Tidy tables

`python -m nbaprops.tidy` rebuilds parquet tables in `data/tidy/` from the raw files
(about half a second for a two-day sample):

| Table | One row per |
|---|---|
| `games` | ESPN game: tip-off, season, final score |
| `box_scores` | player per game, including DNPs |
| `prop_lines` | snapshot x book x market x player x line, over and under prices side by side |
| `prop_outcomes` | `prop_lines` plus the actual stat, `margin` (actual - line), `result` |
| `game_lines` | slate snapshot x game x book: home spread and prices, total and over/under prices, moneylines, `minutes_before_tip`, `espn_game_id` |

`--data-dir` can be repeated to combine data dirs, e.g.
`--data-dir data/mini --data-dir data/gamelines --out-dir data/tidy_mini`. A slate snapshot
is one game's close and an earlier look at the others, so pick each game's close by
`minutes_before_tip`, not by `kind`.

Joins:
- Odds API events match ESPN games by teams and tip-off within 6 hours (ESPN lists
  scheduled tip-off, the Odds API the actual).
- Players match within that game's box score. Books spell names inconsistently
  ("Irving, Kyrie", "Grant Jerami", "D. Jones Jr.", "Nicolas Claxton", "Danilo
  Galinari"), so `match_name` tries strict rules first and accepts only a unique
  candidate. The rule used is kept in `match_method`.
- `player_status`: `played`, `dnp` (listed, didn't play) or `absent` (not in the box
  score: inactive). DNP and absent lines are `void`, as books grade them.

The run prints a match report (events and players matched, rules used, the most common
absent players) for a quick check after each rebuild. On a two-day sample, 100% of
events and 95.5% of lines matched. The rest were absent players, and box-score points
matched final scores in all 19 games.

## Pulling Mini data to the laptop

The Mini is where data accumulates; models are built on the laptop. `data/` isn't in
git, which is the wrong tool for this volume anyway (the backfill is ~600 MB, and Kalshi
and Polymarket add ~150 MB a day in season). So the laptop pulls with rsync over SSH,
one way, into `data/mini/`:

```sh
scripts/pull-from-mini.sh --dry-run     # list what would be copied
scripts/pull-from-mini.sh               # copy new or changed files
```

It connects as `merrittocracyclaw` (the account Earnest runs under) to
`Stephens-mac-mini.local` and asks for that account's password (plain SSH). It reads
`~/nba-props/data/` in that account's home. If that changes, set `NBA_PROPS_MINI`
(user@host) or `NBA_PROPS_MINI_DIR` (path relative to that home). The pull never deletes or writes
anything on the Mini, and it leaves the laptop's own `data/` (dev runs, probes) alone.
In `data/mini/manifest.csv` the `path` column holds Mini absolute paths. Keep the part
from `raw/` on and look it up under `data/mini/`.

## Development

```sh
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

Tests use recorded, trimmed API responses in `tests/fixtures/` and make no network calls.
