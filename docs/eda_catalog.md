# EDA Catalog

One entry per candidate feature (and per outcome-profile question). Each entry has a
hypothesis and an expected result written **before** plotting, then the figures, the
observed result and a decision: include / transform / exclude / revisit, or
"include (override)" when Steve keeps a feature against the evidence.

This is documentation, not a gate. Figures are Plotly HTML under `eda/figures/`
(gitignored; regenerate with the script named in each entry).

Targets: `actual` (the stat) and `margin` (`actual - line`). The market line is the
benchmark: a feature only helps a betting model if it explains `margin`, not just
`actual`.

## Leakage rule

Every feature must be computable as of the snapshot it is paired with. Season totals
from NBA.com may only be used for games in a *later* season unless pulled with
`DateFrom`/`DateTo` ending the day before the game.

---

## Part A: outcome profile (no features yet)

Script: `eda/01_outcome_profile.py`. Base table: `close` snapshot, each book's main
line (the ladder rung whose no-vig over probability is nearest 50%), players who
played. Consensus line = median of the books' main lines.

### A1. Margin distribution by market
- **Question:** what does `actual - consensus close line` look like per market?
- **Expected (written before plotting):** median slightly below 0 and right-skewed in
  every market, because stats are counts bounded at 0 with a long upper tail. Skew is
  strongest for threes and assists (many low lines, many zeros). Spread grows with the
  line, roughly like a count variable (sd ~ sqrt(line) or wider).
- **Figures:** `a1_margin_hist.html`, `a1_sd_vs_line.html`
- **Observed (2026-11-01, close, ~50-57K player-games per market):** confirmed. The median
  margin is -0.5 in every market and the mean is slightly positive (points +0.20,
  assists +0.15, threes +0.11), so lines sit at the median, below the mean. Skew is
  biggest for threes (0.81), then assists (0.59) and rebounds (0.50), and smallest for
  PRA (0.17). The margin sd is 1.4 (threes), 2.0 (assists), 2.6 (rebounds), 6.3 (points),
  7.9 (PRA).
- **Decision:** model the full distribution (quantiles or a count likelihood such as
  negative binomial), not a point estimate, and price over/under from it. Using the mean
  as the line would lean every pick over.

### A2. Over rate by market, season and line level
- **Question:** do overs hit 50% at main lines? Does it depend on how high the line is?
- **Expected:** overall under rate around 51-53%. The under edge is biggest on low
  lines (0.5-4.5 threes/assists/rebounds) and close to zero on high points lines.
- **Figures:** `a2_over_rate_market_season.html`, `a2_over_rate_by_line.html`,
  `a2_calibration_by_line.html` (over rate minus no-vig implied probability: this is the
  edge measure, because the raw over rate ignores price)
