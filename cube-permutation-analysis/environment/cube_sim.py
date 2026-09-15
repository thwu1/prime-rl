#!/usr/bin/env python3

"""
3x3x3 Rubik's Cube Simulator — Facelet Level

Implements all 18 moves (6 faces x {CW, CCW, half-turn}) as explicit permutations
over 54 facelets in Kociemba ordering:
  U(0-8), R(9-17), F(18-26), D(27-35), L(36-44), B(45-53)
  Each face read row-by-row from outside: 0-1-2 / 3-4-5 / 6-7-8

Solved state: UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB

Net layout:
              U0 U1 U2
              U3 U4 U5
              U6 U7 U8
  L0 L1 L2   F0 F1 F2   R0 R1 R2   B0 B1 B2
  L3 L4 L5   F3 F4 F5   R3 R4 R5   B3 B4 B5
  L6 L7 L8   F6 F7 F8   R6 R7 R8   B6 B7 B8
              D0 D1 D2
              D3 D4 D5
              D6 D7 D8
"""

import json
import sys
from math import gcd
from functools import reduce

SOLVED = "UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB"
CENTERS = {4, 13, 22, 31, 40, 49}


def apply_perm(state, perm):
    """Apply permutation: new_state[i] = state[perm[i]]."""
    return [state[perm[i]] for i in range(54)]


def compose_perm(first, second):
    """Compose two permutations: result of applying first then second.
    compose(first, second)[i] = first[second[i]]
    """
    return [first[second[i]] for i in range(54)]


def invert_perm(perm):
    """Compute the inverse permutation."""
    inv = [0] * 54
    for i in range(54):
        inv[perm[i]] = i
    return inv


