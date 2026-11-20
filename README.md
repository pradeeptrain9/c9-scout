# C9 Scout

VALORANT scouting for Cloud9 and Cloud9 GC coaches: where an opponent places utility, and how their
Operator / Outlaw / Marshal / Odin players set up, with the sample size printed beside every number.
Built for the Cloud9 x JetBrains "Sky's The Limit" hackathon, Category 1.

## What a coach sees
- **Utility map**: choose a team, map and side, then an agent and its abilities. The heatmap shows where each cast
  was thrown from, with white arrows for the average aim at the busiest spots. Click any zone (grid A–J / 1–10)
  to see "used here in X% of this agent's rounds (k/n)".
- **Long-range weapon profile**: how often the team has an Operator, Outlaw, Marshal or Odin after the buy phase,
  who holds it, where each holder's first fight of the round happens, and how early (buy / 0–20s / 20–40s / 40s+).
- **Insight cards**: sentences generated straight from the counts, for example
  *"Cloud9 cypher uses trapwire in zone B7 on Pearl (attacker) in 87% of rounds (45/52)."*
  A pattern needs at least 15 rounds to appear. Click a card to open the matching map view.
- **Self-scout**: Cloud9 and Cloud9 GC are listed first, so the team can check its own predictability.

## Run it
Requires Python 3.14 (it reads `.zst` with the standard library; on older versions run `pip install zstandard`).

```bash
# 1. GRID data, cloned NEXT TO this repo (never inside it; the data license forbids committing it)
git clone --filter=blob:none --sparse https://github.com/cloud9esports/stl-hackathon-2026-grid-starter.git ../stl-hackathon-2026-grid-starter
git -C ../stl-hackathon-2026-grid-starter sparse-checkout set meta val val-ability-supplements

# 2. Build the aggregates (about 6 minutes for 857 series with 4 workers)
python3.14 engine/scout.py --data ../stl-hackathon-2026-grid-starter --out web/data

# 3. Serve the UI
python3 -m http.server 8799 --directory web
```

Tests: `python3.14 -m unittest engine/test_scout.py` (uses a tiny hand-made feed, no GRID data needed).

## How it works
1. `engine/scout.py` streams each series feed. At round start it records each team's side and agents. At the end
   of the buy phase it reads every player's inventory to see who has a long-range weapon.
2. Ability casts are joined to Cloud9's ability supplement on `grid_event_id` to get the caster's position and
   aim direction. GRID's own 2D position is the fallback. Landing spots are not in the data, so the map shows the
   cast spot plus the aim.
3. Each player's first long-range damage event in a round marks where they fought and how many seconds after
   the buy phase.
4. Games that GRID rolled back (`series-!started-game`) are dropped.
5. Everything is reduced to binned counts per team. Only those counts reach `web/data/`; no raw events are
   written.

Map shapes are drawn from where players stood across every match, not from game art.

## Data and license
Match data is provided by GRID, under the hackathon data license (no redistribution, hackathon use only).
This repo contains code only. `web/data/` is built on your machine by step 2 above and is gitignored, because
even aggregated output is derived from the licensed data. Not endorsed by Riot Games. Code: MIT, see `LICENSE`.
