"""C9 Scout engine: GRID VALORANT feeds -> aggregated scouting JSON for the web UI.

Only binned counts and per-team summaries leave this script. No raw events or
per-event rows are written, so the output is safe to publish under the data license.

Usage: python3.14 engine/scout.py --data ../stl-hackathon-2026-grid-starter --out web/data
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

try:
    from compression import zstd  # Python 3.14+
except ImportError:  # shortcut: older Pythons need `pip install zstandard`
    import zstandard as zstd

GRID = 64        # heatmap cells per axis
ZONE = 10        # coarse zones per axis, used for "x% of rounds" insights
SIL = 128        # map silhouette resolution
MIN_ROUNDS = 15  # fail closed: no insight below this many rounds
SNIPERS = ("operator", "outlaw", "marshal", "odin")  # high-impact long-range weapons we profile
WANTED = ('"game-started-round"', '"round-ended-freezetime"', '"player-used-ability"',
          '"player-damaged-player"', 'started-game"')  # also matches series-!started-game (rollback)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def phase(t):
    """Round-time bucket: 0 = buy phase, 1 = 0-20s, 2 = 20-40s, 3 = 40s+."""
    if t is None or t < 0:
        return 0
    return 1 if t < 20 else 2 if t < 40 else 3


def cell(x, y, b, n):
    (x0, y0), (x1, y1) = b
    ix = int((x - x0) / (x1 - x0) * n)
    iy = int((y - y0) / (y1 - y0) * n)
    return min(max(ix, 0), n - 1), min(max(iy, 0), n - 1)


def read_jsonl(path):
    with zstd.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield line


def supplement_positions(path):
    """grid_event_id -> (x, y, view_x, view_y) using the best frame per the supplement README."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    for line in read_jsonl(path):
        c = json.loads(line)
        if not c.get("in_grid"):
            continue
        q = c["quality"]
        if q == "gap_exceeded":
            fr = [f for f in (c["frame_before"], c["frame_after"]) if f]
            src = min(fr, key=lambda f: abs(f["offset_ms"])) if fr else None
        else:
            src = c.get("interpolated")
        if src:
            p, v = src["position"], src["view"]
            out[c["grid_event_id"]] = (p["x"], p["y"], v["x"], v["y"])
    return out


