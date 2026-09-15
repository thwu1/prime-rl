"""Stockfish Transposition Table Simulator - Reference Solution.

Faithfully reimplements TTEntry encoding, decoding, ply-adjusted score
storage, cluster probing, replacement strategy, and full cluster lifecycle
simulation from Stockfish's src/tt.cpp, src/search.cpp, and src/types.h.

"""

import struct

# ---------------------------------------------------------------------------
# Constants (from types.h and tt.cpp)
# ---------------------------------------------------------------------------

DEPTH_NONE = -3
DEPTH_UNSEARCHED = -2
DEPTH_QS = 0

MAX_PLY = 246

BOUND_NONE = 0
BOUND_UPPER = 1
BOUND_LOWER = 2
BOUND_EXACT = BOUND_UPPER | BOUND_LOWER  # 3

GENERATION_BITS = 5
GENERATION_MASK = (1 << GENERATION_BITS) - 1  # 31
BOUND_SHIFT = GENERATION_BITS                 # 5
BOUND_MASK = 0b11 << BOUND_SHIFT             # 0x60
PV_SHIFT = BOUND_SHIFT + 2                   # 7
PV_MASK = 1 << PV_SHIFT                      # 0x80

CLUSTER_SIZE = 3

VALUE_ZERO = 0
VALUE_NONE = 32002
VALUE_INFINITE = 32001
VALUE_MATE = 32000
VALUE_MATE_IN_MAX_PLY = VALUE_MATE - MAX_PLY           # 31754
VALUE_MATED_IN_MAX_PLY = -VALUE_MATE_IN_MAX_PLY       # -31754
VALUE_TB = VALUE_MATE_IN_MAX_PLY - 1                   # 31753
VALUE_TB_WIN_IN_MAX_PLY = VALUE_TB - MAX_PLY           # 31507
VALUE_TB_LOSS_IN_MAX_PLY = -VALUE_TB_WIN_IN_MAX_PLY   # -31507


# ---------------------------------------------------------------------------
# Value classification helpers (from types.h)
# ---------------------------------------------------------------------------

def _is_valid(v):
    return v != VALUE_NONE

def _is_win(v):
    return v >= VALUE_TB_WIN_IN_MAX_PLY

def _is_loss(v):
    return v <= VALUE_TB_LOSS_IN_MAX_PLY

def _is_mate(v):
    return v >= VALUE_MATE_IN_MAX_PLY

def _is_mated(v):
    return v <= VALUE_MATED_IN_MAX_PLY

def _is_decisive(v):
    return _is_win(v) or _is_loss(v)


# ---------------------------------------------------------------------------
# genBound8 packing
# ---------------------------------------------------------------------------

def pack_gen_bound(generation: int, bound: int, is_pv: bool) -> int:
    return (generation & GENERATION_MASK) \
        | (bound << BOUND_SHIFT) \
        | (int(is_pv) << PV_SHIFT)


def unpack_gen_bound(gen_bound8: int) -> tuple:
    generation = gen_bound8 & GENERATION_MASK
    bound = (gen_bound8 & BOUND_MASK) >> BOUND_SHIFT
    is_pv = bool(gen_bound8 & PV_MASK)
    return (generation, bound, is_pv)


# ---------------------------------------------------------------------------
# Depth encoding
# ---------------------------------------------------------------------------

def encode_depth(depth: int) -> int:
    return depth - DEPTH_NONE


def decode_depth(depth8: int) -> int:
    return depth8 + DEPTH_NONE


# ---------------------------------------------------------------------------
# Relative age
# ---------------------------------------------------------------------------

def relative_age(current_generation: int, gen_bound8: int) -> int:
    return ((current_generation - gen_bound8) & 0xFF) & GENERATION_MASK


# ---------------------------------------------------------------------------
# Entry encode / decode
# ---------------------------------------------------------------------------

