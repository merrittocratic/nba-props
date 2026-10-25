# nba-props

Daily raw snapshots of NBA player prop lines and prediction-market prices, kept
so a model can be graded against them later. Capture only: nothing is cleaned or
joined here.

## Sources

| Source | What | Cost |
|---|---|---|
| The Odds API | `player_points`, `player_rebounds`, `player_assists`, `player_threes`, `player_points_rebounds_assists`; regions `us` and `us_dfs` | `/events` free; each event's odds up to 5 markets x 2 regions = 10 credits |
| Kalshi | series `KXNBAPTS`, `KXNBAREB`, `KXNBAAST`, `KXNBA3PT`, `KXNBAPRA`, `KXNBAPR`, `KXNBAPA`, `KXNBARA` (open markets) plus batch order books | free, no auth |
| Polymarket | Gamma `/events/keyset?tag_slug=nba` pages, plus CLOB `/books` for player-prop markets (points, rebounds, assists, threes) tipping off in the window | free, no auth |

One run covers games tipping off in the next 24 hours (`--hours-ahead`).
On a typical 8-game night it costs up to 80 Odds API credits; a 15-game night
costs up to 150.

## Credit guard

Before every Odds API request the run checks:

- a daily cap of **150 credits** (today's spend is summed from `data/manifest.csv`
  plus each response's `x-requests-last`), and
- a floor of **3,000 remaining credits** on the plan (from `x-requests-remaining`).

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

**Mac Mini (cron or Earnest's scheduler):** run once a day before the evening slate.
Example, 6 pm local time, after a one-time `mkdir -p data/logs`:

```cron
PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/Users/<user>/.local/bin
0 18 * * * cd /Users/<user>/nba-props && scripts/with-secrets.sh uv run python -m nbaprops.capture >> data/logs/capture.log 2>&1
```

cron has a minimal PATH, hence the first line, so `uv` and `security` resolve. Prefer
the Mac Mini over the laptop: Keychain needs no unlocked 1Password session, and
`data/manifest.csv` accumulates there, which the daily credit cap reads.

**GitHub Actions:** `.github/workflows/capture.yml` runs on manual dispatch only
(dry run by default). It reads the key from the repository secret `ODDS_API_KEY`
and uploads `data/` as a 90-day artifact. To schedule it, uncomment the `schedule`
lines. Each runner starts with an empty `data/`, so there the daily cap only applies
within a single run.

## Development

```sh
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

Tests use recorded, trimmed API responses in `tests/fixtures/` and make no network calls.
