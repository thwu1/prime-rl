#!/usr/bin/env python3
"""Generate FightingICE tournament replay data (binary protobuf).

This script runs during Docker build to create /app/replays/*.bin files.
"""
import sys
import os
sys.path.insert(0, '/app/proto')
import game_pb2

INITIAL_HP = 400
DELAY = 15

# All match definitions: (match_id, p1, p2, character, rounds)
# Each round: (p1_remaining_hp, p2_remaining_hp, elapsed_frames)
MATCHES = [
    # Standard league round-robin (12 matches)
    ("STD_01", "AlphaStrike", "GuardBot", "ZEN",
     [(280, 0, 2400), (0, 120, 2800), (150, 0, 3000)]),
    ("STD_02", "GuardBot", "AlphaStrike", "ZEN",
     [(0, 200, 2200), (0, 180, 2600), (50, 0, 3400)]),
    ("STD_03", "AlphaStrike", "ComboKing", "ZEN",
     [(0, 300, 1800), (0, 250, 2000), (100, 0, 3200)]),
    ("STD_04", "ComboKing", "AlphaStrike", "ZEN",
     [(350, 0, 1500), (320, 0, 1600), (280, 0, 1800)]),
    ("STD_05", "AlphaStrike", "Rushdown", "ZEN",
     [(200, 0, 2400), (180, 0, 2600), (160, 0, 2800)]),
    ("STD_06", "Rushdown", "AlphaStrike", "ZEN",
     [(100, 0, 2800), (0, 220, 2500), (0, 190, 2700)]),
    ("STD_07", "GuardBot", "ComboKing", "ZEN",
     [(0, 380, 1200), (0, 360, 1400), (0, 340, 1600)]),
    ("STD_08", "ComboKing", "GuardBot", "ZEN",
     [(370, 0, 1300), (350, 0, 1500), (330, 0, 1700)]),
    ("STD_09", "GuardBot", "Rushdown", "ZEN",
     [(0, 150, 2600), (0, 130, 2800), (80, 0, 3200)]),
    ("STD_10", "Rushdown", "GuardBot", "ZEN",
     [(120, 0, 2700), (100, 0, 2900), (0, 90, 3100)]),
    ("STD_11", "ComboKing", "Rushdown", "ZEN",
     [(300, 0, 1800), (280, 0, 2000), (0, 50, 3400)]),
    ("STD_12", "Rushdown", "ComboKing", "ZEN",
     [(0, 250, 2000), (80, 0, 3000), (0, 200, 2200)]),

    # Speedrunning league vs MctsBot (8 matches)
    ("SPD_01", "AlphaStrike", "MctsBot", "ZEN",
     [(250, 0, 1800), (200, 0, 2000), (0, 100, 3600)]),
    ("SPD_02", "MctsBot", "AlphaStrike", "ZEN",
     [(0, 180, 2200), (120, 0, 3600), (0, 150, 2400)]),
    ("SPD_03", "GuardBot", "MctsBot", "ZEN",
     [(0, 200, 3600), (0, 180, 3600), (50, 0, 3400)]),
    ("SPD_04", "MctsBot", "GuardBot", "ZEN",
     [(150, 0, 3600), (0, 80, 3200), (130, 0, 3600)]),
    ("SPD_05", "ComboKing", "MctsBot", "ZEN",
     [(380, 0, 1200), (360, 0, 1400), (340, 0, 1000)]),
    ("SPD_06", "MctsBot", "ComboKing", "ZEN",
     [(0, 350, 1300), (0, 330, 1100), (0, 310, 1500)]),
    ("SPD_07", "Rushdown", "MctsBot", "ZEN",
     [(150, 0, 2000), (130, 0, 2200), (0, 80, 3600)]),
    ("SPD_08", "MctsBot", "Rushdown", "ZEN",
     [(0, 120, 2400), (0, 100, 2600), (110, 0, 3600)]),
]