_ENTRY_FORMAT = "<HBBHhh"  # key16, depth8, genBound8, move16, value16, eval16
_ENTRY_SIZE = struct.calcsize(_ENTRY_FORMAT)  # 10 bytes


def encode_entry(key64: int, depth: int, is_pv: bool, bound: int,
                 move16: int, value: int, eval_value: int,
                 generation: int) -> bytes:
    key16 = key64 & 0xFFFF
    depth8 = encode_depth(depth)
    gen_bound8 = pack_gen_bound(generation, bound, is_pv)
    return struct.pack(_ENTRY_FORMAT, key16, depth8, gen_bound8,
                       move16, value, eval_value)


def decode_entry(data: bytes) -> dict:
    key16, depth8, gen_bound8, move16, value16, eval16 = \
        struct.unpack(_ENTRY_FORMAT, data)
    generation, bound, is_pv = unpack_gen_bound(gen_bound8)
    return {
        "key16": key16,
        "depth": decode_depth(depth8),
        "depth8": depth8,
        "is_pv": is_pv,
        "bound": bound,
        "generation": generation,
        "gen_bound8": gen_bound8,
        "move16": move16,
        "value": value16,
        "eval_value": eval16,
    }


# ---------------------------------------------------------------------------
# Cluster index (mul_hi64)
# ---------------------------------------------------------------------------

def cluster_index(key64: int, cluster_count: int) -> int:
    return (key64 * cluster_count) >> 64


# ---------------------------------------------------------------------------
# Replacement decision
# ---------------------------------------------------------------------------

def should_replace(existing: dict, new_key64: int, new_depth: int,
                   new_bound: int, new_is_pv: bool,
                   current_generation: int) -> bool:
    if new_bound == BOUND_EXACT:
        return True

    new_key16 = new_key64 & 0xFFFF
    if new_key16 != existing["key16"]:
        return True

    new_depth8 = encode_depth(new_depth)
    if new_depth8 + 2 * int(new_is_pv) > existing["depth8"] - 4:
        return True

    if relative_age(current_generation, existing["gen_bound8"]) > 0:
        return True

    return False


# ---------------------------------------------------------------------------
# Victim selection (from TranspositionTable::probe)
# ---------------------------------------------------------------------------

def select_victim(entries: list, current_generation: int) -> int:
    def score(e):
        return e["depth8"] - 8 * relative_age(current_generation, e["gen_bound8"])

    best_idx = 0
    best_score = score(entries[0])
    for i in range(1, len(entries)):
        s = score(entries[i])
        if best_score > s:
            best_score = s
            best_idx = i
    return best_idx


# ---------------------------------------------------------------------------
# Secondary aging
# ---------------------------------------------------------------------------

def apply_secondary_aging(entry: dict) -> bool:
    depth8 = entry["depth8"]
    gen_bound8 = entry["gen_bound8"]
    value = entry["value"]

    if depth8 + DEPTH_NONE < 5:
        return False

    bound = (gen_bound8 & BOUND_MASK) >> BOUND_SHIFT
    if bound == BOUND_EXACT:
        return False

    if abs(value) >= VALUE_INFINITE:
        return False
    if not _is_decisive(value):
        return False

    entry["depth8"] = depth8 - 1
    return True


# ---------------------------------------------------------------------------
# value_to_tt / value_from_tt  (from search.cpp)
# ---------------------------------------------------------------------------

def value_to_tt(v: int, ply: int) -> int:
    if _is_win(v):
        return v + ply
    if _is_loss(v):
        return v - ply
    return v


def value_from_tt(v: int, ply: int, r50c: int) -> int:
    if not _is_valid(v):
        return VALUE_NONE

    if _is_win(v):
        if _is_mate(v) and VALUE_MATE - v > 100 - r50c:
            return VALUE_TB_WIN_IN_MAX_PLY - 1
        if VALUE_TB - v > 100 - r50c:
            return VALUE_TB_WIN_IN_MAX_PLY - 1
        return v - ply

    if _is_loss(v):
        if _is_mated(v) and VALUE_MATE + v > 100 - r50c:
            return VALUE_TB_LOSS_IN_MAX_PLY + 1
        if VALUE_TB + v > 100 - r50c:
            return VALUE_TB_LOSS_IN_MAX_PLY + 1
        return v + ply

    return v


