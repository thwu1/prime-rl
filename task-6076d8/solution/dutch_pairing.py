#!/usr/bin/env python3
"""
FIDE Dutch Swiss System (C.04.3, eff. 2026-02-01) pairing engine.
Reads tournament data from trf2json JSON output and SQLite database.

"""

import json
import sqlite3
import argparse
from itertools import permutations, combinations


def load_trf_json(path):
    with open(path) as f:
        return json.load(f)


def query_forbidden_pairs(db_path):
    """Query forbidden_pairs table from SQLite database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT player_a, player_b FROM forbidden_pairs")
    pairs = set()
    for row in c.fetchall():
        pairs.add((min(row[0], row[1]), max(row[0], row[1])))
    conn.close()
    return pairs


def convert_trf_players(trf_data, total_rounds, current_round):
    """Convert trf2json player data to internal format with float history."""
    players_raw = trf_data["players"]

    # Build per-round result values
    round_results = {}
    for p in players_raw:
        tpn = p["tpn"]
        round_results[tpn] = [r["result_value"] for r in p["rounds"]]

    # Cumulative scores after each round
    cumul = {}
    for tpn, results in round_results.items():
        cum = []
        s = 0.0
        for rv in results:
            s += rv
            cum.append(s)
        cumul[tpn] = cum

    # Extract pairings per round
    pairings_by_round = {}
    for p in players_raw:
        tpn = p["tpn"]
        for r in p["rounds"]:
            rnd = r["round"]
            opp = r["opponent"]
            if opp == 0:
                continue
            pairings_by_round.setdefault(rnd, set())
            pairings_by_round[rnd].add(tuple(sorted([tpn, opp])))

    # Compute float history
    downfloat_rounds = {p["tpn"]: [] for p in players_raw}
    upfloat_rounds = {p["tpn"]: [] for p in players_raw}

    for rnd in sorted(pairings_by_round.keys()):
        for (a, b) in pairings_by_round[rnd]:
            if rnd == 1:
                sa, sb = 0.0, 0.0
            else:
                sa = cumul.get(a, [0.0] * rnd)[rnd - 2]
                sb = cumul.get(b, [0.0] * rnd)[rnd - 2]
            if sa > sb:
                downfloat_rounds[a].append(rnd)
                upfloat_rounds[b].append(rnd)
            elif sb > sa:
                downfloat_rounds[b].append(rnd)
                upfloat_rounds[a].append(rnd)

    # Build internal format
    players = []
    for p in players_raw:
        tpn = p["tpn"]
        players.append({
            "tpn": tpn,
            "name": p.get("name", ""),
            "rating": p.get("rating", 0),
            "score": p["score"],
            "colours": [r["colour"] for r in p["rounds"]],
            "opponents": [r["opponent"] for r in p["rounds"]],
            "had_bye": any(r["opponent"] == 0 for r in p["rounds"]),
            "downfloat_rounds": downfloat_rounds[tpn],
            "upfloat_rounds": upfloat_rounds[tpn],
        })

    return {
        "current_round": current_round,
        "total_rounds": total_rounds,
        "players": players,
    }


# ---- Core FIDE Dutch System algorithm ----

def sort_key(p):
    """Article 1.2: score desc, TPN asc."""
    return (-p["score"], p["tpn"])


def colour_diff(p):
    """Article 1.6."""
    return sum(1 for c in p["colours"] if c == "W") - \
           sum(1 for c in p["colours"] if c == "B")


def colour_pref(p):
    """Article 1.7. Returns (type, colour)."""
    played = [c for c in p["colours"] if c is not None]
    if not played:
        return ("none", None)
    cd = colour_diff(p)
    if cd > 1:
        return ("absolute", "B")
    if cd < -1:
        return ("absolute", "W")
    if len(played) >= 2 and played[-1] == played[-2]:
        return ("absolute", "W" if played[-1] == "B" else "B")
    if cd == 1:
        return ("strong", "B")
    if cd == -1:
        return ("strong", "W")
    return ("mild", "B" if played[-1] == "W" else "W")


def pref_strength(ptype):
    return {"absolute": 3, "strong": 2, "mild": 1, "none": 0}[ptype]


def is_topscorer(p, total_rounds, current_round):
    if current_round != total_rounds:
        return False
    max_score = current_round - 1
    return p["score"] > max_score / 2


def can_pair(p1, p2, total_rounds, current_round, forbidden=None):
    """Check absolute criteria C1, C3, and forbidden pairs."""
    if p2["tpn"] in p1["opponents"]:
        return False
    if forbidden:
        pair_key = (min(p1["tpn"], p2["tpn"]), max(p1["tpn"], p2["tpn"]))
        if pair_key in forbidden:
            return False
    ts1 = is_topscorer(p1, total_rounds, current_round)
    ts2 = is_topscorer(p2, total_rounds, current_round)
    if not ts1 and not ts2:
        pr1 = colour_pref(p1)
        pr2 = colour_pref(p2)
        if pr1[0] == "absolute" and pr2[0] == "absolute" and pr1[1] == pr2[1]:
            return False
    return True


def allocate_colour(p1, p2):
    """Article 5. p1 is higher-ranked. Returns (white_tpn, black_tpn)."""
    pr1 = colour_pref(p1)
    pr2 = colour_pref(p2)
    # 5.2.1: Grant both
    if pr1[1] and pr2[1] and pr1[1] != pr2[1]:
        return (p1["tpn"], p2["tpn"]) if pr1[1] == "W" else (p2["tpn"], p1["tpn"])
    # 5.2.2: Grant stronger
    s1, s2 = pref_strength(pr1[0]), pref_strength(pr2[0])
    if s1 != s2:
        winner = (pr1, p1, p2) if s1 > s2 else (pr2, p2, p1)
        pref, pw, po = winner
        if pref[1] == "W":
            return (pw["tpn"], po["tpn"])
        else:
            return (po["tpn"], pw["tpn"])
    if s1 == 3 and s2 == 3:
        cd1, cd2 = abs(colour_diff(p1)), abs(colour_diff(p2))
        if cd1 != cd2:
            winner = (pr1, p1, p2) if cd1 > cd2 else (pr2, p2, p1)
            pref, pw, po = winner
            if pref[1] == "W":
                return (pw["tpn"], po["tpn"])
            else:
                return (po["tpn"], pw["tpn"])
    # 5.2.3: Alternate to most recent divergence
    pl1 = [c for c in p1["colours"] if c is not None]
    pl2 = [c for c in p2["colours"] if c is not None]
    for i in range(1, min(len(pl1), len(pl2)) + 1):
        c1, c2 = pl1[-i], pl2[-i]
        if c1 != c2:
            if c1 == "W":
                return (p2["tpn"], p1["tpn"])
            else:
                return (p1["tpn"], p2["tpn"])
    # 5.2.4: Grant higher-ranked player's preference
    if pr1[1]:
        return (p1["tpn"], p2["tpn"]) if pr1[1] == "W" else (p2["tpn"], p1["tpn"])
    # 5.2.5: Odd TPN gets initial colour (White)
    if p1["tpn"] % 2 == 1:
        return (p1["tpn"], p2["tpn"])
    return (p2["tpn"], p1["tpn"])


def make_pair(a, b):
    higher = a if sort_key(a) < sort_key(b) else b
    lower = b if higher is a else a
    w, bk = allocate_colour(higher, lower)
    return (w, bk)


def eval_candidate(pairs, downfloaters, pby, current_round, total_rounds):
    c10 = c11 = c12 = c13 = c14 = c15 = c16 = c17 = 0
    for (w, b) in pairs:
        pw, pb = pby[w], pby[b]
        for player, assigned in [(pw, "W"), (pb, "B")]:
            pr = colour_pref(player)
            if pr[1] and pr[1] != assigned:
                c12 += 1
                if pr[0] in ("absolute", "strong"):
                    c13 += 1
            cd = colour_diff(player)
            new_cd = cd + (1 if assigned == "W" else -1)
            if abs(new_cd) > 2:
                c10 += 1
            played = [c for c in player["colours"] if c is not None]
            if len(played) >= 2 and played[-1] == played[-2] == assigned:
                c11 += 1
    for d in downfloaters:
        dr = d.get("downfloat_rounds", [])
        if (current_round - 1) in dr:
            c14 += 1
        if (current_round - 2) in dr:
            c16 += 1
    num_df = len(downfloaters)
    df_scores = sorted([d["score"] for d in downfloaters], reverse=True)
    return (num_df, tuple(df_scores), c10, c11, c12, c13, c14, c15, c16, c17)


def pair_homogeneous(players, pby, current_round, total_rounds, is_last,
                     forbidden=None):
    players = sorted(players, key=sort_key)
    n = len(players)
    if n == 0:
        return ([], [], None)
    if n == 1:
        return ([], [], players[0]) if is_last else ([], players[:], None)
    max_pairs = n // 2
    best = None
    best_ev = None

    for n_ex in range(max_pairs + 1):
        s1_orig = list(range(max_pairs))
        s2_orig = list(range(max_pairs, n))
        if n_ex == 0:
            ex_list = [None]
        else:
            ex_list = []
            for s1o in combinations(s1_orig, n_ex):
                for s2i in combinations(s2_orig, n_ex):
                    ex_list.append((s1o, s2i))

            def ex_key(ex):
                s1o, s2i = ex
                return (len(s1o), sum(s2i) - sum(s1o),
                        tuple(sorted(s1o, reverse=True)),
                        tuple(sorted(s2i)))
            ex_list.sort(key=ex_key)

        for ex in ex_list:
            if ex is None:
                s1_idx = set(range(max_pairs))
                s2_idx = set(range(max_pairs, n))
            else:
                s1o, s2i = ex
                s1_idx = (set(range(max_pairs)) - set(s1o)) | set(s2i)
                s2_idx = (set(range(max_pairs, n)) - set(s2i)) | set(s1o)
            s1 = sorted([players[i] for i in s1_idx], key=sort_key)
            s2_all = sorted([players[i] for i in s2_idx], key=sort_key)

            s2_pair = s2_all[:max_pairs] if len(s2_all) >= max_pairs else s2_all[:]
            n_perm = len(s2_pair)
            if n_perm > 7:
                perm_indices = list(permutations(range(n_perm)))[:5040]
            else:
                perm_indices = list(permutations(range(n_perm)))

            for perm in perm_indices:
                s2_ordered = [s2_pair[i] for i in perm]
                pairs = []
                valid = True
                for i in range(min(len(s1), len(s2_ordered))):
                    if not can_pair(s1[i], s2_ordered[i], total_rounds,
                                    current_round, forbidden):
                        valid = False
                        break
                    pairs.append(make_pair(s1[i], s2_ordered[i]))
                if not valid:
                    continue
                paired_tpns = set()
                for w, b in pairs:
                    paired_tpns.add(w)
                    paired_tpns.add(b)
                dfs = [p for p in players if p["tpn"] not in paired_tpns]
                bye_p = None
                if is_last and len(dfs) == 1:
                    bye_p = dfs[0]
                    dfs = []
                ev = eval_candidate(pairs, dfs, pby, current_round, total_rounds)
                if best_ev is None or ev < best_ev:
                    best_ev = ev
                    best = (pairs[:], dfs[:], bye_p)
                if best_ev[4] == 0 and best_ev[0] <= 1:
                    break
            if best and best_ev[4] == 0 and best_ev[0] <= 1 and n_ex == 0:
                break
        if best and best_ev[0] == 0:
            break
    return best if best else ([], players[:], None)


def pair_bracket(residents, mdps, pby, current_round, total_rounds, is_last,
                 forbidden=None):
    if not residents and not mdps:
        return ([], [], None)
    all_players = mdps + residents
    if len(all_players) == 1:
        return ([], [], all_players[0]) if is_last else ([], all_players[:], None)

    m0 = len(mdps)
    if m0 == 0:
        return pair_homogeneous(all_players, pby, current_round, total_rounds,
                                is_last, forbidden)

    max_pairs_total = min(len(all_players) // 2, len(residents)) if residents else 0
    if max_pairs_total == 0:
        return ([], all_players[:], None)

    m1 = min(m0, max_pairs_total, len(residents))
    residents_sorted = sorted(residents, key=sort_key)
    mdps_sorted = sorted(mdps, key=sort_key)

    best = None
    best_ev = None

    if m1 < m0:
        mdp_sets = list(combinations(range(m0), m1))
    else:
        mdp_sets = [tuple(range(m0))]

    for mdp_indices in mdp_sets:
        s1 = [mdps_sorted[i] for i in mdp_indices]
        limbo = [mdps_sorted[i] for i in range(m0) if i not in mdp_indices]

        if len(residents_sorted) > 7:
            perms = list(permutations(range(len(residents_sorted))))[:5040]
        else:
            perms = list(permutations(range(len(residents_sorted))))

        for perm in perms:
            s2_ordered = [residents_sorted[i] for i in perm]
            mdp_pairs = []
            valid = True
            used = set()
            for i in range(m1):
                if i >= len(s2_ordered):
                    valid = False
                    break
                if not can_pair(s1[i], s2_ordered[i], total_rounds,
                                current_round, forbidden):
                    valid = False
                    break
                mdp_pairs.append(make_pair(s1[i], s2_ordered[i]))
                used.add(s2_ordered[i]["tpn"])
            if not valid:
                continue

            remainder = [p for p in residents_sorted if p["tpn"] not in used]
            if remainder:
                rem_pairs, rem_dfs, rem_bye = pair_homogeneous(
                    remainder, pby, current_round, total_rounds, is_last,
                    forbidden)
            else:
                rem_pairs, rem_dfs, rem_bye = [], [], None

            all_pairs = mdp_pairs + rem_pairs
            all_dfs = limbo + rem_dfs
            bye_p = rem_bye

            ev = eval_candidate(all_pairs, all_dfs, pby, current_round,
                                total_rounds)
            if best_ev is None or ev < best_ev:
                best_ev = ev
                best = (all_pairs[:], all_dfs[:], bye_p)
            if best_ev[4] == 0 and best_ev[0] <= len(limbo):
                break
        if best and best_ev[4] == 0:
            break

    if best:
        return best
    rem_pairs, rem_dfs, rem_bye = pair_homogeneous(
        residents_sorted, pby, current_round, total_rounds, is_last, forbidden)
    return (rem_pairs, mdps + rem_dfs, rem_bye)


def compute_pairing(tournament, forbidden=None):
    players = tournament["players"]
    current_round = tournament["current_round"]
    total_rounds = tournament["total_rounds"]
    pby = {p["tpn"]: p for p in players}

    sg = {}
    for p in sorted(players, key=sort_key):
        s = p["score"]
        sg.setdefault(s, []).append(p)
    scores = sorted(sg.keys(), reverse=True)

    all_pairs = []
    mdps = []
    bye_player = None

    for idx, score in enumerate(scores):
        is_last = (idx == len(scores) - 1)
        residents = sg[score]
        pairs, new_mdps, bye_p = pair_bracket(
            residents, mdps, pby, current_round, total_rounds, is_last,
            forbidden)
        all_pairs.extend(pairs)
        mdps = new_mdps
        if bye_p:
            if not bye_p.get("had_bye", False):
                bye_player = bye_p
                mdps = [m for m in mdps if m["tpn"] != bye_p["tpn"]]
            else:
                mdps.append(bye_p)

    if mdps and not bye_player and len(players) % 2 == 1:
        for p in sorted(mdps, key=lambda x: (x["score"], -x["tpn"])):
            if not p.get("had_bye", False):
                bye_player = p
                mdps.remove(p)
                break

    def pair_sort_key(pair):
        w, b = pair
        pw, pb = pby[w], pby[b]
        higher = pw if sort_key(pw) < sort_key(pb) else pb
        return (sort_key(higher), higher["tpn"])

    all_pairs.sort(key=pair_sort_key)

    return {
        "pairings": [{"white": w, "black": b} for w, b in all_pairs],
        "bye": bye_player["tpn"] if bye_player else None,
    }


def main():
    parser = argparse.ArgumentParser(
        description='FIDE Dutch Swiss Pairing Engine')
    parser.add_argument('--trf-json', required=True,
                        help='Path to trf2json --full output JSON')
    parser.add_argument('--total-rounds', type=int, required=True,
                        help='Authoritative total number of rounds')
    parser.add_argument('--current-round', type=int, required=True,
                        help='Current round number to pair')
    parser.add_argument('--initial-colour', default='W',
                        help='Initial colour for odd-numbered players')
    parser.add_argument('--db', required=True,
                        help='Path to SQLite database for forbidden pairs')
    parser.add_argument('--output', required=True,
                        help='Path to write output JSON')

    args = parser.parse_args()

    trf_data = load_trf_json(args.trf_json)
    forbidden = query_forbidden_pairs(args.db)
    if forbidden:
        print(f"Found {len(forbidden)} forbidden pair(s)")

    tournament = convert_trf_players(
        trf_data, args.total_rounds, args.current_round)

    result = compute_pairing(tournament, forbidden)

    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
