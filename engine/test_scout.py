"""Engine self-check on a tiny hand-made feed (no GRID data needed). Run: python3.14 -m unittest engine/test_scout.py"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import scout  # noqa: E402

BOUNDS = {"min": {"x": -5000, "y": -5000}, "max": {"x": 5000, "y": 5000}}


def player(pid, name, agent, inv=()):
    return {"id": pid, "name": name, "character": {"id": agent},
            "inventory": {"items": [{"id": i} for i in inv]}}


def env(t, events):
    return {"occurredAt": t, "events": events}


def feed_lines(rollback=False):
    teams = [{"id": "A", "name": "Alpha", "side": "defender", "players": [player("p1", "sniper", "chamber")]},
             {"id": "B", "name": "Beta", "side": "attacker", "players": [player("p2", "smoker", "omen")]}]
    teams_fz = [dict(teams[0], players=[player("p1", "sniper", "chamber", ["operator"])]), teams[1]]
    lines = [
        env("2025-01-01T00:00:00Z", [{"type": "series-started-game", "target": {"id": "g1"}}]),
        env("2025-01-01T00:00:01Z", [{"type": "game-started-round", "includesFullState": True,
                                      "actor": {"state": {"id": "g1", "map": {"name": "testmap", "bounds": BOUNDS},
                                                          "teams": teams}}}]),
        env("2025-01-01T00:00:31Z", [{"type": "round-ended-freezetime", "includesFullState": True,
                                      "seriesState": {"games": [{"teams": teams_fz}]}}]),
        # trapwire-like cast 5s into the round at (1000, 1000), aiming +x
        env("2025-01-01T00:00:36Z", [{"id": "ev1", "type": "player-used-ability", "target": {"id": "trademark"},
                                      "actor": {"id": "p1", "state": {"game": {"position": {"x": 999, "y": 999}}}}}]),
        # first Operator hit 25s into the round at (-2000, 0)
        env("2025-01-01T00:00:56Z", [{"type": "player-damaged-player",
                                      "actor": {"id": "p1", "state": {"game": {"position": {"x": -2000, "y": 0}}},
                                                "stateDelta": {"round": {"damageDealtSources": [{"source": {"name": "operator"}}]}}}}]),
        # second Operator hit same round must not count as another "first fight"
        env("2025-01-01T00:00:58Z", [{"type": "player-damaged-player",
                                      "actor": {"id": "p1", "state": {"game": {"position": {"x": 3000, "y": 0}}},
                                                "stateDelta": {"round": {"damageDealtSources": [{"source": {"name": "operator"}}]}}}}]),
    ]
    if rollback:
        lines.append(env("2025-01-01T00:01:00Z", [{"type": "series-!started-game", "target": {"id": "g1"}}]))
    return lines


def write_zst(path, rows):
    with scout.zstd.open(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


class EngineTest(unittest.TestCase):
    def run_feed(self, rollback=False):
        with tempfile.TemporaryDirectory() as d:
            feed, supp = Path(d) / "f.jsonl.zst", Path(d) / "s.jsonl.zst"
            write_zst(feed, feed_lines(rollback))
            write_zst(supp, [{"in_grid": True, "grid_event_id": "ev1", "quality": "ok",
                              "interpolated": {"position": {"x": 1000, "y": 1000, "z": 0}, "view": {"x": 1, "y": 0, "z": 0}}}])
            r = scout.parse_series(str(feed), str(supp))
            r["meta"] = {"series_id": "s1"}
            return r, scout.aggregate_series(r)

    def test_cast_uses_supplement_position_and_round_time(self):
        r, agg = self.run_feed()
        (c,) = r["casts"]
        self.assertEqual((c[7], c[8], c[9]), (1000, 1000, 1))  # supplement pos + aim, not GRID's 999
        self.assertEqual(c[-1], 1)  # 5s after freezetime -> 0-20s bucket
        A = agg["t"]["A"]
        self.assertEqual(A["agent_rounds"][("testmap", "defender", "chamber")], 1)
        self.assertEqual(A["zone_rounds"][("testmap", "defender", "chamber", "trademark", 6, 6)], 1)

    def test_operator_round_and_first_fight_only(self):
        r, agg = self.run_feed()
        self.assertEqual(len(r["op_rounds"]), 1)
        self.assertEqual(len(r["op_fights"]), 1)
        A = agg["t"]["A"]
        self.assertEqual(A["op_rounds"][("testmap", "defender", "operator")], 1)
        ix, iy = scout.cell(-2000, 0, ((-5000, -5000), (5000, 5000)), scout.GRID)
        self.assertEqual(A["op_cells"][("testmap", "defender", "operator", "p1", ix, iy, 2)], 1)  # 25s -> 20-40s

    def test_rolled_back_game_is_dropped(self):
        r, _ = self.run_feed(rollback=True)
        self.assertEqual((r["rounds"], r["casts"], r["op_fights"]), ([], [], []))

    def test_insights_fail_closed_below_min_rounds(self):
        _, agg = self.run_feed()
        self.assertEqual(scout.team_insights("Alpha", agg["t"]["A"], {}, scout.SENTINELS), [])


if __name__ == "__main__":
    unittest.main()
