#!/usr/bin/env python3
"""Generate the episodes.db SQLite database for the Crafter evaluation task."""

import os
import sqlite3

DEPS = {
    "collect_wood": [],
    "defeat_zombie": [],
    "defeat_skeleton": [],
    "eat_cow": [],
    "wake_up": [],
    "collect_sapling": [],
    "collect_drink": [],
    "place_table": ["collect_wood"],
    "place_plant": ["collect_sapling"],
    "eat_plant": ["place_plant"],
    "make_wood_pickaxe": ["collect_wood", "place_table"],
    "make_wood_sword": ["collect_wood", "place_table"],
    "collect_stone": ["make_wood_pickaxe"],
    "collect_coal": ["make_wood_pickaxe"],
    "place_stone": ["collect_stone"],
    "make_stone_pickaxe": ["collect_stone", "collect_wood", "place_table"],
    "make_stone_sword": ["collect_stone", "collect_wood", "place_table"],
    "place_furnace": ["collect_stone"],
    "collect_iron": ["make_stone_pickaxe"],
    "make_iron_pickaxe": ["collect_coal", "collect_iron", "collect_wood",
                          "place_furnace", "place_table"],
    "make_iron_sword": ["collect_coal", "collect_iron", "collect_wood",
                         "place_furnace", "place_table"],
    "collect_diamond": ["make_iron_pickaxe"],
}


def compute_depths():
    depth = {a: 0 for a in DEPS}
    changed = True
    while changed:
        changed = False
        for a in DEPS:
            for d in DEPS[a]:
                if depth[d] + 1 > depth[a]:
                    depth[a] = depth[d] + 1
                    changed = True
    return depth


DEPTHS = compute_depths()
ALL = set(DEPS.keys())
ANOMALOUS = {("rnd", 2), ("rnd", 5), ("rnd", 8)}

# dreamer: strong consistent agent - high breadth and depth
dreamer_eps = [
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling", "eat_cow",
     "defeat_zombie", "defeat_skeleton",
     "place_table", "place_plant", "eat_plant",
     "make_wood_pickaxe", "make_wood_sword",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "place_furnace",
     "collect_iron", "make_iron_pickaxe", "collect_diamond"},
    ALL.copy(),
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling", "eat_cow",
     "defeat_zombie",
     "place_table", "place_plant",
     "make_wood_pickaxe", "make_wood_sword",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "place_furnace",
     "collect_iron"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling", "eat_cow",
     "defeat_zombie",
     "place_table",
     "make_wood_pickaxe",
     "collect_stone", "collect_coal"},
    ALL - {"make_iron_sword"},
    {"collect_wood", "wake_up", "collect_drink",
     "eat_cow", "defeat_zombie", "defeat_skeleton",
     "place_table",
     "make_wood_pickaxe",
     "collect_stone"},
    ALL.copy(),
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling",
     "eat_cow", "defeat_zombie",
     "place_table", "place_plant",
     "make_wood_pickaxe",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "place_furnace"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling",
     "eat_cow", "defeat_zombie", "defeat_skeleton",
     "place_table", "place_plant", "eat_plant",
     "make_wood_pickaxe", "make_wood_sword",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "place_furnace",
     "collect_iron", "make_iron_pickaxe"},
    {"collect_wood", "wake_up", "collect_drink",
     "eat_cow",
     "place_table",
     "make_wood_pickaxe",
     "collect_stone"},
]

# ppo: broad coverage agent - consistent on shallow, one deep episode
ppo_eps = [
    ALL.copy(),
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling", "eat_cow",
     "defeat_zombie", "defeat_skeleton",
     "place_table", "place_plant", "eat_plant",
     "make_wood_pickaxe", "make_wood_sword",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "place_furnace"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling", "eat_cow",
     "defeat_zombie", "defeat_skeleton",
     "place_table", "place_plant", "eat_plant",
     "make_wood_pickaxe", "make_wood_sword",
     "collect_stone", "collect_coal"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling", "eat_cow",
     "defeat_zombie", "defeat_skeleton",
     "place_table", "place_plant", "eat_plant",
     "make_wood_pickaxe", "make_wood_sword",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "make_stone_sword", "place_stone", "place_furnace"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling", "eat_cow",
     "defeat_zombie",
     "place_table", "place_plant",
     "make_wood_pickaxe", "make_wood_sword",
     "collect_stone", "collect_coal"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling", "eat_cow",
     "defeat_zombie", "defeat_skeleton",
     "place_table", "place_plant", "eat_plant",
     "make_wood_pickaxe",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "place_furnace"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling", "eat_cow",
     "defeat_zombie", "defeat_skeleton",
     "place_table", "place_plant", "eat_plant",
     "make_wood_pickaxe", "make_wood_sword",
     "collect_stone", "collect_coal"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling", "eat_cow",
     "defeat_zombie",
     "place_table", "place_plant", "eat_plant",
     "make_wood_pickaxe", "make_wood_sword",
     "collect_stone", "collect_coal",
     "place_furnace"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling", "eat_cow",
     "defeat_zombie", "defeat_skeleton",
     "place_table", "place_plant", "eat_plant",
     "make_wood_pickaxe",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "place_furnace", "place_stone"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling", "eat_cow",
     "defeat_zombie", "defeat_skeleton",
     "place_table", "place_plant", "eat_plant",
     "make_wood_pickaxe", "make_wood_sword",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "place_furnace",
     "collect_iron"},
]

