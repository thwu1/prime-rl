#!/usr/bin/env python3

"""Derive behavioral specification by computationally testing the corrected engine.

Each ambiguous mechanic is probed with targeted test scenarios and the observed
behavior is recorded in behavioral_spec.json.
"""

import json
import sys

sys.path.insert(0, "/app")
from engine import GameEngine


def _config(**kw):
    roles = kw.pop("roles", [
        {"name": "default", "vision": 5,
         "actions": ["skip", "move", "rotate", "adopt", "request", "attach",
                     "detach", "connect", "disconnect", "submit", "clear", "survey"],
         "speed": [2, 1, 0],
         "clear": {"chance": 1.0, "maxDistance": 2}}
    ])
    defaults = {
        "grid": {"width": 20, "height": 20}, "roles": roles,
        "maxEnergy": 100, "stepRecharge": 1, "clearEnergyCost": 2,
        "deactivatedDuration": 10, "refreshEnergy": 50,
        "clearDamage": [32, 16, 8, 4, 2, 1], "attachLimit": 10,
        "steps": 500, "randomFail": 0,
    }
    defaults.update(kw)
    return defaults


def _state(**kw):
    base = {"agents": [], "blocks": [], "dispensers": [], "obstacles": [],
            "tasks": [], "norms": [], "goalZones": [], "roleZones": []}
    base.update(kw)
    return base


def derive_rotation():
    """Determine CW and CCW rotation directions for a block south of agent."""
    cfg = _config(stepRecharge=0)
    init = _state(
        agents=[{"name": "a1", "team": "A", "x": 10, "y": 10,
                 "role": "default", "energy": 100}],
        blocks=[{"x": 10, "y": 11, "type": "b0"}]
    )

    # CW test
    e = GameEngine(cfg, init)
    e.step({"a1": {"type": "attach", "p": ["s"]}})
    e.step({"a1": {"type": "rotate", "p": ["cw"]}})
    cw_dir = "unknown"
    for d, pos in [("west", (9, 10)), ("east", (11, 10)),
                   ("north", (10, 9)), ("south", (10, 11))]:
        if any(t["type"] == "block" for t in e.get_things_at(*pos)):
            cw_dir = d
            break

    # CCW test
    e2 = GameEngine(cfg, init)
    e2.step({"a1": {"type": "attach", "p": ["s"]}})
    e2.step({"a1": {"type": "rotate", "p": ["ccw"]}})
    ccw_dir = "unknown"
    for d, pos in [("west", (9, 10)), ("east", (11, 10)),
                   ("north", (10, 9)), ("south", (10, 11))]:
        if any(t["type"] == "block" for t in e2.get_things_at(*pos)):
            ccw_dir = d
            break

    return {"cw_south_block_direction": cw_dir,
            "ccw_south_block_direction": ccw_dir}


def derive_deadline():
    """Determine if submit at exact deadline step is allowed."""
    cfg = _config()
    init = _state(
        agents=[{"name": "a1", "team": "A", "x": 3, "y": 3,
                 "role": "default", "energy": 100}],
        blocks=[{"x": 3, "y": 4, "type": "b0"}],
        tasks=[{"name": "t1", "deadline": 1, "reward": 10,
                "requirements": [{"x": 0, "y": 1, "type": "b0"}]}],
        goalZones=[[3, 3], [3, 4]]
    )
    e = GameEngine(cfg, init)
    e.step({"a1": {"type": "attach", "p": ["s"]}})
    r = e.step({"a1": {"type": "submit", "p": ["t1"]}})
    return {"submit_at_exact_deadline_step":
            "allowed" if r["a1"]["result"] == "success" else "rejected"}


def derive_connect():
    """Determine connect edge directionality."""
    roles = [{"name": "default", "vision": 5,
              "actions": ["skip", "move", "rotate", "adopt", "request", "attach",
                          "detach", "connect", "disconnect", "submit", "clear", "survey"],
              "speed": [3, 2, 2, 1, 1],
              "clear": {"chance": 1.0, "maxDistance": 2}}]
    cfg = _config(roles=roles)
    init = _state(
        agents=[
            {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100},
            {"name": "a2", "team": "A", "x": 5, "y": 8, "role": "default", "energy": 100}
        ],
        blocks=[{"x": 5, "y": 6, "type": "b0"}, {"x": 5, "y": 7, "type": "b1"}]
    )
    e = GameEngine(cfg, init)
    e.step({"a1": {"type": "attach", "p": ["s"]},
            "a2": {"type": "attach", "p": ["n"]}})
    e.step({"a1": {"type": "connect", "p": ["a2", "0", "1"]},
            "a2": {"type": "connect", "p": ["a1", "0", "-1"]}})
    a1 = e.get_agent("a1")
    a2 = e.get_agent("a2")
    sym = len(a1["attached"]) == len(a2["attached"])
    return {"edge_directionality": "bidirectional" if sym else "unidirectional"}


