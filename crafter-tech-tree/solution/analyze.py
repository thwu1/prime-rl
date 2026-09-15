#!/usr/bin/env python3

"""
Reverse-engineer the crafter game engine and produce /app/analysis.json.

Sections:
1. survival_dynamics — simulate coupled accumulator systems
2. combat_model — extract damage values, compute hits-to-kill
3. population_balancing — reverse-engineer dynamic spawning system
4. world_state_seed42 — run simulation and inspect internal state
5. technology_tree — build dependency graph, compute resource costs
6. daylight_model — extract and evaluate daylight formula
"""

import json
import inspect
import math
import re
from collections import defaultdict

import crafter
import crafter.worldgen
from crafter import constants, objects, engine
import numpy as np


def compute_survival_dynamics():
    """Simulate the four coupled accumulators step-by-step."""
    food = 9
    drink = 9
    energy = 9
    health = 9
    hunger = 0.0
    thirst = 0.0
    fatigue = 0
    recover = 0.0
    sleeping = False

    first_food_loss = None
    first_drink_loss = None
    first_energy_loss = None
    drink_zero = None
    first_health_loss = None

    for step in range(1, 500):
        # Reproduce _update_life_stats
        hunger += 0.5 if sleeping else 1
        if hunger > 25:
            hunger = 0
            food -= 1
        thirst += 0.5 if sleeping else 1
        if thirst > 20:
            thirst = 0
            drink -= 1
        if sleeping:
            fatigue = min(fatigue - 1, 0)
        else:
            fatigue += 1
        if fatigue < -10:
            fatigue = 0
            energy += 1
        if fatigue > 30:
            fatigue = 0
            energy -= 1

        # Reproduce _degen_or_regen_health
        necessities = (food > 0, drink > 0, energy > 0 or sleeping)
        if all(necessities):
            recover += 2 if sleeping else 1
        else:
            recover -= 0.5 if sleeping else 1
        if recover > 25:
            recover = 0
            health += 1
        if recover < -15:
            recover = 0
            health -= 1

        # Clamp
        food = max(0, min(food, 9))
        drink = max(0, min(drink, 9))
        energy = max(0, min(energy, 9))
        health = max(0, min(health, 9))

        if first_food_loss is None and food < 9:
            first_food_loss = step
        if first_drink_loss is None and drink < 9:
            first_drink_loss = step
        if first_energy_loss is None and energy < 9:
            first_energy_loss = step
        if drink_zero is None and drink == 0:
            drink_zero = step
        if first_health_loss is None and health < 9:
            first_health_loss = step

    # Sleep energy restore: from energy=0, fatigue=0 (best case)
    e = 0
    f = 0
    sleep_steps = 0
    while e < 9:
        sleep_steps += 1
        f = min(f - 1, 0)
        if f < -10:
            f = 0
            e += 1

    return {
        "first_food_loss_step": first_food_loss,
        "first_drink_loss_step": first_drink_loss,
        "first_energy_loss_step": first_energy_loss,
        "drink_zero_step": drink_zero,
        "first_health_loss_step": first_health_loss,
        "sleep_steps_full_energy_restore": sleep_steps,
    }


