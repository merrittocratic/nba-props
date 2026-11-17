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
  narrow. A ~1.5-point lean under is smaller than the vig, so on its own it
  isn't a bet. Measured 2026-11-15: sportsbook over and under implied probabilities sum to
  106.8% at the close in every market (FanDuel 106.0%, Caesars 107.8%; typical prices -115
  / -115 or -110 / -120), so a side has to beat its no-vig price by about 3.4 points to
  break even. An earlier version of this entry said "~4.5% vig", which was too low.
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

### A7. How one book's line and price move together (A5 follow-up)
- **Question:** when a book's view of a player changes, when does it change the price
  and when does it move the line? How far does it shade the price first?
- **Script:** `eda/02_line_price_moves.py`. Points only.
- **Definitions:**
  - *Chain:* one sportsbook's points line for one player-game, followed across the
    2-hourly snapshots (30 hours to 4 hours before tip) and the 15-minute snapshots (2
    hours to 15 minutes before tip).
  - *Step:* two consecutive snapshots in a chain. 15-minute steps and 2-hour steps are
    reported separately and are not comparable in height.
  - *Line moved:* the main line differs between the two snapshots. *Price only:* same
    line, over or under price differs. Everything else is no change.
  - *Books:* the pooled charts use the nine sportsbooks that post one points line per
    player (BetMGM, BetOnline, DraftKings, Fanatics, FanDuel, MyBookie, PointsBet,
    Caesars, Wynn). Ladder books (Unibet, BetRivers, Barstool, Bovada: more than one line
    in 80%+ of snapshots) are shown only in the by-book chart, because their main line
    is just the rung nearest 50/50. DFS sites are left out (placeholder prices).
- **Expected (written before plotting):** most steps show no change; price-only changes
  outnumber line moves several times over; line moves concentrate in the last 2 hours;
  a book shades the over to about 54-56% before raising a line, then resets to about
  50%; books differ in style.
- **Figures:** `a7_move_type_by_time.html`, `a7_move_chance_by_price.html`,
  `a7_book_style.html`
- **Observed (2026-11-15, 3.9M steps at single-line books):**
  - Frequency: in a 15-minute step in the last 2 hours, 26-36% are price-only changes
    and 5.5-10% are line moves, both rising toward tip-off (final step: 36% and 10%).
    Price-only changes are about four times as common as line moves. As expected.
  - Timing: per 2-hour step, line moves run 6-8% from 28 to 14 hours out and 15-16% from
    6 to 2 hours out. That is under 2% per 15 minutes, against 5.5-10% per 15 minutes in
    the last 2 hours, so line moves are several times denser near tip. As expected.
  - Threshold: lower and sharper than I guessed. With the over at 50% the line moves up
    in 1.7% of 15-minute steps; at 51%, 3.7%; at 52%, 8.5%; at 53% and beyond it sits
    flat at about 11%. Moves down mirror this at 48% and below. So the trigger is about
    2 points of probability off 50%, not 4-6, and shading further does not make a move
    more likely.
  - Reset: 95-98% of line moves are exactly one point. The median price goes from 52%
    on the old line to 48% on the new one (and 48% to 52% for moves down): the book
    flips to the other side of 50%, it does not return to 50%.
  - Translation: a point of line is worth about 5-6% of over probability at these levels
    (A5). A move from "24.5 at 52%" to "25.5 at 48%" is therefore a change of only about
    1.5-2 points of probability, a third of a point of line. The line moves in whole
    points; the price carries the fraction. One line move usually means a small change
    of view crossed a threshold, not a full point of new information.
  - Books: all books trigger at the same 48% / 52%. Style differs in how often they act:
    Fanatics and PointsBet change price in 45% of steps and move lines in 12-14%;
    FanDuel changes price as often (46%) but moves lines in 6%; Caesars and BetMGM
    change price in only 17-22% of steps; DraftKings is in between (26% and 10%).
- **Caveats:** a "no change" step includes a book that simply had not refreshed. Steps
  from the same player-game and from different books are correlated, so no CIs are
  shown. Main line for the nine books is their only line, so no ladder choice is involved.