- **Observed (2026-11-01, books' main close lines, 2.07M book-lines):** overall over rate
  48.0%, so 52% under, inside the expected range. Against the no-vig price, overs come
  in 1.0-1.9 points short in every market: assists -1.0, points -1.5, rebounds -1.8,
  threes -1.9. Line level matters in places I didn't expect. Threes get worse as the line
  rises (2.5: -3.0, 3.5: -4.3, 4.5: -8.7 points). Low points lines (2.5-4.5) are -2 to -5.
  The 0.5 assists line is the one bucket where overs beat the price (+2.5).
  Seasons: ESPN labels a season by its end year (2024 = 2023-24); "2023" is only the
  2023 playoffs (35 games) and "2027" is the first ~4 weeks of 2026-27, so ignore their
  extremes.
- **Caveats:** the rows are book-lines, not independent player-games, so the CIs are too
  narrow. A ~1.5-point lean under is still smaller than the ~4.5% vig, so on its own it
  isn't a bet.
- **Decision:** keep line level x market as a model input (or apply a calibration layer
  after the model). The threes 3.5+ under is worth a closer look once B1 (3PA share) is
  built.

### A3. Book vs consensus and open vs close
- **Question:** which books are off consensus, and is the close more accurate than
  the open?
- **Expected:** close MAE below open MAE in every market (the close carries injury
  news). DFS sites (PrizePicks, Underdog, Pick6) sit closest to consensus because they
  copy lines; offshore books (Bovada, MyBookie, BetOnline) differ most.
- **Figures:** `a3_open_vs_close_mae.html`, `a3_book_offset.html`
- **Observed (2026-11-01):** the close is more accurate than the open in every market,
  but only by about 1% (points MAE 5.25 -> 5.20, threes 1.201 -> 1.199). Big news mostly
  pulls a player's line rather than moving it. The book ranking only partly matches the
  guess. Underdog and William Hill (Caesars) track consensus most closely. The
  Kambi-powered books (BetRivers, Unibet), FanDuel and BetMGM move furthest from it.
  PrizePicks is close on points but loose on rebounds and assists. Offshore books are
  not the outliers I expected.
- **Decision:** use the consensus close as the benchmark line. Line shopping and
  book-specific stale lines are worth their own study (BetRivers/FanDuel vs consensus)
  later; not a model feature.

### A4. Pregame line movement by opening-line window
- **Question:** how do lines move from open to morning to close, split by the player's
  opening-line window (quintiles within each market), and does the move predict the result?
- **Expected (written before plotting):** most lines don't move (median 0). Moves get
  bigger as the line rises. Average drift is about 0. Lines that moved up go over more
  often when measured against the open line, but not against the close line.
- **Figures:** `a4_move_path.html`, `a4_move_vs_result.html` (blue dot = actual over rate,
  grey dash = rate implied by the no-vig price; the gap between them is the edge)
- **Observed (2026-11-01, 170K player-games with an open and close consensus):**
  - Share of lines that moved: about half of points lines, 55-58% of combo lines, 19-23%
    of rebounds/assists, and only 8% of threes. In the count markets the price moves
    instead of the line.
  - Size: the mean absolute move is 0.6 for points and 0.8 for PRA.
  - Direction: points and combo lines drift **up** on average (+0.12 to +0.15). The
    drift is biggest for the lowest windows (points Q1 +0.18, PRA Q1 +0.23) and close to
    0 for the top window (points Q5 +0.02). This is the opposite of my "moves get bigger
    as the line rises" guess.
  - Result: against the open line, up-moves go over 55-62% of the time and down-moves
    37-42%, so the moves carry real information. Against the close line, points and
    combo overs are flat by direction (48-49%), so the close takes it in. Threes,
    rebounds and assists looked like they overshoot (after an up-move only 39% of threes
    went over the new line), but that was the price. Against the no-vig close price the
    gap is -1.6 (threes up), +0.7 (threes down) and -1.1 (assists up), the same 1-2 point
    under lean as A2. Rebounds up (-2.9, se 0.9) is the only cell slightly worse than
    baseline, which isn't enough to act on.
  - Against the open price the moves are a real edge: up-moves beat the open price by
    +4 to +7 points and down-moves fall short by -7 to -9 (points, combos, rebounds,
    assists); threes are smaller (+2.4 / -2.8). That edge exists only for a bet placed at
    the open that anticipates the move.
- **Decision:** candidate features: open-to-close move (direction and size) and opening-line
  window. Only three pregame snapshots are available; denser intraday moves need the
  live capture (from 2026-10) or the in-play table.

---

## Part B: candidates from box scores and game lines (data in hand)

| ID | Feature | Hypothesis | Expected vs `margin` | Status |
|---|---|---|---|---|
| B1 | 3PA share of FGA (season to date) | Three-heavy scorers have wider outcome spread | No mean shift; larger variance, so ladder/alt lines mispriced | not started |
| B2 | FT rate (FTA/FGA) | Free throws are steady, self-created points | Lower variance of points margin | not started |
| B3 | Minutes volatility (rolling sd) | Unstable roles make lines less reliable | Wider margin spread; under lean for bench players | not started |
| B4 | Teammate out (top-usage teammate DNP) | Usage moves to whoever is left | Positive margin if lines adjust late or too little | not started |
| B5 | Spread / blowout risk | Big favourites' starters sit late | Under lean for starters when abs(spread) is large | not started |
| B6 | Game total | Higher total, more possessions | Mostly priced in; little left vs margin | not started |
| B7 | Rest / back-to-back | Tired legs, rest days for stars | Small under lean on the second night | not started |
| B8 | Recent form vs line (last 5 minus line) | Books overreact or underreact to hot streaks | Unknown; test both directions | not started |

---

## Part C: tracking and self-creation (NBA.com, not yet pulled)

Source: NBA.com stats API via the `nba_api` package. Each endpoint needs a probe
(seasons 2023-24 to 2025-26, date filters, works from the Mini).

| ID | Feature | Endpoint | Hypothesis | Status |
|---|---|---|---|---|
| C1 | Unassisted % of FGM (2PT, 3PT) | `leaguedashplayerstats` MeasureType=Scoring | Self-creators hold up when teammates/scheme change; assisted scorers don't | not started |
| C2 | Catch-and-shoot vs pull-up FGA share | `leaguedashptstats` CatchShoot / PullUpShot | Same split, by shot type | not started |
| C3 | Drives per game, drive points | `leaguedashptstats` Drives | Rim pressure, FT generation | not started |
| C4 | Touches, time of possession, dribbles per touch | `leaguedashptstats` Possessions | Ball-dominant vs finisher roles | not started |
| C5 | Wide-open shot share (closest defender 6+ ft) | `playerdashptshots` | Players who need others to get them open are scheme-dependent | not started |
| C6 | Potential assists, assist points created | `leaguedashptstats` Passing | Better assist predictor than raw assists | not started |
| C7 | Play-type frequency (iso, P&R handler, spot-up, transition, putback) | `synergyplaytypes` | Game-plan dependence; pair with opponent play-type defense | not started; probably season-level only, use prior season |
| C8 | Shot location mix (rim / mid / corner 3 / above-break 3) | `shotchartdetail` (per shot x, y, distance, zone) | Shot diet predicts variance and matchup sensitivity | not started |
| C9 | Opponent allowed rates (C&S FGA, rim FGA, defender distance) | team-level versions of C2, C5, C8 | Matchup effect on the shooters who rely on others | not started |
| C10 | C1 x B4 interaction | derived | Assisted scorers drop when main creator sits; self-creators rise | not started |
| C11 | Contested vs uncontested FGA per game | `boxscoreplayertrackv3` | Shooters who need open looks are hurt by switching or long defenders | not started |
| C12 | Screen assists, box outs, deflections | `boxscorehustlev2` | Who creates space for others; a screener out should hurt the shooters he frees | not started |
| C13 | Primary defender faced (matchup minutes, points allowed) | `boxscorematchupsv3` | Defender quality explains the points margin the line misses | not started |

### Tracking data sources (researched 2026-11-01)

The goal: shot location, defender distance at the shot, and who creates space.

| Source | What it has | Cost | Use |
|---|---|---|---|
| NBA.com `shotchartdetail` | Every shot: x/y, distance, zone, action type, made/missed | free | **Yes** (C8, C9) |
| NBA.com `playbyplayv3` | Every action, shot x/y, who assisted | free | **Yes**: build assisted % per game ourselves, no leakage |
| NBA.com per-game box scores: `boxscoreplayertrackv3`, `boxscorehustlev2`, `boxscorematchupsv3` | Touches, passes, contested/uncontested FG, distance run; screen assists, deflections; who guarded whom | free | **Yes** (C4, C11-C13). Per game, so we roll our own as-of-date averages |
| NBA.com `playerdashptshots` | Shots grouped by closest-defender distance (0-2, 2-4, 4-6, 6+ ft), dribbles, touch time | free | **Yes** (C5). Groups only; run it per game with `DateFrom = DateTo` |
| PBP Stats (pbpstats.com) | Possession-level data: on/off, lineups, assisted/unassisted, shot-clock splits | free, has an API | Maybe: cross-check and on/off splits |
| Basketball-Reference | Shooting by distance, % assisted, on/off | free, strict scraping limits | No, NBA.com covers it |
| Cleaning the Glass | Location-based shooting, garbage time removed | paid, no API | No for now |
| BBall Index | Tracking-derived ratings (gravity, openness, matchup difficulty) | paid | Revisit if C-series features pay off |
| Synergy | Full play-type data | paid | No; NBA.com's play-type summary (C7) first |
| Raw optical tracking (Hawk-Eye / Second Spectrum) | Player x/y 25+ times a second | not public | Not available |

**Not available publicly:** the distance from shooter to defender for each individual
shot. NBA.com once had a per-shot log with closest-defender distance
(`playerdashptshotlog`), but it was pulled years ago. The best public substitute is
the defender-distance groups above, pulled per game.
