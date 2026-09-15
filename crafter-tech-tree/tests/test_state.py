
import json
import math
import os
import pytest
import numpy as np


@pytest.fixture(scope="module")
def analysis():
    path = "/app/analysis.json"
    assert os.path.exists(path), "analysis.json not found at /app/analysis.json"
    with open(path) as f:
        data = json.load(f)
    return data


# ── Survival Dynamics ──────────────────────────────────────────────────────

class TestSurvivalDynamics:
    """Verify step numbers by independently simulating the accumulator system."""

    @pytest.fixture(scope="class")
    def ground_truth(self):
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

        results = {}

        for step in range(1, 500):
            # _update_life_stats logic
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

            # _degen_or_regen_health logic
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

            if "first_food_loss" not in results and food < 9:
                results["first_food_loss"] = step
            if "first_drink_loss" not in results and drink < 9:
                results["first_drink_loss"] = step
            if "first_energy_loss" not in results and energy < 9:
                results["first_energy_loss"] = step
            if "drink_zero" not in results and drink == 0:
                results["drink_zero"] = step
            if "first_health_loss" not in results and health < 9:
                results["first_health_loss"] = step

        # Sleep energy restore: simulate sleeping from energy=0, fatigue=0
        e = 0
        f = 0
        steps = 0
        while e < 9:
            steps += 1
            f = min(f - 1, 0)
            if f < -10:
                f = 0
                e += 1
        results["sleep_restore"] = steps

        return results

    def test_first_food_loss_step(self, analysis, ground_truth):
        assert analysis["survival_dynamics"]["first_food_loss_step"] == ground_truth["first_food_loss"]

    def test_first_drink_loss_step(self, analysis, ground_truth):
        assert analysis["survival_dynamics"]["first_drink_loss_step"] == ground_truth["first_drink_loss"]

    def test_first_energy_loss_step(self, analysis, ground_truth):
        assert analysis["survival_dynamics"]["first_energy_loss_step"] == ground_truth["first_energy_loss"]

    def test_drink_zero_step(self, analysis, ground_truth):
        assert analysis["survival_dynamics"]["drink_zero_step"] == ground_truth["drink_zero"]

    def test_first_health_loss_step(self, analysis, ground_truth):
        assert analysis["survival_dynamics"]["first_health_loss_step"] == ground_truth["first_health_loss"]

    def test_sleep_steps_full_energy_restore(self, analysis, ground_truth):
        assert analysis["survival_dynamics"]["sleep_steps_full_energy_restore"] == ground_truth["sleep_restore"]


# ── Combat Model ───────────────────────────────────────────────────────────

class TestCombatWeaponDamage:
    EXPECTED = {
        "bare_hands": 1,
        "wood_sword": 2,
        "stone_sword": 3,
        "iron_sword": 5,
    }

    def test_weapon_damage(self, analysis):
        wd = analysis["combat_model"]["weapon_damage"]
        for weapon, expected in self.EXPECTED.items():
            assert wd[weapon] == expected, f"weapon_damage[{weapon}]: expected {expected}, got {wd[weapon]}"


class TestCombatCreatureHealth:
    EXPECTED = {"zombie": 5, "skeleton": 3, "cow": 3}

    def test_creature_health(self, analysis):
        ch = analysis["combat_model"]["creature_health"]
        for creature, expected in self.EXPECTED.items():
            assert ch[creature] == expected, f"creature_health[{creature}]: expected {expected}"


class TestHitsToKill:
    EXPECTED = {
        "zombie": {"bare_hands": 5, "wood_sword": 3, "stone_sword": 2, "iron_sword": 1},
        "skeleton": {"bare_hands": 3, "wood_sword": 2, "stone_sword": 1, "iron_sword": 1},
        "cow": {"bare_hands": 3, "wood_sword": 2, "stone_sword": 1, "iron_sword": 1},
    }

    def test_hits_to_kill(self, analysis):
        htk = analysis["combat_model"]["hits_to_kill"]
        for creature, weapons in self.EXPECTED.items():
            assert creature in htk, f"Missing creature {creature} in hits_to_kill"
            for weapon, expected in weapons.items():
                assert htk[creature][weapon] == expected, \
                    f"hits_to_kill[{creature}][{weapon}]: expected {expected}, got {htk[creature][weapon]}"


