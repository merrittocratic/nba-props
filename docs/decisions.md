# Decisions

Dated record of capture-scope choices and why, so they are not re-litigated
from scratch. Add new entries at the top.

## 2026-10-25: Kalshi series in scope; steals, blocks and double-doubles skipped

**Captured:** `KXNBAPTS`, `KXNBAREB`, `KXNBAAST`, `KXNBA3PT`, `KXNBAPRA`, plus
`KXNBAPR`, `KXNBAPA`, `KXNBARA`.

- Threes and pts+reb+ast match markets the Odds API already captures, so the same
  player and threshold are priced at sportsbooks, DFS sites and Kalshi in one snapshot.
  That is what's needed to test whether combos are priced consistently with their parts.
- The two-stat combos (PR, PA, RA) had **0 open markets** on 2026-10-25. They are kept
  because each costs one free request, and they get captured if Kalshi starts listing them.

**Skipped:**

| Series | Open markets | With any volume | Why skipped |
|---|---|---|---|
| `KXNBASTL` (steals) | 87 | 2 | Nearly untraded, and no sportsbook line captured to compare against |
| `KXNBABLK` (blocks) | 28 | 2 | Same |
| `KXNBASTOCK` (steals + blocks) | 16 | 0 | Same |
| `KXNBA2D` / `KXNBA3D` (double/triple-double) | 26 / 8 | 5 / 1 | Same |
| `KXNBAPTSPROT` ("protected" points) | 263 | 10 | Mirrors the points ladder; settlement meaning of "protected" not yet checked |

Counts are from a single snapshot on 2026-10-25 (7-game slate). For comparison,
about 60% of base `KXNBAPTS` markets had some volume.

**Revisit if:** the model starts predicting steals, blocks or double-doubles; Kalshi
volume in these series grows; or the Odds API markets `player_steals` / `player_blocks`
are added (that would give a sportsbook comparison, at +2 credits per market per game
across `us` and `us_dfs`). Adding a series is one line in `SERIES` in
`src/nbaprops/kalshi.py`.

## 2026-10-25: Odds API two-stat combos not captured

`player_points_rebounds`, `player_points_assists` and `player_rebounds_assists` would add
6 credits per game (3 markets x 2 regions), so a 15-game night would cost up to 240 and
cross the 150-credit daily cap. Kalshi had no open two-stat combo markets to pair them
with, so they were left out. Revisit if Kalshi lists PR/PA/RA markets or the cap is raised.