def compute_combat_model():
    """Extract combat mechanics via dynamic testing and source inspection."""
    # Weapon damage via dynamic test
    weapon_damage = {}
    weapon_configs = [
        ("bare_hands", {}),
        ("wood_sword", {"wood_sword": 1}),
        ("stone_sword", {"stone_sword": 1}),
        ("iron_sword", {"iron_sword": 1}),
    ]
    for weapon_name, inv_items in weapon_configs:
        w = engine.World((20, 20), constants.materials, (12, 12))
        w.reset(seed=0)
        p = objects.Player(w, (10, 10))
        w.add(p)
        for k, v in inv_items.items():
            p.inventory[k] = v
        z = objects.Zombie(w, (11, 10), p)
        w.add(z)
        hp_before = z.health
        p.facing = (1, 0)
        p.action = "do"
        p.update()
        weapon_damage[weapon_name] = hp_before - z.health

    # Creature health
    creature_health = {"zombie": 5, "skeleton": 3, "cow": 3}
    # Verify dynamically
    w = engine.World((20, 20), constants.materials, (12, 12))
    w.reset(seed=0)
    p = objects.Player(w, (10, 10))
    w.add(p)
    z = objects.Zombie(w, (15, 15), p)
    assert z.health == creature_health["zombie"]
    s = objects.Skeleton(w, (16, 16), p)
    assert s.health == creature_health["skeleton"]
    c = objects.Cow(w, (17, 17))
    assert c.health == creature_health["cow"]

    # Hits to kill
    hits_to_kill = {}
    for creature, hp in creature_health.items():
        hits_to_kill[creature] = {}
        for weapon, dmg in weapon_damage.items():
            hits_to_kill[creature][weapon] = math.ceil(hp / dmg)

    # Zombie attack params from source
    z_update_src = inspect.getsource(objects.Zombie.update)
    z_damages = re.findall(r"damage\s*=\s*(\d+)", z_update_src)
    zombie_dmg_sleeping = int(z_damages[0])
    zombie_dmg_awake = int(z_damages[1])
    zombie_cooldown = int(
        re.search(r"self\.cooldown\s*=\s*(\d+)", z_update_src).group(1)
    )

    # Skeleton attack params from source
    sk_update_src = inspect.getsource(objects.Skeleton.update)
    sk_ranges = re.findall(r"dist\s*<=\s*(\d+)", sk_update_src)
    skel_flee = int(sk_ranges[0])
    skel_shoot = int(sk_ranges[1])
    skel_chase = int(sk_ranges[2])
    sk_shoot_src = inspect.getsource(objects.Skeleton._shoot)
    skel_reload = int(
        re.search(r"self\.reload\s*=\s*(\d+)", sk_shoot_src).group(1)
    )
    arrow_src = inspect.getsource(objects.Arrow.update)
    arrow_dmg = int(
        re.search(r"obj\.health\s*-=\s*(\d+)", arrow_src).group(1)
    )
    mat_list_match = re.search(r"material\s+in\s+\[([^\]]+)\]", arrow_src)
    arrow_destroys = sorted(re.findall(r"'(\w+)'", mat_list_match.group(1)))

    # Player wakes on damage
    wake_src = inspect.getsource(objects.Player._wake_up_when_hurt)
    player_wakes = "self.sleeping = False" in wake_src

    return {
        "weapon_damage": weapon_damage,
        "creature_health": creature_health,
        "hits_to_kill": hits_to_kill,
        "zombie_attack": {
            "damage_awake": zombie_dmg_awake,
            "damage_sleeping": zombie_dmg_sleeping,
            "cooldown": zombie_cooldown,
        },
        "skeleton_attack": {
            "arrow_damage": arrow_dmg,
            "reload_steps": skel_reload,
            "shoot_range": skel_shoot,
            "flee_range": skel_flee,
            "chase_range": skel_chase,
        },
        "arrow_destroys_materials": arrow_destroys,
        "player_wakes_on_damage": player_wakes,
    }