class TestZombieAttack:
    def test_damage_awake(self, analysis):
        assert analysis["combat_model"]["zombie_attack"]["damage_awake"] == 2

    def test_damage_sleeping(self, analysis):
        assert analysis["combat_model"]["zombie_attack"]["damage_sleeping"] == 7

    def test_cooldown(self, analysis):
        assert analysis["combat_model"]["zombie_attack"]["cooldown"] == 5


class TestSkeletonAttack:
    def test_arrow_damage(self, analysis):
        assert analysis["combat_model"]["skeleton_attack"]["arrow_damage"] == 2

    def test_reload_steps(self, analysis):
        assert analysis["combat_model"]["skeleton_attack"]["reload_steps"] == 4

    def test_shoot_range(self, analysis):
        assert analysis["combat_model"]["skeleton_attack"]["shoot_range"] == 5

    def test_flee_range(self, analysis):
        assert analysis["combat_model"]["skeleton_attack"]["flee_range"] == 3

    def test_chase_range(self, analysis):
        assert analysis["combat_model"]["skeleton_attack"]["chase_range"] == 8


class TestCombatMisc:
    def test_arrow_destroys_materials(self, analysis):
        assert sorted(analysis["combat_model"]["arrow_destroys_materials"]) == ["furnace", "table"]

    def test_player_wakes_on_damage(self, analysis):
        assert analysis["combat_model"]["player_wakes_on_damage"] is True


# ── Population Balancing ───────────────────────────────────────────────────

class TestPopulationBalancingGlobal:
    def test_chunk_dimensions(self, analysis):
        assert analysis["population_balancing"]["chunk_dimensions"] == [12, 12]

    def test_rebalance_interval(self, analysis):
        assert analysis["population_balancing"]["rebalance_interval"] == 10


class TestPopulationZombie:
    def test_material(self, analysis):
        assert analysis["population_balancing"]["zombie"]["material"] == "grass"

    def test_spawn_prob(self, analysis):
        assert analysis["population_balancing"]["zombie"]["spawn_prob"] == pytest.approx(0.3)

    def test_despawn_prob(self, analysis):
        assert analysis["population_balancing"]["zombie"]["despawn_prob"] == pytest.approx(0.4)

    def test_spawn_distance(self, analysis):
        assert analysis["population_balancing"]["zombie"]["spawn_distance"] == 6

    def test_despawn_distance(self, analysis):
        assert analysis["population_balancing"]["zombie"]["despawn_distance"] == 0

    def test_space_threshold(self, analysis):
        assert analysis["population_balancing"]["zombie"]["space_threshold"] == 50

    def test_target_night(self, analysis):
        # At daylight=0: target = (int(3.5), int(3.5)) = (3, 3)
        assert analysis["population_balancing"]["zombie"]["target_night"] == [3, 3]

    def test_target_day(self, analysis):
        # At daylight=1: target = (int(0.5), int(0.5)) = (0, 0)
        assert analysis["population_balancing"]["zombie"]["target_day"] == [0, 0]


class TestPopulationSkeleton:
    def test_material(self, analysis):
        assert analysis["population_balancing"]["skeleton"]["material"] == "path"

    def test_spawn_prob(self, analysis):
        assert analysis["population_balancing"]["skeleton"]["spawn_prob"] == pytest.approx(0.1)

    def test_despawn_prob(self, analysis):
        assert analysis["population_balancing"]["skeleton"]["despawn_prob"] == pytest.approx(0.1)

    def test_spawn_distance(self, analysis):
        assert analysis["population_balancing"]["skeleton"]["spawn_distance"] == 7

    def test_despawn_distance(self, analysis):
        assert analysis["population_balancing"]["skeleton"]["despawn_distance"] == 7

    def test_space_threshold(self, analysis):
        assert analysis["population_balancing"]["skeleton"]["space_threshold"] == 6

    def test_target_night(self, analysis):
        # Skeleton targets don't depend on daylight: (int(1), int(2)) = (1, 2)
        assert analysis["population_balancing"]["skeleton"]["target_night"] == [1, 2]

    def test_target_day(self, analysis):
        assert analysis["population_balancing"]["skeleton"]["target_day"] == [1, 2]