- **Decision:** treat a book's position as line plus price, not line alone. Candidate
  feature: a price-adjusted line (line + (no-vig over probability - 50%) / price per
  point from A5), and its change from open, in place of the raw line move from A4. Next:
  (1) redo A4's "does the move predict the result" with the price-adjusted line; (2)
  lead-lag across books (who moves first); (3) the same analysis for the count markets
  once the near-tip pull for the other five markets is tidied.

### A8. Price-adjusted line, and whether its move predicts the result
- **Question:** if a book's position is line plus price (A7), does the open-to-close move
  of a price-adjusted line predict results better than the raw line move from A4, and is
  anything left at the close?
- **Script:** `eda/03_adjusted_line.py`. Points only, sportsbooks only (DFS prices are
  placeholders).
- **Definitions:**
  - *Price per point:* over probability that one point of line is worth at a given line
    level, measured from pairs of ladder rungs one point apart on either side of 50%
    (BetRivers, Bovada, Unibet; 67K pairs). 8.7% at a line of 7, 7.3% at 11, 6.1% at 16,
    5.4% at 21, 5.0% at 26, 4.5% at 31; interpolated between. This reproduces the A5 table.
  - *Adjusted line (one book):* line + (no-vig over probability - 50%) / price per point.
    24.5 with the over at 52% is about 24.8.
  - *Consensus adjusted line:* median across sportsbooks at that snapshot. *Adjusted move:*
    consensus at close minus consensus at open, in points.
  - *Move bands:* down 1+, down 0.5 to 1, down 0.15 to 0.5, within 0.15, up 0.15 to 0.5,
    up 0.5 to 1, up 1+ (each includes its lower edge).
  - *Gap:* share of player-games over the consensus raw line minus the mean no-vig over
    probability at the books whose main line equals it; pushes and player-games with no
    such book left out.
- **Expected (written before running):** (1) the adjusted move predicts the result against
  the open better than the raw move; (2) where the raw line never moved, the price-only
  move still predicts; (3) nothing is left against the close price; (4) a one-point
  adjusted move is worth about one point of result.
- **Figures:** `a8_move_vs_result.html`, `a8_edge_by_move.html`
- **Observed (2026-11-15, 28,325 player-games with an open and a close):**
  - (1) Better, but only slightly: correlation with (actual - open line) is 0.142 for the
    adjusted move against 0.134 for the raw move.
  - (2) Confirmed. The raw consensus line did not move in 53% of player-games, and the
    price-only move still sorts them: against the opening price, overs fall short by 6.7
    points after a 0.5-1 point adjusted move down and beat the price by 3.1 after the same
    move up (no move: -3.0).
  - (3) Mostly confirmed. Against the closing price the gap is -0.7 to -2.9 in every band
    with no trend by size. A faint leftover: after up-moves the under lean is 1.5-2.5
    points smaller than after no move or down-moves (about 2 standard errors in the
    line-unchanged group). Not enough to act on; retest on other markets.
  - (4) Confirmed. Result lands 1.08 points further for each point of adjusted move
    (down 1+: moved -1.60, landed -1.96; up 1+: moved +1.78, landed +1.91). For price-only
    moves the slope is 1.55 (se about 0.16): a shade in price understates the change in
    view by about a third.
  - Betting at the open in the direction of the eventual move: +9.4 points over the price
    for up 1+, -11.7 for down 1+. That needs the move to be known in advance.
- **Caveats:** at the open the median player-game has one sportsbook posted (seven at the
  close), so the "open consensus" is usually a single book and part of the move is the
  difference between that book and the field. The no-move baseline here (-3.0) is lower
  than the all-games points figure in A2 (-1.5) because only player-games with an open
  snapshot are included. Open-to-close only; the intraday path is not used yet.
- **Decision:** include the adjusted line and its move from open as model inputs in place
  of the raw line and raw move; keep the raw move only as a check. Next: (a) rebuild the
  move on a same-book basis (each book against its own open) to remove the one-book-open
  problem; (b) use the intraday and near-tip path to ask how early the move is visible;
  (c) repeat for the count markets, where price carries almost all the movement.

---

## Part B: candidates from box scores and game lines (data in hand)

