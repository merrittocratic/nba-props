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

Script: `eda/01_outcome_profile.py`. Every chart carries its own small print (unit, axes,
groups, what was left out); the shared terms are defined here.

### Definitions used in every Part A chart

| Term | Meaning |
|---|---|
| Player-game | One player in one game in one market, players who played only. |
| Book-line | One book's main line for one player-game. A player priced by 8 books is 8 book-lines, so book-line counts overstate the independent sample. |
| Main line | The one line per book and snapshot priced nearest 50/50 (smallest gap between no-vig over probability and 50%). 87% of book-lines have only one line posted; Unibet, BetRivers, MyBookie, Barstool and Bovada post ladders. For 0.5% of book-lines no line has both prices (mostly Pick6 and MyBookie) and the first listed is used. |
| No-vig over probability | Over implied probability / (over + under implied probabilities), from American odds. |
| Consensus line | Median of the books' main lines for that player-game and snapshot. Median 7 books at close; 7% of player-games have one book and 6% have two, where "consensus" is just that book or the midpoint. A median of an even number of books can be a whole number (1-5% of lines). |
| Margin | Actual stat minus the line. Above 0 = over. |
| Snapshot | `open` (first time lines are posted), `morning` (11:00 ET), `close` (one hour before tip). Base table is `close` unless stated. |
| Season | ESPN's label is the end year; charts show it as 2023-24. Regular season, play-in and playoffs are pooled in A1-A5 (A6 splits them). Preseason is not in the data: the Odds API lists it under a separate sport key that was never pulled. 2022-23 is playoffs only (35 games) and 2026-27 runs to 2026-10-29. |
| Line level on an x-axis | The line value itself, one group per half-point line (a whole-number consensus such as 12.0 is grouped with 12.5). Groups under a stated minimum count are left out. |

Chart audit, 2026-11-15 (after the A4 quintile problem): three more build errors fixed.
`a1_sd_vs_line` grouped lines with `round()`, which rounds halves to even, so each even
number pooled two lines (2.5 with 1.5) and odd numbers held only whole-number lines; it now
uses one group per line. `a1_margin_hist` used automatic bins that did not line up with
half-point margins; bins are now one unit wide. `a3_open_vs_close_mae` drew open and close
as side-by-side bars that could not show a 1% difference; it now plots the change. No
number quoted in A1-A3 below changed.

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
  2023 playoffs (35 games) and "2027" is the first 10 days of the 2026-27 regular season
  (2026-10-20 to 10-29, 71 games), so ignore their extremes.
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

### A4. Pregame line movement by opening-line band
- **Question:** how do lines move from open to morning to close, split by the level of the
  opening line, and does the move predict the result?