def parse_series(feed, supp):
    """Return compact per-series records (kept in memory only, never written)."""
    pos = supplement_positions(supp)
    games, teams, players = {}, {}, {}
    rolled_back = set()
    rounds, casts, op_rounds, op_fights, sil = [], [], [], [], Counter()
    g = None          # current game id
    rnd = 0
    t0 = None         # freezetime end of current round
    roster = {}       # player id -> (team id, agent, side)
    op_seen = set()   # (game, round, player) first Op engagement already recorded

    for line in read_jsonl(feed):
        if not any(w in line for w in WANTED):
            continue
        env = json.loads(line)
        at = ts(env["occurredAt"])
        for e in env["events"]:
            t = e["type"]
            if t == "series-!started-game":
                rolled_back.add(e["target"]["id"])
            elif t == "series-started-game":
                g, rnd, t0 = e["target"]["id"], 0, None
            elif t == "game-started-round" and e.get("includesFullState"):
                gs = e["actor"]["state"]
                g = gs["id"]
                m = gs["map"]
                b = ((m["bounds"]["min"]["x"], m["bounds"]["min"]["y"]),
                     (m["bounds"]["max"]["x"], m["bounds"]["max"]["y"]))
                games[g] = (m["name"], b)
                rnd += 1
                t0 = None
                roster = {}
                for tm in gs["teams"]:
                    teams[tm["id"]] = tm["name"]
                    agents = []
                    for p in tm.get("players", []):
                        players[p["id"]] = p["name"]
                        agent = (p.get("character") or {}).get("id", "?")
                        roster[p["id"]] = (tm["id"], agent, tm["side"])
                        agents.append(agent)
                    rounds.append((g, rnd, tm["id"], tm["side"], tuple(agents)))
            elif t == "round-ended-freezetime" and g in games:
                t0 = at
                gs = (e.get("seriesState") or {}).get("games", [{}])[-1]
                for tm in gs.get("teams", []):
                    for p in tm.get("players", []):
                        items = {i["id"] for i in (p.get("inventory") or {}).get("items", [])}
                        for w in SNIPERS:
                            if w in items and p["id"] in roster:
                                team, agent, side = roster[p["id"]]
                                op_rounds.append((g, rnd, team, p["id"], agent, side, w))
            elif t == "player-used-ability" and g in games:
                pid = e["actor"]["id"]
                if pid not in roster:
                    continue
                team, agent, side = roster[pid]
                if e["id"] in pos:
                    x, y, vx, vy = pos[e["id"]]
                else:
                    gp = e["actor"]["state"].get("game", {}).get("position")
                    if not gp:
                        continue
                    x, y, vx, vy = gp["x"], gp["y"], 0.0, 0.0
                tr = at - t0 if t0 else None
                casts.append((g, rnd, team, pid, agent, side, e["target"]["id"], x, y, vx, vy, phase(tr)))
            elif t == "player-damaged-player" and g in games:
                pid = e["actor"]["id"]
                if pid not in roster:
                    continue
                d = e["actor"].get("stateDelta", {}).get("round", {})
                srcs = {s["source"]["name"] for s in d.get("damageDealtSources", [])}
                gp = e["actor"]["state"].get("game", {}).get("position")
                for w in srcs.intersection(SNIPERS):
                    if not gp or (g, rnd, pid, w) in op_seen:
                        continue
                    op_seen.add((g, rnd, pid, w))
                    team, agent, side = roster[pid]
                    tr = at - t0 if t0 else None
                    op_fights.append((g, rnd, team, pid, agent, side, gp["x"], gp["y"], tr, w))
            # every actor position sketches the map silhouette
            if g in games:
                gp = (e.get("actor") or {}).get("state", {}).get("game", {}).get("position")
                if gp:
                    sil[(games[g][0],) + cell(gp["x"], gp["y"], games[g][1], SIL)] += 1

    keep = lambda r: r[0] not in rolled_back
    return {
        "games": {k: v for k, v in games.items() if k not in rolled_back},
        "teams": teams, "players": players,
        "rounds": list(filter(keep, rounds)), "casts": list(filter(keep, casts)),
        "op_rounds": list(filter(keep, op_rounds)), "op_fights": list(filter(keep, op_fights)),
        "sil": sil,
    }


def _job(args):
    sid, feed, supp, meta = args
    try:
        r = parse_series(feed, supp)
    except Exception as ex:  # one bad feed must not kill the run
        print(f"skip {sid}: {ex!r}", file=sys.stderr)
        return None
    r["meta"] = meta
    return aggregate_series(r)


def nest():
    return defaultdict(nest)


def aggregate_series(r):
    """Reduce one series to counters keyed by team. Only these counters cross processes."""
    games = r["games"]
    out = {"teams": r["teams"], "players": r["players"], "bounds": {}, "sil": Counter(),
           "t": defaultdict(lambda: {"rounds": Counter(), "agent_rounds": Counter(),
                                     "cells": Counter(), "zone_rounds": defaultdict(set),
                                     "aim": defaultdict(lambda: [0.0, 0.0]),
                                     "op_rounds": Counter(), "op_holders": Counter(),
                                     "op_cells": Counter(), "op_zone_phase": Counter(),
                                     "op_fights": Counter(), "series": set()})}
    sid = r["meta"]["series_id"]
    for name, b in games.values():
        out["bounds"][name] = b
    for (m, ix, iy), n in r["sil"].items():
        out["sil"][(m, ix, iy)] += n
    for g, rnd, team, side, agents in r["rounds"]:
        m = games[g][0]
        T = out["t"][team]
        T["rounds"][(m, side)] += 1
        T["series"].add(sid)
        for a in set(agents):
            T["agent_rounds"][(m, side, a)] += 1
    for c in r["casts"]:
        g, rnd, team, pid, agent, side, ab, x, y, vx, vy, ph = c
        m, b = games[g]
        T = out["t"][team]
        ix, iy = cell(x, y, b, GRID)
        T["cells"][(m, side, agent, ab, ix, iy, ph)] += 1
        zx, zy = cell(x, y, b, ZONE)
        T["zone_rounds"][(m, side, agent, ab, zx, zy)].add(f"{sid}/{g}/{rnd}")
        a = T["aim"][(m, side, agent, ab, ix, iy)]
        a[0] += vx
        a[1] += vy
    for g, rnd, team, pid, agent, side, w in r["op_rounds"]:
        m = games[g][0]
        T = out["t"][team]
        T["op_rounds"][(m, side, w, f"{g}/{rnd}")] += 1
        T["op_holders"][(m, side, w, pid, agent)] += 1
    for g, rnd, team, pid, agent, side, x, y, tr, w in r["op_fights"]:
        m, b = games[g]
        T = out["t"][team]
        ix, iy = cell(x, y, b, GRID)
        ph = phase(tr)
        T["op_cells"][(m, side, w, pid, ix, iy, ph)] += 1
        zx, zy = cell(x, y, b, ZONE)
        T["op_zone_phase"][(m, side, w, pid, zx, zy, ph)] += 1
        T["op_fights"][(m, side, w, pid)] += 1
    # sets/defaultdict-of-lambda are not picklable: convert
    for T in out["t"].values():
        T["zone_rounds"] = {k: len(v) for k, v in T["zone_rounds"].items()}
        T["aim"] = dict(T["aim"])
        T["op_rounds"] = Counter((m, s, w) for (m, s, w, _) in T["op_rounds"])
    out["t"] = dict(out["t"])
    return out


