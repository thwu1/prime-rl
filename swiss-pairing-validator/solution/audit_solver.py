#!/usr/bin/env python3
"""
FIDE Dutch System Swiss Pairing Auditor.
Reads tournament state from SQLite database, generates a valid FIDE TRF file,
and validates candidate pairings against FIDE Handbook C.04.3 (2026 edition).

"""
import json
import sqlite3


def load_from_db(db_path):
    """Load tournament data from SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    info = dict(conn.execute("SELECT * FROM tournament_info LIMIT 1").fetchone())
    num_rounds = info["num_rounds"]
    initial_colour = info["initial_colour"]

    players = {}
    for row in conn.execute("SELECT * FROM players ORDER BY tpn"):
        p = dict(row)
        tpn = p["tpn"]

        rounds = conn.execute(
            "SELECT round_num, opponent_tpn, colour, result "
            "FROM round_results WHERE tpn=? ORDER BY round_num", (tpn,)
        ).fetchall()

        colours = []
        opponents = []
        results_f = []
        result_chars = []

        for r in rounds:
            opponents.append(r["opponent_tpn"])
            colours.append(r["colour"].upper() if r["colour"] else None)
            result_chars.append(r["result"])
            res = r["result"]
            if res == "1":
                results_f.append(1.0)
            elif res in ("=", "d"):
                results_f.append(0.5)
            else:
                results_f.append(0.0)

        players[tpn] = {
            "tpn": tpn,
            "sex": p["sex"],
            "title": p["title"],
            "name": p["name"],
            "rating": p["rating"],
            "federation": p["federation"],
            "fide_id": p["fide_id"],
            "birth_date": p["birth_date"],
            "score": p["score"],
            "rank": p["rank"],
            "colours": colours,
            "opponents": opponents,
            "results": results_f,
            "result_chars": result_chars,
        }

    conn.close()

    # Compute float history from cumulative scores
    for tpn in players:
        players[tpn]["floats"] = [None] * num_rounds

    cumulative = {t: 0.0 for t in players}
    for rnd in range(num_rounds):
        for tpn, p in players.items():
            if rnd < len(p["opponents"]):
                opp_tpn = p["opponents"][rnd]
                if cumulative[tpn] > cumulative[opp_tpn]:
                    p["floats"][rnd] = "D"
                elif cumulative[tpn] < cumulative[opp_tpn]:
                    p["floats"][rnd] = "U"

        for tpn, p in players.items():
            if rnd < len(p["results"]):
                cumulative[tpn] += p["results"][rnd]

    return players, num_rounds, initial_colour, info


def generate_trf(players, info, num_rounds):
    """Generate a valid FIDE TRF file from tournament data."""
    lines = []
    lines.append(f"012 {info['name']}")
    lines.append(f"022 {info['city']}")
    lines.append(f"032 {info['country']}")
    lines.append(f"042 {info['start_date']}")
    lines.append(f"052 {info['end_date']}")
    lines.append(f"062 {info['num_players']}")
    lines.append(f"072 {info['num_rated']}")
    lines.append(f"082 {info['num_teams']}")
    lines.append(f"092 {info['type']}")
    lines.append(f"102 {info['chief_arbiter']}")
    lines.append(f"112 {info['deputy_arbiter']}")
    lines.append(f"122 {info['time_control']}")
    lines.append(f"132 {info['round_dates']}")
    lines.append(f"XXR {num_rounds}")
    lines.append(f"XXC {info['initial_colour']}")

    for tpn in sorted(players.keys()):
        p = players[tpn]
        sex_title = f"{p['sex']}{p['title']:<3s}"
        line = (
            f"001 {tpn:>4d} {sex_title} {p['name']:<33s} "
            f"{p['rating']:>4d} {p['federation']:<3s} "
            f"{p['fide_id']:<11s} {p['birth_date']:<10s} "
            f"{p['score']:>4.1f} {p['rank']:>4d}"
        )

        for rnd in range(num_rounds):
            if rnd < len(p["opponents"]):
                opp = p["opponents"][rnd]
                col = p["colours"][rnd].lower() if p["colours"][rnd] else "-"
                res_c = p["result_chars"][rnd]
                line += f"  {opp:>4d} {col} {res_c}"
            else:
                line += "          "

        lines.append(line)

    return "\n".join(lines) + "\n"


def compute_colour_diff(colours):
    """Article 1.6: colour difference = #White - #Black"""
    played = [c for c in colours if c is not None]
    return sum(1 for c in played if c == "W") - sum(1 for c in played if c == "B")


