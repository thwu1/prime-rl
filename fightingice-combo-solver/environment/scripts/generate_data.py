"""Generate binary protobuf character data for ZEN."""
import sys
sys.path.insert(0, '/tmp/proto_out')
import game_pb2

ms = game_pb2.CharacterMoveSet()
ms.character_name = "ZEN"
ms.max_hp = 400
ms.max_energy = 100

SPECIALS = [
    "STAND_D_DF_FA", "STAND_D_DF_FB", "STAND_F_D_DFA", "STAND_F_D_DFB",
    "STAND_D_DB_BA", "STAND_D_DB_BB"
]
HEAVIES = ["STAND_FA", "STAND_FB", "CROUCH_FA", "CROUCH_FB"]

MOVES = [
    # name, startup, active, recovery, damage, guard_damage, energy_cost, energy_gain,
    # hit_stun, block_stun, cancel_start, cancel_end, attack_level,
    # is_launcher, is_knockdown, is_projectile, cancel_into
    ("STAND_A", 5, 3, 8, 26, 13, 0, 8, 15, 8, 5, 10, 0,
     False, False, False,
     ["STAND_B", "CROUCH_B", "STAND_FA", "STAND_FB", "CROUCH_FA", "CROUCH_FB"] + SPECIALS),

    ("STAND_B", 8, 4, 14, 40, 20, 0, 15, 23, 14, 9, 16, 1,
     False, False, False,
     HEAVIES + SPECIALS),

    ("CROUCH_A", 4, 3, 7, 22, 11, 0, 7, 13, 6, 4, 9, 0,
     False, False, False,
     ["STAND_A", "STAND_B", "CROUCH_B", "STAND_FA", "STAND_FB", "CROUCH_FA", "CROUCH_FB"] + SPECIALS),

    ("CROUCH_B", 7, 3, 16, 36, 18, 0, 12, 23, 14, 8, 14, 1,
     False, False, False,
     HEAVIES + SPECIALS),

    ("STAND_FA", 12, 5, 18, 60, 30, 0, 20, 30, 17, 14, 22, 2,
     False, False, False,
     SPECIALS),

    ("STAND_FB", 14, 6, 22, 72, 36, 0, 22, 36, 21, 16, 24, 2,
     False, False, False,
     SPECIALS),

    ("CROUCH_FA", 10, 4, 16, 52, 26, 0, 18, 26, 15, 12, 18, 2,
     False, False, False,
     SPECIALS),

    ("CROUCH_FB", 13, 5, 20, 66, 33, 0, 20, 32, 19, 15, 22, 2,
     True, False, False,
     ["STAND_F_D_DFA", "STAND_F_D_DFB", "STAND_D_DB_BA", "STAND_D_DB_BB"]),

    ("AIR_A", 6, 4, 10, 28, 14, 0, 8, 18, 11, 6, 12, 0,
     False, False, False,
     ["AIR_B", "AIR_FA", "AIR_FB"]),

    ("AIR_B", 9, 5, 14, 46, 23, 0, 12, 24, 15, 10, 16, 1,
     False, False, False,
     ["AIR_FA", "AIR_FB"]),

    ("AIR_FA", 11, 5, 16, 56, 28, 0, 14, 27, 16, 0, 0, 2,
     False, True, False, []),

    ("AIR_FB", 13, 6, 18, 70, 35, 0, 17, 31, 18, 0, 0, 2,
     False, True, False, []),

    ("STAND_D_DF_FA", 15, 4, 24, 82, 41, 25, 0, 36, 21, 0, 0, 3,
     False, False, True, []),

    ("STAND_D_DF_FB", 18, 6, 28, 104, 52, 45, 0, 44, 26, 0, 0, 3,
     False, True, False, []),

    ("STAND_F_D_DFA", 6, 8, 30, 92, 46, 20, 0, 48, 30, 0, 0, 3,
     True, False, False, []),

    ("STAND_F_D_DFB", 8, 10, 34, 116, 58, 35, 0, 56, 34, 0, 0, 3,
     True, False, False, []),

    ("STAND_D_DB_BA", 10, 4, 22, 74, 37, 15, 0, 33, 20, 0, 0, 3,
     False, False, False, []),

    ("STAND_D_DB_BB", 14, 6, 26, 98, 49, 30, 0, 41, 24, 0, 0, 3,
     False, True, False, []),

    ("THROW_A", 3, 2, 20, 78, 0, 0, 0, 0, 0, 0, 0, 3,
     False, True, False, []),

    ("THROW_B", 5, 2, 22, 100, 0, 10, 0, 0, 0, 0, 0, 3,
     False, True, False, []),
]

for (name, startup, active, recovery, damage, guard_damage, energy_cost,
     energy_gain, hit_stun, block_stun, cancel_start, cancel_end,
     attack_level, is_launcher, is_knockdown, is_projectile, cancel_into) in MOVES:
    m = ms.moves.add()
    m.name = name
    m.startup_frames = startup
    m.active_frames = active
    m.recovery_frames = recovery
    m.damage = damage
    m.guard_damage = guard_damage
    m.energy_cost = energy_cost
    m.energy_gain = energy_gain
    m.hit_stun = hit_stun
    m.block_stun = block_stun
    m.cancel_start_frame = cancel_start
    m.cancel_end_frame = cancel_end
    m.attack_level = attack_level
    m.is_launcher = is_launcher
    m.is_knockdown = is_knockdown
    m.is_projectile = is_projectile
    for c in cancel_into:
        m.cancel_into.append(c)

with open('/app/data/character_zen.bin', 'wb') as f:
    f.write(ms.SerializeToString())

print(f"Generated character data: {len(ms.moves)} moves, {len(ms.SerializeToString())} bytes")
