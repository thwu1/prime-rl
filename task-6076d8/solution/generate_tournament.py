#!/usr/bin/env python3
"""
Generate and validate tournament.json.

"""
import json

# 16 players, 4 rounds. Carefully constructed round-by-round.
# Round pairings (no rematches verified):
# R1: 1v9, 2v10, 3v11, 4v12, 5v13, 6v14, 7v15, 8v16
# R2: 1v5, 2v6, 3v7, 4v8, 9v13, 10v14, 11v15, 12v16
# R3: 1v3, 2v4, 5v8, 6v7, 9v12, 10v11, 13v16, 14v15
# R4: 1v2, 3v5, 4v6, 7v8, 9v10, 11v13, 12v14, 15v16

# Colours per round (verified opposite for each pair):
# R1: 1W,9B, 2B,10W, 3W,11B, 4B,12W, 5W,13B, 6B,14W, 7W,15B, 8B,16W
# R2: 1B,5W, 2W,6B, 3B,7W, 4W,8B, 9W,13B, 10B,14W, 11W,15B, 12B,16W
# R3: 1W,3B, 2B,4W, 5B,8W, 6W,7B, 9B,12W, 10W,11B, 13W,16B, 14B,15W
# R4: 1B,2W, 3W,5B, 4B,6W, 7W,8B, 9W,10B, 11W,13B, 12B,14W, 15B,16W

# Results (W=white wins, B=black wins, D=draw):
# R1: 1 beats 9, 10 beats 2, 3 beats 11, 4 draws 12, 5 beats 13, 14 beats 6, 7 draws 15, 8 beats 16
# R2: 1 beats 5, 2 beats 6, 7 beats 3, 4 beats 8, 9 draws 13, 14 beats 10, 15 beats 11, 12 beats 16
# R3: 1 beats 3, 4 beats 2, 5 beats 8, 7 beats 6, 9 beats 12, 10 beats 11, 13 draws 16, 14 beats 15
# R4: 1 draws 2, 3 beats 5, 6 beats 4, 7 draws 8, 9 beats 10, 11 beats 13, 14 beats 12, 15 draws 16

opponents = {
    1:  [9, 5, 3, 2],
    2:  [10, 6, 4, 1],
    3:  [11, 7, 1, 5],
    4:  [12, 8, 2, 6],
    5:  [13, 1, 8, 3],
    6:  [14, 2, 7, 4],
    7:  [15, 3, 6, 8],
    8:  [16, 4, 5, 7],
    9:  [1, 13, 12, 10],
    10: [2, 14, 11, 9],
    11: [3, 15, 10, 13],
    12: [4, 16, 9, 14],
    13: [5, 9, 16, 11],
    14: [6, 10, 15, 12],
    15: [7, 11, 14, 16],
    16: [8, 12, 13, 15],
}

colours = {
    1:  ["W","B","W","B"],
    2:  ["B","W","B","W"],
    3:  ["W","B","B","W"],
    4:  ["B","W","W","B"],
    5:  ["W","W","B","B"],
    6:  ["B","B","W","W"],
    7:  ["W","W","B","W"],
    8:  ["B","B","W","B"],
    9:  ["B","W","B","W"],
    10: ["W","B","W","B"],
    11: ["B","W","B","W"],
    12: ["W","B","W","B"],
    13: ["B","B","W","B"],
    14: ["W","W","B","W"],
    15: ["B","B","W","B"],
    16: ["W","W","B","W"],
}