def get_colour_preference(colours):
    """
    Article 1.7: Determine colour preference type and preferred colour.
    Returns (type, preferred_colour).
    """
    played = [c for c in colours if c is not None]
    if not played:
        return ("none", None)

    cd = compute_colour_diff(played)

    # 1.7.1 Absolute: same colour in last two rounds, or |cd| > 1
    if len(played) >= 2 and played[-1] == played[-2]:
        pref = "B" if played[-1] == "W" else "W"
        return ("absolute", pref)
    if cd > 1:
        return ("absolute", "B")
    if cd < -1:
        return ("absolute", "W")

    # 1.7.2 Strong: |cd| == 1
    if cd == 1:
        return ("strong", "B")
    if cd == -1:
        return ("strong", "W")

    # 1.7.3 Mild: cd == 0
    if cd == 0 and played:
        pref = "B" if played[-1] == "W" else "W"
        return ("mild", pref)

    return ("none", None)


def is_topscorer(score, num_rounds):
    """Article 1.8: score > 50% of max possible score"""
    return score > num_rounds / 2.0


def determine_correct_white(p1_tpn, p2_tpn, players):
    """Article 5.2: Colour allocation cascade (5 priority levels)."""
    d1 = players[p1_tpn]
    d2 = players[p2_tpn]
    pt1, pc1 = get_colour_preference(d1["colours"])
    pt2, pc2 = get_colour_preference(d2["colours"])

    # 5.2.1: Grant both colour preferences
    if pc1 is not None and pc2 is not None and pc1 != pc2:
        return p1_tpn if pc1 == "W" else p2_tpn

    # 5.2.2: Grant stronger preference
    strength = {"absolute": 3, "strong": 2, "mild": 1, "none": 0}
    s1, s2 = strength[pt1], strength[pt2]
    if s1 != s2:
        stronger = p1_tpn if s1 > s2 else p2_tpn
        _, sp = get_colour_preference(players[stronger]["colours"])
        if sp == "W":
            return stronger
        else:
            return p2_tpn if stronger == p1_tpn else p1_tpn

    # Both absolute topscorers: wider colour difference
    if pt1 == "absolute" and pt2 == "absolute":
        cd1 = abs(compute_colour_diff([c for c in d1["colours"] if c]))
        cd2 = abs(compute_colour_diff([c for c in d2["colours"] if c]))
        if cd1 != cd2:
            wider = p1_tpn if cd1 > cd2 else p2_tpn
            _, wp = get_colour_preference(players[wider]["colours"])
            if wp == "W":
                return wider
            else:
                return p2_tpn if wider == p1_tpn else p1_tpn

    # 5.2.3: Alternate from most recent round where colours differed
    pl1 = [c for c in d1["colours"] if c is not None]
    pl2 = [c for c in d2["colours"] if c is not None]
    for i in range(min(len(pl1), len(pl2)) - 1, -1, -1):
        if pl1[i] == "W" and pl2[i] == "B":
            return p2_tpn
        if pl1[i] == "B" and pl2[i] == "W":
            return p1_tpn

    # 5.2.4: Higher ranked player's preference
    if d1["score"] != d2["score"]:
        higher = p1_tpn if d1["score"] > d2["score"] else p2_tpn
    else:
        higher = p1_tpn if p1_tpn < p2_tpn else p2_tpn
    _, hp = get_colour_preference(players[higher]["colours"])
    if hp == "W":
        return higher
    elif hp == "B":
        return p2_tpn if higher == p1_tpn else p1_tpn

    # 5.2.5: Odd TPN gets initial colour
    if higher % 2 == 1:
        return higher
    else:
        return p2_tpn if higher == p1_tpn else p1_tpn


