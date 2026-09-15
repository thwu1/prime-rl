
"""
MASSim simulation replay pipeline.
Loads resolved config + scenario, processes the action log step by step,
records replay data to SQLite, and writes final results to JSON.
"""

import json
import sqlite3
from collections import defaultdict

from massim_engine import MassimWorld, Role


def load_config():
    with open("/app/resolved_config.json") as f:
        return json.load(f)


def load_scenario():
    with open("/app/scenario.json") as f:
        return json.load(f)


def load_action_log():
    with open("/app/action_log.json") as f:
        return json.load(f)


def setup_world(config, scenario):
    match_cfg = config["match"]
    grid_w = match_cfg["grid"]["width"]
    grid_h = match_cfg["grid"]["height"]

    world = MassimWorld(grid_w, grid_h)

    # Energy params from config
    world.set_energy_params(
        max_energy=match_cfg["maxEnergy"],
        step_recharge=match_cfg["stepRecharge"],
        deactivated_duration=match_cfg["deactivatedDuration"],
        refresh_energy=match_cfg["refreshEnergy"],
    )

    # Roles from config
    for role_def in match_cfg["roles"]:
        role = Role(
            name=role_def["name"],
            vision=role_def["vision"],
            actions=role_def["actions"],
            speed=role_def["speed"],
            clear_chance=role_def["clearChance"],
            clear_max_dist=role_def["clearMaxDistance"],
        )
        world.add_role(role)

    # Agents from scenario
    for agent in scenario["agents"]:
        world.add_agent(
            agent["name"], agent["team"], agent["role"],
            agent["x"], agent["y"],
        )

    # Blocks from scenario
    for block in scenario["blocks"]:
        world.place_block(block["id"], block["type"], block["x"], block["y"])

    # Obstacles from scenario
    for obs in scenario.get("obstacles", []):
        world.place_obstacle(obs["x"], obs["y"])

    # Dispensers from scenario
    for disp in scenario.get("dispensers", []):
        world.place_dispenser(disp["type"], disp["x"], disp["y"])

    # Goal zones
    for gz in scenario.get("goal_zones", []):
        world.add_goal_zone(gz["cx"], gz["cy"], gz["radius"])

    # Role zones
    for rz in scenario.get("role_zones", []):
        world.add_role_zone(rz["cx"], rz["cy"], rz["radius"])

    # Norms
    for norm in scenario.get("norms", []):
        world.add_norm(
            norm["name"], norm["subject"], norm["start"], norm["until"],
            norm["level"], norm["requirements"], norm["punishment"],
        )

    # Tasks
    for task in scenario.get("tasks", []):
        world.add_task(
            task["name"], task["deadline"], task["reward"],
            task["requirements"],
        )

    return world


def setup_database():
    db = sqlite3.connect("/app/replay.db")
    db.execute(
        "CREATE TABLE IF NOT EXISTS agent_states ("
        "step INT, agent_name TEXT, x INT, y INT, energy INT, "
        "role TEXT, deactivated INT, num_attachments INT, "
        "PRIMARY KEY(step, agent_name))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS block_states ("
        "step INT, block_id TEXT, block_type TEXT, x INT, y INT, "
        "PRIMARY KEY(step, block_id))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS action_results ("
        "step INT, agent_name TEXT, action TEXT, params TEXT, result TEXT, "
        "PRIMARY KEY(step, agent_name))"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS norm_violations ("
        "step INT, agent_name TEXT, norm_name TEXT)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS scores ("
        "step INT, team TEXT, score INT, "
        "PRIMARY KEY(step, team))"
    )
    db.commit()
    return db


def record_state(db, world, step):
    for name, agent in world.agents.items():
        att_count = len(world.get_all_attached(name))
        db.execute(
            "INSERT OR REPLACE INTO agent_states VALUES (?,?,?,?,?,?,?,?)",
            (step, name, agent["x"], agent["y"], agent["energy"],
             agent["role"], int(agent["deactivated"]), att_count),
        )
    for bid, block in world.blocks.items():
        db.execute(
            "INSERT OR REPLACE INTO block_states VALUES (?,?,?,?,?)",
            (step, bid, block["type"], block["x"], block["y"]),
        )
    for team in world.scores:
        db.execute(
            "INSERT OR REPLACE INTO scores VALUES (?,?,?)",
            (step, team, world.get_score(team)),
        )


def run_pipeline():
    config = load_config()
    scenario = load_scenario()
    action_log = load_action_log()

    world = setup_world(config, scenario)
    db = setup_database()

    # Group actions by step
    actions_by_step = defaultdict(list)
    for entry in action_log:
        actions_by_step[entry["step"]].append(entry)

    max_step = max(actions_by_step.keys()) if actions_by_step else 0

    # Process each step
    for step in range(1, max_step + 1):
        # 1. Recharge all non-deactivated agents
        for name in world.agents:
            world.apply_step_recharge(name)

        # 2. Check norm violations, apply energy penalties
        for name in list(world.agents.keys()):
            violations = world.check_norm_violations(name, step)
            for norm_name in violations:
                norm = world.norms[norm_name]
                world.apply_energy_change(name, -norm["punishment"])
                db.execute(
                    "INSERT INTO norm_violations VALUES (?,?,?)",
                    (step, name, norm_name),
                )

        # 3. Execute actions for this step
        for entry in actions_by_step.get(step, []):
            result = world.execute_action(
                entry["agent"], entry["action"],
                entry["params"], step=step,
            )
            db.execute(
                "INSERT INTO action_results VALUES (?,?,?,?,?)",
                (step, entry["agent"], entry["action"],
                 json.dumps(entry["params"]), result),
            )

        # 4. Record state
        record_state(db, world, step)
        db.commit()

    # Write final results
    results = {
        "teams": {team: score for team, score in world.scores.items()},
        "steps_played": max_step,
    }
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    db.close()


if __name__ == "__main__":
    run_pipeline()