class TestPopulationCow:
    def test_material(self, analysis):
        assert analysis["population_balancing"]["cow"]["material"] == "grass"

    def test_spawn_prob(self, analysis):
        assert analysis["population_balancing"]["cow"]["spawn_prob"] == pytest.approx(0.01)

    def test_despawn_prob(self, analysis):
        assert analysis["population_balancing"]["cow"]["despawn_prob"] == pytest.approx(0.1)

    def test_spawn_distance(self, analysis):
        assert analysis["population_balancing"]["cow"]["spawn_distance"] == 5

    def test_despawn_distance(self, analysis):
        assert analysis["population_balancing"]["cow"]["despawn_distance"] == 5

    def test_space_threshold(self, analysis):
        assert analysis["population_balancing"]["cow"]["space_threshold"] == 30

    def test_target_night(self, analysis):
        # At daylight=0: target = (int(1), int(1.5)) = (1, 1)
        assert analysis["population_balancing"]["cow"]["target_night"] == [1, 1]

    def test_target_day(self, analysis):
        # At daylight=1: target = (int(1), int(2.5)) = (1, 2)
        assert analysis["population_balancing"]["cow"]["target_day"] == [1, 2]


# ── World State Seed42 ────────────────────────────────────────────────────

class TestWorldStateSeed42:
    """Independently run crafter with seed=42 and verify counts."""

    @pytest.fixture(scope="class")
    def ground_truth(self):
        import crafter
        from crafter import objects as obj_mod
        env = crafter.Env(seed=42)
        env.reset()
        world = env._world

        mat_counts = {}
        for idx, name in world._mat_names.items():
            if name is not None:
                c = int((world._mat_map == idx).sum())
                if c > 0:
                    mat_counts[name] = c

        creature_counts = {"cow": 0, "zombie": 0, "skeleton": 0}
        for o in world.objects:
            if isinstance(o, obj_mod.Cow):
                creature_counts["cow"] += 1
            elif isinstance(o, obj_mod.Zombie):
                creature_counts["zombie"] += 1
            elif isinstance(o, obj_mod.Skeleton):
                creature_counts["skeleton"] += 1

        total = world._mat_map.shape[0] * world._mat_map.shape[1]
        return {
            "material_counts": mat_counts,
            "creature_counts": creature_counts,
            "total_tiles": total,
        }

    def test_total_tiles(self, analysis, ground_truth):
        assert analysis["world_state_seed42"]["total_tiles"] == ground_truth["total_tiles"]

    def test_material_counts(self, analysis, ground_truth):
        reported = analysis["world_state_seed42"]["material_counts"]
        expected = ground_truth["material_counts"]
        for mat, count in expected.items():
            assert reported.get(mat, 0) == count, \
                f"material_counts[{mat}]: expected {count}, got {reported.get(mat, 0)}"

    def test_creature_counts(self, analysis, ground_truth):
        reported = analysis["world_state_seed42"]["creature_counts"]
        expected = ground_truth["creature_counts"]
        for ctype, count in expected.items():
            assert reported.get(ctype, 0) == count, \
                f"creature_counts[{ctype}]: expected {count}, got {reported.get(ctype, 0)}"

    def test_no_extra_materials(self, analysis, ground_truth):
        reported = analysis["world_state_seed42"]["material_counts"]
        for mat, count in reported.items():
            if count > 0:
                assert mat in ground_truth["material_counts"], \
                    f"Unexpected material {mat} with count {count}"


# ── Technology Tree ───────────────────────────────────────────────────────

