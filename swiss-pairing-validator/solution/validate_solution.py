#!/usr/bin/env python3
"""
FIDE Dutch System Swiss Pairing Validator
Implements validation per FIDE Handbook C.04.3 (effective from 1 February 2026).

"""
import json


def load_data():
    with open("/app/tournament_state.json") as f:
        state = json.load(f)
    with open("/app/proposed_pairings.json") as f:
        pairings = json.load(f)
    return state, pairings


def compute_colour_diff(colours):
    """Article 1.6: colour difference = #White - #Black"""
    played = [c for c in colours if c is not None]
    w = sum(1 for c in played if c == "W")
    b = sum(1 for c in played if c == "B")
    return w - b


def get_colour_preference(colours):
    """
    Article 1.7: Determine colour preference type and preferred colour.
    Returns (type, preferred_colour) where type is one of:
    'absolute', 'strong', 'mild', 'none'
    """
    played = [c for c in colours if c is not None]
    if not played:
        return ("none", None)

    cd = compute_colour_diff(played)

    # 1.7.1 Absolute: |cd| > 1 OR same colour in last two played rounds
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

    # 1.7.3 Mild: cd == 0, alternate from last game
    if cd == 0 and played:
        pref = "B" if played[-1] == "W" else "W"
        return ("mild", pref)

    return ("none", None)


def is_topscorer(score, num_rounds):
    """Article 1.8: score > 50% of max possible score"""
    return score > num_rounds / 2.0


def determine_correct_white(p1_tpn, p2_tpn, players_by_tpn):
    """
    Article 5.2: Colour allocation rules (5-level priority cascade).
    Returns the TPN of the player who should play White.
    """
    d1 = players_by_tpn[p1_tpn]
    d2 = players_by_tpn[p2_tpn]
    pref_type1, pref_col1 = get_colour_preference(d1["colours"])
    pref_type2, pref_col2 = get_colour_preference(d2["colours"])

    # 5.2.1: Grant both colour preferences (if they differ)
    if pref_col1 is not None and pref_col2 is not None:
        if pref_col1 != pref_col2:
            return p1_tpn if pref_col1 == "W" else p2_tpn

    # 5.2.2: Grant the stronger colour preference
    pref_strength = {"absolute": 3, "strong": 2, "mild": 1, "none": 0}
    s1 = pref_strength[pref_type1]
    s2 = pref_strength[pref_type2]
    if s1 != s2:
        stronger_tpn = p1_tpn if s1 > s2 else p2_tpn
        _, stronger_pref = get_colour_preference(
            players_by_tpn[stronger_tpn]["colours"]
        )
        if stronger_pref == "W":
            return stronger_tpn
        else:
            return p2_tpn if stronger_tpn == p1_tpn else p1_tpn

    # If both absolute, grant wider colour difference (topscorers)
    if pref_type1 == "absolute" and pref_type2 == "absolute":
        cd1 = abs(compute_colour_diff([c for c in d1["colours"] if c]))
        cd2 = abs(compute_colour_diff([c for c in d2["colours"] if c]))
        if cd1 != cd2:
            wider_tpn = p1_tpn if cd1 > cd2 else p2_tpn
            _, wider_pref = get_colour_preference(
                players_by_tpn[wider_tpn]["colours"]
            )
            if wider_pref == "W":
                return wider_tpn
            else:
                return p2_tpn if wider_tpn == p1_tpn else p1_tpn

    # 5.2.3: Alternate to most recent time one had W and other had B
    played1 = [c for c in d1["colours"] if c is not None]
    played2 = [c for c in d2["colours"] if c is not None]
    min_len = min(len(played1), len(played2))
    for i in range(min_len - 1, -1, -1):
        if played1[i] == "W" and played2[i] == "B":
            return p2_tpn  # p1 had W last, so p2 gets W now
        if played1[i] == "B" and played2[i] == "W":
            return p1_tpn  # p2 had W last, so p1 gets W now

    # 5.2.4: Grant colour preference of higher ranked player
    if d1["score"] != d2["score"]:
        higher_tpn = p1_tpn if d1["score"] > d2["score"] else p2_tpn
    else:
        higher_tpn = p1_tpn if p1_tpn < p2_tpn else p2_tpn
    _, higher_pref = get_colour_preference(players_by_tpn[higher_tpn]["colours"])
    if higher_pref == "W":
        return higher_tpn
    elif higher_pref == "B":
        return p2_tpn if higher_tpn == p1_tpn else p1_tpn

    # 5.2.5: Odd TPN gets initial colour (White)
    if higher_tpn % 2 == 1:
        return higher_tpn
    else:
        return p2_tpn if higher_tpn == p1_tpn else p1_tpn