# Explicit combo events for STD_04 (ComboKing vs AlphaStrike)
# Format: (frame, damage, stun_given)
STD_04_EVENTS = {
    1: {  # Round 1: CK deals 400 to AS, AS deals 50 to CK
        "p1": [  # ComboKing's hits on AlphaStrike
            # Combo 1: 4 hits
            (200, 30, 15), (210, 24, 15), (220, 19, 18), (235, 15, 22),
            # Single hit
            (500, 65, 18),
            # Combo 2: 2 hits
            (700, 30, 15), (710, 24, 15),
            # More singles
            (900, 80, 22), (1100, 40, 15), (1300, 45, 15), (1450, 28, 12),
        ],
        "p2": [  # AlphaStrike's hits on ComboKing
            (350, 25, 12), (800, 25, 12),
        ],
    },
    2: {  # Round 2: CK deals 400 to AS, AS deals 80 to CK
        "p1": [
            # Single
            (100, 30, 12),
            # Combo: 3 hits
            (250, 35, 18), (265, 28, 18), (280, 22, 18),
            # Singles
            (500, 65, 22), (700, 80, 22), (900, 50, 18),
            (1100, 40, 15), (1350, 30, 12), (1550, 20, 12),
        ],
        "p2": [
            (400, 40, 15), (850, 40, 15),
        ],
    },
    3: {  # Round 3: CK deals 400 to AS, AS deals 120 to CK
        "p1": [
            # Combo: 3 hits (high damage)
            (300, 80, 22), (320, 64, 22), (340, 51, 22),
            # Singles
            (600, 65, 18), (800, 40, 15), (1000, 30, 12),
            (1200, 30, 12), (1400, 25, 12), (1600, 15, 10),
        ],
        "p2": [
            (200, 40, 15), (500, 40, 15), (700, 40, 15),
        ],
    },
}

# Verify STD_04 damage totals
for rnd, evts in STD_04_EVENTS.items():
    p1_dmg = sum(d for _, d, _ in evts["p1"])
    p2_dmg = sum(d for _, d, _ in evts["p2"])
    m = MATCHES[3]  # STD_04
    expected_p2_hp = m[4][rnd-1][1]  # p2 remaining hp
    expected_p1_hp = m[4][rnd-1][0]  # p1 remaining hp
    assert p1_dmg == INITIAL_HP - expected_p2_hp, \
        f"STD_04 R{rnd} P1 damage mismatch: {p1_dmg} != {INITIAL_HP - expected_p2_hp}"
    assert p2_dmg == INITIAL_HP - expected_p1_hp, \
        f"STD_04 R{rnd} P2 damage mismatch: {p2_dmg} != {INITIAL_HP - expected_p1_hp}"