def merge(acc, part):
    acc["teams"].update(part["teams"])
    acc["players"].update(part["players"])
    acc["bounds"].update(part["bounds"])
    acc["sil"].update(part["sil"])
    for team, T in part["t"].items():
        A = acc["t"].setdefault(team, {k: (set() if k == "series" else Counter()) for k in T})
        for k, v in T.items():
            if k == "series":
                A[k] |= v
            elif k == "aim":
                for kk, (ax, ay) in v.items():
                    cur = A[k].get(kk, (0.0, 0.0))
                    A[k][kk] = (cur[0] + ax, cur[1] + ay)
            else:
                A[k].update(v)


ZONE_COLS = "ABCDEFGHIJ"


def zone_name(zx, zy):
    return f"{ZONE_COLS[zx]}{ZONE - zy}"  # y up in game units -> row 10 at top


def team_insights(name, T, players, sentinel_first):
    """Deterministic sentences, each with its sample size. Below MIN_ROUNDS: nothing."""
    out = []
    for (m, side, agent, ab, zx, zy), k in T["zone_rounds"].items():
        n = T["agent_rounds"].get((m, side, agent), 0)
        if n < MIN_ROUNDS or k / n < 0.35:
            continue
        out.append({"kind": "utility", "map": m, "side": side, "agent": agent, "ability": ab,
                    "zone": [zx, zy], "k": k, "n": n, "pct": round(100 * k / n),
                    "priority": 0 if (agent in sentinel_first) else 1,
                    "text": f"{name} {agent} uses {ab} in zone {zone_name(zx, zy)} on {m.title()} "
                            f"({side}) in {round(100 * k / n)}% of rounds ({k}/{n})."})
    for (m, side, w), k in T["op_rounds"].items():
        n = T["rounds"].get((m, side), 0)
        if n < MIN_ROUNDS or k < 3:
            continue
        holders = [(pid, ag, c) for (mm, ss, ww, pid, ag), c in T["op_holders"].items() if (mm, ss, ww) == (m, side, w)]
        pid, ag, c = max(holders, key=lambda h: h[2])
        fights = T["op_fights"].get((m, side, w, pid), 0)
        W = w.title()
        text = (f"{name} has an {W} in {round(100 * k / n)}% of {side} rounds on {m.title()} ({k}/{n}); "
                f"main holder {players.get(pid, pid)} ({ag}) in {c} of them.")
        zones = Counter()
        early = 0
        for (mm, ss, ww, p, zx, zy, ph), cc in T["op_zone_phase"].items():
            if (mm, ss, ww, p) == (m, side, w, pid):
                zones[(zx, zy)] += cc
                early += cc if ph <= 1 else 0
        if fights >= 5 and zones:
            (zx, zy), zc = zones.most_common(1)[0]
            text += (f" First {W} fight in zone {zone_name(zx, zy)} {round(100 * zc / fights)}% of the time; "
                     f"{round(100 * early / fights)}% within the first 20s ({fights} fights).")
        out.append({"kind": "operator", "weapon": w, "map": m, "side": side, "player": players.get(pid, pid),
                    "pid": pid, "agent": ag, "k": k, "n": n, "pct": round(100 * k / n), "priority": 0, "text": text})
    out.sort(key=lambda i: (i["priority"], -i["pct"] * min(i["n"], 60)))
    return out[:40]