def validate_pairing_set(pairing_set, players_by_tpn, num_rounds):
    result = {
        "c1_violations": 0,
        "c3_violations": 0,
        "colour_allocation_errors": 0,
        "c12_violations": 0,
        "c13_violations": 0,
        "c14_violations": 0,
        "c15_violations": 0,
    }

    for white_tpn, black_tpn in pairing_set:
        pw = players_by_tpn[white_tpn]
        pb = players_by_tpn[black_tpn]

        # C1: No rematches (Article 2.1.1)
        if black_tpn in pw["opponents"]:
            result["c1_violations"] += 1

        # C3: Non-topscorers with same absolute colour preference (Article 2.1.3)
        pref_w_type, pref_w_col = get_colour_preference(pw["colours"])
        pref_b_type, pref_b_col = get_colour_preference(pb["colours"])
        if (
            pref_w_type == "absolute"
            and pref_b_type == "absolute"
            and pref_w_col == pref_b_col
            and not is_topscorer(pw["score"], num_rounds)
            and not is_topscorer(pb["score"], num_rounds)
        ):
            result["c3_violations"] += 1

        # Colour allocation check (Article 5.2)
        correct_white = determine_correct_white(white_tpn, black_tpn, players_by_tpn)
        if correct_white != white_tpn:
            result["colour_allocation_errors"] += 1

        # C12: Players not getting their colour preference (Article 2.4.7)
        if pref_w_col is not None and pref_w_col != "W":
            result["c12_violations"] += 1
        if pref_b_col is not None and pref_b_col != "B":
            result["c12_violations"] += 1

        # C13: Players not getting their strong colour preference (Article 2.4.8)
        if pref_w_type in ("strong", "absolute") and pref_w_col != "W":
            result["c13_violations"] += 1
        if pref_b_type in ("strong", "absolute") and pref_b_col != "B":
            result["c13_violations"] += 1

    # C14: Downfloaters who had downfloat in previous round (Article 2.4.9)
    for white_tpn, black_tpn in pairing_set:
        pw = players_by_tpn[white_tpn]
        pb = players_by_tpn[black_tpn]
        if pw["score"] != pb["score"]:
            higher_tpn = white_tpn if pw["score"] > pb["score"] else black_tpn
            higher_d = players_by_tpn[higher_tpn]
            if higher_d["floats"][-1] == "D":
                result["c14_violations"] += 1

    # C15: MDP opponents who had upfloat in previous round (Article 2.4.10)
    for white_tpn, black_tpn in pairing_set:
        pw = players_by_tpn[white_tpn]
        pb = players_by_tpn[black_tpn]
        if pw["score"] != pb["score"]:
            lower_tpn = black_tpn if pw["score"] > pb["score"] else white_tpn
            lower_d = players_by_tpn[lower_tpn]
            if lower_d["floats"][-1] == "U":
                result["c15_violations"] += 1

    result["is_valid"] = result["c1_violations"] == 0 and result["c3_violations"] == 0
    result["total_quality_cost"] = (
        result["c12_violations"]
        + result["c13_violations"]
        + result["c14_violations"]
        + result["c15_violations"]
    )
    return result


def main():
    state, proposed = load_data()
    players_by_tpn = {p["tpn"]: p for p in state["players"]}
    num_rounds = state["num_rounds_played"]

    results = []
    for i, pairing_set in enumerate(proposed):
        r = validate_pairing_set(pairing_set, players_by_tpn, num_rounds)
        r["pairing_index"] = i
        results.append(r)

    with open("/app/validation_result.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Validation complete. Results written to /app/validation_result.json")
    for r in results:
        print(
            f"  Set {r['pairing_index']}: valid={r['is_valid']}, "
            f"c1={r['c1_violations']}, c3={r['c3_violations']}, "
            f"colour_err={r['colour_allocation_errors']}, "
            f"quality_cost={r['total_quality_cost']}"
        )


if __name__ == "__main__":
    main()