ALL_ACHIEVEMENTS = [
    "collect_coal", "collect_diamond", "collect_drink", "collect_iron",
    "collect_sapling", "collect_stone", "collect_wood", "defeat_skeleton",
    "defeat_zombie", "eat_cow", "eat_plant", "make_iron_pickaxe",
    "make_iron_sword", "make_stone_pickaxe", "make_stone_sword",
    "make_wood_pickaxe", "make_wood_sword", "place_furnace", "place_plant",
    "place_stone", "place_table", "wake_up",
]

EXPECTED_DIRECT_DEPS = {
    "collect_coal": ["make_wood_pickaxe"],
    "collect_diamond": ["make_iron_pickaxe"],
    "collect_drink": [],
    "collect_iron": ["make_stone_pickaxe"],
    "collect_sapling": [],
    "collect_stone": ["make_wood_pickaxe"],
    "collect_wood": [],
    "defeat_skeleton": [],
    "defeat_zombie": [],
    "eat_cow": [],
    "eat_plant": ["place_plant"],
    "make_iron_pickaxe": ["collect_coal", "collect_iron", "collect_wood",
                          "place_furnace", "place_table"],
    "make_iron_sword": ["collect_coal", "collect_iron", "collect_wood",
                        "place_furnace", "place_table"],
    "make_stone_pickaxe": ["collect_stone", "collect_wood", "place_table"],
    "make_stone_sword": ["collect_stone", "collect_wood", "place_table"],
    "make_wood_pickaxe": ["collect_wood", "place_table"],
    "make_wood_sword": ["collect_wood", "place_table"],
    "place_furnace": ["collect_stone"],
    "place_plant": ["collect_sapling"],
    "place_stone": ["collect_stone"],
    "place_table": ["collect_wood"],
    "wake_up": [],
}

EXPECTED_DEPTHS = {
    "collect_coal": 3,
    "collect_diamond": 7,
    "collect_drink": 0,
    "collect_iron": 5,
    "collect_sapling": 0,
    "collect_stone": 3,
    "collect_wood": 0,
    "defeat_skeleton": 0,
    "defeat_zombie": 0,
    "eat_cow": 0,
    "eat_plant": 2,
    "make_iron_pickaxe": 6,
    "make_iron_sword": 6,
    "make_stone_pickaxe": 4,
    "make_stone_sword": 4,
    "make_wood_pickaxe": 2,
    "make_wood_sword": 2,
    "place_furnace": 4,
    "place_plant": 1,
    "place_stone": 4,
    "place_table": 1,
    "wake_up": 0,
}

EXPECTED_CRITICAL_PATH = [
    "collect_wood", "place_table", "make_wood_pickaxe", "collect_stone",
    "make_stone_pickaxe", "collect_iron", "make_iron_pickaxe",
    "collect_diamond",
]


class TestTechTreeStructure:
    def test_total_achievements(self, analysis):
        assert analysis["technology_tree"]["total_achievements"] == 22

    def test_all_achievements_present(self, analysis):
        dd = analysis["technology_tree"]["direct_dependencies"]
        for ach in ALL_ACHIEVEMENTS:
            assert ach in dd, f"Missing achievement: {ach}"


class TestDirectDependencies:
    def test_all_direct_deps(self, analysis):
        dd = analysis["technology_tree"]["direct_dependencies"]
        for ach, expected in EXPECTED_DIRECT_DEPS.items():
            actual = sorted(dd[ach])
            assert actual == expected, \
                f"direct_dependencies[{ach}]: expected {expected}, got {actual}"


class TestAchievementDepths:
    def test_all_depths(self, analysis):
        depths = analysis["technology_tree"]["achievement_depths"]
        for ach, expected in EXPECTED_DEPTHS.items():
            assert depths[ach] == expected, \
                f"depth[{ach}]: expected {expected}, got {depths[ach]}"

    def test_depth_consistency(self, analysis):
        dd = analysis["technology_tree"]["direct_dependencies"]
        depths = analysis["technology_tree"]["achievement_depths"]
        for ach in ALL_ACHIEVEMENTS:
            if not dd[ach]:
                assert depths[ach] == 0
            else:
                expected = 1 + max(depths[d] for d in dd[ach])
                assert depths[ach] == expected