SENTINELS = {"cypher", "killjoy", "chamber", "sage", "deadlock", "vyse"}


def write_output(acc, out_dir):
    out_dir = Path(out_dir)
    (out_dir / "teams").mkdir(parents=True, exist_ok=True)
    (out_dir / "maps").mkdir(parents=True, exist_ok=True)
    players = acc["players"]
    # map silhouettes
    sil = defaultdict(list)
    for (m, ix, iy), n in acc["sil"].items():
        sil[m].append([ix, iy, n])
    for m, cells in sil.items():
        (out_dir / "maps" / f"{m}.json").write_text(json.dumps(
            {"map": m, "n": SIL, "bounds": acc["bounds"][m], "cells": cells}))
    index = []
    for team, T in acc["t"].items():
        name = acc["teams"].get(team, team)
        total = sum(T["rounds"].values())
        if total < MIN_ROUNDS:
            continue
        doc = {"id": team, "name": name, "grid": GRID, "zone": ZONE,
               "series": len(T["series"]), "rounds": nest(), "agentRounds": nest(),
               "casts": nest(), "zones": nest(), "op": nest()}
        for (m, s, a, ab, zx, zy), k in T["zone_rounds"].items():
            doc["zones"][m][s][a].setdefault(ab, []).append([zx, zy, k])
        for (m, s), n in T["rounds"].items():
            doc["rounds"][m][s] = n
        for (m, s, a), n in T["agent_rounds"].items():
            doc["agentRounds"][m][s][a] = n
        for (m, s, a, ab, ix, iy, ph), n in T["cells"].items():
            lst = doc["casts"][m][s][a].setdefault(ab, [])
            ax, ay = T["aim"].get((m, s, a, ab, ix, iy), (0.0, 0.0))
            lst.append([ix, iy, ph, n, round(ax, 2), round(ay, 2)])
        for (m, s, w), k in T["op_rounds"].items():
            doc["op"][m][s][w]["opRounds"] = k
        for (m, s, w, pid, ag), c in T["op_holders"].items():
            doc["op"][m][s][w].setdefault("holders", []).append(
                {"player": players.get(pid, pid), "pid": pid, "agent": ag, "rounds": c})
        for (m, s, w, pid, ix, iy, ph), n in T["op_cells"].items():
            doc["op"][m][s][w].setdefault("cells", []).append([pid, ix, iy, ph, n])
        doc["insights"] = team_insights(name, T, players, SENTINELS)
        (out_dir / "teams" / f"{team}.json").write_text(json.dumps(doc, separators=(",", ":")))
        index.append({"id": team, "name": name, "series": len(T["series"]), "rounds": total,
                      "maps": sorted({m for m, _ in T["rounds"]})})
    index.sort(key=lambda t: (-("Cloud9" in t["name"]), -t["rounds"]))
    (out_dir / "index.json").write_text(json.dumps(
        {"teams": index, "maps": sorted(sil), "grid": GRID, "zone": ZONE,
         "generated": datetime.now().strftime("%Y-%m-%d")}))
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get("STL_DATA_DIR", "../stl-hackathon-2026-grid-starter"))
    ap.add_argument("--out", default="web/data")
    ap.add_argument("--limit", type=int, default=0, help="only parse first N series (dev)")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    a = ap.parse_args()
    data = Path(a.data)
    jobs = []
    with open(data / "val" / "series.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            feed = data / row["file"]
            if not feed.exists():
                continue
            supp = data / row["ability_supplement"] if row["ability_supplement"] else None
            jobs.append((row["series_id"], str(feed), str(supp) if supp else None, row))
    if a.limit:
        jobs = jobs[: a.limit]
    acc = {"teams": {}, "players": {}, "bounds": {}, "sil": Counter(), "t": {}}
    with ProcessPoolExecutor(a.workers) as ex:
        for i, part in enumerate(ex.map(_job, jobs), 1):
            if part:
                merge(acc, part)
            print(f"\r{i}/{len(jobs)} series", end="", file=sys.stderr)
    print(file=sys.stderr)
    index = write_output(acc, a.out)
    print(f"wrote {len(index)} teams, {len(acc['bounds'])} maps -> {a.out}")


if __name__ == "__main__":
    main()
