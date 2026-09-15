The `crafter` Python package (PyPI) implements a 2D open-world survival game engine used as an RL benchmark. No documentation or source files are provided in this environment.

Install the package, reverse-engineer its complete behavioral dynamics through source inspection and targeted experiments, and write `/app/analysis.json` with these sections:

## `survival_dynamics`
The player has four coupled accumulator systems (hunger, thirst, fatigue, health recovery). Assuming the player is awake, takes no actions, and receives no enemy damage:
- `first_food_loss_step`, `first_drink_loss_step`, `first_energy_loss_step`: game step at which each vital first decreases from initial value
- `drink_zero_step`: game step when drink reaches zero
- `first_health_loss_step`: game step when health first decreases (the health recovery accumulator reverses direction when any vital depletes — trace all four accumulators to find this)
- `sleep_steps_full_energy_restore`: minimum sleep steps to restore energy from 0 to max, assuming the fatigue accumulator starts at its best-case value

## `combat_model`
- `weapon_damage`: map from weapon (`bare_hands`, `wood_sword`, `stone_sword`, `iron_sword`) to integer damage
- `creature_health`: map from creature type (`zombie`, `skeleton`, `cow`) to integer max health
- `hits_to_kill`: nested map — creature type to weapon to integer hits required
- `zombie_attack`: object with `damage_awake`, `damage_sleeping`, `cooldown` (wait steps after attack)
- `skeleton_attack`: object with `arrow_damage`, `reload_steps`, `shoot_range`, `flee_range`, `chase_range`
- `arrow_destroys_materials`: sorted list of materials arrows destroy on impact
- `player_wakes_on_damage`: boolean — does taking damage while sleeping cause the player to wake?

## `population_balancing`
A hidden dynamic creature rebalancing system runs periodically during gameplay. Reverse-engineer it:
- `chunk_dimensions`: `[width, height]` of spatial chunks used for population management
- `rebalance_interval`: game steps between rebalancing checks
- For each creature type (`zombie`, `skeleton`, `cow`), an object with: `material` (tile type counted for available space), `spawn_prob`, `despawn_prob`, `spawn_distance` (min from player to spawn), `despawn_distance` (min from player to despawn), `space_threshold` (min tile count for non-zero target_min), `target_night` (`[int(target_min), int(target_max)]` at daylight=0 with sufficient space), `target_day` (same at daylight=1)

## `world_state_seed42`
Instantiate with `seed=42`, call `reset()`, inspect the world's internal grid:
- `material_counts`: map from material name to tile count
- `creature_counts`: map from creature type (`cow`, `zombie`, `skeleton`) to count
- `total_tiles`: total grid cells

## `technology_tree`
22 achievements with prerequisite relationships derivable from crafting/collection mechanics:
- `total_achievements`, `direct_dependencies` (each achievement to sorted prerequisite list), `achievement_depths` (0 = no prereqs; else 1 + max dependency depth), `critical_path` (longest chain from depth-0 to deepest; alphabetic tie-breaking at each backtrack), `critical_path_length` (edge count)
- `critical_path_total_resources`: map from raw material (`wood`, `stone`, `coal`, `iron`) to the minimum quantity that must be collected to perform all crafting/placing operations along the critical path and its transitive dependencies
- `most_depended_achievement`: achievement appearing as a direct prerequisite for the most other achievements
- `most_depended_count`: how many achievements directly depend on it

## `daylight_model`
- `cycle_period`, `phase_offset`, `default_episode_length`
- `daylight_at_step`: map from step number (string keys `"0"`, `"75"`, `"150"`, `"225"`) to computed float daylight value using the engine's daylight formula