# curious: deep crafter, inconsistent on combat/survival
curious_eps = [
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling",
     "place_table", "place_plant", "eat_plant",
     "make_wood_pickaxe",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "place_furnace",
     "collect_iron", "make_iron_pickaxe", "collect_diamond"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling",
     "defeat_zombie",
     "place_table", "place_plant",
     "make_wood_pickaxe", "make_wood_sword",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "make_stone_sword", "place_furnace", "place_stone",
     "collect_iron", "make_iron_pickaxe", "make_iron_sword", "collect_diamond"},
    {"collect_wood", "wake_up", "collect_drink",
     "place_table",
     "make_wood_pickaxe",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "place_furnace",
     "collect_iron"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling",
     "place_table",
     "make_wood_pickaxe",
     "collect_stone"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling",
     "eat_cow",
     "place_table", "place_plant", "eat_plant",
     "make_wood_pickaxe",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "place_furnace",
     "collect_iron", "make_iron_pickaxe", "collect_diamond"},
    {"collect_wood", "wake_up", "collect_drink",
     "defeat_zombie",
     "place_table",
     "make_wood_pickaxe", "make_wood_sword",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "place_furnace"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling",
     "place_table", "place_plant",
     "make_wood_pickaxe",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "make_stone_sword", "place_furnace", "place_stone",
     "collect_iron", "make_iron_pickaxe", "make_iron_sword", "collect_diamond"},
    {"collect_wood", "wake_up", "collect_drink",
     "place_table",
     "make_wood_pickaxe",
     "collect_stone"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling",
     "eat_cow", "defeat_zombie",
     "place_table", "place_plant", "eat_plant",
     "make_wood_pickaxe",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "place_furnace",
     "collect_iron", "make_iron_pickaxe", "collect_diamond"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling",
     "place_table", "place_plant",
     "make_wood_pickaxe",
     "collect_stone", "collect_coal",
     "make_stone_pickaxe", "place_furnace",
     "collect_iron"},
]

# rnd: random agent with 3 anomalous episodes
rnd_eps = [
    {"collect_wood", "wake_up", "collect_drink"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling", "eat_cow"},
    # ANOMALY: collect_diamond without make_iron_pickaxe
    {"collect_wood", "wake_up", "collect_drink", "collect_diamond"},
    {"collect_wood", "wake_up"},
    {"collect_wood", "wake_up", "collect_drink", "defeat_zombie"},
    # ANOMALY: eat_plant without place_plant
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling", "eat_plant"},
    {"collect_wood", "wake_up", "collect_drink"},
    {"collect_wood", "wake_up", "collect_drink", "collect_sapling"},
    # ANOMALY: collect_stone without make_wood_pickaxe
    {"collect_wood", "wake_up", "collect_drink", "place_table", "collect_stone"},
    {"wake_up", "collect_drink"},
]


def compute_step(achievement, episode_idx):
    d = DEPTHS[achievement]
    offset = sum(ord(c) for c in achievement) % 10
    return d * 20 + 5 + offset + episode_idx


def validate_episodes(agent, episodes):
    for i, ep in enumerate(episodes):
        if (agent, i) in ANOMALOUS:
            continue
        for ach in ep:
            if ach not in DEPS:
                raise ValueError(f"{agent} ep {i}: unknown achievement {ach}")
            for dep in DEPS[ach]:
                if dep not in ep:
                    raise ValueError(
                        f"{agent} ep {i}: {ach} requires {dep} but it's absent")


def create_db(db_path="/app/episodes.db"):
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE episodes (
        agent TEXT NOT NULL,
        episode INTEGER NOT NULL,
        length INTEGER NOT NULL,
        reward REAL NOT NULL,
        PRIMARY KEY (agent, episode)
    )""")

    c.execute("""CREATE TABLE achievements (
        agent TEXT NOT NULL,
        episode INTEGER NOT NULL,
        achievement TEXT NOT NULL,
        step INTEGER NOT NULL
    )""")

    c.execute("CREATE INDEX idx_ach_agent ON achievements(agent)")
    c.execute(
        "CREATE INDEX idx_ach_agent_ep ON achievements(agent, episode)")

    agents_data = {
        "dreamer": dreamer_eps,
        "ppo": ppo_eps,
        "curious": curious_eps,
        "rnd": rnd_eps,
    }

    for agent, episodes in agents_data.items():
        validate_episodes(agent, episodes)
        for ep_idx, ach_set in enumerate(episodes):
            length = 200 + len(ach_set) * 50 + ep_idx * 30
            reward = round(len(ach_set) * 1.5 + ep_idx * 0.3, 1)
            c.execute("INSERT INTO episodes VALUES (?, ?, ?, ?)",
                      (agent, ep_idx, length, reward))

            for ach in sorted(ach_set):
                step = compute_step(ach, ep_idx)
                c.execute("INSERT INTO achievements VALUES (?, ?, ?, ?)",
                          (agent, ep_idx, ach, step))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_db()
    print("Created /app/episodes.db")