def define_moves():
    """Define the 6 basic clockwise face moves as permutations.

    Convention: perm[dest] = source means position dest receives the sticker
    that was at position source.

    Corner cubies and their facelets:
      URF: U9(8),  R1(9),  F3(20)
      UFL: U7(6),  F1(18), L3(38)
      ULB: U1(0),  L1(36), B3(47)
      UBR: U3(2),  B1(45), R3(11)
      DFR: D3(29), F9(26), R7(15)
      DLF: D1(27), L9(44), F7(24)
      DBL: D7(33), B9(53), L7(42)
      DRB: D9(35), R9(17), B7(51)

    Edge cubies and their facelets:
      UR: U6(5),  R2(10)    UF: U8(7),  F2(19)
      UL: U4(3),  L2(37)    UB: U2(1),  B2(46)
      DR: D6(32), R8(16)    DF: D2(28), F8(25)
      DL: D4(30), L8(43)    DB: D8(34), B8(52)
      FR: F6(23), R4(12)    FL: F4(21), L6(41)
      BR: B4(48), R6(14)    BL: B6(50), L4(39)
    """
    moves = {}

    # --- U CW ---
    # Cycle: UFL -> URF -> UBR -> ULB -> UFL
    # Strip: F -> R -> B -> L
    U = list(range(54))
    # Face corners: FL(6)->FR(8)->BR(2)->BL(0)->FL(6)
    U[8] = 6; U[2] = 8; U[0] = 2; U[6] = 0
    # Face edges: FC(7)->RC(5)->BC(1)->LC(3)->FC(7)
    U[5] = 7; U[1] = 5; U[3] = 1; U[7] = 3
    # Adjacent strip F->R->B->L:
    # F1(18)->R1(9), F2(19)->R2(10), F3(20)->R3(11)
    U[9] = 18;  U[10] = 19; U[11] = 20
    # R1(9)->B1(45), R2(10)->B2(46), R3(11)->B3(47)
    U[45] = 9;  U[46] = 10; U[47] = 11
    # B1(45)->L1(36), B2(46)->L2(37), B3(47)->L3(38)
    U[36] = 45; U[37] = 46; U[38] = 47
    # L1(36)->F1(18), L2(37)->F2(19), L3(38)->F3(20)
    U[18] = 36; U[19] = 37; U[20] = 38
    moves['U'] = U

    # --- R CW ---
    # Cycle: URF -> UBR -> DRB -> DFR -> URF
    # Strip: F -> U -> B -> D
    R = list(range(54))
    # Face: 9->11->17->15->9, 10->14->16->12->10
    R[11] = 9;  R[17] = 11; R[15] = 17; R[9] = 15
    R[14] = 10; R[16] = 14; R[12] = 16; R[10] = 12
    # Adjacent: F(20,23,26), U(2,5,8), B(45,48,51), D(29,32,35)
    R[2] = 51;  R[5] = 48;  R[8] = 45
    R[45] = 35; R[48] = 32; R[51] = 29
    R[29] = 20; R[32] = 23; R[35] = 26
    R[20] = 2;  R[23] = 5;  R[26] = 8
    moves['R'] = R

    # --- F CW ---
    # Cycle: UFL -> URF -> DFR -> DLF -> UFL
    # Strip: L -> U -> R -> D
    F = list(range(54))
    # Face: 18->20->26->24->18, 19->23->25->21->19
    F[20] = 18; F[26] = 20; F[24] = 26; F[18] = 24
    F[23] = 19; F[25] = 23; F[21] = 25; F[19] = 21
    # Adjacent strip
    F[9] = 6;  F[8] = 38;  F[15] = 8;  F[29] = 9
    F[44] = 29; F[27] = 15; F[38] = 27; F[6] = 44
    F[12] = 7; F[28] = 12; F[41] = 28; F[7] = 41
    moves['F'] = F

    # --- D CW ---
    # Cycle: DLF -> DFR -> DRB -> DBL -> DLF
    # Strip: F -> R -> B -> L (same direction as U)
    D = list(range(54))
    # Face: 27->29->35->33->27, 28->32->34->30->28
    D[29] = 27; D[35] = 29; D[33] = 35; D[27] = 33
    D[32] = 28; D[34] = 32; D[30] = 34; D[28] = 30
    # Adjacent strip
    D[26] = 44; D[15] = 24; D[17] = 26; D[51] = 15
    D[53] = 17; D[42] = 51; D[44] = 53; D[24] = 42
    D[16] = 25; D[52] = 16; D[43] = 52; D[25] = 43
    moves['D'] = D

    # --- L CW ---
    # Cycle: ULB -> UFL -> DLF -> DBL -> ULB
    # Strip: B -> U -> F -> D
    L = list(range(54))
    # Face: 36->38->44->42->36, 37->41->43->39->37
    L[38] = 36; L[44] = 38; L[42] = 44; L[36] = 42
    L[41] = 37; L[43] = 41; L[39] = 43; L[37] = 39
    # Adjacent strip
    L[18] = 0; L[6] = 47; L[24] = 6; L[27] = 18
    L[53] = 27; L[33] = 24; L[47] = 33; L[0] = 53
    L[21] = 3; L[30] = 21; L[50] = 30; L[3] = 50
    moves['L'] = L

    # --- B CW ---
    # Cycle: UBR -> ULB -> DBL -> DRB -> UBR
    # Strip: R -> U -> L -> D
    B = list(range(54))
    # Face: 45->47->53->51->45, 46->50->52->48->46
    B[47] = 45; B[53] = 47; B[51] = 53; B[45] = 51
    B[50] = 46; B[52] = 50; B[48] = 52; B[46] = 48
    # Adjacent strip
    B[36] = 2;  B[0] = 11;  B[42] = 0; B[33] = 36
    B[17] = 33; B[35] = 42; B[11] = 35; B[2] = 17
    B[1] = 14; B[39] = 1; B[34] = 39; B[14] = 34
    moves['B'] = B

    return moves


def get_all_moves(base_moves):
    """Derive inverse (') and half-turn (2) moves from base CW moves."""
    all_moves = {}
    for name, perm in base_moves.items():
        all_moves[name] = perm
        all_moves[name + "'"] = invert_perm(perm)
        all_moves[name + "2"] = compose_perm(perm, perm)
    return all_moves


