# C9 Scout — VALORANT utility + Operator scouting (Cloud9 x JetBrains, Cat 1)

Due **13 Jan 2027 00:30 IST** (12 Jan 11:00 PT). Build window ~23 Dec – 12 Jan.

## What it does (one screen per question)
1. **Utility map** — pick opponent → map → side → agent/ability. Heatmap of cast spots
   (placeables first: trapwire, alarmbot, Vyse walls, Chamber trips), with "N casts / M rounds"
   on every cell. Arrow = mean aim direction per cluster.
2. **Operator profile** — per opponent: Op buy rate per round (by side, econ), who holds it
   (player/agent), how it moves between players, and where the Op holder fights, split by
   round time (0–20s / 20–40s / 40s+). Aggressive-vs-passive tag from distance to own spawn.
3. **Insight cards** — auto sentences straight from the stats, each with sample size:
   "Opponent A uses Sentinel utility at B-main on Corrode in 62% of defence rounds (31/50)."
   Only shown if n ≥ threshold (fail closed, no LLM numbers).
4. **Self-scout toggle** — same views on Cloud9 / Cloud9 GC.
5. Stretch: anti-strat hint per hot zone (e.g. "trap at X in 62% → clear with recon first").

## Data facts (checked on series 2843062, C9 vs Sentinels)
- Ability casts: `player-used-ability` (GRID, 2D pos, laggy) + supplement `interpolated.position`
  (3D, cm) + `view` aim vector. Join on `grid_event_id`. Use `quality == ok` (or the near frame
  for `gap_exceeded`). VCT Americas 2025 is 1 Hz → weight lower / flag in UI.
- No landing spot. v1: cast spot + aim arrow. Maybe later: project aim ray a fixed distance per ability.
- Operator: player `inventory.items` in full-state snapshot at `round-ended-freezetime`
  → who has an Op each round. Op fight spots = holder's `position` on kill/damage events +
  `game.clock.currentSeconds`.
- Map bounds in `game.map.bounds`. **Map backdrop: draw it from all player positions across
  the dataset (density silhouette)** → no Riot art used, our own art.
- Round / side / score from `game-started-round`, `team-won-round`, team `side`.

## Stack
- **Engine (PyCharm, Python):** stream `.zst` → per-(team, map, side, agent, ability) binned counts
  + Op tables → `public/agg/*.json`. Only aggregated bins/counts leave the engine (no raw events,
  no per-event rows) → OK under data license. Unit tests on small fixture built by hand, not real data.
- **UI (WebStorm):** static site, canvas heatmap, filters. Deploy on GitHub Pages.
- **Junie via AIR plugin** (2026.3 moved Junie into bundled AIR; standalone Junie plugin deprecated):
  use for engine tasks + review; commit `.idea/`, `.air/`. Log each prompt for
  `AI_SHOWCASE.md` (bonus prize).

## Guardrails
- Data clone at `~/Desktop/stl-hackathon-2026-grid-starter` (outside repo). `.gitignore` has
  `*.zst *.jsonl *.parquet *.sqlite *.duckdb`. Run the `git ls-files | grep` check before every push.
- Original names/art only. No Riot logos, agent portraits, or minimap images.

## Before 23 Dec (small)
- [ ] Register on Devpost now (JetBrains codes take ≤5 business days).
- [ ] Install PyCharm + WebStorm trial, enable Junie.
- [ ] Join C9 Discord office hours; ask if aggregated heatmap JSON in a public demo is OK.

## Submission checklist
Public repo + LICENSE (MIT) · live demo URL · ≤3 min YouTube video · methodology write-up ·
JetBrains tooling explanation · AI_SHOWCASE.md.