def compute_population_balancing():
    """Reverse-engineer the dynamic creature rebalancing system in env.py."""
    # Extract chunk dimensions from World constructor call in Env.__init__
    init_src = inspect.getsource(crafter.Env.__init__)
    chunk_match = re.search(r"engine\.World\([^,]+,\s*[^,]+,\s*\((\d+),\s*(\d+)\)\)", init_src)
    chunk_dims = [int(chunk_match.group(1)), int(chunk_match.group(2))]

    # Extract rebalance interval from step()
    step_src = inspect.getsource(crafter.Env.step)
    interval_match = re.search(r"self\._step\s*%\s*(\d+)\s*==\s*0", step_src)
    rebalance_interval = int(interval_match.group(1))

    # Extract _balance_chunk source to get parameters for each creature
    balance_src = inspect.getsource(crafter.Env._balance_chunk)

    # Parse the _balance_object calls
    # Pattern: _balance_object(chunk, objs, objects.Type, 'material', span_dist, despan_dist, spawn_prob, despawn_prob, ctor, target_fn)
    calls = re.findall(
        r"self\._balance_object\(\s*"
        r"chunk,\s*objs,\s*objects\.(\w+),\s*'(\w+)',\s*"
        r"(\d+),\s*(\d+),\s*([\d.]+),\s*([\d.]+),",
        balance_src,
    )

    creatures = {}
    for cls_name, material, span_dist, despan_dist, spawn_prob, despawn_prob in calls:
        name = cls_name.lower()
        creatures[name] = {
            "material": material,
            "spawn_prob": float(spawn_prob),
            "despawn_prob": float(despawn_prob),
            "spawn_distance": int(span_dist),
            "despawn_distance": int(despan_dist),
        }

    # Extract target functions by parsing the lambda expressions
    # Zombie: lambda num, space: (0 if space < 50 else 3.5 - 3 * light, 3.5 - 3 * light)
    zombie_lambda = re.search(
        r"objects\.Zombie.*?lambda\s+num,\s*space:\s*\(\s*"
        r"0\s+if\s+space\s*<\s*(\d+)\s+else\s+([\d.]+)\s*-\s*([\d.]+)\s*\*\s*light\s*,\s*"
        r"([\d.]+)\s*-\s*([\d.]+)\s*\*\s*light\s*\)",
        balance_src, re.DOTALL
    )
    z_space_thresh = int(zombie_lambda.group(1))
    z_base = float(zombie_lambda.group(2))
    z_coeff = float(zombie_lambda.group(3))
    creatures["zombie"]["space_threshold"] = z_space_thresh
    creatures["zombie"]["target_night"] = [int(z_base - z_coeff * 0), int(z_base - z_coeff * 0)]
    creatures["zombie"]["target_day"] = [int(z_base - z_coeff * 1), int(z_base - z_coeff * 1)]

    # Skeleton: lambda num, space: (0 if space < 6 else 1, 2)
    skel_lambda = re.search(
        r"objects\.Skeleton.*?lambda\s+num,\s*space:\s*\(\s*"
        r"0\s+if\s+space\s*<\s*(\d+)\s+else\s+(\d+)\s*,\s*(\d+)\s*\)",
        balance_src, re.DOTALL
    )
    s_space_thresh = int(skel_lambda.group(1))
    s_min = int(skel_lambda.group(2))
    s_max = int(skel_lambda.group(3))
    creatures["skeleton"]["space_threshold"] = s_space_thresh
    creatures["skeleton"]["target_night"] = [s_min, s_max]
    creatures["skeleton"]["target_day"] = [s_min, s_max]

    # Cow: lambda num, space: (0 if space < 30 else 1, 1.5 + light)
    cow_lambda = re.search(
        r"objects\.Cow.*?lambda\s+num,\s*space:\s*\(\s*"
        r"0\s+if\s+space\s*<\s*(\d+)\s+else\s+(\d+)\s*,\s*([\d.]+)\s*\+\s*light\s*\)",
        balance_src, re.DOTALL
    )
    c_space_thresh = int(cow_lambda.group(1))
    c_min = int(cow_lambda.group(2))
    c_max_base = float(cow_lambda.group(3))
    creatures["cow"]["space_threshold"] = c_space_thresh
    creatures["cow"]["target_night"] = [c_min, int(c_max_base + 0)]
    creatures["cow"]["target_day"] = [c_min, int(c_max_base + 1)]

    return {
        "chunk_dimensions": chunk_dims,
        "rebalance_interval": rebalance_interval,
        "zombie": creatures["zombie"],
        "skeleton": creatures["skeleton"],
        "cow": creatures["cow"],
    }


def compute_world_state_seed42():
    """Run env with seed=42, inspect internal world state."""
    env = crafter.Env(seed=42)
    env.reset()
    world = env._world

    mat_counts = {}
    for idx, name in world._mat_names.items():
        if name is not None:
            count = int((world._mat_map == idx).sum())
            if count > 0:
                mat_counts[name] = count

    creature_counts = {"cow": 0, "zombie": 0, "skeleton": 0}
    for obj in world.objects:
        if isinstance(obj, objects.Cow):
            creature_counts["cow"] += 1
        elif isinstance(obj, objects.Zombie):
            creature_counts["zombie"] += 1
        elif isinstance(obj, objects.Skeleton):
            creature_counts["skeleton"] += 1

    total = int(world._mat_map.shape[0] * world._mat_map.shape[1])

    return {
        "material_counts": mat_counts,
        "creature_counts": creature_counts,
        "total_tiles": total,
    }