# ---------------------------------------------------------------------------
# empty_entry
# ---------------------------------------------------------------------------

def empty_entry() -> dict:
    return {
        "key16": 0,
        "depth8": 0,
        "gen_bound8": 0,
        "move16": 0,
        "value": 0,
        "eval_value": 0,
    }


# ---------------------------------------------------------------------------
# simulate_tt_probe
# ---------------------------------------------------------------------------

def simulate_tt_probe(cluster: list, key64: int, current_generation: int) -> tuple:
    key16 = key64 & 0xFFFF

    for i in range(CLUSTER_SIZE):
        if cluster[i]["key16"] == key16:
            entry = cluster[i]
            occupied = bool(entry["depth8"])
            if occupied:
                gen, bound, is_pv = unpack_gen_bound(entry["gen_bound8"])
                data = {
                    "move16": entry["move16"],
                    "value": entry["value"],
                    "eval_value": entry["eval_value"],
                    "depth": decode_depth(entry["depth8"]),
                    "bound": bound,
                    "is_pv": is_pv,
                }
                return (True, data, i)
            else:
                return (False, None, i)

    # No key match: find victim
    replace_idx = 0
    replace_score = cluster[0]["depth8"] - 8 * relative_age(
        current_generation, cluster[0]["gen_bound8"])
    for i in range(1, CLUSTER_SIZE):
        s = cluster[i]["depth8"] - 8 * relative_age(
            current_generation, cluster[i]["gen_bound8"])
        if replace_score > s:
            replace_score = s
            replace_idx = i

    return (False, None, replace_idx)


# ---------------------------------------------------------------------------
# simulate_tt_store
# ---------------------------------------------------------------------------

def simulate_tt_store(cluster: list, key64: int, value: int, is_pv: bool,
                      bound: int, depth: int, move16: int,
                      eval_value: int, current_generation: int) -> None:
    _, _, write_idx = simulate_tt_probe(cluster, key64, current_generation)
    entry = cluster[write_idx]
    key16 = key64 & 0xFFFF

    # Move preservation: only keep old move if key matches AND new move is none
    if move16 or key16 != entry["key16"]:
        entry["move16"] = move16

    # Replacement check (four-condition OR from TTEntry::save)
    depth8_new = encode_depth(depth)
    if (bound == BOUND_EXACT
            or key16 != entry["key16"]
            or depth8_new + 2 * int(is_pv) > entry["depth8"] - 4
            or relative_age(current_generation, entry["gen_bound8"]) > 0):

        entry["key16"] = key16
        entry["depth8"] = depth8_new
        entry["gen_bound8"] = pack_gen_bound(current_generation, bound, is_pv)
        entry["value"] = value
        entry["eval_value"] = eval_value
    else:
        # Secondary aging fallback
        if (entry["depth8"] + DEPTH_NONE >= 5
                and ((entry["gen_bound8"] & BOUND_MASK) >> BOUND_SHIFT) != BOUND_EXACT):
            v = entry["value"]
            if abs(v) < VALUE_INFINITE and _is_decisive(v):
                entry["depth8"] -= 1


# ---------------------------------------------------------------------------
# hashfull
# ---------------------------------------------------------------------------

def hashfull(clusters: list, current_generation: int, max_age: int = 0) -> int:
    sample = min(1000, len(clusters))
    cnt = 0
    for i in range(sample):
        for j in range(CLUSTER_SIZE):
            e = clusters[i][j]
            if e["depth8"] and relative_age(current_generation, e["gen_bound8"]) <= max_age:
                cnt += 1
    return cnt // CLUSTER_SIZE