def distribute_damage(total_damage, total_frames, offset=100, stun=15):
    """Distribute damage into evenly-spaced single hit events.

    Returns list of (frame, damage, stun) tuples.
    Spacing guaranteed > stun to avoid accidental combos.
    """
    if total_damage <= 0:
        return []
    num_hits = max(1, total_damage // 50)
    base_dmg = total_damage // num_hits
    remainder = total_damage - base_dmg * num_hits
    usable = total_frames - 2 * offset
    frame_step = max(stun + 20, usable // (num_hits + 1))
    events = []
    for i in range(num_hits):
        frame = offset + frame_step * (i + 1)
        dmg = base_dmg + (1 if i < remainder else 0)
        events.append((frame, dmg, stun))
    return events


def make_player_frame(hp, energy, x, y, facing_right,
                      stun_remaining=0, attack_landed=False,
                      received_hit=False, damage_dealt=0,
                      action=game_pb2.NEUTRAL, action_elapsed=0):
    pf = game_pb2.PlayerFrame()
    pf.hp = hp
    pf.energy = energy
    pf.x = x
    pf.y = y
    pf.current_action = action
    pf.action_elapsed_frames = action_elapsed
    pf.facing_right = facing_right
    pf.attack_landed = attack_landed
    pf.received_hit = received_hit
    pf.stun_remaining = stun_remaining
    pf.damage_dealt = damage_dealt
    return pf


def create_frames_for_round(round_num, p1_events, p2_events, total_frames):
    """Create GameFrame messages from hit event lists."""
    # Merge and sort all events: (frame, attacker_player, damage, stun)
    all_events = [(f, 1, d, s) for f, d, s in p1_events] + \
                 [(f, 2, d, s) for f, d, s in p2_events]
    all_events.sort(key=lambda x: (x[0], x[1]))

    p1_hp = INITIAL_HP
    p2_hp = INITIAL_HP
    p1_stun = 0  # stun remaining on P1 (from P2's attacks)
    p2_stun = 0  # stun remaining on P2 (from P1's attacks)
    last_frame_num = 0
    p1_energy = 0
    p2_energy = 0

    frames = []

    # Initial frame
    gf = game_pb2.GameFrame()
    gf.frame_number = 0
    gf.round_number = round_num
    gf.p1.CopyFrom(make_player_frame(p1_hp, 0, 200, 0, True))
    gf.p2.CopyFrom(make_player_frame(p2_hp, 0, 760, 0, False))
    frames.append(gf)

    for evt_frame, attacker, dmg, stun in all_events:
        elapsed = evt_frame - last_frame_num
        p1_stun = max(0, p1_stun - elapsed)
        p2_stun = max(0, p2_stun - elapsed)

        gf = game_pb2.GameFrame()
        gf.frame_number = evt_frame
        gf.round_number = round_num

        if attacker == 1:
            # P1 attacks P2
            p2_hp = max(0, p2_hp - dmg)
            p1_energy = min(300, p1_energy + dmg // 4)
            gf.p1.CopyFrom(make_player_frame(
                p1_hp, p1_energy, 200, 0, True,
                stun_remaining=p1_stun,
                attack_landed=True, damage_dealt=dmg,
                action=game_pb2.STAND_A))
            gf.p2.CopyFrom(make_player_frame(
                p2_hp, p2_energy, 760, 0, False,
                stun_remaining=p2_stun,
                received_hit=True))
            p2_stun = stun
        else:
            # P2 attacks P1
            p1_hp = max(0, p1_hp - dmg)
            p2_energy = min(300, p2_energy + dmg // 4)
            gf.p1.CopyFrom(make_player_frame(
                p1_hp, p1_energy, 200, 0, True,
                stun_remaining=p1_stun,
                received_hit=True))
            gf.p2.CopyFrom(make_player_frame(
                p2_hp, p2_energy, 760, 0, False,
                stun_remaining=p2_stun,
                attack_landed=True, damage_dealt=dmg,
                action=game_pb2.STAND_A))
            p1_stun = stun

        frames.append(gf)
        last_frame_num = evt_frame

    # Final frame
    elapsed = total_frames - last_frame_num
    p1_stun = max(0, p1_stun - elapsed)
    p2_stun = max(0, p2_stun - elapsed)
    gf = game_pb2.GameFrame()
    gf.frame_number = total_frames
    gf.round_number = round_num
    gf.p1.CopyFrom(make_player_frame(p1_hp, p1_energy, 200, 0, True,
                                      stun_remaining=p1_stun))
    gf.p2.CopyFrom(make_player_frame(p2_hp, p2_energy, 760, 0, False,
                                      stun_remaining=p2_stun))
    frames.append(gf)

    return frames


def main():
    os.makedirs('/app/replays', exist_ok=True)

    for match_id, p1_name, p2_name, char, rounds in MATCHES:
        replay = game_pb2.MatchReplay()
        replay.match_id = match_id
        replay.p1_name = p1_name
        replay.p2_name = p2_name
        replay.character_name = char
        replay.initial_hp = INITIAL_HP
        replay.info_delay_frames = DELAY

        for r_idx, (p1_hp, p2_hp, total_frames) in enumerate(rounds):
            rnd = r_idx + 1

            if match_id == "STD_04" and rnd in STD_04_EVENTS:
                p1_evts = STD_04_EVENTS[rnd]["p1"]
                p2_evts = STD_04_EVENTS[rnd]["p2"]
            else:
                p1_damage = INITIAL_HP - p2_hp
                p2_damage = INITIAL_HP - p1_hp
                p1_evts = distribute_damage(p1_damage, total_frames,
                                            offset=100, stun=15)
                p2_evts = distribute_damage(p2_damage, total_frames,
                                            offset=150, stun=15)

            frames = create_frames_for_round(rnd, p1_evts, p2_evts,
                                             total_frames)
            replay.frames.extend(frames)

            rr = replay.round_results.add()
            rr.round_number = rnd
            rr.p1_remaining_hp = p1_hp
            rr.p2_remaining_hp = p2_hp
            rr.elapsed_frames = total_frames

        out_path = f'/app/replays/{match_id}.bin'
        with open(out_path, 'wb') as f:
            f.write(replay.SerializeToString())
        print(f"Generated {out_path} ({os.path.getsize(out_path)} bytes)")

    print(f"Generated {len(MATCHES)} replay files.")


if __name__ == '__main__':
    main()