# Compute scores from results
# R1: 1W beats 9B → 1:1,9:0; 10W beats 2B → 10:1,2:0; 3W beats 11B → 3:1,11:0;
#     4B draws 12W → 4:0.5,12:0.5; 5W beats 13B → 5:1,13:0; 14W beats 6B → 14:1,6:0;
#     7W draws 15B → 7:0.5,15:0.5; 8B beats 16W → 8:1,16:0
# R2: 1B beats 5W → 1:1,5:0; 2W beats 6B → 2:1,6:0; 7W beats 3B → 7:1,3:0;
#     4W beats 8B → 4:1,8:0; 9W draws 13B → 9:0.5,13:0.5; 14W beats 10B → 14:1,10:0;
#     15B... wait, 11W v 15B. Result: 15 beats 11 → 15:1,11:0 (B wins)
#     12B v 16W. Result: 12 beats 16 → 12:1(B wins),16:0 -- wait, 12 is B and beats 16 who is W.
# R3: 1W beats 3B → 1:1,3:0; 4W beats 2B → 4:1,2:0(wait, "2B,4W" means 2 has B and 4 has W;
#     result "4 beats 2" means 4 wins) → 4:1,2:0;
#     5B beats 8W → 5:1,8:0; 7B beats-- no, 6W v 7B. Result "7 beats 6" → 7:1(B wins),6:0;
#     9B beats-- no, 9B v 12W. Result "9 beats 12" → 9:1(B wins),12:0;
#     10W beats 11B → 10:1,11:0; 13W draws 16B → 13:0.5,16:0.5;
#     14B beats-- no, 14B v 15W. Result "14 beats 15" → 14:1(B wins),15:0
# R4: 1B draws 2W → 1:0.5,2:0.5; 3W beats 5B → 3:1,5:0; 4B draws-- no, 4B v 6W.
#     Result "6 beats 4" → 6:1(W wins),4:0;
#     7W draws 8B → 7:0.5,8:0.5; 9W beats 10B → 9:1,10:0;
#     11W beats 13B → 11:1,13:0; 12B loses-- 12B v 14W. Result "14 beats 12" → 14:1,12:0;
#     15B draws 16W → 15:0.5,16:0.5

round_scores = {i: [0,0,0,0] for i in range(1,17)}

# R1
round_scores[1][0]=1; round_scores[9][0]=0
round_scores[10][0]=1; round_scores[2][0]=0
round_scores[3][0]=1; round_scores[11][0]=0
round_scores[4][0]=0.5; round_scores[12][0]=0.5
round_scores[5][0]=1; round_scores[13][0]=0
round_scores[14][0]=1; round_scores[6][0]=0
round_scores[7][0]=0.5; round_scores[15][0]=0.5
round_scores[8][0]=1; round_scores[16][0]=0
# R2
round_scores[1][1]=1; round_scores[5][1]=0
round_scores[2][1]=1; round_scores[6][1]=0
round_scores[7][1]=1; round_scores[3][1]=0
round_scores[4][1]=1; round_scores[8][1]=0
round_scores[9][1]=0.5; round_scores[13][1]=0.5
round_scores[14][1]=1; round_scores[10][1]=0
round_scores[15][1]=1; round_scores[11][1]=0
round_scores[12][1]=1; round_scores[16][1]=0
# R3
round_scores[1][2]=1; round_scores[3][2]=0
round_scores[4][2]=1; round_scores[2][2]=0
round_scores[5][2]=1; round_scores[8][2]=0
round_scores[7][2]=1; round_scores[6][2]=0
round_scores[9][2]=1; round_scores[12][2]=0
round_scores[10][2]=1; round_scores[11][2]=0
round_scores[13][2]=0.5; round_scores[16][2]=0.5
round_scores[14][2]=1; round_scores[15][2]=0
# R4
round_scores[1][3]=0.5; round_scores[2][3]=0.5
round_scores[3][3]=1; round_scores[5][3]=0
round_scores[6][3]=1; round_scores[4][3]=0
round_scores[7][3]=0.5; round_scores[8][3]=0.5
round_scores[9][3]=1; round_scores[10][3]=0
round_scores[11][3]=1; round_scores[13][3]=0
round_scores[14][3]=1; round_scores[12][3]=0
round_scores[15][3]=0.5; round_scores[16][3]=0.5

total_scores = {i: sum(round_scores[i]) for i in range(1,17)}
print("Scores:", total_scores)
print("Total:", sum(total_scores.values()))
assert sum(total_scores.values()) == 32.0

# Compute cumulative scores after each round (needed for float determination)
cumul = {i: [] for i in range(1,17)}
for i in range(1,17):
    s = 0
    for r in range(4):
        s += round_scores[i][r]
        cumul[i].append(s)

# Determine floats: in each round, if paired players had different scores going into that round
downfloat_rounds = {i: [] for i in range(1,17)}
upfloat_rounds = {i: [] for i in range(1,17)}