| ID | Feature | Hypothesis | Expected vs `margin` | Status |
|---|---|---|---|---|
| B1 | 3PA share of FGA (season to date) | Three-heavy scorers have wider outcome spread | No mean shift; larger variance, so ladder/alt lines mispriced | not started |
| B2 | FT rate (FTA/FGA) | Free throws are steady, self-created points | Lower variance of points margin | not started |
| B3 | Minutes level, volatility, trend (previous 10 games) | Unstable roles make lines less reliable | Wider margin spread; under lean for bench players | **done 2026-11-15, see B3 below** |
| B4 | Teammate out (top-usage teammate DNP) | Usage moves to whoever is left | Positive margin if lines adjust late or too little | partly: minutes side covered in B9 (hindsight on absences adds little); usage shift not tested |
| B5 | Spread / blowout risk | Big favourites' starters sit late | Under lean for starters when abs(spread) is large | partly: enters the B9 projection (blowout risk costs a 34-minute player about 1 minute per 10 points of spread); not tested against margin directly |
| B6 | Game total | Higher total, more possessions | Mostly priced in; little left vs margin | not started |
| B7 | Rest / back-to-back | Tired legs, rest days for stars | Small under lean on the second night | partly: enters the B9 projection (long rest -1.2 minutes); not tested against margin directly |
| B8 | Recent form vs line (last 5 minus line) | Books overreact or underreact to hot streaks | Unknown; test both directions | **done 2026-11-15, see B8 below** |

### B3. Minutes: level, volatility and trend
- **Script:** `eda/04_minutes_features.py`. Regular season, close snapshot, all six markets.
- **Definitions (all from the player's previous 10 games played, at least 5, never the
  game itself; games he sat out are skipped; seasons are not separated):**
  - *Level:* mean minutes. Groups: under 18, 18 to <24, 24 to <30, 30 to <34, 34+.
  - *Volatility:* standard deviation of minutes. Groups: under 3, 3 to <5, 5 to <7, 7 to
    <9, 9+.
  - *Trend:* mean of the previous 3 games minus the mean of the previous 10. Groups: down
    4+, down 2 to 4, within 2, up 2 to 4, up 4+.
  - *Gap:* over rate minus mean no-vig over probability, one row per player-game-market
    (mean over its books, pushes excluded). 291K player-game-markets.
- **Expected (written before plotting):** volatility widens the spread of results and adds
  a 1-2 point under lean at the top; trend is mostly priced in, with slight under-reaction
  (rising minutes, overs do a little better); low-minute players lean under most (about
  -4.7 under 18 minutes, from the A6 check).
- **Figures:** `b3_level_gap.html`, `b3_volatility_gap.html`, `b3_trend_gap.html`,
  `b3_volatility_spread.html`
- **Observed (2026-11-15):**
  - *Level, opposite of expected.* The under lean is largest for the heaviest-minute
    players, not the lightest. Points: -1.2 (under 18), -0.6, -0.4, -1.5, -2.8 (34+, se
    0.6). Pts+Reb (-3.3), Pts+Reb+Ast (-2.8) and threes (-2.8) show the same at 34+.
    Rebounds are flat at about -2. Assists run the other way (-1.5 under 18, +0.5 at 34+).
    The -4.7 from A6 used full-season minutes including the game itself, so it was not a
    clean number.
  - Players at 34+ go on to play 1.0 minute less than their level and score 0.29 below
    the points line on average; players under 18 who have a line play 3.5 minutes more
    than their level (lines are posted for bench players on nights they are expected to
    play more) and score 0.43 above it.
  - *Volatility, weakly as expected.* Spread of the points margin rises with volatility
    for lines under 20 (10 to <15: sd 5.7 at volatility under 3, 6.5 at 9+) and not for
    lines of 20+. The gap is U-shaped for points: -2.6 under 3 (these are mostly the
    34+ players again), -0.8 in the middle, -2.9 at 9+ (se 0.9).
  - *Trend, opposite of expected.* No under-reaction. After minutes rise the under lean
    is slightly bigger, not smaller: Pts+Reb -0.5 (down 4+) to -1.9 (up 4+), rebounds
    +0.1 to -2.8, points -1.2 to -1.7. Differences are 1-3 points at about 2 standard
    errors each.
  - Every effect here is 1-3 points of probability, inside the vig.