class TestCriticalPath:
    def test_critical_path(self, analysis):
        assert analysis["technology_tree"]["critical_path"] == EXPECTED_CRITICAL_PATH

    def test_critical_path_length(self, analysis):
        assert analysis["technology_tree"]["critical_path_length"] == 7

    def test_path_is_valid_chain(self, analysis):
        path = analysis["technology_tree"]["critical_path"]
        dd = analysis["technology_tree"]["direct_dependencies"]
        for i in range(len(path) - 1):
            assert path[i] in dd[path[i + 1]], \
                f"{path[i]} should be a dep of {path[i + 1]}"


class TestCriticalPathResources:
    # To traverse the critical path (and its transitive deps), these crafting
    # operations consume raw materials:
    # place_table: 2 wood
    # make_wood_pickaxe: 1 wood
    # make_stone_pickaxe: 1 wood + 1 stone
    # place_furnace: 4 stone (transitive dep of make_iron_pickaxe)
    # make_iron_pickaxe: 1 wood + 1 coal + 1 iron
    # Total: wood=5, stone=5, coal=1, iron=1
    EXPECTED_RESOURCES = {"wood": 5, "stone": 5, "coal": 1, "iron": 1}

    def test_critical_path_total_resources(self, analysis):
        resources = analysis["technology_tree"]["critical_path_total_resources"]
        for material, expected in self.EXPECTED_RESOURCES.items():
            assert resources[material] == expected, \
                f"critical_path_total_resources[{material}]: expected {expected}, got {resources.get(material)}"


class TestMostDepended:
    def test_most_depended_achievement(self, analysis):
        # collect_wood appears as a direct dep of 7 other achievements
        assert analysis["technology_tree"]["most_depended_achievement"] == "collect_wood"

    def test_most_depended_count(self, analysis):
        assert analysis["technology_tree"]["most_depended_count"] == 7

    def test_count_is_correct(self, analysis):
        """Verify the count matches the actual dependency graph."""
        dd = analysis["technology_tree"]["direct_dependencies"]
        target = analysis["technology_tree"]["most_depended_achievement"]
        actual_count = sum(1 for deps in dd.values() if target in deps)
        assert actual_count == analysis["technology_tree"]["most_depended_count"]


# ── Daylight Model ────────────────────────────────────────────────────────

class TestDaylightParams:
    def test_cycle_period(self, analysis):
        assert analysis["daylight_model"]["cycle_period"] == 300

    def test_phase_offset(self, analysis):
        assert analysis["daylight_model"]["phase_offset"] == pytest.approx(0.3)

    def test_default_episode_length(self, analysis):
        assert analysis["daylight_model"]["default_episode_length"] == 10000


class TestDaylightComputed:
    """Verify computed daylight values against the formula."""

    @staticmethod
    def _daylight(step):
        progress = (step / 300) % 1 + 0.3
        return float(1 - abs(math.cos(math.pi * progress)) ** 3)

    @pytest.mark.parametrize("step", [0, 75, 150, 225])
    def test_daylight_at_step(self, analysis, step):
        expected = self._daylight(step)
        reported = analysis["daylight_model"]["daylight_at_step"][str(step)]
        assert reported == pytest.approx(expected, abs=1e-4), \
            f"daylight_at_step[{step}]: expected {expected:.6f}, got {reported}"


# ── Top-level Structure ──────────────────────────────────────────────────

class TestTopLevelKeys:
    REQUIRED_KEYS = [
        "survival_dynamics", "combat_model", "population_balancing",
        "world_state_seed42", "technology_tree", "daylight_model",
    ]

    def test_all_sections_present(self, analysis):
        for key in self.REQUIRED_KEYS:
            assert key in analysis, f"Missing top-level key: {key}"