- **Definitions:**
  - *Unit:* one player-game-market with a consensus line at both `open` and `close`
    (consensus = median of the books' main lines, as above).
  - *Move:* consensus line at the snapshot minus the consensus opening line, in stat
    units. Lines that didn't move count as 0 in every average.
  - *Opening-line band:* a fixed range of the consensus opening line, set per market in
    `BANDS` in the script. Each band includes its lower edge.

    | Market | Bands |
    |---|---|
    | Points | under 10, 10 to <15, 15 to <20, 20 to <25, 25+ |
    | Rebounds | under 3, 3 to <5, 5 to <7, 7 to <9, 9+ |
    | Assists | under 2, 2 to <4, 4 to <6, 6 to <8, 8+ |
    | Threes | under 1 (the 0.5 line), 1 to <2, 2 to <3, 3+ |
    | Pts+Reb | under 15, 15 to <20, 20 to <25, 25 to <30, 30+ |
    | Pts+Reb+Ast | under 15, 15 to <20, 20 to <25, 25 to <30, 30 to <35, 35+ |

  - A band describes the line that night, not the player: most players appear in more
    than one band over the sample. "Low band = bench player, top band = star" is a loose
    reading, not something the chart measures.
  - Replaced 2026-11-15: the first version used quintiles of the opening line within
    each market ("Q1 lowest" .. "Q5 highest"). Prop lines take few distinct values, so
    equal-count groups split one line value across groups by row order (threes Q2 and Q3
    were both entirely the 1.5 line; 59-77% of rebounds, assists and threes rows sat on a
    value shared between groups).
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
    drift is biggest for the lowest bands (points under 10: +0.18, PRA under 15: +0.24)
    and about 0 for the top band (points 25+: -0.00, PRA 35+: -0.01). High lines do move
    more often (points: 41% of lines under 10 moved, 57% of lines 25+), as guessed, but
    their moves cancel out, where low lines move mostly up.
  - The count markets show the same ordering at a smaller scale: threes +0.06 on the 0.5
    line down to -0.10 at 3+, assists +0.04 under 2 down to -0.08 at 8+, rebounds +0.11
    under 3 down to -0.03 at 9+.
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
  level (the opening line itself, not a band). Only three pregame snapshots are available; denser intraday moves need the
  live capture (from 2026-10) or the in-play table.

### A5. How price and line trade off (price per point of line)
- **Question:** when news moves a player's expected output, how much price is one point of
  line worth, and how do books split a move between line and price?
- **Expected (written before plotting):** near the middle of the distribution, a point
  of line is worth roughly the density there: about 1/(sd x 2.5), so ~6% for points
  (sd ~6.3) and far more for threes (sd ~1.4), where one step is most of the move.
- **Observed (2026-11-01, close ladders at Bovada, BetRivers, Unibet):** mean no-vig over
  probability by distance from the main line:

  | Market | -2 | -1 | main | +1 | +2 |
  |---|---|---|---|---|---|
  | Points | 62.7% | 56.3% | 49.9% | 43.7% | 37.7% |
  | PRA | 59.8% | 54.9% | 49.9% | 45.0% | 40.6% |
  | Rebounds | 68.0% | 62.8% | 49.6% | 37.2% | 32.3% |
  | Assists | 69.0% | 64.3% | 49.4% | 35.5% | 31.2% |
  | Threes | | 69.0% | 49.0% | 30.9% | |

  For points, one point of line is worth 8.2% at lines up to 10, 6.8% at 10-15, 5.8% at
  15-20, 5.3% at 20-25, 4.8% at 25-30 and 4.5% above 30 (wider distributions spread the
  probability thinner). In the count markets the first step off the main line is worth
  13-20%, which is why those books move the price instead of the line (A4: 92% of
  threes lines never moved).
- **Decision:** next, follow the same book's line *and* price across open -> morning ->
  close to classify moves (price only; line moves and price resets; both) and to measure
  how big a price move has to get before the line moves. Finer than three pregame
  snapshots would need more frequent pregame capture (costs credits).

### A6. Regular season vs postseason
- **Question:** do the Part A results differ by phase of the season? (Asked as "split out
  preseason"; there is no preseason data, so the split is regular season vs postseason =
  play-in + playoffs.)
- **Expected (written before running):** preseason is a small share of lines, so pooled
  numbers barely move; preseason itself leans further under. Wrong on the premise: zero
  preseason rows. No expectation was written for the postseason before seeing it.
- **Figure:** `a6_phase_gap.html` (over rate minus no-vig over probability, by market and
  phase, one row per player-game)
- **Observed (2026-11-15, close, books' main lines, 299K regular-season and 27K postseason
  player-games):**
  - Overs fall short of the price by 3.4 points in the postseason (se 0.3) against 1.3 in
    the regular season (se 0.1). All four postseasons agree: -4.0, -2.4, -4.4, -3.0.
  - By market (postseason vs regular season): assists -5.2 vs -0.2, PRA -3.9 vs -1.2,
    points -3.6 vs -1.2, threes -3.1 vs -1.7, Pts+Reb -3.1 vs -1.4. Rebounds show no
    difference (-1.4 vs -1.9).
  - Betting every sportsbook under at the close returned +0.0% in the postseason (se 0.6%)
    against -4.1% in the regular season. That is break-even, not a profit; assists alone
    were +3.5% (se 1.4%), the best of six markets, so treat it as a lead, not a result.
  - Pooled A1-A5 numbers are regular-season numbers in practice (92% of player-games).
    Postseason lines also move less (points: 38% of lines moved vs 49% overall).
- **Why (Steve's hypothesis, 2026-11-15: playoff rotations shrink from 10-12 players to
  7-8), tested ad hoc against `box_scores.parquet`, players with 20+ regular-season games:**
  - The shrink is real but smaller than that in the average game: players with 10+ minutes
    per team-game go from 9.1 to 8.3, and the top five's share of minutes from 66% to 72%.
    Players averaging under 18 minutes sit out 48% of postseason games.
  - Minutes against the player's own regular-season average: -4.2 (under 18 min), -3.8
    (18-24), -0.9 (24-30), +2.5 (30-34), +3.5 (34+).
  - The extra under lean is **not** where minutes were cut. It is largest for 30-34 minute
    players (-4.3 postseason vs -0.3 regular), who play more, and absent for 18-24 minute
    players (-1.9 vs -2.1).
  - What drops is production per minute: points per 36 minutes fall about 2.5 in every
    tier (30-34 tier: 20.5 to 17.9). Starters play 2.5 more minutes and still score 0.9
    fewer points; their points line sits only 0.5 below their season average.
  - Holding minutes fixed (within 2 of the player's average), the gap is -4.6 in the
    postseason vs -1.6 in the regular season.
  - Reading: books appear to price the minutes change and under-adjust for lower output
    per minute (slower pace, tougher defense, or both; not separated here).
- **Caveats:** four postseasons, 300 games; the under-return figure was looked at after
  the gap was found; the rotation test is not yet in a script.
- **Decision:** include a postseason indicator as a model input, and build the Part B
  minutes features (B3) so they can interact with it. Next: split per-minute output into
  pace and efficiency using game totals (B6), and move the rotation test into the B-series
  script.

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

Source: NBA.com stats API via the `nba_api` package.

**Probe results (2026-11-01, from the laptop):** every endpoint below answered for
2023-24, 2024-25, 2025-26 and 2026-27, responding in 0.1-1 s.
- `DateFrom`/`DateTo` works on the league dashboards (Brunson 2024-25: 65 GP for the
  full season, 20 GP to 2024-12-01) and on `playerdashptshots` (single-game shot groups).
  So season-to-date, as-of-the-day-before values can be built without leakage.
- `synergyplaytypes` has **no date parameters**: season-level only, so C7 must use the
  prior season.
- Per-game boxes (`boxscoreplayertrackv3`, `boxscorehustlev2`, `boxscorematchupsv3`,
  `playbyplayv3`) work back to 2023-24 and for 2026-27 games already played. The
  player-tracking box has contested/uncontested FGA, touches, passes, secondary assists,
  speed, distance and rebound chances. The hustle box has screen assists, screen-assist
  points, deflections and box outs. The matchups box has every offense-defense pair's
  matchup minutes, partial possessions, points, FGA and switches. The play-by-play has
  shot x/y, distance and shot subtype (pull-up, driving, step back), and the assister is
  in the description text.
- NBA.com game IDs (e.g. `0022400264`) differ from ESPN's; join on date + teams.
- Works from the Mini too (Earnest, 2026-11-01: `boxscoreplayertrackv3` returned (35, 37)).
  Not yet tested: how hard NBA.com throttles a long run.
- Rough backfill size: 4 per-game boxes x ~4,100 games = ~16K requests (~7 h at a
  1.5 s pause). For defender-distance shot groups, use the league-wide per-day version
  (`leaguedashplayerptshot` with a defender-distance filter, not yet tested) instead of
  per-player calls.

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