- **Caveats:** the six markets share the same player-games, so agreement across markets
  is not independent confirmation. Level, volatility and trend are correlated (level and
  volatility -0.21). Groups were fixed before looking, but three features and six markets
  is many comparisons.
- **Decision:**
  - Level: **include**, with a market interaction (scoring markets vs assists).
  - Volatility: **include** as an input to the spread of the predicted distribution; weak
    for the mean.
  - Trend: **include** as a model input, low priority; the direction (overs slightly worse
    after a rise) should be rechecked once expected minutes is modelled.
  - Next: these three all describe one thing, expected minutes tonight. Build a minutes
    projection (level, trend, starter status, rest, teammate absences from B4) and test
    "projected minutes vs what the line implies" as a single feature.

### B9. Minutes projection, and projected minutes vs what the line implies
- **Script:** `eda/05_minutes_projection.py`. Regular season. Covers the minutes side of
  B4 (teammates out), B5 (spread) and B7 (rest) as inputs to one projection.
- **Model:** ordinary least squares (numpy `lstsq`; no extra dependency, and each
  coefficient reads as minutes per unit). Fitted on 2023-24 and 2024-25 (49,669
  player-games), tested on 2025-26 onward (30,067), which the model never saw.
- **Definitions:**
  - *Inputs (all known before the game):* mean minutes over the previous 10, 3 and 1
    games played; share of the previous 10 started; started last game; back-to-back (under
    1.5 days since his last game); long rest (4+ days); team games missed since he last
    played; home; absolute closing point spread; rotation minutes the team was missing in
    its previous game. Spread and missing minutes also enter multiplied by (level - 24)
    / 10 so their effect can differ by role.
  - *Rotation minutes missing:* players who played at least 2 of the team's previous 5
    games and did not play; each counts his average minutes in those games.
  - *Hindsight version:* adds rotation minutes missing **tonight**, read from tonight's box
    score. Not usable as a feature; it bounds what an injury report could add.
  - *Line-implied minutes (points only):* points line / the player's points per minute
    over his previous 10 games. *Projected minus line-implied* groups: 4+ below, 2 to 4
    below, within 2, 2 to 4 above, 4+ above.
  - *Projected minus level* groups: 3+ below, 1 to 3 below, within 1, 1 to 3 above, 3+
    above (projection minus the 10-game average).
- **Expected (written before building):** average miss falls from about 4.9 minutes (10-game
  average) to about 4.5, and to about 4.2 with hindsight on absences; against the price,
  roughly flat, 1-2 points at the extremes.
- **Figures:** `b9_projection_accuracy.html`, `b9_proj_vs_level_gap.html`,
  `b9_proj_vs_line_gap.html`, `b9_hindsight_vs_line_gap.html`
- **Observed (2026-11-15, test seasons only):**
  - Accuracy, as expected. Average miss for players with a points line: 5.51 minutes
    (last game), 4.80 (10-game average), 4.49 (projection), 4.40 (hindsight). Knowing
    exactly who sat out adds only 0.09, less than I guessed. Calibrated within 0.3 minutes
    in every projected band except 34+ (projects 35.4, actual 34.6).
  - Coefficients worth knowing: started last game +2.2 minutes; long rest -1.2; each team
    game just missed -0.2; a 34-minute player in a game with a 10-point spread -1.0
    (blowout risk). Level, last 3 and last game carry weights of 0.55, 0.23 and 0.15.
  - Projected above the player's average: overs fall short more, not less. At 3+ above:
    points -2.2, Pts+Reb -4.0, Pts+Reb+Ast -3.5, rebounds -4.3, threes -3.8, against about
    -1.1 within 1 (se 1.3 each). Those players do play the extra minutes (0.8 more than
    projected), so the market is not wrong about minutes; it prices the extra minutes at
    the player's usual rate and they are worth less. Same direction as the B3 trend result.
  - Projected vs line-implied (points): flat at -1.5 to -2.0 in four groups, then +2.5
    (se 0.9, n 3,339) at 4+ above, where the line implies at least 4 fewer minutes than
    projected. Those players did play less than projected (-1.7 minutes), so books had a
    reason to lower the line, and lowered it too far. With hindsight on absences the
    figure is +2.2: knowing who sat out does not add to it.
  - What that last feature really is: projection x points per minute is close to the
    player's 10-game scoring average, so "4+ above" mostly means "the line is well below
    his recent scoring average". That is B8 (recent form vs line), not a minutes effect.