def derive_energy():
    """Determine energy recharge eligibility and reactivation source."""
    cfg = _config(maxEnergy=100, stepRecharge=5, deactivatedDuration=3,
                  refreshEnergy=50, clearDamage=[0, 100])
    init = _state(agents=[
        {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 20},
        {"name": "a2", "team": "B", "x": 5, "y": 6, "role": "default", "energy": 100}
    ])
    e = GameEngine(cfg, init)
    # Deactivate a1 via clear
    e.step({"a1": {"type": "skip", "p": []},
            "a2": {"type": "clear", "p": ["0", "-1"]}})
    # a1 should be deactivated now; check energy after one more step
    e.step({"a1": {"type": "skip", "p": []}})
    a1 = e.get_agent("a1")
    recharges = a1["energy"] > 0  # if recharge happens, energy > 0

    # Determine reactivation source by checking energy on reactivation
    cfg2 = _config(maxEnergy=100, stepRecharge=5, deactivatedDuration=2,
                   refreshEnergy=50, clearDamage=[0, 100])
    e2 = GameEngine(cfg2, init)
    e2.step({"a1": {"type": "skip", "p": []},
             "a2": {"type": "clear", "p": ["0", "-1"]}})
    e2.step({"a1": {"type": "skip", "p": []}})
    a1_reactivated = e2.get_agent("a1")
    # refreshEnergy=50, stepRecharge=5: if reactivation uses refreshEnergy, energy=50
    source = "refresh_energy" if a1_reactivated["energy"] == 50 else "step_recharge"

    return {"recharge_while_deactivated": recharges,
            "reactivation_energy_source": source}


def derive_norms():
    """Determine norm enforcement ordering."""
    cfg = _config(maxEnergy=100, stepRecharge=0)
    init = _state(
        agents=[{"name": "a1", "team": "A", "x": 5, "y": 5,
                 "role": "default", "energy": 10}],
        blocks=[{"x": 5, "y": 6, "type": "b0"}, {"x": 6, "y": 5, "type": "b1"}],
        norms=[{"name": "n1", "start": 0, "until": 100, "level": "individual",
                "requirements": [{"type": "block", "name": "any", "quantity": 1}],
                "punishment": 15}]
    )
    e = GameEngine(cfg, init)
    e.step({"a1": {"type": "attach", "p": ["s"]}})
    e.step({"a1": {"type": "attach", "p": ["e"]}})
    a1 = e.get_agent("a1")
    # penalty first: energy 10->0, then deactivated=True
    # check first: energy=10 > 0, no deactivation, then energy 10->0
    if a1["deactivated"]:
        return {"order": "penalty_then_deactivation_check"}
    return {"order": "deactivation_check_then_penalty"}


def derive_unknown_action():
    """Determine unknown action result code."""
    cfg = _config()
    init = _state(agents=[
        {"name": "a1", "team": "A", "x": 5, "y": 5, "role": "default", "energy": 100}
    ])
    e = GameEngine(cfg, init)
    r = e.step({"a1": {"type": "fly", "p": []}})
    return {"unknown_action_result_code": r["a1"]["result"]}


def main():
    spec = {
        "rotation": derive_rotation(),
        "task_deadline": derive_deadline(),
        "connect_action": derive_connect(),
        "energy_lifecycle": derive_energy(),
        "norm_enforcement": derive_norms(),
        "action_dispatch": derive_unknown_action(),
    }
    out_path = "/app/behavioral_spec.json"
    with open(out_path, "w") as f:
        json.dump(spec, f, indent=2)
    print(f"Wrote {out_path}")
    print(json.dumps(spec, indent=2))


if __name__ == "__main__":
    main()