def parse_and_apply_scramble(scramble_str, all_moves):
    """Parse a scramble string and return the resulting cube state."""
    state = list(SOLVED)
    for token in scramble_str.strip().split():
        if len(token) == 1:
            move_name = token
        elif len(token) == 2 and token[1] in ("'", "2"):
            move_name = token
        else:
            raise ValueError(f"Unknown move token: {token}")
        state = apply_perm(state, all_moves[move_name])
    return ''.join(state)


def scramble_to_perm(scramble_str, all_moves):
    """Compute the composed permutation for a scramble sequence."""
    result = list(range(54))
    for token in scramble_str.strip().split():
        if len(token) == 1:
            move_name = token
        elif len(token) == 2 and token[1] in ("'", "2"):
            move_name = token
        else:
            raise ValueError(f"Unknown move token: {token}")
        result = compose_perm(result, all_moves[move_name])
    return result


def get_cycles(perm):
    """Get cycle decomposition over 48 non-center facelets."""
    visited = set(CENTERS)
    cycles = []
    for i in range(54):
        if i in visited:
            continue
        cycle = []
        j = i
        while j not in visited:
            visited.add(j)
            cycle.append(j)
            j = perm[j]
        if cycle:
            cycles.append(cycle)
    return cycles


def perm_order(perm):
    """Compute the order of a permutation on non-center facelets."""
    cycles = get_cycles(perm)
    lengths = [len(c) for c in cycles]
    if not lengths:
        return 1
    return reduce(lambda a, b: a * b // gcd(a, b), lengths)


def cycle_type(perm):
    """Sorted list of cycle lengths (ascending) on non-center facelets."""
    return sorted(len(c) for c in get_cycles(perm))


def count_fixed(perm):
    """Count non-center facelets fixed by the permutation."""
    return sum(1 for i in range(54) if i not in CENTERS and perm[i] == i)


def perm_parity(perm):
    """Parity of the permutation on non-center facelets."""
    total = sum(len(c) - 1 for c in get_cycles(perm))
    return "even" if total % 2 == 0 else "odd"


def main():
    """Process scrambles and write analysis to sim_output.json."""
    base_moves = define_moves()
    all_moves = get_all_moves(base_moves)

    with open("/app/scrambles.txt") as f:
        scrambles = [line.strip() for line in f if line.strip()]

    results = {"scrambles": []}

    for i, scramble in enumerate(scrambles):
        facelet_str = parse_and_apply_scramble(scramble, all_moves)
        perm = scramble_to_perm(scramble, all_moves)
        order = perm_order(perm)
        ct = cycle_type(perm)
        fixed = count_fixed(perm)
        parity = perm_parity(perm)

        results["scrambles"].append({
            "index": i,
            "facelet_string": facelet_str,
            "permutation_order": order,
            "cycle_type": ct,
            "num_fixed_facelets": fixed,
            "parity": parity,
        })

    # Global computations
    orders = [r["permutation_order"] for r in results["scrambles"]]
    max_order = max(orders)
    max_order_idx = orders.index(max_order)
    total_fixed = sum(r["num_fixed_facelets"] for r in results["scrambles"])

    cycle_types_list = [tuple(r["cycle_type"]) for r in results["scrambles"]]
    shared_pairs = []
    for i in range(len(cycle_types_list)):
        for j in range(i + 1, len(cycle_types_list)):
            if cycle_types_list[i] == cycle_types_list[j]:
                shared_pairs.append([i, j])

    # Composite permutation: apply all 15 scrambles in sequence
    composite = list(range(54))
    for scramble in scrambles:
        perm = scramble_to_perm(scramble, all_moves)
        composite = compose_perm(composite, perm)
    composite_ord = perm_order(composite)

    results["max_order_index"] = max_order_idx
    results["max_order"] = max_order
    results["total_fixed"] = total_fixed
    results["shared_cycle_type_pairs"] = shared_pairs
    results["composite_order"] = composite_ord

    with open("/app/sim_output.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"Analysis written to /app/sim_output.json")
    print(f"Processed {len(scrambles)} scrambles")
    print(f"Max order: {max_order} at index {max_order_idx}")
    print(f"Total fixed facelets: {total_fixed}")
    print(f"Composite permutation order: {composite_ord}")


if __name__ == "__main__":
    main()