def validate_candidate(pairing_set, players, num_rounds):
    """Validate a single candidate pairing set against FIDE criteria."""
    result = {
        "c1": 0, "c3": 0, "colour_allocation_errors": 0,
        "c12": 0, "c13": 0, "c14": 0, "c15": 0,
    }

    for white_tpn, black_tpn in pairing_set:
        pw = players[white_tpn]
        pb = players[black_tpn]

        # C1: No rematches
        if black_tpn in pw["opponents"]:
            result["c1"] += 1

        # C3: Non-topscorers with same absolute colour preference
        pwt, pwc = get_colour_preference(pw["colours"])
        pbt, pbc = get_colour_preference(pb["colours"])
        if (pwt == "absolute" and pbt == "absolute" and pwc == pbc
                and not is_topscorer(pw["score"], num_rounds)
                and not is_topscorer(pb["score"], num_rounds)):
            result["c3"] += 1

        # Colour allocation check
        correct_white = determine_correct_white(white_tpn, black_tpn, players)
        if correct_white != white_tpn:
            result["colour_allocation_errors"] += 1

        # C12: Players not getting colour preference
        if pwc is not None and pwc != "W":
            result["c12"] += 1
        if pbc is not None and pbc != "B":
            result["c12"] += 1

        # C13: Strong/absolute preference denials
        if pwt in ("strong", "absolute") and pwc != "W":
            result["c13"] += 1
        if pbt in ("strong", "absolute") and pbc != "B":
            result["c13"] += 1

    # C14: Downfloaters who had downfloat in previous round
    for white_tpn, black_tpn in pairing_set:
        pw = players[white_tpn]
        pb = players[black_tpn]
        if pw["score"] != pb["score"]:
            higher_tpn = white_tpn if pw["score"] > pb["score"] else black_tpn
            if players[higher_tpn]["floats"][-1] == "D":
                result["c14"] += 1

    # C15: MDP opponents who had upfloat in previous round
    for white_tpn, black_tpn in pairing_set:
        pw = players[white_tpn]
        pb = players[black_tpn]
        if pw["score"] != pb["score"]:
            lower_tpn = black_tpn if pw["score"] > pb["score"] else white_tpn
            if players[lower_tpn]["floats"][-1] == "U":
                result["c15"] += 1

    result["legal"] = result["c1"] == 0 and result["c3"] == 0
    result["quality_penalty"] = (
        result["c12"] + result["c13"] + result["c14"] + result["c15"]
    )
    return result


def main():
    players, num_rounds, initial_colour, info = load_from_db("/app/tournament.db")

    # Generate TRF file from database
    trf_content = generate_trf(players, info, num_rounds)
    with open("/app/tournament.trf", "w") as f:
        f.write(trf_content)
    print("Generated /app/tournament.trf from SQLite database")

    # Load candidates and run audit
    with open("/app/candidates.json") as f:
        candidates = json.load(f)

    output = []
    for i, candidate in enumerate(candidates):
        r = validate_candidate(candidate, players, num_rounds)
        r["candidate_index"] = i
        output.append({
            "candidate_index": r["candidate_index"],
            "c1": r["c1"],
            "c3": r["c3"],
            "colour_allocation_errors": r["colour_allocation_errors"],
            "c12": r["c12"],
            "c13": r["c13"],
            "c14": r["c14"],
            "c15": r["c15"],
            "legal": r["legal"],
            "quality_penalty": r["quality_penalty"],
        })

    with open("/app/audit_result.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Audit complete. Results written to /app/audit_result.json")
    for r in output:
        print(f"  Candidate {r['candidate_index']}: legal={r['legal']}, "
              f"c1={r['c1']}, c3={r['c3']}, col_err={r['colour_allocation_errors']}, "
              f"penalty={r['quality_penalty']}")


if __name__ == "__main__":
    main()