- **Postseason (added 2026-11-15, after Steve asked whether playoff minutes were handled;
  they were not: the projection above is fitted and tested on regular-season games only):**
  - *Expected (written before running):* the regular-season model over-projects bench
    players by 3-4 minutes in the postseason and under-projects starters by 2-3; postseason
    terms remove most of that and cut the average miss by about 0.3 minutes.
  - *Test:* postseason terms = an indicator for play-in and playoff games, on its own and
    multiplied by level, by started-last-game and by the spread. Fitted on everything
    through 2024-25 (53,653 player-games, 3,984 of them postseason); tested on the 2026
    postseason (1,948 player-games). Figure: `b9_postseason_bias.html`.
  - *Observed:* the regular-season model over-projects players averaging under 18 minutes
    by 3.2 and those at 18 to <24 by 1.6, and under-projects everyone from 24 up by about
    1.5. With postseason terms those become 0.8, 0.6 and, from 30 up, under 0.5; the 24 to
    <30 group is still under-projected by 1.5. Average miss 5.46 to 5.07. The key
    coefficient: in the postseason each 10 minutes of level is worth 1.4 more minutes.
    Regular-season accuracy is unchanged (4.95).
  - *Limits:* only players who appeared are scored, and players under 18 minutes sit out
    about half of postseason games, so the bench error is understated. One postseason of
    testing.
- **Postseason against the price (2026-11-17):**
  - *Definitions:* unit = one postseason player-game (play-in and playoffs, 2023 from May
    3 to 2026) in one market at the close. *Role* = 10-game average minutes, same groups
    as B3. *Adjustment* = projection with postseason terms minus the regular-season
    model's projection, in minutes; groups: 2+ fewer, 1 to 2 fewer, within 1, 1 to 2 more,
    2+ more. Each postseason is projected by models fitted on every other season (so all
    four postseasons can be scored; the fit uses later seasons, which a live model could
    not). 25,374 player-game-markets.
  - *Expected (written before building):* no usable edge. The postseason under lean
    (about -3.4, A6) appears in every minutes tier, not only the bench; players adjusted
    up do 1 to 2 points worse on overs, within noise. A gap of 4+ points confined to
    bench players would mean books carry regular-season minutes into the playoffs.
  - *Figures:* `b9_postseason_gap_by_level.html`, `b9_postseason_adjustment_gap.html`
  - *Observed:* as expected; the bench is not where the lean is.
    - By role, the extra postseason under lean sits with heavy-minute players in the
      scoring markets. Points: -5.6 (30 to <34) and -4.8 (34+) against -1.7 and -2.3 in
      the regular season; -1.1 to -3.2 below 30 minutes (se 1.5 to 2.0 each). Pts+Reb+Ast
      at 34+ misses the line by 1.0 on average (regular season 0.45).
    - Assists lean under in every tier, -4.1 to -6.0, against about 0 in the regular
      season. Rebounds show no postseason effect (-2 in both phases).
    - By adjustment, points go from -2.5 (within 1) to -5.2 (1 to 2 more) and -5.5 (2+
      more, se 2.2); the combined markets are similar. The step is about 3 points, a
      little over one standard error. Rebounds and assists are flat.
    - Bench players who get a line are not over-priced: those adjusted down 2+ minutes
      played 1.8 more than projected and points overs ran +1.9 (se 3.1, n 252). Books
      post a line for a bench player when he is expected to play.
  - *Reading (interpretation, not measured):* books do not carry regular-season minutes
    into the playoffs. Starters get the extra minutes and still fall short, so the miss
    is in output per minute, in line with A6. The postseason terms improve the minutes
    forecast but are not an edge against the price by themselves.
- **Caveats:** one test period (2025-26 plus ten days of 2026-27). The +2.5 was the one
  extreme group of five and is about break-even after vig, not a profit. Linear model:
  no interactions beyond the two listed. The six markets share player-games.