def compute_technology_tree():
    """Build achievement dependency graph and compute resource costs."""
    achievements = list(constants.achievements)

    # Build item-to-achievement mappings
    item_to_collect = {}
    for material, info in constants.collect.items():
        for item in info["receive"]:
            item_to_collect[item] = f"collect_{item}"

    item_to_make = {}
    for name in constants.make:
        item_to_make[name] = f"make_{name}"

    nearby_to_place = {}
    for name in constants.place:
        nearby_to_place[name] = f"place_{name}"

    def resolve_item(item):
        if item in item_to_collect:
            return item_to_collect[item]
        if item in item_to_make:
            return item_to_make[item]
        return None

    # Direct dependencies
    deps = {ach: set() for ach in achievements}

    for material, info in constants.collect.items():
        for received_item in info["receive"]:
            ach_name = f"collect_{received_item}"
            if ach_name not in deps:
                continue
            for req_item in info.get("require", {}):
                dep = resolve_item(req_item)
                if dep:
                    deps[ach_name].add(dep)

    for name, info in constants.make.items():
        ach_name = f"make_{name}"
        if ach_name not in deps:
            continue
        for used_item in info.get("uses", {}):
            dep = resolve_item(used_item)
            if dep:
                deps[ach_name].add(dep)
        for mat in info.get("nearby", []):
            if mat in nearby_to_place:
                deps[ach_name].add(nearby_to_place[mat])

    for name, info in constants.place.items():
        ach_name = f"place_{name}"
        if ach_name not in deps:
            continue
        for used_item in info.get("uses", {}):
            dep = resolve_item(used_item)
            if dep:
                deps[ach_name].add(dep)

    # Special: eat_plant requires place_plant
    deps["eat_plant"] = {"place_plant"}

    direct_deps = {k: sorted(v) for k, v in deps.items()}

    # Depths
    memo = {}
    def depth(ach):
        if ach in memo:
            return memo[ach]
        if not direct_deps[ach]:
            memo[ach] = 0
            return 0
        d = 1 + max(depth(dep) for dep in direct_deps[ach])
        memo[ach] = d
        return d

    achievement_depths = {ach: depth(ach) for ach in achievements}

    # Critical path
    max_depth = max(achievement_depths.values())
    deepest = sorted(a for a, d in achievement_depths.items() if d == max_depth)[0]
    path = [deepest]
    current = deepest
    while achievement_depths[current] > 0:
        d_deps = direct_deps[current]
        max_dep_d = max(achievement_depths[d] for d in d_deps)
        candidates = sorted(d for d in d_deps if achievement_depths[d] == max_dep_d)
        current = candidates[0]
        path.append(current)
    path.reverse()

    # Critical path total resources: find all crafting/placing operations
    # needed for the critical path and its transitive dependencies
    needed_achievements = set(path)
    # Expand to include all transitive dependencies
    queue = list(needed_achievements)
    while queue:
        ach = queue.pop()
        for dep in direct_deps[ach]:
            if dep not in needed_achievements:
                needed_achievements.add(dep)
                queue.append(dep)

    # Sum resources consumed by all crafting/placing operations
    total_resources = defaultdict(int)
    for ach in needed_achievements:
        if ach.startswith("make_"):
            name = ach[len("make_"):]
            if name in constants.make:
                for item, amount in constants.make[name]["uses"].items():
                    total_resources[item] += amount
        elif ach.startswith("place_"):
            name = ach[len("place_"):]
            if name in constants.place:
                for item, amount in constants.place[name]["uses"].items():
                    total_resources[item] += amount

    # Only report raw materials (wood, stone, coal, iron)
    raw_materials = {"wood", "stone", "coal", "iron"}
    critical_path_resources = {
        mat: total_resources[mat] for mat in raw_materials if total_resources[mat] > 0
    }

    # Most depended achievement
    dep_count = defaultdict(int)
    for ach, dep_list in direct_deps.items():
        for dep in dep_list:
            dep_count[dep] += 1
    most_depended = max(dep_count.items(), key=lambda x: (x[1], x[0]))

    return {
        "total_achievements": len(achievements),
        "direct_dependencies": direct_deps,
        "achievement_depths": achievement_depths,
        "critical_path": path,
        "critical_path_length": len(path) - 1,
        "critical_path_total_resources": critical_path_resources,
        "most_depended_achievement": most_depended[0],
        "most_depended_count": most_depended[1],
    }


def compute_daylight_model():
    """Extract day/night cycle parameters and compute specific values."""
    update_src = inspect.getsource(crafter.Env._update_time)
    period = int(re.search(r"self\._step\s*/\s*(\d+)", update_src).group(1))
    offset = float(re.search(r"%\s*1\s*\+\s*([\d.]+)", update_src).group(1))

    init_src = inspect.getsource(crafter.Env.__init__)
    ep_length = int(re.search(r"length\s*=\s*(\d+)", init_src).group(1))

    def daylight(step):
        progress = (step / period) % 1 + offset
        return float(1 - abs(math.cos(math.pi * progress)) ** 3)

    daylight_at_step = {}
    for step in [0, 75, 150, 225]:
        daylight_at_step[str(step)] = daylight(step)

    return {
        "cycle_period": period,
        "phase_offset": offset,
        "default_episode_length": ep_length,
        "daylight_at_step": daylight_at_step,
    }


def main():
    analysis = {
        "survival_dynamics": compute_survival_dynamics(),
        "combat_model": compute_combat_model(),
        "population_balancing": compute_population_balancing(),
        "world_state_seed42": compute_world_state_seed42(),
        "technology_tree": compute_technology_tree(),
        "daylight_model": compute_daylight_model(),
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)

    print("Analysis written to /app/analysis.json")


if __name__ == "__main__":
    main()
