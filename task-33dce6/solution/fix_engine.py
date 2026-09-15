#!/usr/bin/env python3

"""Apply targeted fixes to the buggy MASSim game engine.

Bugs identified through reference data analysis with sqlite3/jq/trace_diff:

1. CW/CCW rotation transforms are swapped
   - Discovered via: sqlite3 query on rotation trace shows block should be at (9,10)
     after CW rotation of south block, but engine produces (11,10)
   - Root cause: CW formula uses (dy,-dx) instead of (-dy,dx)

2. Connect action creates one-way attachment edge (not symmetric)
   - Discovered via: make diff-trace T=connect shows partner can't move merged component
   - Root cause: uses adj[].add() instead of _attach_edge()

3. Submit deadline uses strict > instead of >= (off-by-one)
   - Discovered via: jq filter on deadline NDJSON events shows submit should succeed
     at exact deadline step but engine returns failed_target
   - Root cause: comparison is > when it should be >=

4. Energy recharge applies to deactivated agents (should be non-deactivated only)
   - Discovered via: sqlite3 query on energy trace shows deactivated agent should
     have energy=0 but engine adds stepRecharge
   - Root cause: recharge line is outside if/else, applies to all agents

5. Norm enforcement checks deactivation threshold before applying penalty (wrong order)
   - Discovered via: jq filter on norms NDJSON events shows agents should deactivate
     when penalty brings energy to 0
   - Root cause: energy==0 check happens before energy subtraction

6. Missing unknown_action fallback for unrecognized action types
   - Discovered via: test divergence — agents with unknown action type get no result
   - Root cause: action types not in _ACTION_ORDER are never iterated
"""

import sys


def apply_fixes(filepath):
    with open(filepath, "r") as f:
        code = f.read()

    fixes_applied = 0

    # ---- Fix 1: Rotation CW/CCW formulas are swapped ----
    old_rotation = (
        '            if direction == "cw":\n'
        '                ndx, ndy = dy, -dx\n'
        '            else:\n'
        '                ndx, ndy = -dy, dx'
    )
    new_rotation = (
        '            if direction == "cw":\n'
        '                ndx, ndy = -dy, dx\n'
        '            else:\n'
        '                ndx, ndy = dy, -dx'
    )
    if old_rotation in code:
        code = code.replace(old_rotation, new_rotation)
        fixes_applied += 1
        print("Fix 1 applied: CW/CCW rotation formulas corrected")

    # ---- Fix 2: Task deadline comparison uses > instead of >= ----
    old_deadline = 't["deadline"] > self.current_step'
    new_deadline = 't["deadline"] >= self.current_step'
    if old_deadline in code:
        code = code.replace(old_deadline, new_deadline)
        fixes_applied += 1
        print("Fix 2 applied: Task deadline comparison corrected (> -> >=)")

    # ---- Fix 3: Connect creates unidirectional edge ----
    old_connect = "self.adj[my_block].add(p_block)"
    new_connect = "self._attach_edge(my_block, p_block)"
    if old_connect in code:
        code = code.replace(old_connect, new_connect)
        fixes_applied += 1
        print("Fix 3 applied: Connect edge made bidirectional")

    # ---- Fix 4a: Carry norm enforcement - deactivation check AFTER penalty ----
    old_carry_norm = (
        '                            if agent["energy"] == 0 and not agent["deactivated"]:\n'
        '                                self._deactivate_agent(name)\n'
        '                            agent["energy"] = max(0, agent["energy"] - norm["punishment"])'
    )
    new_carry_norm = (
        '                            agent["energy"] = max(0, agent["energy"] - norm["punishment"])\n'
        '                            if agent["energy"] == 0 and not agent["deactivated"]:\n'
        '                                self._deactivate_agent(name)'
    )
    if old_carry_norm in code:
        code = code.replace(old_carry_norm, new_carry_norm)
        fixes_applied += 1
        print("Fix 4a applied: Carry norm deactivation order corrected")

    # ---- Fix 4b: Adopt norm enforcement - same ordering fix ----
    old_adopt_norm = (
        '                                if agent["energy"] == 0 and not agent["deactivated"]:\n'
        '                                    self._deactivate_agent(name)\n'
        '                                agent["energy"] = max(0, agent["energy"] - norm["punishment"])'
    )
    new_adopt_norm = (
        '                                agent["energy"] = max(0, agent["energy"] - norm["punishment"])\n'
        '                                if agent["energy"] == 0 and not agent["deactivated"]:\n'
        '                                    self._deactivate_agent(name)'
    )
    if old_adopt_norm in code:
        code = code.replace(old_adopt_norm, new_adopt_norm)
        fixes_applied += 1
        print("Fix 4b applied: Adopt norm deactivation order corrected")

    # ---- Fix 5: Missing else branch causes recharge during deactivation ----
    old_recharge = (
        '        for name, agent in self.agents.items():\n'
        '            if agent["deactivated"]:\n'
        '                agent["deactivated_steps"] -= 1\n'
        '                if agent["deactivated_steps"] <= 0:\n'
        '                    agent["deactivated"] = False\n'
        '                    agent["energy"] = self.refresh_energy\n'
        '            agent["energy"] = min(self.max_energy,\n'
        '                                  agent["energy"] + self.step_recharge)'
    )
    new_recharge = (
        '        for name, agent in self.agents.items():\n'
        '            if agent["deactivated"]:\n'
        '                agent["deactivated_steps"] -= 1\n'
        '                if agent["deactivated_steps"] <= 0:\n'
        '                    agent["deactivated"] = False\n'
        '                    agent["energy"] = self.refresh_energy\n'
        '            else:\n'
        '                agent["energy"] = min(self.max_energy,\n'
        '                                      agent["energy"] + self.step_recharge)'
    )
    if old_recharge in code:
        code = code.replace(old_recharge, new_recharge)
        fixes_applied += 1
        print("Fix 5 applied: Added else branch to prevent recharge during deactivation")

    # ---- Fix 6: Add unknown_action fallback ----
    old_fallback = '        # --- End-of-step processing ---'
    new_fallback = (
        '        # Handle agents with unknown action types\n'
        '        for name in self.agents:\n'
        '            if name not in results:\n'
        '                results[name] = {"result": "unknown_action"}\n'
        '\n'
        '        # --- End-of-step processing ---'
    )
    if old_fallback in code and 'Handle agents with unknown action' not in code:
        code = code.replace(old_fallback, new_fallback, 1)
        fixes_applied += 1
        print("Fix 6 applied: Added unknown_action fallback for unrecognized action types")

    with open(filepath, "w") as f:
        f.write(code)

    print(f"\nTotal fixes applied: {fixes_applied}")
    return fixes_applied


if __name__ == "__main__":
    target = "/app/engine.py"
    n = apply_fixes(target)
    if n == 0:
        print("WARNING: No fixes were applied.")
        sys.exit(1)
    print(f"Successfully patched {target}")