- **Decision:**
  - Projected minutes: **include** as a model input in place of the three B3 features.
  - Postseason terms in the projection: **include** (better minutes forecast); as a price
    signal by themselves, **exclude**. The postseason lean for 30+ minute players and for
    assists is a phase-by-role effect to carry into the model (A6), not a minutes effect.
  - Injury-report data for minutes: **exclude for now**; hindsight on absences improved
    the projection by 0.09 minutes and did not change the price test.
  - Projected-minus-level: **include**; a consistent 1-3 point under lean when minutes are
    projected up.
  - Line vs recent scoring average: **revisit as B8**, tested directly (10-game points
    average minus the line, by market) rather than through minutes.

### B8. The line against the player's recent average
- **Script:** `eda/06_recent_form.py`. Regular season, close snapshot, all six markets,
  288K player-game-markets. No model is fitted, so all seasons are used; 2023-24 and
  2024-25 are reported apart from 2025-26 onward because B9 found the hint in the later
  period.
- **Definitions:**
  - *10-game average:* the player's mean of that stat over his previous 10 games played
    (at least 5, never the game itself). Left out when it is under 0.5.
  - *Line vs average:* consensus close line / 10-game average - 1. Groups: 20%+ below, 10
    to 20% below, within 10%, 10 to 20% above, 20%+ above (each includes its lower edge).
  - *Streak:* 10-game average / 30-game average - 1 (at least 15 of the 30). Hot = 10%+
    above, cold = 10%+ below, steady = between.
  - *Gap:* over rate minus mean no-vig over probability. *Return:* profit per 1 staked at
    each sportsbook's price, averaged per player-game-market (DFS left out).
- **Expected (written before running):** line well below the average: overs beat the price
  by 2-3 points; line well above: the usual 1-2 point under lean, no mirror effect;
  similar across scoring markets; shows up in the earlier seasons too. Also tested: are
  books fading hot streaks too hard?
- **Figures:** `b8_line_vs_average_gap.html`, `b8_streak_split.html`
- **Observed (2026-11-15):**
  - A gradient, smaller than expected and the same in both periods. All markets pooled:
    line 20%+ below the average, gap +0.2 (2023-25) and 0.0 (2025-26); within 10%, -1.5
    and -1.5; 20%+ above, -1.6 and -2.4. So a line well below recent form removes the
    usual under lean; it does not make overs profitable (return -6.4% against -9.1%
    within 10%).
  - B9's +2.5 for points does not hold up as stated: the direct points figure is +0.1 in
    2023-25 and +1.4 (se 1.0) in 2025-26.
  - Hot streaks: the opposite of the idea tested. Books do not over-fade hot players;
    overs on hot players do worse in every line group (within 10%: hot -2.5, steady -1.4,
    cold -0.5).
  - The largest effect: hot players whose line is set 20%+ above even their 10-game
    average (the market expects a bigger role still). Gap -4.3 (se 0.6; -4.4 in 2023-25
    and -4.0 in 2025-26). Unders there returned +1.8% (se 1.0; +1.7% and +1.8% by
    period), against -3.6% for unders in general. By market the under return is +5.8%
    rebounds, +5.0% threes, +1.6% assists, about 0 for the scoring markets. 7,048
    player-game-markets from 3,542 player-games.
  - Sportsbook prices are wider than the catalog assumed: over and under returns sum to
    about -13% at baseline, i.e. roughly -115 / -115, not the 4.5% vig quoted in A2.
- **Reading across B3, B9 and B8:** one pattern three ways. When the market prices in a
  step up (minutes trending up, minutes projected above average, a line above recent
  production), overs fall short by 2-4 points more than usual. The market is right about
  the direction and overshoots the size.
- **Caveats:** the hot / 20%+ above cell is one of fifteen and was picked after looking;
  its positive return is under 2 standard errors and comes mostly from two markets. The
  six markets share player-games.
- **Decision:** **include** line-vs-10-game-average and the streak measure as model
  inputs, with their interaction. Not a standalone bet. The A2 vig figure needs
  correcting (see Observed).

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