pairings_by_round = [
    [(1,9),(2,10),(3,11),(4,12),(5,13),(6,14),(7,15),(8,16)],  # R1
    [(1,5),(2,6),(3,7),(4,8),(9,13),(10,14),(11,15),(12,16)],  # R2
    [(1,3),(2,4),(5,8),(6,7),(9,12),(10,11),(13,16),(14,15)],  # R3
    [(1,2),(3,5),(4,6),(7,8),(9,10),(11,13),(12,14),(15,16)],  # R4
]

for rnd in range(4):
    for (a, b) in pairings_by_round[rnd]:
        if rnd == 0:
            score_a = 0
            score_b = 0
        else:
            score_a = cumul[a][rnd-1]
            score_b = cumul[b][rnd-1]
        if score_a != score_b:
            # Higher scorer gets downfloat, lower gets upfloat
            if score_a > score_b or (score_a == score_b and a < b):
                if score_a > score_b:
                    downfloat_rounds[a].append(rnd+1)
                    upfloat_rounds[b].append(rnd+1)
                else:
                    downfloat_rounds[b].append(rnd+1)
                    upfloat_rounds[a].append(rnd+1)
            else:
                downfloat_rounds[b].append(rnd+1)
                upfloat_rounds[a].append(rnd+1)

print("\nFloat data:")
for i in range(1,17):
    if downfloat_rounds[i] or upfloat_rounds[i]:
        print(f"  Player {i}: df={downfloat_rounds[i]}, uf={upfloat_rounds[i]}")

# Validate symmetry
for i in range(1,17):
    for r in range(4):
        opp = opponents[i][r]
        assert i in opponents[opp], f"Player {i} has opp {opp} in R{r+1} but not reciprocal"
        opp_round = opponents[opp].index(i)
        assert opp_round == r, f"Player {i} faces {opp} in R{r+1} but opp faces back in R{opp_round+1}"
        assert colours[i][r] != colours[opp][r], \
            f"Players {i} and {opp} both {colours[i][r]} in R{r+1}"

# Build tournament JSON
names = {
    1: "Karjakin", 2: "Nakamura", 3: "Caruana", 4: "Ding",
    5: "Nepomniachtchi", 6: "Giri", 7: "Rapport", 8: "Dominguez",
    9: "Vidit", 10: "Praggnanandhaa", 11: "Erigaisi", 12: "Abdusattorov",
    13: "Keymer", 14: "Van_Foreest", 15: "Sevian", 16: "Sarana"
}
ratings = {
    1: 2750, 2: 2740, 3: 2730, 4: 2720, 5: 2710, 6: 2700, 7: 2690, 8: 2680,
    9: 2670, 10: 2660, 11: 2650, 12: 2640, 13: 2630, 14: 2620, 15: 2610, 16: 2600
}

tournament = {
    "current_round": 5,
    "total_rounds": 7,
    "initial_colour": "W",
    "players": []
}

for i in range(1, 17):
    tournament["players"].append({
        "tpn": i,
        "name": names[i],
        "rating": ratings[i],
        "score": total_scores[i],
        "colours": colours[i],
        "opponents": opponents[i],
        "had_bye": False,
        "downfloat_rounds": downfloat_rounds[i],
        "upfloat_rounds": upfloat_rounds[i]
    })

print("\nScore distribution:")
from collections import Counter
sc = Counter(total_scores.values())
for s in sorted(sc.keys(), reverse=True):
    tpns = [i for i in range(1,17) if total_scores[i]==s]
    print(f"  {s}: players {tpns}")

print("\nColour preferences for R5:")
for i in range(1,17):
    c = colours[i]
    cd = c.count("W") - c.count("B")
    played = [x for x in c if x is not None]
    if len(played) >= 2 and played[-1] == played[-2]:
        ptype = "absolute"
        pcol = "W" if played[-1] == "B" else "B"
    elif cd > 1 or cd < -1:
        ptype = "absolute"
        pcol = "W" if cd < -1 else "B"
    elif cd == 1:
        ptype = "strong"
        pcol = "B"
    elif cd == -1:
        ptype = "strong"
        pcol = "W"
    else:
        ptype = "mild"
        pcol = "B" if played[-1] == "W" else "W"
    print(f"  Player {i} (score={total_scores[i]}): colours={c}, cd={cd}, pref={ptype} {pcol}")

with open("/app/tournament.json", "w") as f:
    json.dump(tournament, f, indent=2)

print("\n✓ tournament.json written successfully")
print("✓ All validations passed")
